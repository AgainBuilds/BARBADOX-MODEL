#!/usr/bin/env python3
"""
BARBADOX console server.

Core 1:
    Over 1.5 goals.
    Existing model pipeline and owner-review safeguard preserved.

Core 2:
    Under 3.5 goals.
    Runs independently of Core 1 success.
    Has separate execution status and output validation.

The server does not modify the prediction mathematics.
"""

import json
import os
import subprocess
import threading
import time

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

import gh_sync


BASE = Path(__file__).resolve().parent

SNAPSHOT = BASE / "docs" / "data.json"
UNDER35 = BASE / "docs" / "under35.json"
SLIP = BASE / "slip.md"

app = Flask(__name__)

_lock = threading.Lock()

WAIT_SECONDS = 300

CORE1_TIMEOUT = 1200
CORE2_TIMEOUT = 900


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


_state = {
    "running": False,
    "waiting": False,
    "wait_seconds": 0,
    "log": "",
    "finished_at": None,

    # Legacy Core 1 fields.
    "ok": None,
    "ready": False,
    "owner_pending": 0,
    "context_added": 0,
    "scanned": 0,
    "leagues_empty": [],

    # Explicit Core 1 status.
    "core1_status": "idle",
    "core1_finished_at": None,
    "core1_error": None,

    # Independent Core 2 status.
    "core2_status": "idle",
    "core2_model_status": None,
    "core2_error": None,
    "core2_finished_at": None,
    "core2_generated_at": None,
    "core2_scanned": 0,
    "core2_qualified": 0,
    "core2_threshold": 0.75,
}


def _export():
    return subprocess.run(
        ["python", "export_snapshot.py", "--days", "3"],
        capture_output=True,
        text=True,
        cwd=str(BASE),
        timeout=CORE1_TIMEOUT,
    )


def _read_snapshot():
    return read_json(SNAPSHOT)


def _run_under35():
    """
    Run Core 2 separately from Core 1.

    A failed Core 1 run must not prevent Core 2 from being attempted.
    Delete old Core 2 output before running so stale results cannot
    be mistaken for a successful fresh run.
    """

    _state.update(
        core2_status="running",
        core2_model_status=None,
        core2_error=None,
        core2_generated_at=None,
        core2_scanned=0,
        core2_qualified=0,
    )

    # Remove old output before execution.
    try:
        UNDER35.unlink(missing_ok=True)
    except Exception as exc:
        _state.update(
            core2_status="failed",
            core2_error=f"Could not remove old Core 2 output: {exc}",
            core2_finished_at=utc_now(),
        )

        return (
            "\n--- CORE 2 FAILED ---\n"
            f"Could not remove old output: {exc}\n"
        )

    try:
        proc = subprocess.run(
            ["python", "barbadox_under35.py", "--days", "3"],
            capture_output=True,
            text=True,
            cwd=str(BASE),
            timeout=CORE2_TIMEOUT,
        )

        log = (
            "\n--- CORE 2 (UNDER 3.5) ---\n"
            + (proc.stdout or "")
            + "\n"
            + (proc.stderr or "")
        )

        if proc.returncode != 0:
            error = (
                f"Core 2 exited with return code {proc.returncode}."
            )

            _state.update(
                core2_status="failed",
                core2_error=error,
                core2_finished_at=utc_now(),
            )

            return log + "\nCORE 2 ERROR: " + error + "\n"

        # A successful process exit is not enough.
        # The output must exist and be valid.
        snapshot = read_json(UNDER35)

        if not isinstance(snapshot, dict):
            error = "Core 2 produced no valid JSON output."

            _state.update(
                core2_status="failed",
                core2_error=error,
                core2_finished_at=utc_now(),
            )

            return log + "\nCORE 2 ERROR: " + error + "\n"

        fixtures = snapshot.get("fixtures")

        if not isinstance(fixtures, list):
            error = "Core 2 JSON is missing a valid fixtures list."

            _state.update(
                core2_status="failed",
                core2_error=error,
                core2_finished_at=utc_now(),
            )

            return log + "\nCORE 2 ERROR: " + error + "\n"

        model_status = snapshot.get("status")

        if model_status not in ("ok", "no-history"):
            error = (
                "Core 2 returned an unexpected model status: "
                + str(model_status)
            )

            _state.update(
                core2_status="failed",
                core2_model_status=model_status,
                core2_error=error,
                core2_finished_at=utc_now(),
            )

            return log + "\nCORE 2 ERROR: " + error + "\n"

        qualified = [
            fixture
            for fixture in fixtures
            if isinstance(fixture, dict)
            and fixture.get("decision") == "qualified"
        ]

        _state.update(
            core2_status="success",
            core2_model_status=model_status,
            core2_error=None,
            core2_generated_at=snapshot.get("generated_at"),
            core2_scanned=len(fixtures),
            core2_qualified=len(qualified),
            core2_threshold=snapshot.get("threshold", 0.75),
            core2_finished_at=utc_now(),
        )

        log += (
            "\nCORE 2 VERIFIED: "
            f"{len(fixtures)} fixtures scanned; "
            f"{len(qualified)} qualified; "
            f"threshold={_state['core2_threshold']}.\n"
        )

        return log

    except subprocess.TimeoutExpired:
        error = f"Core 2 timed out after {CORE2_TIMEOUT} seconds."

        _state.update(
            core2_status="failed",
            core2_error=error,
            core2_finished_at=utc_now(),
        )

        return "\n--- CORE 2 TIMEOUT ---\n" + error + "\n"

    except Exception as exc:
        error = str(exc)

        _state.update(
            core2_status="failed",
            core2_error=error,
            core2_finished_at=utc_now(),
        )

        return "\n--- CORE 2 FAILED ---\n" + error + "\n"


def _do_run():
    """
    Run Core 1 while preserving its existing owner-review procedure.

    Core 2 is attempted even if Core 1 fails.
    """

    log = ""

    try:
        # ---------------------------------------------------------
        # CORE 1
        # ---------------------------------------------------------

        _state["core1_status"] = "running"
        _state["core1_error"] = None

        try:
            proc = _export()

            log += (
                "\n--- CORE 1 INITIAL EXPORT ---\n"
                + (proc.stdout or "")
                + "\n"
                + (proc.stderr or "")
            )

            _state["ok"] = proc.returncode == 0

            if proc.returncode != 0:
                _state.update(
                    core1_status="failed",
                    core1_error=(
                        "Initial Core 1 export failed with return code "
                        + str(proc.returncode)
                    ),
                    ready=False,
                )

            else:
                snapshot = _read_snapshot() or {}

                added = int(snapshot.get("context_added", 0) or 0)

                _state["context_added"] = added
                _state["owner_pending"] = int(
                    snapshot.get("owner_pending", 0) or 0
                )

                # Preserve the five-minute owner-review safeguard.
                if added > 0:
                    _state.update(
                        waiting=True,
                        wait_seconds=WAIT_SECONDS,
                        ready=False,
                    )

                    log += (
                        "\n!!! IMPORTANT !!! "
                        + str(added)
                        + " new match(es) added to context.csv.\n"
                        "WAIT 5 MINUTES for the owner to review/update "
                        "context.csv (set checked=1).\n"
                        "Unconfirmed matches must NOT be used as picks.\n"
                    )

                    for remaining in range(WAIT_SECONDS, 0, -1):
                        _state["wait_seconds"] = remaining
                        time.sleep(1)

                    _state["waiting"] = False

                    # Re-run Core 1 after the owner-review window.
                    proc2 = _export()

                    log += (
                        "\n--- CORE 1 OWNER REVIEW RECHECK ---\n"
                        + (proc2.stdout or "")
                        + "\n"
                        + (proc2.stderr or "")
                    )

                    _state["ok"] = proc2.returncode == 0

                    if proc2.returncode != 0:
                        _state.update(
                            core1_status="failed",
                            core1_error=(
                                "Core 1 owner-review recheck failed "
                                "with return code "
                                + str(proc2.returncode)
                            ),
                            ready=False,
                        )

                    snapshot = _read_snapshot() or {}

                    _state["owner_pending"] = int(
                        snapshot.get("owner_pending", 0) or 0
                    )

                # Final Core 1 state.
                if _state["ok"]:
                    _state["core1_status"] = "success"

                    _state["scanned"] = int(
                        snapshot.get(
                            "scanned",
                            len(snapshot.get("fixtures", [])),
                        )
                        or 0
                    )

                    _state["leagues_empty"] = snapshot.get(
                        "leagues_empty", []
                    )

                    _state["ready"] = (
                        _state["owner_pending"] == 0
                        and _state["scanned"] > 0
                    )

                    if _state["scanned"] == 0:
                        log += (
                            "\nCORE 1 NOT READY: zero matches scanned. "
                            "Check FOOTBALL_DATA_KEY, API limits, "
                            "league data and upcoming fixtures.\n"
                        )

                    elif not _state["ready"]:
                        log += (
                            "\nCORE 1 OWNER CONFIRMATION REQUIRED: "
                            + str(_state["owner_pending"])
                            + " unconfirmed match(es) remain.\n"
                        )

                else:
                    _state["ready"] = False

        except Exception as exc:
            _state.update(
                ok=False,
                ready=False,
                core1_status="failed",
                core1_error=str(exc),
            )

            log += "\nCORE 1 ERROR: " + str(exc) + "\n"

        finally:
            _state["core1_finished_at"] = utc_now()

        # ---------------------------------------------------------
        # CORE 2
        # ---------------------------------------------------------
        #
        # This is deliberately outside the Core 1 success branch.
        # Core 1 failure does not skip the Core 2 attempt.
        #
        # The processes still run sequentially to avoid unnecessary
        # simultaneous access to local cached match data.
        # ---------------------------------------------------------

        log += _run_under35()

    except Exception as exc:
        log += "\nSERVER RUN ERROR: " + str(exc) + "\n"

    finally:
        _state["waiting"] = False
        _state["running"] = False
        _state["finished_at"] = utc_now()
        _state["log"] = log[-12000:]


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
    snapshot = _read_snapshot()

    if snapshot is None:
        return jsonify({
            "error": "No valid Core 1 snapshot yet. Tap RUN."
        }), 404

    return jsonify(snapshot)


@app.get("/api/under35")
def under35():
    snapshot = read_json(UNDER35)

    if snapshot is None:
        return jsonify({
            "error": "No valid Core 2 data yet. Run the model."
        }), 404

    return jsonify(snapshot)


@app.post("/api/run")
def run():
    if _state["running"]:
        return jsonify({
            "ok": False,
            "message": "A run is already in progress.",
        }), 409

    if not _lock.acquire(blocking=False):
        return jsonify({
            "ok": False,
            "message": "Server busy. Try again shortly.",
        }), 409

    _state.update(
        running=True,
        waiting=False,
        wait_seconds=0,
        ready=False,
        owner_pending=0,
        context_added=0,
        log="Starting Barbadox...",
        ok=None,
        core1_status="running",
        core1_error=None,
        core2_status="queued",
        core2_model_status=None,
        core2_error=None,
        core2_finished_at=None,
        core2_generated_at=None,
        core2_scanned=0,
        core2_qualified=0,
    )

    threading.Thread(
        target=_worker,
        daemon=True,
    ).start()

    return jsonify({
        "ok": True,
        "message": "Core 1 and Core 2 run started.",
    })


@app.get("/api/status")
def status():
    return jsonify(_state)


@app.get("/api/slip")
def slip():
    if gh_sync.enabled():
        try:
            gh_sync.pull("picks.csv")
        except Exception as exc:
            return jsonify({
                "ok": False,
                "slip": "Could not read picks from GitHub: " + str(exc),
            })

    try:
        subprocess.run(
            ["python", "barbadox_core.py", "slip"],
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        body = (
            SLIP.read_text(encoding="utf-8")
            if SLIP.exists()
            else "No slip generated."
        )

        return jsonify({
            "ok": True,
            "slip": body,
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "slip": "Slip generation failed: " + str(exc),
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
    )
