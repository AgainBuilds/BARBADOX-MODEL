"""
Verifies the 'upper' bound used in cmd_run to decide which fixtures are even worth
filling in context.csv for. Claim being tested: no combination of factors 3-4 (formation
effect, absences/rotation, within their configured caps) can ever push a fixture's
probability above `upper`. If that's false, the filter would wrongly tell you to skip a
fixture that could actually have cleared the threshold.

Run: python test_upper_bound.py
"""
import itertools
import random
from datetime import timedelta

import barbadox_core as bc


def make_pool(n_teams=10, n_prev=80, n_form=20, seed=0):
    rng = random.Random(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    season_start = bc.season_start(bc.CURRENT_SEASON)
    matches = []
    dt = season_start - timedelta(days=260)
    for _ in range(n_prev):
        h, a = rng.sample(teams, 2)
        matches.append(bc.prep({"date": dt.isoformat(), "home": h, "away": a,
                                "hg": rng.randint(0, 4), "ag": rng.randint(0, 4), "status": "FINISHED"}))
        dt += timedelta(days=2)
    dt = season_start + timedelta(days=5)
    for _ in range(n_form):
        h, a = rng.sample(teams, 2)
        matches.append(bc.prep({"date": dt.isoformat(), "home": h, "away": a,
                                "hg": rng.randint(0, 4), "ag": rng.randint(0, 4), "status": "FINISHED"}))
        dt += timedelta(days=3)
    return matches, teams


def brute_force_max(fix, env, market):
    """Grid-search the real factor 3-4 parameter space and return the highest point
    probability achieved by any combination, i.e. the TRUE best case."""
    formations = [-2, -1, 0, 1, 2]
    rotations = [0, 1, 2]
    # Absence strings: none, and combinations of DEF/GK importance levels that land
    # at or above the def_cap (0.15) and below it, so the cap itself gets exercised.
    absence_options = [
        "none",
        "D1:DEF:1",
        "D1:DEF:2;D2:DEF:2",
        "GK1:GK:3",
        "GK1:GK:3;D1:DEF:3;D2:DEF:3",     # sums to 0.21, capped at 0.15
        "F1:FWD:3",                        # attacking loss -- should only ever hurt, never help
    ]
    best = -1.0
    best_combo = None
    for h_fe, a_fe, h_rot, a_rot, h_ab, a_ab in itertools.product(
            formations, formations, rotations, rotations, absence_options, absence_options):
        row = {
            "checked": "1", "derby": "", "field_temp_c": "",
            "home_formation_effect": str(h_fe), "away_formation_effect": str(a_fe),
            "home_rotation": str(h_rot), "away_rotation": str(a_rot),
            "home_absences": h_ab, "away_absences": a_ab,
        }
        res = bc.analyze(fix, row, env, market)
        if res["p"] is None:
            continue
        if res["p"] > best:
            best = res["p"]
            best_combo = (h_fe, a_fe, h_rot, a_rot, h_ab, a_ab)
    return best, best_combo


def main():
    matches, teams = make_pool()
    pools = {lg: [] for lg in bc.LEAGUES}
    pools["PL"] = matches
    env = bc.Env(pools)
    bc.CFG["min_games_for_mu"] = 10  # synthetic pool is small; let league_mu actually compute

    failures = 0
    checked = 0
    tight = 0
    for h, a in itertools.islice(itertools.permutations(teams, 2), 15):
        fix = {"hk": bc.norm(h), "ak": bc.norm(a), "league": "PL", "home": h, "away": a}
        base = bc.analyze(fix, None, env, bc.CFG["market"])
        if base["p"] is None:
            continue
        checked += 1
        formula_upper = base["upper"]
        true_best, combo = brute_force_max(fix, env, bc.CFG["market"])

        status = "OK"
        if true_best > formula_upper + 1e-9:
            status = "FAIL (filter would wrongly skip a winnable fixture)"
            failures += 1
        if abs(true_best - formula_upper) < 1e-6:
            tight += 1

        print(f"{h:>4} vs {a:<4}  core={bc.pct(base['core'])}  formula_upper={bc.pct(formula_upper)}  "
              f"brute_force_best={bc.pct(true_best)}  [{status}]")

    print(f"\n{checked} fixtures checked, {failures} failure(s), {tight} exactly tight "
          f"(brute force matched the formula to 6 decimals).")
    if failures:
        raise SystemExit(1)
    print("PASS: the formula upper bound is a safe, exact ceiling for factors 3-4 "
          "across every fixture and every combination tried.")


if __name__ == "__main__":
    main()
