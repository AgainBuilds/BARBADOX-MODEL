"""
BARBADOX Live-Score API
Provides football scores to the existing console.html slips tracker.

Required Render environment variable:
    API_FOOTBALL_KEY
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import Blueprint, jsonify, send_from_directory


live_scores_bp = Blueprint("barbadox_live_scores", __name__)

ROOT = Path(__file__).resolve().parent

CACHE = {
    "at": 0.0,
    "payload": None,
}

CACHE_SECONDS = 900


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

    The API key remains on the server and is never sent to the browser.
    """

    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()

    if not api_key:
        return jsonify({
            "ok": False,
            "configured": False,
            "message": (
                "Add API_FOOTBALL_KEY in Render → Environment."
            ),
            "fixtures": [],
        })

    now = time.time()

    # Reuse cached results to reduce API requests.
    if (
        CACHE["payload"] is not None
        and now - CACHE["at"] < CACHE_SECONDS
    ):
        return jsonify(CACHE["payload"])

    today = datetime.now(timezone.utc).date()

    date_from = (today - timedelta(days=2)).isoformat()
    date_to = (today + timedelta(days=8)).isoformat()

    try:
        response = requests.get(
            "https://v3.football.api-sports.io/fixtures",
            params={
                "from": date_from,
                "to": date_to,
                "timezone": "Africa/Lagos",
            },
            headers={
                "x-apisports-key": api_key,
            },
            timeout=12,
        )

        if response.status_code != 200:
            message = (
                f"Football score provider HTTP "
                f"{response.status_code}"
            )

            if response.status_code in (401, 403):
                message += (
                    ". Check the API key and your API plan."
                )

            return jsonify({
                "ok": False,
                "configured": True,
                "message": message,
                "fixtures": [],
            }), 502

        data = response.json()

        if data.get("errors"):
            return jsonify({
                "ok": False,
                "configured": True,
                "message": (
                    "Provider error: "
                    + json.dumps(data["errors"])
                ),
                "fixtures": [],
            }), 502

        fixtures = []

        for item in data.get("response", []):
            fixture = item.get("fixture") or {}
            teams = item.get("teams") or {}
            goals = item.get("goals") or {}
            fixture_status = fixture.get("status") or {}

            home = teams.get("home") or {}
            away = teams.get("away") or {}

            home_name = home.get("name")
            away_name = away.get("name")

            if not home_name or not away_name:
                continue

            kickoff = fixture.get("date") or ""

            fixtures.append({
                "id": fixture.get("id"),
                "date": kickoff[:10],
                "kickoff": kickoff,
                "timestamp": fixture.get("timestamp"),

                "league": (
                    item.get("league") or {}
                ).get("name", ""),

                "home": home_name,
                "away": away_name,

                "homeScore": goals.get("home"),
                "awayScore": goals.get("away"),

                "status": fixture_status.get(
                    "short", "NS"
                ),

                "statusText": fixture_status.get(
                    "long", "Not Started"
                ),

                "elapsed": fixture_status.get("elapsed"),
            })

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
        CACHE["payload"] = payload

        return jsonify(payload)

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

