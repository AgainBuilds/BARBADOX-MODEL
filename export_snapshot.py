#!/usr/bin/env python3
"""
BARBADOX model snapshot exporter.

Uses the same prediction pipeline as barbadox_core.py.
The five-minute review window is separate from checked=1.

IMPORTANT:
- checked=1 means a match is finished/confirmed.
- Upcoming fixtures do not need checked=1 to be analysed.
- New fixtures trigger a review window.
- Pick logging can be deferred during that window.
- context.csv remains append-only.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import barbadox_core as bc
import gh_sync


BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_FILE = BASE_DIR / "docs" / "data.json"


def _pct_from(sheet_line):
    """Convert a percentage in a model sheet line to a probability."""
    try:
        value = sheet_line.split(":")[1].strip().split("%")[0]
        return round(float(value) / 100, 4)
    except (IndexError, ValueError):
        return None


def _match_key(fixture):
    """Stable key used to identify a fixture."""
    return (
        fixture["ldate"],
        bc.norm(fixture["home"]),
        bc.norm(fixture["away"]),
    )


def _context_key(fixture):
    """Key used by barbadox_core's context lookup."""
    return (
        fixture["ldate"],
        fixture["hk"],
        fixture["ak"],
    )


def export(args):
    leagues = [
        value.strip().upper()
        for value in args.leagues.split(",")
        if value.strip()
    ]

    bad = [league for league in leagues if league not in bc.LEAGUES]

    if bad:
        sys.exit(f"Unknown league key(s): {', '.join(bad)}")

    print("Loading data...")

    pools = bc.load_for_leagues(leagues, args.refresh)
    env = bc.Env(pools)

    tz = timedelta(hours=bc.CFG["kickoff_tz_hours"])

    if args.date:
        d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        d0 = (bc.NOW + tz).date()

    d1 = d0 + timedelta(days=args.days)

    fixtures = []

    for league in leagues:
        for match in pools.get(league, []):
            local_time = match["dt"] + tz

            if not (d0 <= local_time.date() < d1):
                continue

            if match["status"] not in ("SCHEDULED", "TIMED"):
                continue

            item = dict(match)
            item["league"] = league
            item["ldate"] = local_time.strftime("%Y-%m-%d")
            item["ltime"] = local_time.strftime("%H:%M")

            fixtures.append(item)

    threshold = args.threshold
    market = args.market
    use_github = gh_sync.enabled()

    if use_github:
        print(
            "GitHub sync ON: context.csv and picks.csv "
            "are read from and saved to the repository."
        )
    else:
        print(
            "WARNING: GITHUB SYNC OFF. "
            "Changes will remain in the local environment."
        )

    if args.defer_picks:
        print(
            "PICK LOGGING DEFERRED: this is the initial review pass. "
            "No new picks will be logged during this pass."
        )

    def build():
        """
        Build one snapshot.

        Existing context rows are preserved by sync_context().
        The checked field is displayed as completion status only.
        """

        context, added_context = bc.sync_context(
            fixtures,
            env,
            market,
            threshold,
        )

        if added_context:
            print("=" * 70)
            print(
                f"REVIEW WINDOW: {added_context} new fixture(s) "
                "were appended to context.csv."
            )
            print("WAIT 5 MINUTES before final pick logging.")
            print(
                "Do not change checked=1 on upcoming fixtures "
                "to approve them."
            )
            print("=" * 70)

        picks = bc.read_picks()

        logged_keys = {
            (
                pick["date"],
                bc.norm(pick["home"]),
                bc.norm(pick["away"]),
            )
            for pick in picks
        }

        new_picks = 0
        output_fixtures = []

        ordered_fixtures = sorted(
            fixtures,
            key=lambda fixture: (
                fixture["ldate"],
                fixture["ltime"],
            ),
        )

        for fixture in ordered_fixtures:
            row = context.get(_context_key(fixture))

            result = bc.analyze(
                fixture,
                row,
                env,
                market,
            )

            # checked=1 describes completion/confirmation.
            # It must not be used as an approval flag for an upcoming fixture.
            checked = (
                bool(row)
                and str(row.get("checked", "")).strip() == "1"
            )

            entry = {
                "date": fixture["ldate"],
                "time": fixture["ltime"],
                "league": fixture["league"],
                "home": fixture["home"],
                "away": fixture["away"],
                "checked": checked,
            }

            if result.get("p") is None:
                entry.update({
                    "decision": "skipped",
                    "reason": result.get(
                        "reason",
                        "The model could not analyse this fixture.",
                    ),
                })

                output_fixtures.append(entry)
                continue

            key = _match_key(fixture)

            probability = result["p"]
            upper_bound = result.get("upper", probability)

            if key in logged_keys:
                decision = "logged"

            elif args.defer_picks:
                decision = "review-window"

            elif probability >= threshold:
                picks.append(
                    bc.make_pick(
                        fixture,
                        result,
                        row,
                        market,
                    )
                )

                logged_keys.add(key)
                new_picks += 1
                decision = "logged"

            else:
                decision = "below-line"

            p_form = None
            p_base = None

            for line in result.get("sheet", []):
                if line.startswith("1 form"):
                    p_form = _pct_from(line)

                elif line.startswith("2 historical"):
                    p_base = _pct_from(line)

            entry.update({
                "decision": decision,
                "lam_h": round(result["lam_h"], 4),
                "lam_a": round(result["lam_a"], 4),
                "core": round(result["core"], 4),
                "p_form": p_form,
                "p_base": p_base,
                "point": round(probability, 
