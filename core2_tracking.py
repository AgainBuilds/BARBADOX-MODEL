#!/usr/bin/env python3
"""
BARBADOX CORE 2 TRACKING

Imports qualified Under 3.5 selections from:
    reports/core2_results.csv
    reports/core2_upcoming.csv

Stores them in the persistent picks.csv.

Historical picks receive HIT/MISS immediately.
Upcoming picks remain pending until their results are available.

Existing Core 1 picks are preserved.
Repeated runs do not duplicate the same fixture.
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / os.getenv("REPORT_DIR", "reports")
PICKS_FILE = ROOT / "picks.csv"

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
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        return list(csv.DictReader(file))


def normalise_team(name):
    return "".join(
        char.lower()
        for char in str(name or "")
        if char.isalnum()
    )


def fixture_key(row):
    return (
        str(row.get("date", "")).strip(),
        str(row.get("league", "")).strip().upper(),
        normalise_team(row.get("home")),
        normalise_team(row.get("away")),
    )


def is_core2(row):
    return str(row.get("note", "")).startswith(
        "CORE2_UNDER35"
    )


def is_historical_core2(row):
    return (
        str(row.get("note", "")).startswith(
            "CORE2_UNDER35|HISTORICAL"
        )
    )


def make_pick(source, historical):
    try:
        probability = float(source.get("p_final", ""))
    except (TypeError, ValueError):
        return None

    # Only record selections that pass the configured threshold.
    if probability < THRESHOLD:
        return None

    if historical:
        try:
            home_goals = int(source["hg"])
            away_goals = int(source["ag"])
        except (KeyError, TypeError, ValueError):
            print(
                "Skipping historical row without a valid score:",
                source,
            )
            return None

        # Under 3.5 wins when the match has 0, 1, 2, or 3 goals.
        result = (
            "HIT"
            if home_goals + away_goals <= 3
            else "MISS"
        )

        hg = home_goals
        ag = away_goals
        note = "CORE2_UNDER35|HISTORICAL"

        # Confirm that the result file's hit label agrees with
        # the actual score. The score is the grading source of truth.
        recorded_hit = str(source.get("hit", "")).strip()

        if recorded_hit in ("0", "1"):
            expected_hit = "1" if result == "HIT" else "0"

            if recorded_hit != expected_hit:
                print(
                    "WARNING: Core 2 report hit flag disagrees "
                    "with score for",
                    source.get("home"),
                    "vs",
                    source.get("away"),
                )

    else:
        result = ""
        hg = ""
        ag = ""
        note = "CORE2_UNDER35|UPCOMING"

    return {
        "date": source.get("date", ""),
        "league": source.get("league", ""),
        "home": source.get("home", ""),
        "away": source.get("away", ""),
        "market": "3.5",
        "probability": f"{probability:.4f}",
        "core_probability": (
            source.get("p_cal", "")
            or source.get("p_raw", "")
        ),
        "low": "",
        "high": "",
        "field_temp_c": "",
        "factors": (
            "Core 2 Under 3.5 historical walk-forward"
            if historical
            else "Core 2 Under 3.5 upcoming forecast"
        ),
        "logged_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "hg": hg,
        "ag": ag,
        "result": result,
        "note": note,
    }


def main():
    existing = read_csv(PICKS_FILE)

    # Keep a mapping to the existing row positions.
    positions = {
        fixture_key(row): i
        for i, row in enumerate(existing)
    }

    historical_file = REPORT_DIR / "core2_results.csv"
    upcoming_file = REPORT_DIR / "core2_upcoming.csv"

    added = 0
    updated = 0
    skipped_existing = 0

    # Historical records first, so the graded result wins over
    # a pending prediction for the same fixture.
    sources = [
        (historical_file, True),
        (upcoming_file, False),
    ]

    for source_file, historical in sources:
        source_rows = read_csv(source_file)

        if not source_file.exists():
            print("Source not present:", source_file)
            continue

        for source in source_rows:
            # Historical report contains every scored match.
            # Only qualifying predictions belong in the track record.
            if historical:
                if str(source.get("cleared", "")).strip() != "1":
                    continue

            pick = make_pick(source, historical)

            if pick is None:
                continue

            key = fixture_key(pick)

            if key not in positions:
                positions[key] = len(existing)
                existing.append(pick)
                added += 1
                continue

            index = positions[key]
            old = existing[index]

            # Never overwrite Core 1 or any non-Core-2 pick.
            if not is_core2(old):
                skipped_existing += 1
                continue

            # Historical graded data replaces a pending Core 2
            # prediction for the same fixture.
            if historical:
                if not is_historical_core2(old):
                    existing[index] = pick
                    updated += 1
                else:
                    # Refresh an already historical row without
                    # creating a duplicate.
                    existing[index] = pick

            else:
                # Never replace a historical result with a pending
                # upcoming prediction.
                if not is_historical_core2(old):
                    existing[index] = pick

    # Preserve the shared CSV schema and every existing Core 1 row.
    with PICKS_FILE.open(
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

        for row in existing:
            writer.writerow({
                field: row.get(field, "")
                for field in FIELDS
            })

    print()
    print("BARBADOX CORE 2 TRACKING COMPLETE")
    print("--------------------------------")
    print("Threshold:", f"{THRESHOLD:.1%}")
    print("New picks:", added)
    print("Updated to historical:", updated)
    print("Non-Core-2 existing rows protected:", skipped_existing)
    print("Total picks in shared record:", len(existing))
    print("Shared record:", PICKS_FILE)


if __name__ == "__main__":
    main()
