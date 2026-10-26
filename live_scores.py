#!/usr/bin/env python3
"""
BARBADOX live-score API, backed by football-data.org.

The browser sends dates belonging to pending active and archived slips.
Dates are grouped into seven-day ranges, cached independently, and
processed in batches so old pending slips can be graded without wasting
the provider quota on every browser poll.

Render runs this module through server.py's registered blueprint.
"""

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request


live_scores_bp = Blueprint("barbadox_live_scores", __name__)

FOOTBALL_DATA_URL = "https://api.football-data.org/v4/matches"
LIVE_COMPETITIONS = "PL,PD,FL1,BL1,SA"

LIVE_CACHE_SECONDS = 900
LIVE_ERROR_CACHE_SECONDS = 3600
LIVE_MAX_FETCHES_PER_REQUEST = 3

# A separate cache entry for each seven-day range.
LIVE_MATCH_CACHE = {}
_live_lock = threading.RLock()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _football_data_key():
    """Read the football-data.org token without exposing it to the browser."""
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
    """Map football-data.org statuses to the codes expected by the tracker."""
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
    """Normalize one provider match without inventing missing scores."""
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

        if (
            home_score is not None and home_score < 0
        ) or (
            away_score is not None and away_score < 0
        ):
            home_score = None
            away_score = None

    except (TypeError, ValueError, OverflowError):
        home_score = None
        away_score = None

    kickoff = str(match.get("utcDate") or "")
    timestamp = None

    if kickoff:
        try:
            parsed = datetime.fromisoformat(
                kickoff.replace("Z", "+00:00")
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            timestamp = int(parsed.timestamp())

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
        headers={
            "X-Auth-Token": api_key,
        },
        timeout=18,
    )

    if response.status_code != 200:
        messages = {
            401: (
                "Authentication failed. Check FOOTBALL_DATA_KEY "
                "in Render."
            ),
            403: (
                "football-data.org denied this date range or competition "
                "on the current plan."
            ),
            429: (
                "football-data.org rate limit reached; score refresh "
                "is paused temporarily."
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

    matches = (
        payload.get("matches")
        if isinstance(payload, dict)
        else None
    )

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
    """Return a validated ISO calendar date or None."""
    if not isinstance(value, str) or len(value) != 10:
        return None

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

    return parsed if parsed.isoformat() == value else None


def _week_start(day):
    """Return the Monday starting the requested calendar week."""
    return day - timedelta(days=day.weekday())


@live_scores_bp.route("/api/live-scores", methods=["GET", "POST"])
def live_scores():
    """
    Return current fixtures and match dates required by pending slips.

    POST body:
        {"dates": ["YYYY-MM-DD", ...]}

    Up to three uncached or stale seven-day ranges are fetched per request.
    Remaining ranges stay queued for subsequent polls.

    Failed provider ranges are cached for longer to prevent rapid retries
    from exhausting the API quota.
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
            "updatedAt": _utc_now(),
            "provider": "football-data.org",
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

    # Maintain coverage for recent results, today's matches, and
    # upcoming fixtures, even when the browser has no pending slips.
    current_days = {
        today + timedelta(days=offset)
        for offset in range(-2, 8)
    }

    requested_days = set()

    for raw in raw_dates:
        parsed = _date_from_client(raw)

        if parsed:
            requested_days.add(parsed)

    current_weeks = {
        _week_start(day)
        for day in current_days
    }

    requested_weeks = {
        _week_start(day)
        for day in requested_days
    }

    # Current/near-future windows come first. Historical windows follow,
    # allowing the backlog to progress on subsequent page polls.
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
            date_to = (
                week + timedelta(days=6)
            ).isoformat()

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
                # Preserve the uncached/stale range for the next poll.
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
        current_time = time.time()

        for week in ordered_weeks:
            key = (
                week.isoformat()
                + ":"
                + (
                    week + timedelta(days=6)
                ).isoformat()
            )

            entry = LIVE_MATCH_CACHE.get(key)

            if (
                entry is None
                or current_time - entry.get("at", 0)
                >= entry.get("ttl", LIVE_CACHE_SECONDS)
            ):
                waiting += 1

    fixtures = sorted(
        fixtures_by_id.values(),
        key=lambda item: (
            item.get("timestamp")
            if isinstance(
                item.get("timestamp"),
                (int, float),
            )
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
        "updatedAt": _utc_now(),
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
