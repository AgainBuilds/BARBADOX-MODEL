#!/usr/bin/env python3
"""
Barbadox Core 2 v2 (Under 3.5) - live feed for the slips.

This does NOT change the Core 2 maths. It imports barbadox_core2.py (v2:
joint opponent-adjusted attack/defence strengths, Poisson predictive by
default, calibration slope + walk-forward shrunk league offsets, safety
haircut with optional P_CAP) and applies them to the upcoming fixtures,
then writes docs/under35.json for the console.

Same data as the Over 1.5 run: it reuses barbadox_core's loader and its data/ cache,
so right after a normal run it makes no extra API calls.

It never touches picks.csv, context.csv or docs/data.json.

USAGE
    python barbadox_under35.py
    python barbadox_under35.py --days 3 --threshold 0.75
    python barbadox_under35.py --leagues PL,PD,FL1,BL1,SA

ENVIRONMENT (optional)
    UNDER35_THRESHOLD   final-probability cutoff, default 0.75
    SAFETY_Z            Core 2 haircut strength, default 1.0 (read by barbadox_core2)
    K_JOINT             joint-fit prior weight, default 30 (read by barbadox_core2)
    USE_NB              1 = negative-binomial predictive (read by barbadox_core2)
    LEAGUE_RIDGE        league-offset shrinkage, default 25 (read by barbadox_core2)
    P_CAP               final probability cap, default 1.0 (read by barbadox_core2)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import barbadox_core as bc
import barbadox_core2 as c2


BASE_DIR = Path(__file__).resolve().parent
OUT_FILE = BASE_DIR / "docs" / "under35.json"

DEFAULT_LEAGUES = "PL,PD,FL1,BL1,SA"
DEFAULT_THRESHOLD = float(
    os.environ.get("UNDER35_THRESHOLD", "0.75")
)


def load_history(leagues):
    """Load the previous and current seasons in the format Core 2 expects."""
    out = []
    empty = []

    for lg in leagues:
        got = 0

        for season in (
            bc.CURRENT_SEASON - 1,
            bc.CURRENT_SEASON,
        ):
            for m in bc.load_league(lg, season, False):
                got += 1

                out.append({
                    "league": lg,
                    "season": season,
                    "date": m["date"][:10],
                    "utc": m["date"],
                    "home_id": m["hk"],
                    "away_id": m["ak"],
                    "home": m["home"],
                    "away": m["away"],
                    "status": m.get("status", ""),
                    "hg": m.get("hg"),
                    "ag": m.get("ag"),
                    "dt": m["dt"],
                })

        if not got:
            empty.append(lg)

    return out, empty


def analyse(matches, threshold, d0, d1):
    """
    Analyse upcoming fixtures using Core 2 v2.

    Returns:
        (status, reason, fixtures)
    """
    tz = timedelta(
        hours=bc.CFG["kickoff_tz_hours"]
    )

    latest = bc.CURRENT_SEASON
    fixtures = []

    for m in matches:
        if (
            m["season"] != latest
            or m["status"] not in ("SCHEDULED", "TIMED")
        ):
            continue

        loc = m["dt"] + tz

        if d0 <= loc.date() < d1:
            fixtures.append((loc, m))

    fixtures.sort(key=lambda x: x[0])

    if not fixtures:
        return "ok", "no fixtures in the window", []

    rows, states = c2.build_rows(matches)
    model, nb_by = c2.walk_forward(rows)

    if len(model) < c2.MIN_HISTORY:
        return (
            "no-history",
            "not enough finished matches to calibrate yet",
            [],
        )

    prior = sum(r["y"] for r in model) / len(model)

    b = c2.fit_slope([
        (r["off"], r["x"], r["y"])
        for r in model
    ])

    # NEW in v2: shrunk per-league logit offsets from walk-forward history.
    deltas = c2.league_deltas(model, b)

    done = [
        r for r in model
        if r["p_cal"] is not None
    ]

    # (v0, c) for the optional negative-binomial predictive.
    # With USE_NB=0 (default) raw_prob ignores it and uses Poisson.
    nbpar = nb_by.get(latest, (0.0, 0.0))

    out = []

    for loc, m in fixtures:
        entry = {
            "date": loc.strftime("%Y-%m-%d"),
            "time": loc.strftime("%H:%M"),
            "league": m["league"],
            "home": m["home"],
            "away": m["away"],
        }

        st = states.get((m["league"], latest))

        f = (
            st.feats(m["home_id"], m["away_id"])
            if st
            else None
        )

        if f is None:
            entry.update({
                "decision": "skipped",
                "reason": "not enough games yet",
            })

            out.append(entry)
            continue

        # v2: expected total goals now comes from the joint fit
        # (State2/JointState inside feats); K_JOINT governs the prior.
        p_raw = c2.raw_prob(f, nbpar)

        off = c2.logit(
            c2.season_base(f, prior)
        )

        # v2: slope calibration + per-league offset.
        p_cal = c2.sigmoid(
            off + b * (
                c2.logit(p_raw) - off
            ) + deltas.get(m["league"], 0.0)
        )

        # Unchanged; v2 also applies P_CAP inside guard().
        p_fin = c2.guard(
            p_cal,
            done,
        )

        if p_fin is None:
            entry.update({
                "decision": "skipped",
                "reason": "not enough history",
            })

            out.append(entry)
            continue

        entry.update({
            "decision": (
                "qualified"
                if p_fin >= threshold
                else "below-line"
            ),
            "p_raw": round(p_raw, 4),
            "p_cal": round(p_cal, 4),
            "p_final": round(p_fin, 4),
            "league_delta": round(
                deltas.get(m["league"], 0.0), 4
            ),
        })

        out.append(entry)

    return "ok", "", out


def main():
    ap = argparse.ArgumentParser(
        description="Barbadox Core 2 v2 (Under 3.5) live feed"
    )

    ap.add_argument(
        "--date",
        default=None,
        help="start date YYYY-MM-DD (default: today)",
    )

    ap.add_argument(
        "--days",
        type=int,
        default=3,
        help="scan window (default: 3 days)",
    )

    ap.add_argument(
        "--leagues",
        default=DEFAULT_LEAGUES,
    )

    ap.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
    )

    args = ap.parse_args()

    if not 0 < args.threshold < 1:
        sys.exit(
            "Threshold must be greater than 0 and less than 1."
        )

    if args.days < 1:
        sys.exit("--days must be at least 1.")

    leagues = [
        x.strip().upper()
        for x in args.leagues.split(",")
        if x.strip()
    ]

    bad = [
        x for x in leagues
        if x not in bc.LEAGUES
    ]

    if bad:
        sys.exit(
            f"Unknown league key(s): {', '.join(bad)}"
        )

    tz = timedelta(
        hours=bc.CFG["kickoff_tz_hours"]
    )

    d0 = (
        datetime.strptime(
            args.date,
            "%Y-%m-%d",
        ).date()
        if args.date
        else (bc.NOW + tz).date()
    )

    d1 = d0 + timedelta(days=args.days)

    print(
        "CORE 2 v2 (UNDER 3.5): loading data..."
    )

    matches, empty = load_history(leagues)

    status, reason, fixtures = analyse(
        matches,
        args.threshold,
        d0,
        d1,
    )

    snapshot = {
        "generated_at": bc.NOW.isoformat(),
        "window": {
            "from": str(d0),
            "to": str(d1 - timedelta(days=1)),
        },
        "model": "Core 2 v2 (Under 3.5)",
        "market": 3.5,
        "threshold": args.threshold,
        "status": status,
        "reason": reason,
        "scanned": len(fixtures),
        "leagues_empty": empty,
        "fixtures": fixtures,
    }

    OUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = OUT_FILE.with_suffix(".json.tmp")

    tmp.write_text(
        json.dumps(snapshot, indent=1),
        encoding="utf-8",
    )

    # Atomic replacement prevents a partially written JSON file.
    tmp.replace(OUT_FILE)

    qualified = [
        f for f in fixtures
        if f["decision"] == "qualified"
    ]

    print(
        f"CORE 2 v2 (UNDER 3.5): {len(fixtures)} fixture(s) "
        f"scanned, {len(qualified)} cleared "
        f"{args.threshold * 100:.0f}%. "
        f"Status: {status}"
        f"{' (' + reason + ')' if reason else ''}."
    )

    top = sorted(
        qualified,
        key=lambda x: -x["p_final"],
    )[:5]

    for f in top:
        print(
            f"  {f['date']} {f['league']:<4} "
            f"{f['home']} vs {f['away']}  "
            f"{f['p_final'] * 100:.1f}%"
        )

    if len(qualified) > len(top):
        print(
            f"  ... and {len(qualified) - len(top)} more "
            "in docs/under35.json"
        )

    if empty:
        print(
            "CORE 2 v2 (UNDER 3.5): no data from: "
            + ", ".join(empty)
        )


if __name__ == "__main__":
    main()
