#!/usr/bin/env python3
"""
Core calibration check (separate from everything else).

What it does, plainly: for every match already finished, going back up to a full extra
season, it pretends it's the morning before that match and only looks at results from
before it, nothing after. It asks the Poisson core (factors 1-2 only, no LLM, no
hand-entered factors) what it would have said, then checks that against the real
result. No leakage: by the time it's judging any given match, nothing in its own future
has been shown to it, including no peeking at a LATER season to judge an EARLIER one.

This does its own season-aware strength calculation rather than reusing Env.strength()
from barbadox_core.py, because that method decides "current form vs historical baseline"
using today's real season. That's correct for live picks (today's real season IS the
one that matters) but wrong for testing last season's matches, it would silently throw
away real same-season form for anything not in the current real season and score it on
baseline alone. This file fixes that without changing barbadox_core.py at all.

This is NOT the old backtest. It doesn't touch factors 3-5, doesn't call an LLM, and
doesn't go anywhere near the hindsight-leakage problem that one had.

It does not change picks.csv, context.csv, or anything barbadox_core.py writes. It only
reads data and prints a report.

Run:
    python core_calibration_check.py                    # this season + 1 full prior season
    python core_calibration_check.py --seasons-back 1    # just this season, old behaviour
    python core_calibration_check.py --leagues PL,PD

Needs FOOTBALL_DATA_KEY set, same as everything else.
"""
import argparse
import sys

import barbadox_core as bc


def team_strength_asof(team, league, pools, cutoff_dt, season, mu_h, mu_a):
    """Same math as Env.strength() in barbadox_core.py, but split by the given season,
    not whatever today's real season happens to be."""
    ms = [m for m in pools.get(league, []) if m["finished"] and m["dt"] < cutoff_dt
          and team in (m["hk"], m["ak"])]
    ms.sort(key=lambda m: m["dt"])
    cs = bc.season_start(season)
    base = [m for m in ms if m["dt"] < cs][-bc.CFG["baseline_games"]:]
    form = [m for m in ms if m["dt"] >= cs]
    sb = bc.shrunk_strengths(bc.split(team, base), mu_h, mu_a)
    sf = bc.shrunk_strengths(bc.split(team, form), mu_h, mu_a)
    nb, nf = len(base), len(form)
    w = 1.0 if nb == 0 else nf / (nf + bc.CFG["form_half_weight_games"])
    blend = {k: w * sf[k] + (1 - w) * sb[k] for k in sf}
    return blend, nb, nf


def core_probability(hk, ak, league, pools, cutoff_dt, season, market):
    mu_h, mu_a = bc.league_mu(pools.get(league, []))
    sh, nbh, nfh = team_strength_asof(hk, league, pools, cutoff_dt, season, mu_h, mu_a)
    sa, nba, nfa = team_strength_asof(ak, league, pools, cutoff_dt, season, mu_h, mu_a)
    if nbh + nfh == 0 or nba + nfa == 0:
        return None
    lam_h, lam_a = bc.expected_goals(sh, sa, mu_h, mu_a)
    return bc.p_over(lam_h + lam_a, market)


def walk_forward(pools, leagues, test_seasons, market, threshold):
    rows = []
    skipped = 0
    for lg in leagues:
        for season in test_seasons:
            cs, nxt = bc.season_start(season), bc.season_start(season + 1)
            matches = sorted([m for m in pools.get(lg, []) if m["finished"] and cs <= m["dt"] < nxt],
                             key=lambda m: m["dt"])
            for m in matches:
                past_pools = {l2: [x for x in ms if x["dt"] < m["dt"]] for l2, ms in pools.items()}
                p = core_probability(m["hk"], m["ak"], lg, past_pools, m["dt"], season, market)
                if p is None:
                    skipped += 1
                    continue
                rows.append({"date": m["dt"].date().isoformat(), "league": lg, "season": season,
                            "home": m["home"], "away": m["away"],
                            "core": p, "actual_over": (m["hg"] + m["ag"]) > market})
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description="Check the Poisson core against real matches already played.")
    ap.add_argument("--leagues", default="PL,PD,FL1,BL1,SA")
    ap.add_argument("--market", type=float, default=bc.CFG["market"])
    ap.add_argument("--threshold", type=float, default=bc.CFG["threshold"])
    ap.add_argument("--seasons-back", type=int, default=2,
                    help="how many seasons to test, counting this one. 2 = this season + 1 full prior season.")
    args = ap.parse_args()
    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]
    test_seasons = [bc.CURRENT_SEASON - i for i in range(args.seasons_back)]

    print(f"Testing seasons: {', '.join(f'{s}-{str(s+1)[2:]}' for s in sorted(test_seasons))}")
    print("Loading data (fetching one extra season back for baselines)...")
    pools = {lg: [] for lg in bc.LEAGUES}
    for lg in leagues:
        ms = []
        for season in range(min(test_seasons) - 1, bc.CURRENT_SEASON + 1):
            ms += bc.load_league(lg, season, refresh=False)
        pools[lg] = ms

    print("\nWalking forward through finished matches...\n")
    rows, skipped = walk_forward(pools, leagues, test_seasons, args.market, args.threshold)

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
        print("None cleared the threshold yet.")


if __name__ == "__main__":
    main()
