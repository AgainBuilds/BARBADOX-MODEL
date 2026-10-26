"""
BARBADOX Live-Score API (football-data.org edition)
Provides football scores to the existing console.html slips tracker.

Drop-in replacement for the API-Football version. The JSON payload
served to live_scores.js is identical in shape, so the tracker,
the archive and auto-grading need no frontend changes.

Uses the SAME free football-data.org key the model cores already
use for fixtures and results. API-Football is no longer required
for score tracking.

Required Render environment variable (already set for the model):
    FOOTBALL_DATA_KEY

Status mapping (football-data.org -> tracker codes):
    FINISHED  -> FT      (graded as finished)
    AWARDED   -> AWD
    IN_PLAY   -> LIVE
    PAUSED    -> HT
    SUSPENDED -> SUSP
    POSTPONED -> PST
    CANCELLED -> CANC
    SCHEDULED / TIMED -> NS

Free-tier note: football-data.org publishes full-time scores
reliably but does not expose in-play minute-by-minute scores, so
matches show "LIVE" with the final score appearing at full time.
Slip grading only needs full-time results, so this is safe.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, send_from_directory
from pathlib import Path


live_scores_bp = Blueprint("barbadox_live_scores", __name__)

ROOT = Path(__file__).resolve().parent

CACHE = {
    "at": 0.0,
    "ttl": CACHE_SECONDS,
    "payload": None,
}

API = "https://api.football-data.org/v4/matches"

# 15-minute cache keeps upstream calls far under the free-tier
# limit of 10 requests/minute (2 calls per cache cycle).
CACHE_SECONDS = 900

# On provider errors (rate limit, outage) hold the result longer so
# the remaining quota is not burned on retries.
ERROR_CACHE_SECONDS = 3600

# Match window: today - 2 days (recently finished matches that may
# still need grading) up to today + 8 days (upcoming legs).
# football-data.org caps dateFrom/dateTo at 10 days per request,
# so the 11-day window is fetched in two calls.
LOOKBACK_DAYS = 2
LOOKAHEAD_DAYS = 8

# Top-5 leagues — the codes used across BARBADOX.
LEAGUE_CODES = ["PL", "PD", "FL1", "BL1", "SA"]

# football-data.org status -> tracker status codes
STATUS_MAP = {
    "FINISHED": ("FT", "Match Finished"),
    "AWARDED": ("AWD", "Awarded"),
    "IN_PLAY": ("LIVE", "In Play"),
    "PAUSED": ("HT", "Halftime"),
    "SUSPENDED": ("SUSP", "Suspended"),
    "POSTPONED": ("PST", "Postponed"),
    "CANCELLED": ("CANC", "Cancelled"),
}

STATUS_DEFAULT = ("NS", "Not Started")


def _api_key():
    """Read the football-data.org key, accepting the same aliases
    the model cores accept."""
    for name in (
        "FOOTBALL_DATA_KEY",
        "FOOTBALL_DATA_TOKEN",
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_API_KEY",
        "API_KEY",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _map_status(status):
    return STATUS_MAP.get(status, STATUS_DEFAULT)


def _fetch_window(api_key, date_from, date_to):
    """Fetch one date window (max 10 days) from football-data.org."""
    response = requests.get(
        API,
        params={
            "dateFrom": date_from,
            "dateTo": date_to,
        },
        headers={"X-Auth-Token": api_key},
        timeout=12,
    )

    if response.status_code != 200:
        message = (
            f"Football score provider HTTP {response.status_code}"
        )

        if response.status_code == 401:
            message += (
                ". Check FOOTBALL_DATA_KEY in Render → Environment."
            )
        elif response.status_code == 403:
            message += (
                ". The football-data.org plan does not cover "
                "one or more of the requested competitions."
            )
        elif response.status_code == 429:
            message += (
                ". Rate limit reached — retrying later."
            )

        raise ProviderError(message, response.status_code)

    try:
        data = response.json()
    except ValueError:
        raise ProviderError(
            "The provider returned an invalid response.",
            502,
        )

    matches = data.get("matches")

    if not isinstance(matches, list):
        raise ProviderError(
            "The provider returned an unexpected response shape.",
            502,
        )

    return matches


class ProviderError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status
        self.message = message


def _build_fixtures(matches):
    """Convert football-data.org matches into the tracker shape."""
    fixtures = []

    for match in matches:
        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}

        home_name = home_team.get("name")
        away_name = away_team.get("name")

        if not home_name or not away_name:
            continue

        competition = match.get("competition") or {}
        score = match.get("score") or {}

        # Full-time score: present only when the match finished.
        full_time = score.get("fullTime") or {}

        home_score = full_time.get("home")
        away_score = full_time.get("away")

        # Sanity-check the score values before serving them.
        if home_score is not None:
            home_score = int(home_score)
        if away_score is not None:
            away_score = int(away_score)

        status_code, status_text = _map_status(match.get("status"))

        kickoff = match.get("utcDate") or ""

        fixtures.append({
            "id": match.get("id"),
            "date": kickoff[:10],
            "kickoff": kickoff,
            "timestamp": (
                int(
                    datetime.fromisoformat(
                        kickoff.replace("Z", "+00:00")
                    ).timestamp()
                )
                if kickoff
                else None
            ),

            "league": competition.get("name", ""),

            "home": home_name,
            "away": away_name,

            "homeScore": home_score,
            "awayScore": away_score,

            "status": status_code,
            "statusText": status_text,

            # football-data.org does not provide the live minute.
            "elapsed": None,
        })

    return fixtures


@live_scores_bp.get("/live_scores.js")
def live_scores_script():
    """Serve the frontend live-score script."""
    return send_from_directory(
        str(ROOT),
        "live_scores.js",
        mimetype="application/javascript",
    )


@live_scores_bp.get("/api/live-scores")
def live_scores():
    """
    Return football fixtures, scores and match statuses.

    The API key remains on the server and is never sent to the
    browser.
    """

    api_key = _api_key()

    if not api_key:
        return jsonify({
            "ok": False,
            "configured": False,
            "message": (
                "Add FOOTBALL_DATA_KEY in Render → Environment."
            ),
            "fixtures": [],
        })

    now = time.time()

    # Reuse cached results to reduce API requests.
    if (
        CACHE["payload"] is not None
        and now - CACHE["at"] < CACHE["ttl"]
    ):
        return jsonify(CACHE["payload"])

    today = datetime.now(timezone.utc).date()

    # 11-day window split into two legal <=10-day requests.
    windows = [
        (
            (today - timedelta(days=LOOKBACK_DAYS)).isoformat(),
            (today + timedelta(days=3)).isoformat(),
        ),
        (
            (today + timedelta(days=4)).isoformat(),
            (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
        ),
    ]

    try:
        collected = []

        for date_from, date_to in windows:
            collected.extend(
                _fetch_window(api_key, date_from, date_to)
            )

        fixtures = _build_fixtures(collected)

        payload = {
            "ok": True,
            "configured": True,
            "updatedAt": datetime.now(
                timezone.utc
            ).isoformat(),

            "cacheSeconds": CACHE_SECONDS,
            "fixtures": fixtures,
        }

        CACHE["at"] = now
        CACHE["ttl"] = CACHE_SECONDS
        CACHE["payload"] = payload

        return jsonify(payload)

    except ProviderError as error:
        # Hold errors longer so the quota is not burned on retries.
        CACHE["at"] = time.time()
        CACHE["ttl"] = ERROR_CACHE_SECONDS
        CACHE["payload"] = {
            "ok": False,
            "configured": True,
            "message": error.message,
            "fixtures": [],
        }

        return jsonify(CACHE["payload"]), error.status

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ) as error:
        return jsonify({
            "ok": False,
            "configured": True,
            "message": (
                f"Live-score request failed: {error}"
            ),
            "fixtures": [],
        }), 502
