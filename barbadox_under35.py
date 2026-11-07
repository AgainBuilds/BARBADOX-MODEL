#!/usr/bin/env python3
"""
Barbadox Core 2 - Under 3.5 Goals - Live Feed.

Uses barbadox_core2.py for:
    - Shrunk attack and defence strengths
    - Poisson Under 3.5 probability
    - Season-baseline adjustment
    - Walk-forward calibration
    - Wilson-neighbour safety guard

The live feed reads match data through barbadox_core.py and writes:
    docs/under35.json

It does not modify:
    context.csv
    docs/data.json

It appends each qualified pick to picks.csv (market 3.5, note
CORE2_UNDER35|UPCOMING, probability = p_blue) so that Core 2
recommendations are graded by the daily review and settled into the
universal BLUE balance like Core 1 recommendations.

BLUE (universal team-balance system) is applied before qualification:
adjusted probability = original probability + home balance + away
balance. The threshold is unchanged (0.60).

Default scan window: 7 days.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import barbadox_core as bc
import barbadox_core2 as c2
import blue_balance as blue
import gh_sync

# Fixtures kicking off sooner than this (or already started) never qualify.
KICKOFF_BUFFER_MIN = max(0, int(os.environ.get("KICKOFF_BUFFER_MINUTES", "30")))


BASE_DIR = Path(__file__).resolve().parent
OUT_FILE = BASE_DIR / "docs" / "under35.json"

DEFAULT_LEAGUES = "PL,PD,FL1,BL1,SA"

DEFAULT_THRESHOLD = float(
    os.environ.get("UNDER35_THRESHOLD", "0.60")
)


def load_history(leagues):
    """Load finished and upcoming matches from Core 1's cached data."""
    out = []
    empty = []

    for league in leagues:
        league_count = 0

        for season in (
            bc.CURRENT_SEASON - 1,
            bc.CURRENT_SEASON,
        ):
            matches = bc.load_league(
                league,
                season,
                False,
            )

            for match in matches:
                league_count += 1

                out.append({
                    "league": league,
                    "season": season,
                    "date": match["date"][:10],
                    "utc": match["date"],
                    "home_id": match["hk"],
                    "away_id": match["ak"],
                    "home": match["home"],
                    "away": match["away"],
                    "status": match.get("status", ""),
                    "hg": match.get("hg"),
                    "ag": match.get("ag"),
                    "dt": match["dt"],
                })

        if league_count == 0:
            empty.append(league)

    return out, empty


def analyse(matches, threshold, d0, d1):
    """
    Analyse upcoming Under 3.5 fixtures.

    d0 is inclusive.
    d1 is exclusive.

    Returns:
        status, reason, fixtures
    """
    timezone_offset = timedelta(
        hours=bc.CFG["kickoff_tz_hours"]
    )

    latest_season = bc.CURRENT_SEASON
    upcoming = []

    # Select fixtures inside the requested date window.
    for match in matches:
        if match["season"] != latest_season:
            continue

        if match["status"] not in (
            "SCHEDULED",
            "TIMED",
        ):
            continue

        local_datetime = match["dt"] + timezone_offset

        if d0 <= local_datetime.date() < d1:
            upcoming.append((local_datetime, match))

    upcoming.sort(key=lambda item: item[0])

    if not upcoming:
        return "ok", "no fixtures in the window", []

    # Build historical rows and team states.
    rows, states = c2.build_rows(matches)
    model, k_by_season = c2.walk_forward(rows)

    if len(model) < c2.MIN_HISTORY:
        return (
            "no-history",
            "not enough finished matches to calibrate yet",
            [],
        )

    historical_under35_rate = (
        sum(row["y"] for row in model) / len(model)
    )

    # Fit calibration using historical predictions.
    slope = c2.fit_slope([
        (row["off"], row["x"], row["y"])
        for row in model
    ])

    completed_predictions = [
        row for row in model
        if row["p_cal"] is not None
    ]

    # Choose the model's shrinkage K.
    if latest_season in k_by_season:
        K = k_by_season[latest_season]
    else:
        earlier_rows = [
            row for row in rows
            if row["season"] < latest_season
        ]
        K = c2.tune_k(earlier_rows)

    output = []

    # Predict upcoming fixtures.
    for local_datetime, match in upcoming:
        entry = {
            "date": local_datetime.strftime("%Y-%m-%d"),
            "time": local_datetime.strftime("%H:%M"),
            "league": match["league"],
            "home": match["home"],
            "away": match["away"],
            "kickoff_utc": match["dt"].isoformat(),
        }

        if match["dt"] <= bc.NOW + timedelta(minutes=KICKOFF_BUFFER_MIN):
            entry.update({
                "decision": "started",
                "reason": "Kickoff has passed or is inside the buffer.",
            })
            output.append(entry)
            continue

        state = states.get((
            match["league"],
            latest_season,
        ))

        if state is None:
            entry.update({
                "decision": "skipped",
                "reason": "no season state available",
            })
            output.append(entry)
            continue

        features = state.feats(
            match["home_id"],
            match["away_id"],
        )

        if features is None:
            entry.update({
                "decision": "skipped",
                "reason": "not enough games yet",
            })
            output.append(entry)
            continue

        # Expected total goals.
        lambda_total = c2.lam_total(features, K)

        # Probability of 0, 1, 2 or 3 total goals.
        p_raw = c2.pois_cdf(
            c2.GOAL_LINE,
            lambda_total,
        )

        # Season baseline and calibration.
        offset = c2.logit(
            c2.season_base(
                features,
                historical_under35_rate,
            )
        )

        x = c2.logit(p_raw) - offset
        p_cal = c2.sigmoid(offset + slope * x)

        # Historical safety guard.
        p_final = c2.guard(
            p_cal,
            completed_predictions,
        )

        if p_final is None:
            entry.update({
                "decision": "skipped",
                "reason": "not enough history for safety check",
            })
            output.append(entry)
            continue

        # BLUE: adjusted probability = original probability
        # + home balance + away balance. Threshold unchanged (0.60).
        # A fixture only sees settlements from strictly earlier days.
        p_blue = blue.adjust(
            match["home"],
            match["away"],
            p_final,
            as_of=entry["date"],
        )

        entry.update({
            "decision": (
                "qualified"
                if p_blue >= threshold
                else "below-line"
            ),
            "p_raw": round(p_raw, 4),
            "p_cal": round(p_cal, 4),
            "p_final": round(p_final, 4),
            "p_blue": round(p_blue, 4),
            "lambda_total": round(lambda_total, 4),
            "threshold": threshold,
        })

        output.append(entry)

    return "ok", "", output


def _log_picks(qualified):
    """
    Append qualified Under 3.5 picks to picks.csv.

    Rows use market 3.5 and note CORE2_UNDER35|UPCOMING so Core 1
    tooling never confuses them with Over picks. The probability is
    the BLUE-adjusted value (the one that cleared the bar).
    Deduplicated on date/league/teams/market; never rewrites or drops
    existing rows.
    """
    if not qualified:
        return 0

    picks = bc.read_picks()

    existing = {
        (
            str(p.get("date", ""))[:10],
            str(p.get("league", "")).upper().strip(),
            bc.norm(p.get("home")),
            bc.norm(p.get("away")),
            "3.5",
        )
        for p in picks
    }

    added = 0

    for fixture in qualified:
        key = (
            str(fixture.get("date", ""))[:10],
            str(fixture.get("league", "")).upper().strip(),
            bc.norm(fixture.get("home")),
            bc.norm(fixture.get("away")),
            "3.5",
        )

        if key in existing:
            continue

        picks.append({
            "date": str(fixture.get("date", ""))[:10],
            "league": fixture.get("league", ""),
            "home": fixture.get("home", ""),
            "away": fixture.get("away", ""),
            "market": "3.5",
            "probability": f"{fixture.get('p_blue', 0):.4f}",
            "core_probability": f"{fixture.get('p_final', 0):.4f}",
            "low": "",
            "high": "",
            "field_temp_c": "",
            "factors": "Core 2 Under 3.5 live (blue-adjusted)",
            "logged_at": bc.NOW.isoformat(),
            "hg": "",
            "ag": "",
            "result": "",
            "note": "CORE2_UNDER35|UPCOMING",
        })

        existing.add(key)
        added += 1

    if added:
        bc.write_picks(picks)

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Barbadox Core 2 - Under 3.5 Goals - Live Feed"
    )

    parser.add_argument(
        "--date",
        default=None,
        help="Start date in YYYY-MM-DD format (default: today)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to scan (default: 7)",
    )

    parser.add_argument(
        "--leagues",
        default=DEFAULT_LEAGUES,
        help="Comma-separated league keys",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Minimum final probability, default 0.60",
    )

    args = parser.parse_args()

    if not 0 < args.threshold < 1:
        sys.exit(
            "Threshold must be greater than 0 and less than 1."
        )

    if args.days < 1:
        sys.exit("--days must be at least 1.")

    leagues = [
        item.strip().upper()
        for item in args.leagues.split(",")
        if item.strip()
    ]

    invalid_leagues = [
        league for league in leagues
        if league not in bc.LEAGUES
    ]

    if invalid_leagues:
        sys.exit(
            "Unknown league key(s): "
            + ", ".join(invalid_leagues)
        )

    timezone_offset = timedelta(
        hours=bc.CFG["kickoff_tz_hours"]
    )

    if args.date:
        try:
            start_date = datetime.strptime(
                args.date,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            sys.exit("--date must use YYYY-MM-DD format.")
    else:
        start_date = (
            bc.NOW + timezone_offset
        ).date()

    end_date = start_date + timedelta(days=args.days)

    print("CORE 2 UNDER 3.5: loading match data...")

    # BLUE: settle the universal team-balance ledger before analysis.
    # Reads picks.csv; idempotent; does not modify picks.csv.
    try:
        blue_settled = blue.settle()

        if blue_settled:
            print(
                "CORE 2 UNDER 3.5: BLUE settled "
                + str(blue_settled)
                + " new recommendation(s)."
            )

    except Exception as exc:
        print("CORE 2 UNDER 3.5: BLUE settlement skipped: " + str(exc))

    matches, empty_leagues = load_history(leagues)

    status, reason, fixtures = analyse(
        matches,
        args.threshold,
        start_date,
        end_date,
    )

    snapshot = {
        "generated_at": bc.NOW.isoformat(),
        "window": {
            "from": str(start_date),
            "to": str(end_date - timedelta(days=1)),
        },
        "model": "Core 2 - Under 3.5",
        "market": 3.5,
        "threshold": args.threshold,
        "status": status,
        "reason": reason,
        "scanned": len(fixtures),
        "leagues_empty": empty_leagues,
        "fixtures": fixtures,
    }

    OUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = OUT_FILE.with_suffix(".json.tmp")

    temporary_file.write_text(
        json.dumps(snapshot, indent=1),
        encoding="utf-8",
    )

    # Atomic replacement prevents partially written JSON.
    temporary_file.replace(OUT_FILE)

    qualified = [
        fixture for fixture in fixtures
        if fixture["decision"] == "qualified"
    ]

    # Log the qualified picks to picks.csv so the daily review grades
    # them and BLUE settles them into the universal balance.
    try:
        if qualified and gh_sync.enabled():
            gh_sync.pull("picks.csv")

        new_picks = _log_picks(qualified)

        if new_picks and gh_sync.enabled():
            gh_sync.push(
                "picks.csv",
                f"Barbadox: log {new_picks} Core 2 Under 3.5 pick(s)",
            )

        if new_picks:
            print(
                "CORE 2 UNDER 3.5: logged "
                + str(new_picks)
                + " new Under pick(s) to picks.csv."
            )

    except Exception as exc:
        print("CORE 2 UNDER 3.5: pick logging skipped: " + str(exc))

    print(
        f"CORE 2 UNDER 3.5: {len(fixtures)} fixture(s) "
        f"scanned, {len(qualified)} cleared "
        f"{args.threshold * 100:.0f}%. Status: {status}"
        f"{' (' + reason + ')' if reason else ''}."
    )

    top_fixtures = sorted(
        qualified,
        key=lambda fixture: -fixture["p_blue"],
    )[:5]

    for fixture in top_fixtures:
        print(
            f"  {fixture['date']} "
            f"{fixture['league']:<4} "
            f"{fixture['home']} vs {fixture['away']} "
            f"{fixture['p_blue'] * 100:.1f}% (blue)"
        )

    if len(qualified) > len(top_fixtures):
        print(
            f"  ... and {len(qualified) - len(top_fixtures)} "
            "more in docs/under35.json"
        )

    if empty_leagues:
        print(
            "CORE 2 UNDER 3.5: no data from: "
            + ", ".join(empty_leagues)
        )


if __name__ == "__main__":
    main()

