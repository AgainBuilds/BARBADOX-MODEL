
#!/usr/bin/env python3
"""
BARBADOX SLIPS HISTORY — permanent server-side storage.

Storage:
  1. slips_browser.csv on the server.
  2. GitHub backup through gh_sync when configured.

Endpoints:
  GET  /api/slip-history
  POST /api/slip-history
  POST /api/slip-history/generate
  GET  /slips_history.js

Generation is reserved atomically on the server. A fixture cannot
appear in two unsettled slips, including slips generated in separate
browser sessions.
"""

import csv
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

import gh_sync

slips_history_bp = Blueprint("barbadox_slips_history", __name__)

ROOT = Path(__file__).resolve().parent
HISTORY_CSV = ROOT / "slips_browser.csv"
REMOTE_NAME = "slips_browser.csv"

FIELDS = [
    "id",
    "number",
    "created_at",
    "status",
    "graded_at",
    "auto_graded",
    "archived_at",
    "legs",
]

_lock = threading.Lock()
_last_push = {"signature": ""}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read_rows():
    """Read every archived slip from the CSV."""
    if not HISTORY_CSV.exists():
        return []

    rows = []

    with HISTORY_CSV.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
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
    """Write the archive using the established CSV schema."""
    temporary = HISTORY_CSV.with_suffix(".csv.tmp")

    with temporary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for row in rows:
            out = dict(row)
            out["legs"] = json.dumps(
                row.get("legs") or [],
                ensure_ascii=False
            )
            writer.writerow({
                field: out.get(field, "")
                for field in FIELDS
            })

    temporary.replace(HISTORY_CSV)


def _is_graded(status):
    return str(status or "").upper() in ("WON", "LOST")


def _should_keep(existing, record):
    """
    Prevent a graded slip from regressing to PENDING.
    When both records are graded, keep the newer grading.
    """
    old_status = existing.get("status")
    new_status = record.get("status")

    if _is_graded(old_status) and not _is_graded(new_status):
        return True

    if (
        _is_graded(old_status)
        and _is_graded(new_status)
        and str(existing.get("graded_at") or "")
        >= str(record.get("graded_at") or "")
    ):
        return True

    return False


def _merge_leg_scores(existing, record):
    """Preserve scores/results arriving with an older browser copy."""
    old = existing.get("legs") or []
    new = record.get("legs") or []

    if (
        not isinstance(old, list)
        or not isinstance(new, list)
        or len(old) != len(new)
    ):
        return False

    merged = []
    changed = False

    for old_leg, new_leg in zip(old, new):
        if not isinstance(old_leg, dict) or not isinstance(new_leg, dict):
            merged.append(old_leg)
            continue

        leg = dict(old_leg)

        for key in ("liveScore", "fixtureStatus"):
            if new_leg.get(key) and not old_leg.get(key):
                leg[key] = new_leg[key]
                changed = True

        new_result = str(new_leg.get("result") or "").upper()
        old_result = str(old_leg.get("result") or "PENDING").upper()

        if new_result in ("WON", "LOST") and old_result == "PENDING":
            leg["result"] = new_result
            changed = True

        merged.append(leg)

    if changed:
        existing["legs"] = merged

    return changed


def _normalize(slip):
    """Convert browser camelCase or API snake_case into CSV fields."""
    auto = slip.get("autoGraded")

    if auto is None:
        auto = str(slip.get("auto_graded") or "").upper() == "YES"

    legs = slip.get("legs")
    if not isinstance(legs, list):
        legs = []

    return {
        "id": str(slip.get("id") or "").strip(),
        "number": slip.get("number", ""),
        "created_at": (
            slip.get("createdAt")
            or slip.get("created_at")
            or ""
        ),
        "status": str(slip.get("status") or "PENDING").upper(),
        "graded_at": (
            slip.get("gradedAt")
            or slip.get("graded_at")
            or ""
        ),
        "auto_graded": "YES" if auto else "NO",
        "archived_at": (
            slip.get("archivedAt")
            or slip.get("archived_at")
            or _now()
        ),
        "legs": legs,
    }


def _public_slip(record):
    """Return the browser's expected camelCase representation."""
    return {
        "id": record.get("id"),
        "number": record.get("number"),
        "createdAt": record.get("created_at"),
        "status": record.get("status") or "PENDING",
        "gradedAt": record.get("graded_at") or None,
        "autoGraded": str(record.get("auto_graded") or "").upper() == "YES",
        "archivedAt": record.get("archived_at"),
        "legs": record.get("legs") or [],
    }


def _team_key(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"\b(fc|sc|afc|cf|club)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _leg_fixture_key(leg):
    """
    Stable fixture identity for reservation purposes.
    Uses the fixture date and ordered home/away names.
    """
    if not isinstance(leg, dict):
        return None

    home = _team_key(leg.get("home"))
    away = _team_key(leg.get("away"))

    raw_date = (
        leg.get("date")
        or leg.get("kickoff")
        or ""
    )

    date = str(raw_date).strip()[:10]

    if not home or not away or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None

    return date + "|" + home + "|" + away


def _pending_fixture_keys(rows):
    """Collect fixtures currently reserved by unsettled slips."""
    used = set()

    for row in rows:
        if str(row.get("status") or "PENDING").upper() != "PENDING":
            continue

        legs = row.get("legs") or []
        if not isinstance(legs, list):
            continue

        for leg in legs:
            key = _leg_fixture_key(leg)
            if key:
                used.add(key)

    return used


def _valid_candidate(slip):
    """A generated slip must contain four identifiable selections."""
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

    markets = [str(leg.get("market") or "").upper() for leg in legs]

    over_count = sum("OVER 1.5" in market for market in markets)
    under_count = sum("UNDER 3.5" in market for market in markets)

    if over_count != 3 or under_count != 1:
        return False, "Slip must contain 3 Over 1.5 legs and 1 Under 3.5 leg."

    return True, ""


def _push_to_github():
    """Commit the CSV archive to GitHub when configured."""
    if not HISTORY_CSV.exists() or not gh_sync.enabled():
        return

    try:
        signature = hashlib.sha256(
            HISTORY_CSV.read_bytes()
        ).hexdigest()

        if signature == _last_push["signature"]:
            return

        gh_sync.push_snapshot(
            REMOTE_NAME,
            "Update slips history (browser tracker archive)"
        )

        _last_push["signature"] = signature

    except Exception as exc:
        print("Slips archive GitHub backup failed: " + str(exc))


def _startup_restore():
    """Restore the permanent archive after a server restart/deploy."""
    if not gh_sync.enabled():
        return

    try:
        if gh_sync.pull(REMOTE_NAME):
            print("Restored slips history from GitHub.")

    except Exception as exc:
        print("Could not restore slips history: " + str(exc))


_startup_restore()


@slips_history_bp.get("/slips_history.js")
def slips_history_script():
    return send_from_directory(
        str(ROOT),
        "slips_history.js",
        mimetype="application/javascript"
    )


@slips_history_bp.get("/api/slip-history")
def get_history():
    with _lock:
        rows = _read_rows()

    return jsonify({
        "ok": True,
        "count": len(rows),
        "slips": [_public_slip(row) for row in rows]
    })


@slips_history_bp.post("/api/slip-history")
def save_history():
    data = request.get_json(silent=True) or {}
    incoming = data.get("slips")

    if not isinstance(incoming, list):
        return jsonify({
            "ok": False,
            "error": "Body must contain a slips array."
        }), 400

    changed = False

    with _lock:
        by_id = {
            row["id"]: row
            for row in _read_rows()
            if row.get("id")
        }

        for slip in incoming:
            if not isinstance(slip, dict):
                continue

            record = _normalize(slip)
            if not record["id"]:
                continue

            existing = by_id.get(record["id"])

            if existing is not None and _should_keep(existing, record):
                if _merge_leg_scores(existing, record):
                    changed = True
                continue

            if existing != record:
                by_id[record["id"]] = record
                changed = True

        if changed:
            ordered = sorted(
                by_id.values(),
                key=lambda row: str(row.get("created_at") or "")
            )
            _write_rows(ordered)

        count = len(by_id)

    if changed:
        _push_to_github()

    return jsonify({
        "ok": True,
        "changed": changed,
        "count": count
    })


@slips_history_bp.post("/api/slip-history/generate")
def generate_history_slips():
    """
    Atomically reserve and archive newly generated slips.

    Request:
      {"slips": [browser slip objects]}

    Response:
      {"ok": true, "accepted": [...], "rejected": [...]}

    Existing pending fixtures are never reused. The check and write
    happen under the same lock to prevent concurrent duplicate slips.
    """
    data = request.get_json(silent=True) or {}
    candidates = data.get("slips")

    if not isinstance(candidates, list):
        return jsonify({
            "ok": False,
            "error": "Body must contain a slips array."
        }), 400

    accepted = []
    rejected = []
    changed = False

    with _lock:
        rows = _read_rows()
        by_id = {
            row["id"]: row
            for row in rows
            if row.get("id")
        }

        used = _pending_fixture_keys(rows)

        next_number = max(
            [int(row.get("number") or 0) for row in rows
             if str(row.get("number") or "").isdigit()]
            or [0]
        ) + 1

        for index, candidate in enumerate(candidates):
            valid, reason = _valid_candidate(candidate)

            if not valid:
                rejected.append({
                    "index": index,
                    "reason": reason
                })
                continue

            legs = candidate["legs"]
            keys = [_leg_fixture_key(leg) for leg in legs]

            conflict = next((key for key in keys if key in used), None)

            if conflict:
                rejected.append({
                    "index": index,
                    "reason": "One or more fixtures are already reserved by a pending slip."
                })
                continue

            record = _normalize(candidate)

            # IDs are assigned by the server, not trusted from the browser.
            record["id"] = "slip-" + uuid.uuid4().hex
            record["number"] = next_number
            record["status"] = "PENDING"
            record["graded_at"] = ""
            record["auto_graded"] = "NO"
            record["created_at"] = record["created_at"] or _now()
            record["archived_at"] = _now()

            by_id[record["id"]] = record
            accepted.append(_public_slip(record))

            used.update(keys)
            next_number += 1
            changed = True

        if changed:
            ordered = sorted(
                by_id.values(),
                key=lambda row: str(row.get("created_at") or "")
            )
            _write_rows(ordered)

    if changed:
        _push_to_github()

    return jsonify({
        "ok": True,
        "accepted": accepted,
        "rejected": rejected,
        "count": len(accepted)
    })
