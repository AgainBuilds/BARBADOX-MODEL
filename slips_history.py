#!/usr/bin/env python3
"""BARBADOX permanent slip archive and dedicated tracker routes."""

import csv
import hashlib
import json
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

import gh_sync

slips_history_bp = Blueprint("barbadox_slips_history", __name__)
ROOT = Path(__file__).resolve().parent
HISTORY_CSV = ROOT / "slips_browser.csv"
REMOTE_NAME = "slips_browser.csv"
FIELDS = [
    "id", "number", "created_at", "status", "graded_at",
    "auto_graded", "archived_at", "legs",
]
_lock = threading.RLock()
_last_push = {"signature": "", "at": 0.0, "status": "not checked"}
GITHUB_PUSH_MIN_SECONDS = 120


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read_rows():
    if not HISTORY_CSV.exists():
        return []
    rows = []
    with HISTORY_CSV.open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            row = dict(raw)
            try:
                row["legs"] = json.loads(row.get("legs") or "[]")
            except (ValueError, TypeError):
                row["legs"] = []
            row["number"] = row.get("number") or ""
            row["status"] = str(row.get("status") or "PENDING").upper()
            rows.append(row)
    return rows


def _write_rows(rows):
    HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_CSV.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["legs"] = json.dumps(
                row.get("legs") or [], ensure_ascii=False, separators=(",", ":")
            )
            writer.writerow({field: output.get(field, "") for field in FIELDS})
    temporary.replace(HISTORY_CSV)


def _is_graded(status):
    return str(status or "").upper() in {"WON", "LOST"}


def _should_keep(existing, incoming):
    old_status = str(existing.get("status") or "PENDING").upper()
    new_status = str(incoming.get("status") or "PENDING").upper()
    if _is_graded(old_status) and not _is_graded(new_status):
        return True
    if _is_graded(old_status) and _is_graded(new_status):
        return True
    return False


def _merge_leg_scores(existing, incoming):
    old_legs = existing.get("legs") or []
    new_legs = incoming.get("legs") or []
    if not isinstance(old_legs, list) or not isinstance(new_legs, list):
        return False
    if len(old_legs) != len(new_legs):
        return False
    merged = []
    changed = False
    for old_leg, new_leg in zip(old_legs, new_legs):
        if not isinstance(old_leg, dict) or not isinstance(new_leg, dict):
            merged.append(old_leg)
            continue
        leg = dict(old_leg)
        old_result = str(old_leg.get("result") or "PENDING").upper()
        incoming_result = str(new_leg.get("result") or "PENDING").upper()
        if old_result in {"WON", "LOST"}:
            incoming_is_final = str(new_leg.get("fixtureState") or "").upper() == "FINISHED"
            outcome_agrees = incoming_result == old_result
            if not incoming_is_final or not outcome_agrees:
                merged.append(leg)
                continue
        incoming_provisional = new_leg.get("scoreProvisional") is True
        old_confirmed_score = (
            old_leg.get("homeScore") is not None
            and old_leg.get("awayScore") is not None
            and old_leg.get("scoreProvisional") is not True
        )
        old_state = str(old_leg.get("fixtureState") or "UNKNOWN").upper()
        if old_state == "UNKNOWN":
            old_status_text = str(
                old_leg.get("fixtureStatusCode") or old_leg.get("fixtureStatus") or ""
            ).upper()
            if "FULL TIME" in old_status_text or "FINISHED" in old_status_text or "AWARDED" in old_status_text:
                old_state = "FINISHED"
            elif "LIVE" in old_status_text or "HALF TIME" in old_status_text or "IN PLAY" in old_status_text:
                old_state = "LIVE"
            elif "SCHEDULED" in old_status_text or "NOT STARTED" in old_status_text:
                old_state = "SCHEDULED"
        new_state = str(new_leg.get("fixtureState") or "UNKNOWN").upper()
        status_regression = (
            old_state == "FINISHED" and new_state != "FINISHED"
        ) or (
            old_state == "LIVE" and new_state in {"SCHEDULED", "UNKNOWN"}
        )
        protected_status_fields = {
            "fixtureState", "fixtureStatusCode", "fixtureStatus",
            "matchMinute", "injuryTime", "scoreProvisional",
            "scoreFinalConfirmed", "scoreUnconfirmed",
            "homeScore", "awayScore", "liveScore",
        }
        for key, value in new_leg.items():
            if value is None or value == "":
                continue
            if status_regression and key in protected_status_fields:
                continue
            if old_leg.get("scoreFinalConfirmed") is True and key == "scoreFinalConfirmed" and value is not True:
                continue
            if old_leg.get("scoreFinalConfirmed") is True and key == "scoreUnconfirmed" and value is True:
                continue
            if incoming_provisional and old_confirmed_score and key in {"homeScore", "awayScore", "liveScore"}:
                continue
            if key == "result":
                old_result = str(leg.get("result") or "PENDING").upper()
                new_result = str(value).upper()
                if old_result in {"WON", "LOST"}:
                    continue
                if new_result not in {"WON", "LOST"}:
                    continue
            if leg.get(key) != value:
                leg[key] = value
                changed = True
        merged.append(leg)
    if changed:
        existing["legs"] = merged
    return changed


def _normalize(slip):
    auto = slip.get("autoGraded")
    if auto is None:
        auto = str(slip.get("auto_graded") or "").upper() == "YES"
    legs = slip.get("legs")
    if not isinstance(legs, list):
        legs = []
    return {
        "id": str(slip.get("id") or "").strip(),
        "number": slip.get("number", ""),
        "created_at": slip.get("createdAt") or slip.get("created_at") or "",
        "status": str(slip.get("status") or "PENDING").upper(),
        "graded_at": slip.get("gradedAt") or slip.get("graded_at") or "",
        "auto_graded": "YES" if auto else "NO",
        "archived_at": slip.get("archivedAt") or slip.get("archived_at") or _now(),
        "legs": legs,
    }


def _derived_settlement(legs):
    if not isinstance(legs, list) or len(legs) != 4:
        return None
    results = [
        str(leg.get("result") or "PENDING").upper()
        for leg in legs if isinstance(leg, dict)
    ]
    if len(results) != 4:
        return None
    if "LOST" in results:
        return "LOST"
    if all(result == "WON" for result in results):
        return "WON"
    return None


def _public_slip(row):
    return {
        "id": row.get("id"),
        "number": row.get("number"),
        "createdAt": row.get("created_at"),
        "status": row.get("status") or "PENDING",
        "gradedAt": row.get("graded_at") or None,
        "autoGraded": str(row.get("auto_graded") or "").upper() == "YES",
        "archivedAt": row.get("archived_at"),
        "legs": row.get("legs") or [],
    }


def _team_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"\b(football club|soccer club|fc|sc|afc|cf|ac|ssc|club|football)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _leg_fixture_key(leg):
    if not isinstance(leg, dict):
        return None
    home = _team_key(leg.get("home"))
    away = _team_key(leg.get("away"))
    raw_date = leg.get("date") or leg.get("kickoff") or ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(raw_date).strip())
    if not home or not away or not match:
        return None
    return match.group(1) + "|" + home + "|" + away


def _market_key(leg):
    market = str(leg.get("market") or "").upper().replace("GOALS", "").strip()
    market = re.sub(r"\s+", " ", market)
    if "OVER" in market and "1.5" in market:
        return "OVER 1.5"
    if "UNDER" in market and "3.5" in market:
        return "UNDER 3.5"
    return market


def _slip_signature(slip_or_legs):
    legs = slip_or_legs.get("legs") if isinstance(slip_or_legs, dict) else slip_or_legs
    if not isinstance(legs, list) or len(legs) != 4:
        return None
    parts = []
    for leg in legs:
        if not isinstance(leg, dict):
            return None
        fixture = _leg_fixture_key(leg)
        market = _market_key(leg)
        if not fixture or market not in {"OVER 1.5", "UNDER 3.5"}:
            return None
        parts.append(fixture + "|" + market)
    fixture_keys = [_leg_fixture_key(leg) for leg in legs]
    if len(set(fixture_keys)) != 4:
        return None
    canonical = "\n".join(sorted(parts))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pending_fixture_keys(rows):
    used = set()
    for row in rows:
        if str(row.get("status") or "PENDING").upper() != "PENDING":
            continue
        legs = row.get("legs") or []
        if isinstance(legs, list):
            used.update(key for leg in legs if (key := _leg_fixture_key(leg)))
    return used


def _valid_candidate(slip):
    if not isinstance(slip, dict):
        return False, "Slip is not an object."
    legs = slip.get("legs")
    if not isinstance(legs, list) or len(legs) != 4:
        return False, "Every slip must contain exactly four legs."
    keys = [_leg_fixture_key(leg) for leg in legs]
    if any(key is None for key in keys):
        return False, "A leg is missing a valid date or team name."
    if len(set(keys)) != 4:
        return False, "A slip contains the same fixture more than once."
    markets = [_market_key(leg) for leg in legs]
    if markets.count("OVER 1.5") != 3 or markets.count("UNDER 3.5") != 1:
        return False, "Slip must contain exactly 3 Over 1.5 legs and 1 Under 3.5 leg."
    if not _slip_signature(legs):
        return False, "Slip combination could not be identified safely."
    return True, ""


def _push_to_github(force=False):
    if not HISTORY_CSV.exists() or not gh_sync.enabled():
        _last_push["status"] = "GitHub backup is not configured."
        return _last_push["status"]
    try:
        signature = hashlib.sha256(HISTORY_CSV.read_bytes()).hexdigest()
        if signature == _last_push["signature"]:
            return _last_push["status"]
        if not force and time.time() - _last_push["at"] < GITHUB_PUSH_MIN_SECONDS:
            _last_push["status"] = "Backup queued; waiting for the safe-sync interval."
            return _last_push["status"]
        gh_sync.push_snapshot(REMOTE_NAME, "Update slips history (browser tracker archive)")
        _last_push.update(signature=signature, at=time.time(), status="Archive backed up to GitHub.")
    except Exception as exc:
        _last_push["status"] = "GitHub backup failed: " + str(exc)[:220]
    return _last_push["status"]


def _startup_restore():
    if not gh_sync.enabled() or HISTORY_CSV.exists():
        return
    try:
        if gh_sync.pull(REMOTE_NAME):
            print("Restored slips history from GitHub.")
    except Exception as exc:
        print("Could not restore slips history: " + str(exc))


_startup_restore()


@slips_history_bp.get("/slips-tracker")
def slips_tracker_page():
    return send_from_directory(str(ROOT), "slips_tracker.html")


@slips_history_bp.get("/slips_tracker.js")
def slips_tracker_script():
    return send_from_directory(str(ROOT), "slips_tracker.js", mimetype="application/javascript")


@slips_history_bp.get("/slips_history.js")
def slips_history_script():
    return send_from_directory(str(ROOT), "slips_history.js", mimetype="application/javascript")


@slips_history_bp.get("/api/slip-history")
def get_history():
    with _lock:
        rows = _read_rows()
    return jsonify({
        "ok": True,
        "count": len(rows),
        "slips": [_public_slip(row) for row in rows],
        "backupStatus": _last_push["status"],
    })


@slips_history_bp.post("/api/slip-history")
def save_history():
    data = request.get_json(silent=True) or {}
    incoming = data.get("slips")
    if not isinstance(incoming, list):
        return jsonify({"ok": False, "error": "Body must contain a slips array."}), 400

    changed = False
    important_change = False
    with _lock:
        rows = _read_rows()
        by_id = {row["id"]: row for row in rows if row.get("id")}
        for slip in incoming:
            if not isinstance(slip, dict):
                continue
            record = _normalize(slip)
            if not record["id"]:
                continue
            existing = by_id.get(record["id"])
            if existing is None:
                derived = _derived_settlement(record.get("legs"))
                if derived:
                    record["status"] = derived
                    record["graded_at"] = record.get("graded_at") or _now()
                    record["auto_graded"] = "YES"
                by_id[record["id"]] = record
                changed = True
                important_change = True
                continue
            merged = dict(existing)
            _merge_leg_scores(merged, record)
            if not _is_graded(existing.get("status")):
                new_status = str(record.get("status") or "PENDING").upper()
                if new_status in {"PENDING", "WON", "LOST"}:
                    merged["status"] = new_status
                if new_status in {"WON", "LOST"}:
                    merged["graded_at"] = record.get("graded_at") or _now()
                    merged["auto_graded"] = record.get("auto_graded") or "YES"
                    if str(existing.get("status") or "PENDING").upper() != new_status:
                        important_change = True
                derived = _derived_settlement(merged.get("legs"))
                if derived and merged.get("status") != derived:
                    merged["status"] = derived
                    merged["graded_at"] = merged.get("graded_at") or _now()
                    merged["auto_graded"] = "YES"
                    important_change = True
            merged["id"] = existing["id"]
            merged["number"] = existing.get("number")
            merged["created_at"] = existing.get("created_at") or record.get("created_at")
            if merged != existing:
                by_id[record["id"]] = merged
                changed = True
        if changed:
            ordered = sorted(by_id.values(), key=lambda row: str(row.get("created_at") or ""))
            _write_rows(ordered)
        count = len(by_id)

    backup = _push_to_github(force=important_change) if changed else _last_push["status"]
    return jsonify({"ok": True, "changed": changed, "count": count, "backupStatus": backup})


@slips_history_bp.post("/api/slip-history/generate")
def generate_history_slips():
    """Reserve new slips atomically; IDs and visible numbers belong to server."""
    data = request.get_json(silent=True) or {}
    candidates = data.get("slips")
    if not isinstance(candidates, list):
        return jsonify({"ok": False, "error": "Body must contain a slips array."}), 400

    accepted, rejected = [], []
    changed = False
    with _lock:
        rows = _read_rows()
        by_id = {row["id"]: row for row in rows if row.get("id")}
        signatures = {_slip_signature(row) for row in rows}
        signatures.discard(None)
        used = _pending_fixture_keys(rows)
        numeric = [int(row.get("number") or 0) for row in rows if str(row.get("number") or "").isdigit()]
        next_number = max(numeric or [0]) + 1

        for index, candidate in enumerate(candidates):
            valid, reason = _valid_candidate(candidate)
            if not valid:
                rejected.append({"index": index, "reason": reason})
                continue
            legs = candidate["legs"]
            keys = [_leg_fixture_key(leg) for leg in legs]
            conflict = next((key for key in keys if key in used), None)
            if conflict:
                rejected.append({
                    "index": index,
                    "reason": "A fixture is already reserved by an unsettled slip.",
                })
                continue
            signature = _slip_signature(legs)
            if signature in signatures:
                rejected.append({
                    "index": index,
                    "reason": "This exact four-leg combination already exists in the permanent archive.",
                })
                continue

            record = _normalize(candidate)
            record["id"] = "slip-" + signature[:24]
            record["number"] = next_number
            record["status"] = "PENDING"
            record["graded_at"] = ""
            record["auto_graded"] = "NO"
            record["created_at"] = record["created_at"] or _now()
            record["archived_at"] = _now()
            by_id[record["id"]] = record
            accepted.append(_public_slip(record))
            signatures.add(signature)
            used.update(keys)
            next_number += 1
            changed = True

        if changed:
            ordered = sorted(by_id.values(), key=lambda row: str(row.get("created_at") or ""))
            _write_rows(ordered)

    backup = _push_to_github(force=True) if changed else _last_push["status"]
    return jsonify({
        "ok": True,
        "accepted": accepted,
        "rejected": rejected,
        "count": len(accepted),
        "backupStatus": backup,
    })
