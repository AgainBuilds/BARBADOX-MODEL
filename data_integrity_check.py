
#!/usr/bin/env python3
"""BARBADOX read-only historical data integrity audit."""

import csv
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent

FILES = {
    "core1": ROOT / "reports" / "core1_results.csv",
    "core2": ROOT / "reports" / "core2_results.csv",
    "picks": ROOT / "picks.csv",
}

REQUIRED = {
    "core1": {
        "date", "league", "home", "away",
        "hg", "ag", "hit", "cleared"
    },
    "core2": {
        "date", "league", "home", "away",
        "hg", "ag", "hit", "cleared"
    },
    "picks": {
        "date", "league", "home", "away",
        "market", "hg", "ag", "result"
    },
}


def normalise(value):
    return "".join(
        c.lower()
        for c in str(value or "")
        if c.isalnum()
    )


def read_file(path):
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)
        return reader.fieldnames or [], list(reader)


def fixture_key(row, market=None):
    return (
        str(row.get("date", ""))[:10],
        str(row.get("league", "")).strip().upper(),
        normalise(row.get("home")),
        normalise(row.get("away")),
        str(
            market if market is not None
            else row.get("market", "")
        ).strip(),
    )


def audit_file(name, path):
    headers, rows = read_file(path)
    problems = []

    missing_headers = REQUIRED[name] - set(headers)

    if missing_headers:
        problems.append(
            f"Missing columns: {sorted(missing_headers)}"
        )

    keys = [
        fixture_key(
            row,
            "1.5" if name == "core1"
            else "3.5" if name == "core2"
            else None
        )
        for row in rows
    ]

    duplicates = [
        key
        for key, count in Counter(keys).items()
        if count > 1
    ]

    missing_identity = [
        index + 2
        for index, row in enumerate(rows)
        if not all(
            row.get(field)
            for field in (
                "date", "league", "home", "away"
            )
        )
    ]

    if name == "picks":
        allowed = {
            "", "HIT", "MISS",
            "POSTPONED", "CANCELLED", "VOID"
        }

        invalid_results = [
            index + 2
            for index, row in enumerate(rows)
            if str(row.get("result", "")).upper()
            not in allowed
        ]

    else:
        invalid_results = [
            index + 2
            for index, row in enumerate(rows)
            if (
                row.get("hit", "") not in ("0", "1")
                or row.get("cleared", "") not in ("", "0", "1")
            )
        ]

    print(f"\n[{name.upper()}]")
    print(f"Rows: {len(rows)}")
    print(f"Columns: {len(headers)}")
    print(f"Duplicate fixture keys: {len(duplicates)}")
    print(f"Missing identity fields: {len(missing_identity)}")
    print(f"Invalid result fields: {len(invalid_results)}")

    if duplicates:
        problems.append(
            f"Duplicate keys: {duplicates[:5]}"
        )

    if missing_identity:
        problems.append(
            f"Missing identity rows: {missing_identity[:10]}"
        )

    if invalid_results:
        problems.append(
            f"Invalid result rows: {invalid_results[:10]}"
        )

    for problem in problems:
        print("WARNING:", problem)

    return rows, problems


def compare_reports(picks, reports):
    pick_map = {
        fixture_key(row): row
        for row in picks
    }

    print("\n[CROSS-FILE CONSISTENCY]")

    for name, rows in reports.items():
        market = "1.5" if name == "core1" else "3.5"

        checked = 0
        missing = 0
        disagreements = 0

        for row in rows:
            if row.get("cleared") != "1":
                continue

            key = fixture_key(row, market)
            pick = pick_map.get(key)

            if pick is None:
                missing += 1
                continue

            checked += 1

            expected = (
                "HIT" if row.get("hit") == "1"
                else "MISS"
            )

            if pick.get("result", "").upper() != expected:
                disagreements += 1

        print(
            f"{name.upper()}: "
            f"matched={checked}, "
            f"missing={missing}, "
            f"outcome disagreements={disagreements}"
        )


def main():
    reports = {}
    results = {}
    total_problems = 0

    for name, path in FILES.items():
        try:
            rows, problems = audit_file(name, path)

            results[name] = rows
            total_problems += len(problems)

            if name in ("core1", "core2"):
                reports[name] = rows

        except Exception as exc:
            print(f"\n[{name.upper()}] ERROR: {exc}")
            total_problems += 1

    if "picks" in results and len(reports) == 2:
        compare_reports(
            results["picks"],
            reports
        )

    print("\n" + "=" * 40)
    print(f"TOTAL AUDIT WARNINGS: {total_problems}")
    print("READ-ONLY AUDIT COMPLETE")
    print("No repository data was modified.")


if __name__ == "__main__":
    main()
