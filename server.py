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
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / "docs" / "data.json"
SLIP = BASE / "slip.md"

app = Flask(__name__)

_lock = threading.Lock()
_state = {"running": False, "log": "", "finished_at": None, "ok": None}


def _do_run():
    try:
        proc = subprocess.run(
            ["python", "export_snapshot.py", "--days", "3"],
            capture_output=True, text=True, cwd=str(BASE), timeout=1200,
        )
        _state["log"] = (proc.stdout + "\n" + proc.stderr)[-8000:]
        _state["ok"] = proc.returncode == 0
    except Exception as e:  # keep the service alive no matter what the model does
        _state["log"] = str(e)
        _state["ok"] = False
    finally:
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
    _state.update(running=True, log="starting barbadox_core pipeline...", ok=None)
    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "message": "run started"})


@app.get("/api/status")
def status():
    return jsonify(_state)


@app.get("/api/slip")
def slip():
    subprocess.run(["python", "barbadox_core.py", "slip"], cwd=str(BASE),
                   capture_output=True, text=True, timeout=300)
    body = SLIP.read_text(encoding="utf-8") if SLIP.exists() else "no slip generated"
    return jsonify({"ok": True, "slip": body})


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
