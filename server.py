#!/usr/bin/env python3
"""
BARBADOX Match Intelligence System — Flask server.

Core 1: Over 1.5 goals.
Core 2: Under 3.5 goals.

Includes:
- Core 1 and Core 2 execution.
- Five-minute review window for new context rows.
- Existing dashboard API routes.
- Live fixtures and scores from football-data.org.
- Cached live-score results.
- Safe handling of provider errors.
- Persistent slips history backed by CSV and GitHub.

Required Render environment variables:
    FOOTBALL_DATA_KEY
    GITHUB_TOKEN
    GITHUB_REPO
    GITHUB_BRANCH
"""

import json
import os
import subprocess
import threading
import time

import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import gh_sync
import slips_tracker
import slips_history


BASE = Path(__file__).resolve().parent

SNAPSHOT = BASE / "docs" / "data.json"
UNDER35 = BASE / "docs" / "under35.json"
SLIP = BASE / "slip.md"

app = Flask(__name__)

# Persistent slips-history API and frontend JavaScript.
app.register_blueprint(slips_history.slips_history_bp)

_lock = threading.Lock()

WAIT_SECONDS = 300
CORE1_TIMEOUT = 1200
CORE2_TIMEOUT = 900
SCAN_DAYS = 7

# football-data.org is the active live-score provider.
FOOTBALL_DATA_URL = "https://api.football-data.org/v4/matches"
LIVE_COMPETITIONS = "PL,PD,FL1,BL1,SA"

LIVE_CACHE_SECONDS = 900
LIVE_ERROR_CACHE_SECONDS = 3600

# Process no more than three stale/new weekly score windows per request.
# Older windows are gradually processed by subsequent polls.
LIVE_MAX_FETCHES_PER_REQUEST = 3

LIVE_MATCH_CACHE = {}

_live_lock = threading.Lock()


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------
# MODEL RUNNER
# ---------------------------------------------------------

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
                        + name
                        + ": "
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
# LIVE SCORES — FOOTBALL-DATA.ORG
# ---------------------------------------------------------

def _football_data_key():
    """Read the server-side football-data.org token."""
    for name in (
        "FOOTBALL_DATA_KEY",
        "FOOTBALL_DATA_TOKEN",
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_API_KEY",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _football_status(status):
    mapping = {
        "FINISHED": ("FT", "Full Time"),
        "AWARDED": ("AWD", "Awarded"),
        "IN_PLAY": ("LIVE", "In Play"),
        "PAUSED": ("HT", "Halftime"),
        "SUSPENDED": ("SUSP", "Suspended"),
        "POSTPONED": ("PST", "Postponed"),
        "CANCELLED": ("CANC", "Cancelled"),
        "TIMED": ("NS", "Not Started"),
        "SCHEDULED": ("NS", "Not Started"),
        "TBD": ("NS", "Not Started"),
    }
    return mapping.get(
        str(status or "").upper(),
        ("NS", "Not Started"),
    )


def _football_fixture(match):
    """Normalize a football-data.org match without inventing scores."""
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}

    home = home_team.get("name")
    away = away_team.get("name")

    if not home or not away:
        return None

    competition = match.get("competition") or {}
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}

    home_score = full_time.get("home")
    away_score = full_time.get("away")

    try:
        if home_score is not None:
            home_score = int(home_score)

        if away_score is not None:
            away_score = int(away_score)

    except (TypeError, ValueError):
        home_score = None
        away_score = None

    kickoff = str(match.get("utcDate") or "")
    timestamp = None

    if kickoff:
        try:
            timestamp = int(
                datetime.fromisoformat(
                    kickoff.replace("Z", "+00:00")
                ).timestamp()
            )
        except (TypeError, ValueError, OverflowError):
            timestamp = None

    status, status_text = _football_status(match.get("status"))

    return {
        "id": match.get("id"),
        "date": kickoff[:10],
        "kickoff": kickoff,
        "timestamp": timestamp,
        "home": home,
        "away": away,
        "homeScore": home_score,
        "awayScore": away_score,
        "status": status,
        "statusText": status_text,
        "league": competition.get("name", ""),
        "elapsed": None,
    }


def _football_data_fetch(date_from, date_to, api_key):
    """Fetch one seven-day range from football-data.org."""
    response = requests.get(
        FOOTBALL_DATA_URL,
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
            "competitions": LIVE_COMPETITIONS,
        },
        headers={"X-Auth-Token": api_key},
        timeout=18,
    )

    if response.status_code != 200:
        messages = {
            401: (
                "Authentication failed. Check FOOTBALL_DATA_KEY "
                "in Render."
            ),
            403: (
                "football-data.org denied this date range or "
                "competition on the current plan."
            ),
            429: (
                "football-data.org rate limit reached; score "
                "refresh is paused temporarily."
            ),
        }

        raise RuntimeError(
            messages.get(
                response.status_code,
                "football-data.org returned HTTP "
                + str(response.status_code)
                + ".",
            )
        )

    payload = response.json()
    matches = payload.get("matches") if isinstance(payload, dict) else None

    if not isinstance(matches, list):
        raise ValueError(
            "football-data.org returned an unexpected response shape."
        )

    fixtures = []

    for match in matches:
        if isinstance(match, dict):
            fixture = _football_fixture(match)

            if fixture:
                fixtures.append(fixture)

    return fixtures


def _date_from_client(value):
    """Validate an ISO calendar date received from the browser."""
    if not isinstance(value, str) or len(value) != 10:
        return None

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

    return parsed if parsed.isoformat() == value else None


@app.route("/api/live-scores", methods=["GET", "POST"])
def live_scores():
    """
    Return current fixtures and historical windows required by pending slips.

    The browser sends leg dates from the active tracker and permanent archive.
    Each week is cached independently. At most three stale/new weeks are
    fetched per poll to protect the provider quota; later polls handle backlog.
    """
    api_key = _football_data_key()

    if not api_key:
        return jsonify({
            "ok": False,
            "configured": False,
            "message": (
                "Add FOOTBALL_DATA_KEY in Render → Environment."
            ),
            "fixtures": [],
            "updatedAt": utc_now(),
        }), 200

    body = (
        request.get_json(silent=True)
        if request.method == "POST"
        else {}
    )
    body = body if isinstance(body, dict) else {}

    raw_dates = body.get("dates", [])

    if not isinstance(raw_dates, list):
        raw_dates = []

    today = datetime.now(timezone.utc).date()

    # Keep current/recent/upcoming fixtures available for the UI.
    current_days = {
        today + timedelta(days=n)
        for n in range(-2, 8)
    }

    requested_days = set()

    for raw in raw_dates[:500]:
        parsed = _date_from_client(raw)

        if parsed:
            requested_days.add(parsed)

    def week_start(day):
        return day - timedelta(days=day.weekday())

    current_weeks = {
        week_start(day)
        for day in current_days
    }

    requested_weeks = {
        week_start(day)
        for day in requested_days
    }

    ordered_weeks = (
        sorted(current_weeks)
        + sorted(requested_weeks - current_weeks)
    )

    warnings = []
    fixtures_by_id = {}

    fetched_this_request = 0
    successful_windows = 0

    with _live_lock:
        now = time.time()

        for week in ordered_weeks:
            date_from = week.isoformat()
            date_to = (week + timedelta(days=6)).isoformat()

            cache_key = date_from + ":" + date_to
            cached = LIVE_MATCH_CACHE.get(cache_key)

            valid = (
                cached is not None
                and now - cached.get("at", 0)
                < cached.get("ttl", LIVE_CACHE_SECONDS)
            )

            if (
                not valid
                and fetched_this_request < LIVE_MAX_FETCHES_PER_REQUEST
            ):
                fetched_this_request += 1

                try:
                    cached = {
                        "at": time.time(),
                        "ttl": LIVE_CACHE_SECONDS,
                        "fixtures": _football_data_fetch(
                            date_from,
                            date_to,
                            api_key,
                        ),
                        "error": None,
                        "ok": True,
                    }

                except (
                    requests.RequestException,
                    ValueError,
                    TypeError,
                    RuntimeError,
                ) as exc:
                    cached = {
                        "at": time.time(),
                        "ttl": LIVE_ERROR_CACHE_SECONDS,
                        "fixtures": [],
                        "error": str(exc)[:350],
                        "ok": False,
                    }

                LIVE_MATCH_CACHE[cache_key] = cached
                valid = True

            elif not valid:
                # Leave remaining ranges queued for a subsequent poll.
                cached = None

            if not valid or cached is None:
                continue

            if cached.get("ok"):
                successful_windows += 1

                for fixture in cached.get("fixtures", []):
                    ident = fixture.get("id")

                    if ident is None:
                        ident = "|".join((
                            str(fixture.get("date") or ""),
                            str(
                                fixture.get("home") or ""
                            ).casefold(),
                            str(
                                fixture.get("away") or ""
                            ).casefold(),
                        ))

                    fixtures_by_id[str(ident)] = fixture

            elif cached.get("error"):
                warnings.append(
                    date_from
                    + "–"
                    + date_to
                    + ": "
                    + cached["error"]
                )

        waiting = 0

        for week in ordered_weeks:
            key = (
                week.isoformat()
                + ":"
                + (week + timedelta(days=6)).isoformat()
            )

            entry = LIVE_MATCH_CACHE.get(key)

            if (
                entry is None
                or time.time() - entry.get("at", 0)
                >= entry.get("ttl", LIVE_CACHE_SECONDS)
            ):
                waiting += 1

    fixtures = sorted(
        fixtures_by_id.values(),
        key=lambda item: (
            item.get("timestamp")
            if isinstance(item.get("timestamp"), (int, float))
            else 0
        ),
    )

    if waiting:
        warnings.append(
            str(waiting)
            + " score window(s) are queued for the next refresh "
            "to protect the API quota."
        )

    payload = {
        "ok": bool(successful_windows) or not warnings,
        "configured": True,
        "error": None,
        "message": (
            warnings[0]
            if warnings and not successful_windows
            else None
        ),
        "updatedAt": utc_now(),
        "cacheSeconds": LIVE_CACHE_SECONDS,
        "provider": "football-data.org",
        "fixtures": fixtures,
        "historyWarnings": warnings[:8],
        "queuedWindows": waiting,
    }

    if not successful_windows and warnings and not waiting:
        payload["ok"] = False
        return jsonify(payload), 502

    return jsonify(payload), 200


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


@app.get("/live_scores.js")
def live_scores_script():
    """Serve the client-side live-score + archive-grading script."""
    return send_from_directory(
        str(BASE),
        "live_scores.js",
        mimetype="application/javascript",
    )


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

    return jsonify({
        "ok": True,
        **slips_tracker.tracker_data(),
    })


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
