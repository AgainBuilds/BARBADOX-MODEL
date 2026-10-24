#!/usr/bin/env python3
"""
BARBADOX SLIPS HISTORY — permanent server-side storage.

Storage layers:
  1. slips_browser.csv on the server  -> survives browser wipes.
  2. Committed back to GitHub         -> survives Render redeploys
     (the Render free-tier filesystem is wiped on every deploy).

Uses GITHUB_TOKEN via gh_sync when configured; otherwise it keeps
the local CSV only (still better than browser-only storage).

Blueprint endpoints:
  GET  /api/slip-history   -> {"ok": true, "slips": [...]}
  POST /api/slip-history   -> body {"slips": [...]} upserts by slip id
  GET  /slips_history.js   -> serves the frontend script
"""

import csv
import hashlib
import json
import threading
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

            rows.append(row)

    return rows


def _write_rows(rows):
    with HISTORY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)

        writer.writeheader()

        for row in rows:
            out = dict(row)
            out["legs"] = json.dumps(
                row.get("legs") or [],
                ensure_ascii=False
            )

            writer.writerow(out)


def _normalize(slip):
    """Convert a browser slip object into a CSV record."""
    auto = slip.get("autoGraded")

    if auto is None:
        auto = slip.get("auto_graded") == "YES"

    return {
        "id": str(slip.get("id", "")).strip(),
        "number": slip.get("number", ""),
        "created_at": (
            slip.get("createdAt")
            or slip.get("created_at")
            or ""
        ),
        "status": str(
            slip.get("status", "PENDING")
        ).upper(),
        "graded_at": (
            slip.get("gradedAt")
            or slip.get("graded_at")
            or ""
        ),
        "auto_graded": "YES" if auto else "NO",
        "archived_at": (
            slip.get("archivedAt")
            or slip.get("archived_at")
            or datetime.now(timezone.utc).isoformat()
        ),
        "legs": (
            slip.get("legs")
            if isinstance(slip.get("legs"), list)
            else []
        ),
    }


def _push_to_github():
    """Commit the CSV to GitHub so it survives the next deploy."""
    if not HISTORY_CSV.exists():
        return

    try:
        signature = hashlib.sha256(
            HISTORY_CSV.read_bytes()
        ).hexdigest()

        if signature == _last_push["signature"]:
            return

        if gh_sync.enabled():
            gh_sync.push_snapshot(
                REMOTE_NAME,
                "Update slips history (browser tracker archive)"
            )

            _last_push["signature"] = signature

    except Exception:
        # Never fail the request because the GitHub sync failed.
        pass


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
        "slips": rows
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
            r["id"]: r
            for r in _read_rows()
            if r.get("id")
        }

        for slip in incoming:
            if not isinstance(slip, dict):
                continue

            record = _normalize(slip)

            if not record["id"]:
                continue

            if by_id.get(record["id"]) != record:
                by_id[record["id"]] = record
                changed = True

        if changed:
            ordered = sorted(
                by_id.values(),
                key=lambda r: str(r.get("created_at", ""))
            )

            _write_rows(ordered)

    if changed:
        _push_to_github()

    return jsonify({
        "ok": True,
        "changed": changed,
        "count": len(by_id)
    })
