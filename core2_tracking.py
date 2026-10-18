#!/usr/bin/env python3
"""Merge qualifying Core 2.2 picks into picks.csv."""

import csv
import os

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT = ROOT / os.getenv("REPORT_DIR", "reports")
PICKS = ROOT / "picks.csv"

THRESHOLD = float(os.getenv("THRESHOLD", "0.75"))

FIELDS = [
    "date",
    "league",
    "home",
    "away",
    "market",
    "probability",
    "core_probability",
    "low",
    "high",
    "field_temp_c",
    "factors",
    "logged_at",
    "hg",
    "ag",
    "result",
    "note",
]


def read_csv(path):
    if not path.exists():
        return []

    with path.open(
        newline="",
        encoding="utf-8-sig",
    ) as file:
        return list(csv.DictReader(file))


def normalize_name(value):
    return "".join(
        char.lower()
        for char in str(value or "")
        if char.isalnum()
    )


def is_core2(row):
    return (
        str(row.get("note", ""))
        .strip()
        .upper()
        .startswith("CORE2_UNDER35")
    )


def fixture_key(row):
    market = (
        "U3.5"
        if is_core2(row)
        else str(row.get("market", "")).strip()
    )

    return (
        str(row.get("date", ""))[:10],
        str(row.get("league", "")).upper().strip(),
        normalize_name(row.get("home")),
        normalize_name(row.get("away")),
        market,
    )


def main():
    old_rows = read_csv(PICKS)

    # Remove previous Core 2 records so old-version predictions
    # cannot silently contaminate the new Core 2.2 record.
    #
    # Core 1 and other non-Core-2 records are preserved.
    existing = [
        row
        for row in old_rows
        if not is_core2(row)
    ]

    positions = {
        fixture_key(row): index
        for index, row in enumerate(existing)
    }

    added = 0
    updated = 0

    sources = [
        (
            read_csv(REPORT / "core2_results.csv"),
            True,
        ),
        (
            read_csv(REPORT / "core2_upcoming.csv"),
            False,
        ),
    ]

    for rows, historical in sources:
        for row in rows:

            if str(row.get("cleared", "0")) != "1":
                continue

            try:
                probability = float(row.get("p_final", ""))
            except (TypeError, ValueError):
                continue

            if probability < THRESHOLD:
                continue

            goals_home = ""
            goals_away = ""
            result = ""

            if historical:
                try:
                    goals_home = int(row["hg"])
                    goals_away = int(row["ag"])
                except (KeyError, TypeError, ValueError):
                    continue

                result = (
                    "HIT"
                    if goals_home + goals_away <= 3
                    else "MISS"
                )

            pick = {
                "date": str(row.get("date", ""))[:10],
                "league": row.get("league", ""),
                "home": row.get("home", ""),
                "away": row.get("away", ""),
                "market": "3.5",
                "probability": f"{probability:.6f}",
                "core_probability": (
                    row.get("p_cal", "")
                    or row.get("p_raw", "")
                ),
                "low": "",
                "high": "",
                "field_temp_c": "",
                "factors": "Core 2.2 Under 3.5",
                "logged_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "hg": goals_home,
                "ag": goals_away,
                "result": result,
                "note": (
                    "CORE2_UNDER35|HISTORICAL"
                    if historical
                    else "CORE2_UNDER35|UPCOMING"
                ),
            }

            key = fixture_key(pick)

            if key not in positions:
                positions[key] = len(existing)
                existing.append(pick)
                added += 1
            else:
                index = positions[key]
                existing[index] = pick
                updated += 1

    with PICKS.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
            extrasaction="ignore",
        )

        writer.writeheader()

        writer.writerows(
            {
                field: row.get(field, "")
                for field in FIELDS
            }
            for row in existing
        )

    print()
    print("BARBADOX CORE 2.2 TRACKING COMPLETE")
    print(f"Threshold: {THRESHOLD:.1%}")
    print(f"Added: {added}")
    print(f"Updated: {updated}")
    print(f"Total rows in picks.csv: {len(existing)}")


if __name__ == "__main__":
    main()
