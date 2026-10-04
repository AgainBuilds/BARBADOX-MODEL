#!/usr/bin/env python3
"""
Core calibration check (separate from everything else).

What it does, plainly: for every match already finished this season, it pretends it's
the morning before that match and only looks at results from before it, nothing after.
It asks the Poisson core (factors 1-2 only, no LLM, no hand-entered factors) what it
would have said, then checks that against the real result. No leakage: by the time it's
judging any given match, nothing in its own future has been shown to it.

This is NOT the old backtest. It doesn't touch factors 3-5, doesn't call an LLM, and
doesn't go anywhere near the hindsight-leakage problem that one had. It also doesn't need
the international break to end, it only needs matches that have already been played,
and this season already has some.

It does not change picks.csv, context.csv, or anything barbadox_core.py writes. It only
reads data and prints a report.

Run:
    python core_calibration_check.py
    python core_calibration_check.py --leagues PL,PD --market 1.5 --threshold 0.79

Needs FOOTBALL_DATA_KEY set, same as everything else.
"""
import argparse
import sys
from datetime import timedelta

import barbadox_core as bc


def walk_forward(pools, leagues, market, threshold):
    rows = []
    skipped = 0
    for lg in leagues:
        current = sorted([m for m in pools.get(lg, [])
                          if m["finished"] and m["dt"] >= bc.season_start(bc.CURRENT_SEASON)],
                         key=lambda m: m["dt"])
        for m in current:
            past_pools = {l2: [x for x in ms if x["dt"] < m["dt"]] for l2, ms in pools.items()}
            env = bc.Env(past_pools)
            fix = {"hk": m["hk"], "ak": m["ak"], "league": lg, "home": m["home"], "away": m["away"]}
            res = bc.analyze(fix, None, env, market)
            if res["p"] is None:
                skipped += 1
                continue
            rows.append({
                "date": m["dt"].date().isoformat(), "league": lg, "home": m["home"], "away": m["away"],
                "core": res["p"], "actual_over": (m["hg"] + m["ag"]) > market,
            })
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description="Check the Poisson core against real matches already played.")
    ap.add_argument("--leagues", default="PL,PD,FL1,BL1,SA")
    ap.add_argument("--market", type=float, default=bc.CFG["market"])
    ap.add_argument("--threshold", type=float, default=bc.CFG["threshold"])
    args = ap.parse_args()
    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]

    print("Loading data...")
    pools = bc.load_for_leagues(leagues)

    print("Walking forward through this season's finished matches...\n")
    rows, skipped = walk_forward(pools, leagues, args.market, args.threshold)

    if not rows:
        print("No finished matches to check yet. Nothing to report.")
        sys.exit(0)

    cleared = [r for r in rows if r["core"] >= args.threshold]
    hits = [r for r in cleared if r["actual_over"]]

    print(f"{len(rows)} matches checked, {skipped} skipped (not enough prior data at the time)")
    print(f"{len(cleared)} would have cleared {bc.pct(args.threshold)}")
    if cleared:
        print(f"{len(hits)}/{len(cleared)} of those hit -> {len(hits)/len(cleared)*100:.0f}%\n")
        for r in sorted(cleared, key=lambda x: x["date"]):
            print(f"  {r['date']} {r['league']:<5} {r['home']} vs {r['away']}  "
                  f"{bc.pct(r['core'])}  {'HIT' if r['actual_over'] else 'MISS'}")
    else:
        print("None cleared the threshold yet this season.")


if __name__ == "__main__":
    main()
