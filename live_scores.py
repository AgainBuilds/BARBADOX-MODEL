#!/usr/bin/env python3
"""BARBADOX live-score API backed by football-data.org v4.

The endpoint accepts every date required by unsettled archived slips. It
refreshes one stale seven-day window per request, prioritises the current
week, retains the last good response through provider failures, and returns
provider IDs, scores, status, minute, kickoff and refresh timestamps.
"""

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request

live_scores_bp = Blueprint("barbadox_live_scores", __name__)
FOOTBALL_DATA_URL = "https://api.football-data.org/v4/matches"
LIVE_COMPETITIONS = "PL,PD,FL1,BL1,SA"

LIVE_CACHE_SECONDS = 45
HISTORY_CACHE_SECONDS = 900
UPCOMING_CACHE_SECONDS = 300
ERROR_CACHE_SECONDS = 90
LIVE_MAX_FETCHES_PER_REQUEST = 1

LIVE_MATCH_CACHE = {}
_LAST_GOOD_FIXTURES = {}
_live_lock = threading.RLock()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _football_data_key():
    for name in (
        "FOOTBALL_DATA_KEY", "FOOTBALL_DATA_TOKEN",
        "FOOTBALL_DATA_API_KEY", "FOOTBALL_API_KEY",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _status_info(raw_status):
    raw = str(raw_status or "").upper()
    mapping = {
        "FINISHED": ("FT", "Full Time", "FINISHED"),
        "AWARDED": ("AWD", "Awarded", "FINISHED"),
        "IN_PLAY": ("LIVE", "In Play", "LIVE"),
        "PAUSED": ("HT", "Half Time", "LIVE"),
        "EXTRA_TIME": ("ET", "Extra Time", "LIVE"),
        "PENALTY_SHOOTOUT": ("P", "Penalty Shootout", "LIVE"),
        "SUSPENDED": ("SUSP", "Suspended", "DELAYED"),
        "POSTPONED": ("PST", "Postponed", "DELAYED"),
        "CANCELLED": ("CANC", "Cancelled", "VOID"),
        "TIMED": ("NS", "Not Started", "SCHEDULED"),
        "SCHEDULED": ("NS", "Not Started", "SCHEDULED"),
        "TBD": ("NS", "Not Started", "SCHEDULED"),
    }
    return mapping.get(raw, ("UNKNOWN", raw or "Unknown", "UNKNOWN"))


def _score_pair(node):
    if not isinstance(node, dict):
        return None, None
    home = node.get("home")
    away = node.get("away")
    try:
        home = int(home) if home is not None else None
        away = int(away) if away is not None else None
    except (TypeError, ValueError, OverflowError):
        return None, None
    if home is not None and home < 0 or away is not None and away < 0:
        return None, None
    return home, away


def _timestamp(kickoff):
    if not kickoff:
        return None
    try:
        parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def _football_fixture(match, refreshed_at=None):
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    home = home_team.get("name")
    away = away_team.get("name")
    if not home or not away:
        return None

    raw_status = str(match.get("status") or "").upper()
    status, status_text, state = _status_info(raw_status)
    score = match.get("score") or {}
    home_score, away_score = _score_pair(score.get("fullTime"))
    if home_score is None or away_score is None:
        if raw_status == "PAUSED":
            ht_home, ht_away = _score_pair(score.get("halfTime"))
            if ht_home is not None and ht_away is not None:
                home_score, away_score = ht_home, ht_away

    provisional = False
    if state == "LIVE" and (home_score is None or away_score is None):
        home_score, away_score = 0, 0
        provisional = True
    final_score_confirmed = (
        state == "FINISHED" and home_score is not None and away_score is not None
    )

    kickoff = str(match.get("utcDate") or "")
    minute = match.get("minute")
    injury_time = match.get("injuryTime")
    try:
        minute = int(minute) if minute is not None else None
    except (TypeError, ValueError, OverflowError):
        minute = None
    try:
        injury_time = int(injury_time) if injury_time is not None else None
    except (TypeError, ValueError, OverflowError):
        injury_time = None

    return {
        "id": match.get("id"),
        "providerId": match.get("id"),
        "date": kickoff[:10],
        "kickoff": kickoff or None,
        "timestamp": _timestamp(kickoff),
        "home": home,
        "away": away,
        "homeTeamId": home_team.get("id"),
        "awayTeamId": away_team.get("id"),
        "homeScore": home_score,
        "awayScore": away_score,
        "scoreProvisional": provisional,
        "scoreFinalConfirmed": final_score_confirmed,
        "scoreUnconfirmed": state == "FINISHED" and not final_score_confirmed,
        "status": status,
        "statusCode": status,
        "providerStatus": raw_status,
        "statusText": status_text,
        "state": state,
        "league": (match.get("competition") or {}).get("name", ""),
        "minute": minute,
        "injuryTime": injury_time,
        "duration": score.get("duration"),
        "refreshedAt": refreshed_at or _utc_now(),
        "providerLastUpdated": match.get("lastUpdated"),
    }


def _merge_fixture(new, old):
    """Merge provider updates without erasing previously confirmed scores."""
    if not old:
        return dict(new)
    merged = dict(old)
    for key, value in new.items():
        if value is not None and value != "":
            merged[key] = value

    if old.get("homeScore") is not None and old.get("awayScore") is not None:
        if (
            new.get("homeScore") is None
            or new.get("awayScore") is None
            or new.get("scoreProvisional") is True
        ):
            merged["homeScore"] = old["homeScore"]
            merged["awayScore"] = old["awayScore"]
            merged["scoreProvisional"] = old.get("scoreProvisional", False)

    old_state = str(old.get("state") or "UNKNOWN").upper()
    new_state = str(new.get("state") or "UNKNOWN").upper()
    if (
        old_state == "FINISHED" and new_state != "FINISHED"
    ) or (
        old_state == "LIVE" and new_state in {"SCHEDULED", "UNKNOWN"}
    ):
        for key in ("status", "statusCode", "providerStatus", "statusText", "state"):
            merged[key] = old.get(key)
    elif old_state != "UNKNOWN" and new_state == "UNKNOWN":
        for key in ("status", "statusCode", "providerStatus", "statusText", "state"):
            merged[key] = old.get(key)

    if old.get("scoreFinalConfirmed") is True and new.get("scoreFinalConfirmed") is not True:
        merged["scoreFinalConfirmed"] = True
    if new.get("scoreProvisional") is False:
        merged["scoreProvisional"] = False
    merged["scoreUnconfirmed"] = (
        merged.get("state") == "FINISHED"
        and merged.get("scoreFinalConfirmed") is not True
    )
    return merged


def _football_data_fetch(date_from, date_to, api_key):
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
            401: "Authentication failed. Check FOOTBALL_DATA_KEY in Render.",
            403: "football-data.org denied this date range or competition on the current plan.",
            429: "football-data.org rate limit reached; refresh is paused temporarily.",
        }
        raise RuntimeError(messages.get(
            response.status_code,
            "football-data.org returned HTTP " + str(response.status_code) + ".",
        ))
    payload = response.json()
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(matches, list):
        raise ValueError("football-data.org returned an unexpected response shape.")
    refreshed = _utc_now()
    return [
        fixture for item in matches if isinstance(item, dict)
        if (fixture := _football_fixture(item, refreshed)) is not None
    ]


def _date_from_client(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _week_start(day):
    return day - timedelta(days=day.weekday())


def _ttl_for_week(week, current_week):
    if week == current_week:
        return LIVE_CACHE_SECONDS
    if week > current_week:
        return UPCOMING_CACHE_SECONDS
    return HISTORY_CACHE_SECONDS


@live_scores_bp.route("/api/live-scores", methods=["GET", "POST"])
def live_scores():
    api_key = _football_data_key()
    if not api_key:
        return jsonify({
            "ok": False,
            "configured": False,
            "message": "Add FOOTBALL_DATA_KEY in Render → Environment.",
            "fixtures": [],
            "updatedAt": _utc_now(),
            "provider": "football-data.org",
        }), 200

    body = request.get_json(silent=True) if request.method == "POST" else {}
    body = body if isinstance(body, dict) else {}
    raw_dates = body.get("dates", [])
    if not isinstance(raw_dates, list):
        raw_dates = []

    today = datetime.now(timezone.utc).date()
    current_days = {today + timedelta(days=n) for n in range(-2, 9)}
    requested_days = {d for raw in raw_dates if (d := _date_from_client(raw))}
    current_week = _week_start(today)
    current_weeks = {_week_start(day) for day in current_days}
    requested_weeks = {_week_start(day) for day in requested_days}
    ordered_weeks = (
        [current_week]
        + sorted((current_weeks | requested_weeks) - {current_week})
    )

    warnings = []
    fetched_this_request = 0
    successful_windows = 0
    fixtures_by_id = {}
    now = time.time()

    with _live_lock:
        for week in ordered_weeks:
            date_from = week.isoformat()
            date_to = (week + timedelta(days=6)).isoformat()
            cache_key = date_from + ":" + date_to
            cached = LIVE_MATCH_CACHE.get(cache_key)
            ttl = _ttl_for_week(week, current_week)
            fresh = cached is not None and now - cached.get("at", 0) < cached.get("ttl", ttl)

            if not fresh and fetched_this_request < LIVE_MAX_FETCHES_PER_REQUEST:
                fetched_this_request += 1
                try:
                    incoming = _football_data_fetch(date_from, date_to, api_key)
                    merged_items = []
                    for fixture in incoming:
                        ident = str(fixture.get("id") or "")
                        old = _LAST_GOOD_FIXTURES.get(ident) or {}
                        current = _merge_fixture(fixture, old)
                        if ident:
                            _LAST_GOOD_FIXTURES[ident] = current
                        merged_items.append(current)
                    cached = {
                        "at": time.time(), "ttl": ttl,
                        "fixtures": merged_items, "error": None, "ok": True,
                    }
                except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
                    old_items = cached.get("fixtures", []) if cached else []
                    cached = {
                        "at": time.time(), "ttl": ERROR_CACHE_SECONDS,
                        "fixtures": old_items, "error": str(exc)[:350], "ok": False,
                    }
                LIVE_MATCH_CACHE[cache_key] = cached

            if cached is None:
                continue
            if cached.get("ok"):
                successful_windows += 1
            elif cached.get("error"):
                warnings.append(date_from + "–" + date_to + ": " + cached["error"])

            for fixture in cached.get("fixtures", []):
                ident = str(fixture.get("id") or "")
                if ident:
                    fixture = _LAST_GOOD_FIXTURES.get(ident, fixture)
                    fixtures_by_id[ident] = _merge_fixture(
                        fixture, fixtures_by_id.get(ident)
                    )

        waiting = 0
        now = time.time()
        for week in ordered_weeks:
            key = week.isoformat() + ":" + (week + timedelta(days=6)).isoformat()
            entry = LIVE_MATCH_CACHE.get(key)
            ttl = entry.get("ttl", _ttl_for_week(week, current_week)) if entry else 0
            if entry is None or now - entry.get("at", 0) >= ttl:
                waiting += 1

    fixtures = sorted(
        fixtures_by_id.values(),
        key=lambda row: row.get("timestamp") or 0,
    )
    if waiting:
        warnings.append(
            str(waiting) + " score window(s) remain queued; they will be fetched on later refreshes."
        )

    ok = successful_windows > 0 or bool(fixtures)
    return jsonify({
        "ok": ok,
        "configured": True,
        "message": warnings[0] if warnings and not ok else None,
        "updatedAt": _utc_now(),
        "cacheSeconds": LIVE_CACHE_SECONDS,
        "provider": "football-data.org",
        "fixtures": fixtures,
        "historyWarnings": warnings[:10],
        "queuedWindows": waiting,
    }), 200 if ok or not warnings else 502
