#!/usr/bin/env python3
"""
BARBADOX console server.

Core 1: Over 1.5 goals.
Core 2: Under 3.5 goals.

Includes live scores for the existing slips tracker.
Configure APIFOOTBALL_KEY in the Render environment.
"""

import json
import os
import subprocess
import threading
import time
import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory

import gh_sync
import slips_tracker


BASE = Path(__file__).resolve().parent

SNAPSHOT = BASE / "docs" / "data.json"
UNDER35 = BASE / "docs" / "under35.json"
SLIP = BASE / "slip.md"

app = Flask(__name__)
_lock = threading.Lock()

WAIT_SECONDS = 300
CORE1_TIMEOUT = 1200
CORE2_TIMEOUT = 900
SCAN_DAYS = 7

LIVE_API_URL = "https://v3.football.api-sports.io/fixtures"
LIVE_CACHE_SECONDS = 60

_live_cache = {
    "time": 0,
    "data": None,
}

_live_lock = threading.Lock()


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
    "ok": None,
    "ready": False,
    "owner_pending": 0,
    "context_added": 0,
    "scanned": 0,
    "leagues_empty": [],
    "core1_status": "idle",
    "core1_finished_at": None,
    "core1_error": None,
    "core2_status": "idle",
    "core2_model_status": None,
    "core2_error": None,
    "core2_finished_at": None,
    "core2_generated_at": None,
    "core2_scanned": 0,
    "core2_qualified": 0,
    "core2_threshold": 0.60,
}


def _export(defer_picks=False):
    command = [
        "python",
        "export_snapshot.py",
        "--days",
        str(SCAN_DAYS),
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
    """Run Core 2 independently of Core 1."""
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
        error = "Could not remove old Core 2 output: " + str(exc)
        _state.update(
            core2_status="failed",
            core2_error=error,
            core2_finished_at=utc_now(),
        )
        return "\n--- CORE 2 FAILED ---\n" + error + "\n"

    try:
        proc = subprocess.run(
            [
                "python",
                "barbadox_under35.py",
                "--days",
                str(SCAN_DAYS),
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
            f for f in fixtures
            if isinstance(f, dict)
            and f.get("decision") == "qualified"
        ]

        _state.update(
            core2_status="success",
            core2_model_status=model_status,
            core2_error=None,
            core2_generated_at=snapshot.get("generated_at"),
            core2_scanned=len(fixtures),
            core2_qualified=len(qualified),
            core2_threshold=snapshot.get("threshold", 0.60),
            core2_finished_at=utc_now(),
        )

        log += (
            "\nCORE 2 VERIFIED: "
            + str(len(fixtures))
            + " fixtures scanned; "
            + str(len(qualified))
            + " qualified; threshold="
            + str(_state["core2_threshold"])
            + ".\n"
        )

        return log

    except subprocess.TimeoutExpired:
        error = (
            "Core 2 timed out after "
            + str(CORE2_TIMEOUT)
            + " seconds."
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
    """Run Core 1, then attempt Core 2 independently."""
    log = ""

    try:
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
                added = int(snapshot.get("context_added", 0) or 0)

                _state["context_added"] = added
                _state["owner_pending"] = 0

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
                        + str(added)
                        + " NEW FIXTURE(S) ADDED TO context.csv.\n"
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
                        ) or 0
                    )

                    _state.update(
                        core1_status="success",
                        core1_error=None,
                        scanned=scanned,
                        owner_pending=0,
                        leagues_empty=snapshot.get("leagues_empty", []),
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
                            + str(scanned)
                            + " fixture(s) scanned. "
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

        log += _run_under35()

        if gh_sync.enabled():
            for name, path in (
                ("docs/data.json", SNAPSHOT),
                ("docs/under35.json", UNDER35),
            ):
                if not path.exists():
                    continue

                try:
                    gh_sync.push_snapshot(
                        name,
                        "Barbadox: persist console snapshot",
                    )
                    log += "\nSnapshot persisted: " + name + "\n"
                except Exception as exc:
                    log += (
                        "\nSnapshot persistence failed for "
                        + name + ": "
                        + str(exc)
                        + "\n"
                    )
        else:
            log += (
                "\nSnapshot persistence skipped: "
                "GITHUB_TOKEN is not configured.\n"
            )

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


def _startup_restore():
    if not gh_sync.enabled():
        return

    for name, path in (
        ("docs/data.json", SNAPSHOT),
        ("docs/under35.json", UNDER35),
    ):
        if path.exists():
            continue

        try:
            if gh_sync.pull(name):
                print("Restored " + name + " from GitHub.")
        except Exception as exc:
            print("Could not restore " + name + ": " + str(exc))


_startup_restore()


# ---------------------------------------------------------
# LIVE SCORES
# ---------------------------------------------------------

def _api_football_request():
    """
    Fetch fixtures from API-Football.

    API key remains on the server and is never sent to console.html.
    """
    API_KEY = os.getenv("API_FOOTBALL_KEY")

    if not key:
        return {
            "ok": False,
            "configured": False,
            "error": "APIFOOTBALL_KEY is not configured in Render.",
            "fixtures": [],
            "updated_at": utc_now(),
        }

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=2)
    end_date = today + timedelta(days=SCAN_DAYS)

    headers = {"x-apisports-key": key}
    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timezone": "Africa/Lagos",
    }

    try:
        response = requests.get(
            LIVE_API_URL,
            headers=headers,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("errors"):
            return {
                "ok": False,
                "configured": True,
                "error": "API-Football returned an API error.",
                "fixtures": [],
                "updated_at": utc_now(),
            }

        fixtures = []

        for item in payload.get("response", []):
            fixture = item.get("fixture") or {}
            teams = item.get("teams") or {}
            goals = item.get("goals") or {}
            status = fixture.get("status") or {}

            home = teams.get("home") or {}
            away = teams.get("away") or {}

            # Do not invent a score for an unscored fixture.
            hg = goals.get("home")
            ag = goals.get("away")

            fixtures.append({
                "id": fixture.get("id"),
                "date": fixture.get("date"),
                "timestamp": fixture.get("timestamp"),
                "home": home.get("name"),
                "away": away.get("name"),
                "home_goals": hg,
                "away_goals": ag,
                "status": status.get("short"),
                "status_long": status.get("long"),
                "elapsed": status.get("elapsed"),
                "finished": status.get("short") in (
                    "FT", "AET", "PEN"
                ),
            })

        return {
            "ok": True,
            "configured": True,
            "error": None,
            "fixtures": fixtures,
            "updated_at": utc_now(),
        }

    except requests.RequestException as exc:
        # Do not return the API key or request headers to the client.
        print("Live-score request failed:", str(exc))
        return {
            "ok": False,
            "configured": True,
            "error": "Could not retrieve live scores from the provider.",
            "fixtures": [],
            "updated_at": utc_now(),
        }

    except (ValueError, TypeError) as exc:
        print("Invalid live-score response:", str(exc))
        return {
            "ok": False,
            "configured": True,
            "error": "The live-score provider returned invalid data.",
            "fixtures": [],
            "updated_at": utc_now(),
        }


@app.get("/api/live-scores")
def live_scores():
    """
    Cached live-score endpoint.
    Refreshes provider data at most once per 60 seconds.
    """
    now = time.time()

    with _live_lock:
        cached = _live_cache["data"]

        if (
            cached is not None
            and now - _live_cache["time"] < LIVE_CACHE_SECONDS
        ):
            return jsonify(cached)

        data = _api_football_request()

        _live_cache["time"] = time.time()
        _live_cache["data"] = data

        return jsonify(data)


# ---------------------------------------------------------
# EXISTING CONSOLE ROUTES
# ---------------------------------------------------------

@app.get("/")
def index():
    """Serve the main console."""
    return send_from_directory(str(BASE), "console.html")


@app.get("/slips")
def slips_page():
    return send_from_directory(str(BASE), "slips.html")


@app.get("/api/slipstracker")
def slipstracker():
    if gh_sync.enabled():
        try:
            gh_sync.pull("picks.csv")
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "Could not read picks from GitHub: " + str(exc),
            }), 500

    try:
        subprocess.run(
            ["python", "barbadox_slips.py"],
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": "Slip tracking refresh failed: " + str(exc),
        }), 500

    return jsonify({"ok": True, **slips_tracker.tracker_data()})


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

    try:
        threading.Thread(
            target=_worker,
            daemon=True,
        ).start()
    except Exception as exc:
        _state.update(
            running=False,
            core1_status="failed",
            core1_error=str(exc),
        )
        _lock.release()

        return jsonify({
            "ok": False,
            "message": "Could not start model run: " + str(exc),
        }), 500

    return jsonify({
        "ok": True,
        "message": (
            "Core 1 and Core 2 run started. "
            "Both scan the next 7 days. "
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


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
    )
