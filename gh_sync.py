#!/usr/bin/env python3
"""
GitHub as the single source of truth for context.csv and picks.csv.

Needs these environment variables on Render (Environment tab):
    GITHUB_TOKEN   fine-grained token, this repo only, Contents: Read and write
    GITHUB_REPO    defaults to AgainBuilds/BARBADOX-MODEL
    GITHUB_BRANCH  defaults to main

Every push sends the sha it last read, so if the owner edited the file in the meantime
GitHub rejects the write (Conflict) instead of overwriting the owner's edit. The caller
then re-pulls and retries. Commit messages carry [skip render] so our own commits never
trigger a redeploy that would kill a run in progress.
"""
import base64
import os
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
API = "https://api.github.com"
_shas = {}


class Conflict(Exception):
    pass


class SyncError(Exception):
    pass


def enabled():
    return bool(os.environ.get("GITHUB_TOKEN", "").strip())


def _repo():
    return os.environ.get("GITHUB_REPO", "AgainBuilds/BARBADOX-MODEL").strip()


def _branch():
    return os.environ.get("GITHUB_BRANCH", "main").strip()


def _headers(raw=False):
    return {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"].strip(),
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def pull(name):
    """Make the local copy of `name` identical to GitHub's. Returns True if it exists there."""
    url = f"{API}/repos/{_repo()}/contents/{name}"
    try:
        r = requests.get(url, headers=_headers(), params={"ref": _branch()}, timeout=30)
    except requests.RequestException as e:
        raise SyncError(f"GitHub unreachable while reading {name}: {e}")
    if r.status_code == 404:
        _shas.pop(name, None)
        (BASE / name).unlink(missing_ok=True)
        return False
    if r.status_code in (401, 403):
        raise SyncError(f"GitHub rejected the token while reading {name} (HTTP {r.status_code})")
    if not r.ok:
        raise SyncError(f"GitHub HTTP {r.status_code} while reading {name}")
    j = r.json()
    if j.get("encoding") == "base64" and j.get("content"):
        data = base64.b64decode(j["content"])
    else:  # large file: ask for the raw bytes
        rr = requests.get(url, headers=_headers(raw=True), params={"ref": _branch()}, timeout=30)
        if not rr.ok:
            raise SyncError(f"GitHub HTTP {rr.status_code} while reading {name}")
        data = rr.content
    (BASE / name).write_bytes(data)
    _shas[name] = j["sha"]
    return True


def push(name, message):
    """Commit the local `name` to GitHub on top of the sha we last pulled."""
    body = {"message": message + " [skip render]",
            "content": base64.b64encode((BASE / name).read_bytes()).decode(),
            "branch": _branch()}
    if name in _shas:
        body["sha"] = _shas[name]
    try:
        r = requests.put(f"{API}/repos/{_repo()}/contents/{name}", headers=_headers(), json=body, timeout=30)
    except requests.RequestException as e:
        raise SyncError(f"GitHub unreachable while writing {name}: {e}")
    if r.status_code in (409, 422):
        raise Conflict(name)
    if r.status_code in (401, 403, 404):
        raise SyncError(f"GitHub refused the write to {name} (HTTP {r.status_code}). "
                        "Check the token has Contents: Read and write on this repo.")
    if not r.ok:
        raise SyncError(f"GitHub HTTP {r.status_code} while writing {name}")
    _shas[name] = r.json()["content"]["sha"]
