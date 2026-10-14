#!/usr/bin/env python3
"""
BARBADOX SLIP TRACKER

Creates sequential 3+1 slips:
    - 3 Over 1.5 selections
    - 1 Under 3.5 selection

Rules:
    - Core 1 Over 1.5 threshold: 79%
    - Core 2 Under 3.5 threshold: 75%
    - No fixture is reused within a slip.
    - Only eligible, ungraded, upcoming selections are used.
    - Slips are saved permanently in slip_history.csv.
    - Finished matches are graded from actual football results.
    - slip.md reports current slips and historical performance.

This file imports barbadox_core.py without modifying it.
"""

import csv
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import barbadox_core as core


BASE_DIR = Path(__file__).resolve().parent

PICKS_FILE = BASE_DIR / "picks.csv"
HISTORY_FILE = BASE_DIR / "slip_history.csv"
REPORT_FILE = BASE_DIR / "slip.md"

OVER_THRESHOLD = float(
    os.environ.get("CORE1_SLIP_THRESHOLD", "0.79")
)

UNDER_THRESHOLD = float(
    os.environ.get("CORE2_SLIP_THRESHOLD", "0.75")
)

HISTORY_FIELDS = [
    "slip_id",
    "generated_at",
    "slip_no",
    "leg_no",
    "date",
    "league",
    "home",
    "away",
    "selection",
    "market",
    "probability",
    "source",
    "hg",
    "ag",
    "leg_result",
    "slip_result",
]


def utc_now():
    return datetime.now(timezone.utc)


def normalise(value):
    return " ".join(str(value or "").lower().split())


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_core2_under(pick):
    note = str(pick.get("note", "")).strip().upper()

    return (
        note.startswith("CORE2_UNDER35")
        or (
            str(pick.get("selection", "")).strip().upper()
            == "UNDER 3.5"
        )
    )


def is_core1_over(pick):
    if is_core2_under(pick):
        return False

    return abs(as_float(pick.get("market")) - 1.5) < 0.0001


def fixture_key(pick):
    return (
        str(pick.get
