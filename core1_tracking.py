#!/usr/bin/env python3
"""Merge qualifying historical Core 1 Over 1.5 picks from reports/core1_results.csv
into picks.csv, mirroring what core2_tracking.py does for Core 2.

Rules:
- Only rows with cleared=1 (core probability >= CORE1_THRESHOLD, default 0.79) merge.
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
import csv, os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "core1_results.csv"
PICKS = ROOT / "picks.csv"
THRESHOLD = float(os.getenv("CORE1_THRESHOLD", "0.79"))
FIELDS = ["date", "league", "home", "away", "market", "probability", "core_probability",
          "low", "high", "field_temp_c", "factors", "logged_at", "hg", "ag", "result", "note"]


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def is_core1_hist(r):
    return str(r.get("note", "")).strip().upper().startswith("CORE1_OVER15")


def key(r):
    market = "1.5" if is_core1_hist(r) else str(r.get("market", "")).strip()
    return (str(r.get("date", ""))[:10], str(r.get("league", "")).upper().strip(),
            norm(r.get("home")), norm(r.get("away")), market)


def make_pick(s):
    try:
        p = float(s.get("p_final", ""))
    except (ValueError, TypeError):
        return None
    if not 0 <= p <= 1 or p < THRESHOLD:
        return None
    if str(s.get("cleared", "")).strip() != "1":
        return None
    try:
        hg, ag = int(s["hg"]), int(s["ag"])
    except (KeyError, ValueError, TypeError):
        return None
    result = "HIT" if hg + ag >= 2 else "MISS"
    flag = str(s.get("hit", "")).strip()
    if flag in ("0", "1") and flag != ("1" if result == "HIT" else "0"):
        print("WARNING: Core 1 report hit flag disagrees with score:",
              s.get("home"), "vs", s.get("away"))
    return {
        "date": str(s.get("date", ""))[:10], "league": s.get("league", ""),
        "home": s.get("home", ""), "away": s.get("away", ""),
        "market": "1.5", "probability": f"{p:.4f}", "core_probability": f"{p:.4f}",
        "low": "", "high": "", "field_temp_c": "",
        "factors": "Core 1 Over 1.5 walk-forward (factors 1-2 only)",
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "hg": hg, "ag": ag, "result": result,
        "note": "CORE1_OVER15|HISTORICAL",
    }


def main():
    if not REPORT.exists():
        print("::error::reports/core1_results.csv not found. Run "
              "core_calibration_check.py first (it writes that report).")
        raise SystemExit(1)

    existing = read_csv(PICKS)
    positions = {key(row): i for i, row in enumerate(existing)}
    added = updated = protected = 0

    for source in read_csv(REPORT):
        pick = make_pick(source)
        if pick is None:
            continue
        k = key(pick)
        if k not in positions:
            positions[k] = len(existing)
            existing.append(pick)
            added += 1
            continue
        i = positions[k]
        old = existing[i]
        if not is_core1_hist(old):
            # A live Core 1 pick already covers this fixture+market; live rows win.
            protected += 1
            continue
        existing[i] = pick
        updated += 1

    with PICKS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows({field: r.get(field, "") for field in FIELDS} for r in existing)

    print("\nBARBADOX CORE 1 HISTORICAL TRACKING COMPLETE")
    print(f"Threshold: {THRESHOLD:.1%} | new: {added} | updated: {updated} | protected (live rows kept): {protected}")
    print(f"Total shared picks: {len(existing)}")


if __name__ == "__main__":
    main()
