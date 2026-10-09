#!/usr/bin/env python3
"""
BARBADOX console server — Render Web Service.
Serves the console UI and runs the REAL model on demand. The model math
is untouched: this only shells out to export_snapshot.py, which imports
barbadox_core and runs its own pipeline. Set FOOTBALL_DATA_KEY in the
Render dashboard.
"""
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

import gh_sync

BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / "docs" / "data.json"
SLIP = BASE / "slip.md"

app = Flask(__name__)

_lock = threading.Lock()
WAIT_SECONDS = 300  # the 5-minute owner review window
_state = {"running": False, "waiting": False, "wait_seconds": 0, "log": "", "finished_at": None,
          "ok": None, "ready": False, "owner_pending": 0, "context_added": 0,
          "scanned": 0, "leagues_empty": []}


def _export():
    return subprocess.run(
        ["python", "export_snapshot.py", "--days", "3"],
        capture_output=True, text=True, cwd=str(BASE), timeout=1200,
    )


def _read_snapshot():
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None


def _do_run():
    try:
        proc = _export()
        log = proc.stdout + "\n" + proc.stderr
        _state["ok"] = proc.returncode == 0
        if proc.returncode == 0:
            snap = _read_snapshot() or {}
            added = snap.get("context_added", 0)
            _state["context_added"] = added
            _state["owner_pending"] = snap.get("owner_pending", 0)

            if added:
                # NEW matches were appended to context.csv: force the 5-minute owner window.
                _state.update(waiting=True, wait_seconds=WAIT_SECONDS, ready=False)
                log += ("\n!!! IMPORTANT !!! " + str(added) + " new match(es) added to context.csv.\n"
                        "WAIT 5 MINUTES for the owner to review/update context.csv (set checked=1).\n"
                        "Unconfirmed matches are blocked and must NOT be used as picks.\n")
                for remaining in range(WAIT_SECONDS, 0, -1):
                    _state["wait_seconds"] = remaining
                    time.sleep(1)
                _state["waiting"] = False
                # Re-run so whatever the owner confirmed is now applied to the predictions.
                proc2 = _export()
                log += "\n--- OWNER REVIEW RECHECK ---\n" + proc2.stdout + "\n" + proc2.stderr
                _state["ok"] = proc2.returncode == 0
                snap = _read_snapshot() or {}
                _state["owner_pending"] = snap.get("owner_pending", 0)

            _state["scanned"] = snap.get("scanned", len(snap.get("fixtures", [])))
            _state["leagues_empty"] = snap.get("leagues_empty", [])
            _state["ready"] = bool(_state["ok"]) and _state["owner_pending"] == 0 and _state["scanned"] > 0
            if _state["ok"] and _state["scanned"] == 0:
                log += ("\nNOT READY: 0 matches were scanned. Leagues with no data: " +
                        (", ".join(_state["leagues_empty"]) or "none") +
                        ". Check FOOTBALL_DATA_KEY, the API rate limit, or that fixtures exist in the next 3 days.")
            if _state["ok"] and not _state["ready"] and _state["scanned"] > 0:
                log += ("\nOWNER WAIT REQUIRED: context.csv still has " + str(_state["owner_pending"]) +
                        " unconfirmed match(es). Do NOT use those picks. Keep waiting for the owner "
                        "to set checked=1, then tap RUN again.")
        _state["log"] = log[-8000:]
    except Exception as e:  # keep the service alive no matter what the model does
        _state["log"] = str(e)
        _state["ok"] = False
    finally:
        _state["waiting"] = False
        _state["running"] = False
        _state["finished_at"] = datetime.now().isoformat()


def _worker():
    try:
        _do_run()
    finally:
        _lock.release()


@app.get("/")
def index():
    return send_from_directory(str(BASE), "console.html")


@app.get("/api/data")
def data():
    if not SNAPSHOT.exists():
        return jsonify({"error": "no snapshot yet — tap RUN"}), 404
    return jsonify(json.loads(SNAPSHOT.read_text(encoding="utf-8")))


@app.post("/api/run")
def run():
    if _state["running"]:
        return jsonify({"ok": False, "message": "a run is already in progress"})
    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "message": "server busy"})
    _state.update(running=True, waiting=False, wait_seconds=0, ready=False, owner_pending=0,
                  context_added=0, log="starting BARBADOX context scan...", ok=None)
    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "message": "run started"})


@app.get("/api/status")
def status():
    return jsonify(_state)


@app.get("/api/slip")
def slip():
    if gh_sync.enabled():
        try:
            gh_sync.pull("picks.csv")  # the slip must use the repo's picks, not a stale local copy
        except Exception as e:
            return jsonify({"ok": False, "slip": "Could not read picks from GitHub: " + str(e)})
    subprocess.run(["python", "barbadox_core.py", "slip"], cwd=str(BASE),
                   capture_output=True, text=True, timeout=300)
    body = SLIP.read_text(encoding="utf-8") if SLIP.exists() else "no slip generated"
    return jsonify({"ok": True, "slip": body})


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
