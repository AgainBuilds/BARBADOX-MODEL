#!/usr/bin/env python3
"""Merge qualifying historical Core 1 Over 1.5 picks from reports/core1_results.csv
into picks.csv, mirroring what core2_tracking.py does for Core 2.

Rules:
- Only rows with cleared=1 (core probability >= CORE1_THRESHOLD, default 0.80) merge.
- Rows are tagged CORE1_OVER15|HISTORICAL so the live grader and slip tracker can tell
  them apart from live Core 1 picks (empty note).
- Existing live Core 1 rows for the same fixture+market are NEVER overwritten; the
  live row wins (protected). Historical rows update only other historical rows.
- Market is part of the key, so an Over 1.5 row can coexist with a Core 2 Under 3.5
  row for the same fixture.
- Historical rows are pre-graded (HIT/MISS) from the actual scores in the report.
  These predictions were produced by a leakage-aware walk-forward replay
  (core_calibration_check.py), not by the live model at the time.

Caveat recorded on every row: historical Core 1 probabilities come from the Poisson
core only (factors 1-2); live picks additionally use factors 3-5.
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "core1_results.csv"
PICKS = ROOT / "picks.csv"

THRESHOLD = float(os.getenv("CORE1_THRESHOLD", "0.80"))

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

    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def norm(value):
    return "".join(
        char.lower()
        for char in str(value or "")
        if char.isalnum()
    )


def is_core1_hist(row):
    return (
        str(row.get("note", ""))
        .strip()
        .upper()
        .startswith("CORE1_OVER15")
    )


def key(row):
    market = (
        "1.5"
        if is_core1_hist(row)
        else str(row.get("market", "")).strip()
    )

    return (
        str(row.get("date", ""))[:10],
        str(row.get("league", "")).upper().strip(),
        norm(row.get("home")),
        norm(row.get("away")),
        market,
    )


def make_pick(source):
    try:
        probability = float(source.get("p_final", ""))
    except (ValueError, TypeError):
        return None

    if not 0 <= probability <= 1:
        return None

    if probability < THRESHOLD:
        return None

    if str(source.get("cleared", "")).strip() != "1":
        return None

    try:
        home_goals = int(source["hg"])
        away_goals = int(source["ag"])
    except (KeyError, ValueError, TypeError):
        return None

    result = (
        "HIT"
        if home_goals + away_goals >= 2
        else "MISS"
    )

    recorded_hit = str(source.get("hit", "")).strip()

    expected_hit = "1" if result == "HIT" else "0"

    if recorded_hit in ("0", "1") and recorded_hit != expected_hit:
        print(
            "WARNING: Core 1 report hit flag disagrees with score:",
            source.get("home"),
            "vs",
            source.get("away"),
        )

    return {
        "date": str(source.get("date", ""))[:10],
        "league": source.get("league", ""),
        "home": source.get("home", ""),
        "away": source.get("away", ""),
        "market": "1.5",
        "probability": f"{probability:.4f}",
        "core_probability": f"{probability:.4f}",
        "low": "",
        "high": "",
        "field_temp_c": "",
        "factors": "Core 1 Over 1.5 walk-forward (factors 1-2 only)",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "hg": home_goals,
        "ag": away_goals,
        "result": result,
        "note": "CORE1_OVER15|HISTORICAL",
    }


def main():
    if not REPORT.exists():
        print(
            "::error::reports/core1_results.csv not found. "
            "Run core_calibration_check.py first (it writes that report)."
        )
        raise SystemExit(1)

    existing = read_csv(PICKS)
    positions = {
        key(row): index
        for index, row in enumerate(existing)
    }

    added = 0
    updated = 0
    protected = 0

    for source in read_csv(REPORT):
        pick = make_pick(source)

        if pick is None:
            continue

        fixture_key = key(pick)

        if fixture_key not in positions:
            positions[fixture_key] = len(existing)
            existing.append(pick)
            added += 1
            continue

        index = positions[fixture_key]
        old = existing[index]

        if not is_core1_hist(old):
            # A live Core 1 pick already covers this fixture and market.
            # Preserve the live row.
            protected += 1
            continue

        existing[index] = pick
        updated += 1

    with PICKS.open("w", newline="", encoding="utf-8") as file:
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
    print("BARBADOX CORE 1 HISTORICAL TRACKING COMPLETE")
    print(f"Threshold: {THRESHOLD:.1%}")
    print(f"New rows: {added}")
    print(f"Updated historical rows: {updated}")
    print(f"Protected live rows: {protected}")
    print(f"Total shared picks: {len(existing)}")


if __name__ == "__main__":
    main()
