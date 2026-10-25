#!/usr/bin/env python3
"""
BARBADOX SLIPS HISTORY — permanent server-side storage.

Storage layers:
  1. slips_browser.csv on the server  -> survives browser wipes.
  2. Committed back to GitHub         -> survives Render redeploys
     (the Render free-tier filesystem is wiped on every deploy).

Uses GITHUB_TOKEN via gh_sync when configured; otherwise it keeps
the local CSV only (still better than browser-only storage).

NEW:
  - The archive is restored from GitHub at boot, so a Render deploy
    never starts from an empty slips_browser.csv.
  - A graded slip (WON/LOST) is never overwritten by an ungraded
    (PENDING) copy of the same slip. When both copies are graded,
    the newer grading wins.
  - Final scores captured by live_scores.js are merged into kept
    records, so scores survive even when the status is protected.

Blueprint endpoints:
  GET  /api/slip-history   -> {"ok": true, "slips": [...]}
  POST /api/slip-history   -> body {"slips": [...]} upserts by slip id
  GET  /slips_history.js   -> serves the frontend script
"""

import csv
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

import gh_sync

slips_history_bp = Blueprint("barbadox_slips_history", __name__)

ROOT = Path(__file__).resolve().parent
HISTORY_CSV = ROOT / "slips_browser.csv"
REMOTE_NAME = "slips_browser.csv"

FIELDS = [
    "id",
    "number",
    "created_at",
    "status",
    "graded_at",
    "auto_graded",
    "archived_at",
    "legs",
]

_lock = threading.Lock()
_last_push = {"signature": ""}


def _read_rows():
    """Read every archived slip from the CSV."""
    if not HISTORY_CSV.exists():
        return []

    rows = []

    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = dict(raw)

            try:
                row["legs"] = json.loads(row.get("legs") or "[]")
            except (ValueError, TypeError):
                row["legs"] = []

            rows.append(row)

    return rows


def _write_rows(rows):
    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)

        writer.writeheader()

        for row in rows:
            out = dict(row)
            out["legs"] = json.dumps(
                row.get("legs") or [],
                ensure_ascii=False
            )

            writer.writerow(out)


def _is_graded(status):
    return str(status or "").upper() in ("WON", "LOST")


def _should_keep(existing, record):
    """True when the existing CSV record must not be overwritten.

    A graded slip (WON/LOST) never regresses to PENDING, and when
    both copies are graded the newer grading wins. This stops a
    browser holding an ungraded copy of a slip from erasing a
    manual or automatic grading that is already recorded.
    """
    if _is_graded(existing.get("status")) and not _is_graded(record["status"]):
        return True

    if (
        _is_graded(existing.get("status"))
        and _is_graded(record["status"])
        and str(existing.get("graded_at") or "")
        >= str(record.get("graded_at") or "")
    ):
        return True

    return False


def _merge_leg_scores(existing, record):
    """Merge incoming leg scores into a kept record.

    Called when the existing record wins the status comparison:
    the status stays untouched, but any final scores, fixture
    statuses, or leg results that arrived with the incoming copy
    are adopted where the stored legs do not have them yet.
    """
    old = existing.get("legs") or []
    new = record.get("legs") or []

    if not isinstance(old, list) or not isinstance(new, list):
        return False

    if not new:
        return False

    if len(old) != len(new):
        return False

    merged = []
    changed = False

    for o, n in zip(old, new):
        if not isinstance(o, dict) or not isinstance(n, dict):
            merged.append(o)
            continue

        leg = dict(o)

        for key in ("liveScore", "fixtureStatus"):
            if n.get(key) and not o.get(key):
                leg[key] = n[key]
                changed = True

        if (
            n.get("result")
            and str(n["result"]).upper() != "PENDING"
            and str(o.get("result") or "").upper() in ("", "PENDING")
        ):
            leg["result"] = n["result"]
            changed = True

        merged.append(leg)

    if changed:
        existing["legs"] = merged

    return changed


def _startup_restore():
    """Pull the permanent archive from GitHub at boot.

    The Render filesystem is wiped on every deploy, so without
    this restore the server would start from an empty CSV and
    blindly trust whatever the first browser pushes.
    """
    if not gh_sync.enabled():
        return

    try:
        if gh_sync.pull(REMOTE_NAME):
            print("Restored slips history from GitHub.")

    except Exception as exc:
        print("Could not restore slips history: " + str(exc))


def _normalize(slip):
    """Convert a browser slip object into a CSV record."""
    auto = slip.get("autoGraded")

    if auto is None:
        auto = slip.get("auto_graded") == "YES"

    return {
        "id": str(slip.get("id", "")).strip(),
        "number": slip.get("number", ""),
        "created_at": (
            slip.get("createdAt")
            or slip.get("created_at")
            or ""
        ),
        "status": str(
            slip.get("status", "PENDING")
        ).upper(),
        "graded_at": (
            slip.get("gradedAt")
            or slip.get("graded_at")
            or ""
        ),
        "auto_graded": "YES" if auto else "NO",
        "archived_at": (
            slip.get("archivedAt")
            or slip.get("archived_at")
            or datetime.now(timezone.utc).isoformat()
        ),
        "legs": (
            slip.get("legs")
            if isinstance(slip.get("legs"), list)
            else []
        ),
    }


def _push_to_github():
    """Commit the CSV to GitHub so it survives the next deploy."""
    if not HISTORY_CSV.exists():
        return

    try:
        signature = hashlib.sha256(
            HISTORY_CSV.read_bytes()
        ).hexdigest()

        if signature == _last_push["signature"]:
            return

        if gh_sync.enabled():
            gh_sync.push_snapshot(
                REMOTE_NAME,
                "Update slips history (browser tracker archive)"
            )

            _last_push["signature"] = signature

    except Exception:
        # Never fail the request because the GitHub sync failed.
        pass


_startup_restore()


@slips_history_bp.get("/slips_history.js")
def slips_history_script():
    return send_from_directory(
        str(ROOT),
        "slips_history.js",
        mimetype="application/javascript"
    )


@slips_history_bp.get("/api/slip-history")
def get_history():
    with _lock:
        rows = _read_rows()

    return jsonify({
        "ok": True,
        "count": len(rows),
        "slips": rows
    })


@slips_history_bp.post("/api/slip-history")
def save_history():
    data = request.get_json(silent=True) or {}

    incoming = data.get("slips")

    if not isinstance(incoming, list):
        return jsonify({
            "ok": False,
            "error": "Body must contain a slips array."
        }), 400

    changed = False

    with _lock:
        by_id = {
            r["id"]: r
            for r in _read_rows()
            if r.get("id")
        }

        for slip in incoming:
            if not isinstance(slip, dict):
                continue

            record = _normalize(slip)

            if not record["id"]:
                continue

            existing = by_id.get(record["id"])

            if existing is not None and _should_keep(existing, record):
                # Keep the graded record, but still adopt any
                # final scores that arrived with the new copy.
                if _merge_leg_scores(existing, record):
                    changed = True

                continue

            if existing != record:
                by_id[record["id"]] = record
                changed = True

        if changed:
            ordered = sorted(
                by_id.values(),
                key=lambda r: str(r.get("created_at", ""))
            )

            _write_rows(ordered)

    if changed:
        _push_to_github()

    return jsonify({
        "ok": True,
        "changed": changed,
        "count": len(by_id)
    })
