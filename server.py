#!/usr/bin/env python3
"""
BARBADOX console server.

Core 1:
Over 1.5 goals.

Core 2:
Under 3.5 goals.
Runs independently of Core 1 success.

IMPORTANT:
checked=1 is a finished-match marker, not an approval
requirement for upcoming fixtures.

When new fixtures are added to context.csv:
    1. Run a deferred initial export.
    2. Wait five minutes.
    3. Run the final export and allow qualifying picks
       to be logged.

When no fixtures are added:
    Run the final export immediately.

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

BASE = Path(file).resolve().parent

SNAPSHOT = BASE / "docs" / "data.json"
UNDER35 = BASE / "docs" / "under35.json"
SLIP = BASE / "slip.md"

app = Flask(name)

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

# Core 1 status.
"ok": None,
"ready": False,
"owner_pending": 0,
"context_added": 0,
"scanned": 0,
"leagues_empty": [],

"core1_status": "idle",
"core1_finished_at": None,
"core1_error": None,

# Core 2 status.
"core2_status": "idle",
"core2_model_status": None,
"core2_error": None,
"core2_finished_at": None,
"core2_generated_at": None,
"core2_scanned": 0,
"core2_qualified": 0,
"core2_threshold": 0.75,

}

def _export(defer_picks=False):
"""
Run the Core 1 exporter.

defer_picks=True:
    Analyse fixtures and update context, but do not log
    new picks during the initial review pass.

defer_picks=False:
    Perform the normal final export.
"""

command = [
    "python",
    "export_snapshot.py",
    "--days",
    "3",
]

if defer_picks:
    command.append("--defer-picks")

return subprocess.run(
    command,
    capture_output=True,
    text=True,
    cwd=str(BASE),
    timeout=CORE1_TIMEOUT,
)

def _read_snapshot():
return read_json(SNAPSHOT)

def _run_under35():
"""
Run Core 2 independently.

Core 1 failure must not prevent Core 2 from being attempted.
Old output is removed before execution to avoid presenting
stale results as a successful fresh run.
"""

_state.update(
    core2_status="running",
    core2_model_status=None,
    core2_error=None,
    core2_generated_at=None,
    core2_scanned=0,
    core2_qualified=0,
)

try:
    UNDER35.unlink(missing_ok=True)

except Exception as exc:
    _state.update(
        core2_status="failed",
        core2_error=(
            "Could not remove old Core 2 output: "
            + str(exc)
        ),
        core2_finished_at=utc_now(),
    )

    return (
        "\n--- CORE 2 FAILED ---\n"
        f"Could not remove old output: {exc}\n"
    )

try:
    proc = subprocess.run(
        [
            "python",
            "barbadox_under35.py",
            "--days",
            "3",
        ],
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
            "Core 2 exited with return code "
            + str(proc.returncode)
            + "."
        )

        _state.update(
            core2_status="failed",
            core2_error=error,
            core2_finished_at=utc_now(),
        )

        return log + "\nCORE 2 ERROR: " + error + "\n"

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
        error = (
            "Core 2 JSON is missing a valid fixtures list."
        )

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
        if (
            isinstance(fixture, dict)
            and fixture.get("decision") == "qualified"
        )
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
    error = (
        f"Core 2 timed out after {CORE2_TIMEOUT} seconds."
    )

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
Run Core 1 and then Core 2.

Core 1 uses a deferred initial pass so newly discovered
fixtures cannot be logged before the review window.

Core 2 is attempted regardless of Core 1's outcome.
"""

log = ""

try:
    # =========================================================
    # CORE 1: INITIAL PASS
    # =========================================================

    _state.update(
        core1_status="running",
        core1_error=None,
        ready=False,
    )

    try:
        initial = _export(defer_picks=True)

        log += (
            "\n--- CORE 1 INITIAL DEFERRED EXPORT ---\n"
            + (initial.stdout or "")
            + "\n"
            + (initial.stderr or "")
        )

        _state["ok"] = initial.returncode == 0

        if initial.returncode != 0:
            error = (
                "Initial Core 1 export failed with return code "
                + str(initial.returncode)
            )

            _state.update(
                core1_status="failed",
                core1_error=error,
                ready=False,
            )

            log += "\nCORE 1 ERROR: " + error + "\n"

        else:
            snapshot = _read_snapshot() or {}

            added = int(
                snapshot.get("context_added", 0) or 0
            )

            _state["context_added"] = added

            # checked=1 is not a pre-match approval flag.
            # Keep this legacy field at zero so old dashboard
            # code does not block fixtures because checked=0.
            _state["owner_pending"] = 0

            # =================================================
            # FIVE-MINUTE REVIEW WINDOW
            # =================================================

            if added > 0:
                _state.update(
                    waiting=True,
                    wait_seconds=WAIT_SECONDS,
                    ready=False,
                )

                log += (
                    "\n"
                    + "!" * 65
                    + "\n"
                    + f"{added} NEW FIXTURE(S) ADDED TO context.csv.\n"
                    + "WAIT 5 MINUTES BEFORE FINAL PICK LOGGING.\n"
                    + "Review contextual information if available.\n"
                    + "Do not set checked=1 to approve an upcoming match.\n"
                    + "checked=1 is reserved for finished-match status.\n"
                    + "!" * 65
                    + "\n"
                )

                for remaining in range(WAIT_SECONDS, 0, -1):
                    _state["wait_seconds"] = remaining
                    time.sleep(1)

                _state.update(
                    waiting=False,
                    wait_seconds=0,
                )

                log += (
                    "\nFive-minute review window complete. "
                    "Starting the final export.\n"
                )

            else:
                log += (
                    "\nNo new context rows were added. "
                    "Skipping the five-minute wait.\n"
                )

            # ================================================
            # CORE 1: FINAL EXPORT
            # ================================================
            #
            # Run without --defer-picks. The exporter can now
            # log qualifying picks according to the threshold.
            # ================================================

            final = _export(defer_picks=False)

            log += (
                "\n--- CORE 1 FINAL EXPORT ---\n"
                + (final.stdout or "")
                + "\n"
                + (final.stderr or "")
            )

            _state["ok"] = final.returncode == 0

            if final.returncode != 0:
                error = (
                    "Final Core 1 export failed with return code "
                    + str(final.returncode)
                )

                _state.update(
                    core1_status="failed",
                    core1_error=error,
                    ready=False,
                )

                log += "\nCORE 1 ERROR: " + error + "\n"

            else:
                snapshot = _read_snapshot() or {}

                scanned = int(
                    snapshot.get(
                        "scanned",
                        len(snapshot.get("fixtures", [])),
                    )
                    or 0
                )

                _state.update(
                    core1_status="success",
                    core1_error=None,
                    scanned=scanned,
                    owner_pending=0,
                    leagues_empty=snapshot.get(
                        "leagues_empty",
                        [],
                    ),
                    ready=scanned > 0,
                )

                if scanned == 0:
                    log += (
                        "\nCORE 1 NOT READY: zero fixtures scanned. "
                        "Check API keys, plan limits, league data, "
                        "and the requested date window.\n"
                    )
                else:
                    log += (
                        "\nCORE 1 COMPLETE: "
                        f"{scanned} fixture(s) scanned. "
                        "The checked=1 flag did not block "
                        "upcoming fixtures.\n"
                    )

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

    # =========================================================
    # CORE 2: INDEPENDENT UNDER 3.5 MODEL
    # =========================================================

    log += _run_under35()

except Exception as exc:
    log += "\nSERVER RUN ERROR: " + str(exc) + "\n"

finally:
    _state.update(
        waiting=False,
        wait_seconds=0,
        running=False,
        finished_at=utc_now(),
        log=log[-12000:],
    )

def _worker():
try:
_do_run()
finally:
_lock.release()

@app.get("/")
def index():
return send_from_directory(
str(BASE),
"console.html",
)

@app.get("/api/data")
def data():
snapshot = _read_snapshot()

if snapshot is None:
    return jsonify({
        "error": (
            "No valid Core 1 snapshot yet. "
            "Tap RUN to start the model."
        )
    }), 404

return jsonify(snapshot)

@app.get("/api/under35")
def under35():
snapshot = read_json(UNDER35)

if snapshot is None:
    return jsonify({
        "error": (
            "No valid Core 2 data yet. "
            "Run the model first."
        )
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
    scanned=0,
    leagues_empty=[],
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
    "message": (
        "Core 1 and Core 2 run started. "
        "New fixtures, if any, receive a five-minute review window."
    ),
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
            "slip": (
                "Could not read picks from GitHub: "
                + str(exc)
            ),
        })

try:
    subprocess.run(
        [
            "python",
            "barbadox_core.py",
            "slip",
        ],
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

if name == "main":
app.run(
host="0.0.0.0",
port=int(os.environ.get("PORT", 5000)),
)
