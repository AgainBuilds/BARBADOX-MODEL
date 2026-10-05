#!/usr/bin/env python3
"""
Head-to-head analysis (separate from everything else).

What this answers: across real, already-played matches, do pairs with a history of
low-scoring meetings actually miss the Over more often than pairs without one? This is
an aggregate statistical test, not a search for stories about specific teams. It reuses
core_calibration_check.py's walk-forward results (same leakage-safe, core-only matches
that cleared the threshold), then for each one looks up that pair's REAL prior meetings,
not invented ones, strictly before that match's date, same no-future-peeking rule as
everything else here.

It does not change barbadox_core.py, does not change picks.csv or context.csv, and does
not add anything to the live model. It only reads data and prints a report. Any decision
to act on what it finds (e.g. a static list of specific pairs with a real, deep,
low-scoring history) is a separate, manual, human call, not something this script does
on its own.

Run:
    python h2h_analysis.py
    python h2h_analysis.py --h2h-min-meetings 4 --h2h-low-share 0.5

Needs FOOTBALL_DATA_KEY set, same as everything else.
"""
import argparse

import barbadox_core as bc
import core_calibration_check as cc


def h2h_history(hk, ak, pools, cutoff_dt, lookback):
    """Every prior meeting between these two teams, across all loaded leagues/seasons,
    strictly before cutoff_dt (same leakage rule as the walk-forward check), most recent
    first, capped at `lookback` matches."""
    meetings = []
    for lg, ms in pools.items():
        for m in ms:
            if not m["finished"] or m["dt"] >= cutoff_dt:
                continue
            if {m["hk"], m["ak"]} == {hk, ak}:
                meetings.append(m)
    meetings.sort(key=lambda m: m["dt"], reverse=True)
    return meetings[:lookback]


def h2h_group(meetings, market, min_meetings, low_share):
    if len(meetings) < min_meetings:
        return "insufficient"
    unders = sum(1 for m in meetings if (m["hg"] + m["ag"]) <= market)
    share = unders / len(meetings)
    return "low" if share >= low_share else "normal"


def summarize(rows, label):
    if not rows:
        print(f"  {label}: 0 matches")
        return
    hits = sum(1 for r in rows if r["actual_over"])
    rate = hits / len(rows) * 100
    import math
    se = math.sqrt(rate/100 * (1 - rate/100) / len(rows)) * 100 if len(rows) > 1 else 0
    lo, hi = max(0, rate - 1.96*se), min(100, rate + 1.96*se)
    print(f"  {label}: {hits}/{len(rows)} hit -> {rate:.0f}%  (approx 95% CI: {lo:.0f}%-{hi:.0f}%)")


def main():
    ap = argparse.ArgumentParser(description="Does a low-scoring H2H history actually predict misses?")
    ap.add_argument("--leagues", default="PL,PD,FL1,BL1,SA")
    ap.add_argument("--market", type=float, default=bc.CFG["market"])
    ap.add_argument("--threshold", type=float, default=bc.CFG["threshold"])
    ap.add_argument("--seasons-back", type=int, default=2)
    ap.add_argument("--data-seasons", type=int, default=6)
    ap.add_argument("--h2h-lookback", type=int, default=10, help="max prior meetings to consider per pair")
    ap.add_argument("--h2h-min-meetings", type=int, default=4,
                    help="minimum real prior meetings needed before a pair counts as having H2H history")
    ap.add_argument("--h2h-low-share", type=float, default=0.5,
                    help="share of prior meetings that must be under the line to flag a pair as 'low'")
    args = ap.parse_args()
    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]
    test_seasons = [bc.CURRENT_SEASON - i for i in range(args.seasons_back)]
    data_seasons = max(args.data_seasons, args.seasons_back + 1)

    print(f"Fetching {data_seasons} seasons of raw data...")
    pools = {lg: [] for lg in bc.LEAGUES}
    for lg in leagues:
        ms = []
        for season in range(bc.CURRENT_SEASON - data_seasons + 1, bc.CURRENT_SEASON + 1):
            ms += bc.load_league(lg, season, refresh=False)
        pools[lg] = ms

    print("Running the walk-forward core check to get the matches that cleared the threshold...")
    rows, skipped = cc.walk_forward(pools, leagues, test_seasons, args.market, args.threshold)
    cleared = [r for r in rows if r["core"] >= args.threshold]
    print(f"{len(rows)} matches checked, {len(cleared)} cleared {bc.pct(args.threshold)}\n")

    print(f"Looking up real head-to-head history for each (min {args.h2h_min_meetings} meetings, "
          f"flag 'low' if >= {args.h2h_low_share*100:.0f}% of their last {args.h2h_lookback} meetings "
          f"were under the line)...\n")

    groups = {"low": [], "normal": [], "insufficient": []}
    for r in cleared:
        past_pools = {lg: [x for x in ms if x["dt"] < r["dt"]] for lg, ms in pools.items()}
        meetings = h2h_history(r["hk"], r["ak"], past_pools, r["dt"], args.h2h_lookback)
        g = h2h_group(meetings, args.market, args.h2h_min_meetings, args.h2h_low_share)
        groups[g].append(r)

    print("Results (this is the actual test, not a story about any one team):")
    summarize(groups["low"], "H2H flagged LOW (history of low-scoring meetings)")
    summarize(groups["normal"], "H2H normal (no such history)")
    summarize(groups["insufficient"], "Not enough real H2H history to judge")

    print()
    low_n, normal_n = len(groups["low"]), len(groups["normal"])
    if low_n >= 15 and normal_n >= 15:
        low_rate = sum(1 for r in groups["low"] if r["actual_over"]) / low_n
        normal_rate = sum(1 for r in groups["normal"] if r["actual_over"]) / normal_n
        gap = (normal_rate - low_rate) * 100
        print(f"Gap: {gap:.0f} points (normal-group hit rate minus low-group hit rate).")
        if gap >= 8:
            print("That's a real enough gap to be worth a closer, careful look, not proof on its own, "
                  "but worth examining which specific pairs are driving the 'low' group before acting.")
        else:
            print("Not a clear enough gap to act on. Could easily be noise at this sample size.")
    else:
        print("Too few matches in one of the groups yet (need 15+ each) for the gap to mean much. "
              "Re-run with more seasons, or revisit once more fixtures have been played.")


if __name__ == "__main__":
    main()
