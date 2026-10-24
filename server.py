#!/usr/bin/env python3
"""
BARBADOX Match Intelligence System — Flask server.

Core 1: Over 1.5 goals.
Core 2: Under 3.5 goals.

Includes:
- Core 1 and Core 2 execution.
- Five-minute review window for new context rows.
- Existing dashboard API routes.
- Live fixtures and scores from API-Football.
- Nigeria-time fixture requests.
- Cached live-score results.
- Safe handling of provider errors.
- Persistent slips history backed by CSV and GitHub.

Required Render environment variables:
    FOOTBALL_DATA_KEY
    API_FOOTBALL_KEY
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

from flask import Flask, jsonify, send_from_directory

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

LIVE_API_URL = "https://v3.football.api-sports.io/fixtures"
# Free API-Football tiers are typically ~100 req/day. 15-minute cache
# keeps upstream calls under ~96/day even with continuous client polling.
LIVE_CACHE_SECONDS = 900
# When the provider returns a rate-limit or hard error, hold that result
# longer so we do not burn the remaining quota on retries.
LIVE_ERROR_CACHE_SECONDS = 3600
LIVE_TIMEZONE = "Africa/Lagos"

_live_cache = {
    "time": 0,
    "data": None,
    "ttl": LIVE_CACHE_SECONDS,
}

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


def _api_error_text(payload):
    """Extract a readable error without exposing credentials."""
    if not isinstance(payload, dict):
        return "The provider returned an invalid response."

    errors = payload.get("errors")

    if not errors:
        return None

    if isinstance(errors, dict):
        parts = [
            f"{name}: {value}"
            for name, value in errors.items()
            if value not in (None, "", [], {})
        ]

        return "; ".join(parts) or "Unspecified API-Football error."

    if isinstance(errors, list):
        parts = [str(value) for value in errors if value]

        return "; ".join(parts) or "Unspecified API-Football error."

    return str(errors)


def _is_date_parameter_error(message):
    """
    Detect provider date-parameter errors.

    If a range request is rejected because of its date parameters,
    the live-score code can retry using individual dates.
    """
    if not message:
        return False

    value = message.lower()

    date_fields = (
        "from:",
        "to:",
        "timezone:",
        "the from field",
        "the to field",
        "the timezone field",
    )

    return any(field in value for field in date_fields)


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
# LIVE SCORES
# ---------------------------------------------------------

def _request_api_football(key, params):
    """Make one API-Football request and validate its JSON response."""
    response = requests.get(
        LIVE_API_URL,
        headers={"x-apisports-key": key},
        params=params,
        timeout=20,
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("API-Football response was not a JSON object.")

    return payload


def _normalise_fixtures(payload):
    """Convert API-Football fixtures to the console's expected format."""
    fixtures = []

    for item in payload.get("response", []):
        if not isinstance(item, dict):
            continue

        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        status = fixture.get("status") or {}

        home = teams.get("home") or {}
        away = teams.get("away") or {}

        short_status = status.get("short")

        fixtures.append({
            "id": fixture.get("id"),
            "date": fixture.get("date"),
            "timestamp": fixture.get("timestamp"),
            "home": home.get("name"),
            "away": away.get("name"),
            "home_goals": goals.get("home"),
            "away_goals": goals.get("away"),
            "status": short_status,
            "status_long": status.get("long"),
            "elapsed": status.get("elapsed"),
            "finished": short_status in ("FT", "AET", "PEN"),
        })

    return fixtures


def _fetch_fixtures_by_date(key, start_date, end_date):
    """
    Fallback method: query one calendar date at a time.

    This is used only if the provider rejects the date-range request
    with a parameter error.

    The primary request is preferred because it uses fewer API
    requests. The fallback merges results by fixture ID to avoid
    duplicate fixtures.
    """
    merged = {}
    errors = []

    current_date = start_date

    while current_date <= end_date:
        params = {
            "date": current_date.isoformat(),
            "timezone": LIVE_TIMEZONE,
        }

        try:
            payload = _request_api_football(key, params)

            provider_error = _api_error_text(payload)

            if provider_error:
                # If the provider also rejects timezone, retry without it.
                if "timezone" in provider_error.lower():
                    payload = _request_api_football(
                        key,
                        {"date": current_date.isoformat()},
                    )

                    provider_error = _api_error_text(payload)

            if provider_error:
                errors.append(
                    current_date.isoformat() + ": " + provider_error
                )

            else:
                for item in _normalise_fixtures(payload):
                    fixture_id = item.get("id")

                    if fixture_id is not None:
                        merged[str(fixture_id)] = item

        except requests.RequestException as exc:
            errors.append(
                current_date.isoformat()
                + ": request failed ("
                + type(exc).__name__
                + ")"
            )

        except (ValueError, TypeError, AttributeError) as exc:
            errors.append(
                current_date.isoformat()
                + ": invalid response ("
                + type(exc).__name__
                + ")"
            )

        current_date += timedelta(days=1)

    if errors and not merged:
        return {
            "ok": False,
            "configured": True,
            "error": (
                "API-Football date-by-date fallback failed. "
                + " | ".join(errors[:3])
            ),
            "fixtures": [],
            "updated_at": utc_now(),
        }

    return {
        "ok": True,
        "configured": True,
        "error": None,
        "fixtures": sorted(
            merged.values(),
            key=lambda item: (
                item.get("timestamp")
                if isinstance(item.get("timestamp"), (int, float))
                else 0
            ),
        ),
        "updated_at": utc_now(),
        "fallback_used": True,
        "fallback_warnings": errors[:5],
    }


def _api_football_request():
    """
    Fetch upcoming, live, and recently finished fixtures.

    The API key stays on the server. If the range query is rejected
    for date-parameter validation, retry by calendar date.
    """
    key = (
        os.getenv("API_FOOTBALL_KEY")
        or os.getenv("APIFOOTBALL_KEY")
        or ""
    ).strip()

    if not key:
        return {
            "ok": False,
            "configured": False,
            "error": (
                "API_FOOTBALL_KEY (or APIFOOTBALL_KEY) is not configured "
                "in Render. Add the environment variable and redeploy."
            ),
            "fixtures": [],
            "updated_at": utc_now(),
        }

    today = datetime.now(timezone.utc).date()

    start_date = today - timedelta(days=2)
    end_date = today + timedelta(days=SCAN_DAYS)

    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timezone": LIVE_TIMEZONE,
    }

    try:
        payload = _request_api_football(key, params)

        provider_error = _api_error_text(payload)

        if provider_error:
            print(
                "API-Football provider error:",
                provider_error[:1000],
            )

            if _is_date_parameter_error(provider_error):
                print(
                    "Retrying API-Football by date because "
                    "the date-range parameters were rejected."
                )

                return _fetch_fixtures_by_date(
                    key,
                    start_date,
                    end_date,
                )

            return {
                "ok": False,
                "configured": True,
                "error": "API-Football error: " + provider_error[:350],
                "provider_error": provider_error[:1000],
                "fixtures": [],
                "updated_at": utc_now(),
            }

        fixtures = _normalise_fixtures(payload)

        return {
            "ok": True,
            "configured": True,
            "error": None,
            "fixtures": fixtures,
            "updated_at": utc_now(),
        }

    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)

        status_code = (
            getattr(response, "status_code", None)
            if response is not None
            else None
        )

        # HTTP 4xx/5xx errors are not silently presented as valid scores.
        detail = (
            f"API-Football returned HTTP {status_code}."
            if status_code
            else "API-Football rejected the request."
        )

        print("Live-score HTTP error:", detail)

        return {
            "ok": False,
            "configured": True,
            "error": detail,
            "fixtures": [],
            "updated_at": utc_now(),
        }

    except requests.RequestException as exc:
        print(
            "Live-score network failure:",
            type(exc).__name__,
            str(exc)[:500],
        )

        return {
            "ok": False,
            "configured": True,
            "error": (
                "Network timeout or connection error "
                "while contacting API-Football."
            ),
            "fixtures": [],
            "updated_at": utc_now(),
        }

    except (ValueError, TypeError, AttributeError) as exc:
        print(
            "Invalid live-score response:",
            type(exc).__name__,
            str(exc)[:500],
        )

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

    Successful payloads are refreshed at most once per LIVE_CACHE_SECONDS.
    Rate-limit and other provider errors are held for LIVE_ERROR_CACHE_SECONDS
    so the free daily quota is not exhausted by client polls.
    """
    now = time.time()

    with _live_lock:
        cached = _live_cache["data"]
        ttl = _live_cache.get("ttl") or LIVE_CACHE_SECONDS

        if cached is not None and now - _live_cache["time"] < ttl:
            status_code = 200 if cached.get("ok") else 502
            return jsonify(cached), status_code

        data = _api_football_request()

        # Detect rate-limit / quota messages and back off hard.
        err_text = str(
            data.get("error")
            or data.get("provider_error")
            or data.get("message")
            or ""
        ).lower()
        is_rate_limited = (
            not data.get("ok")
            and (
                "rate" in err_text
                or "limit" in err_text
                or "quota" in err_text
                or "reached the request" in err_text
            )
        )

        _live_cache["time"] = time.time()
        _live_cache["data"] = data
        _live_cache["ttl"] = (
            LIVE_ERROR_CACHE_SECONDS
            if (not data.get("ok"))
            else LIVE_CACHE_SECONDS
        )
        if is_rate_limited:
            _live_cache["ttl"] = LIVE_ERROR_CACHE_SECONDS

        # Surface how long the client should wait before asking again.
        data = dict(data)
        data["cacheSeconds"] = _live_cache["ttl"]
        data["rateLimited"] = bool(is_rate_limited)

        status_code = 200 if data.get("ok") else 502

        return jsonify(data), status_code


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
