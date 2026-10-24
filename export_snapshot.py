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
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import barbadox_core as bc
import gh_sync


BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_FILE = BASE_DIR / "docs" / "data.json"

# Fixtures kicking off sooner than this (or already started) are never
# offered as picks or slip legs.
KICKOFF_BUFFER_MIN = max(0, int(os.environ.get("KICKOFF_BUFFER_MINUTES", "30")))


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


def _is_core1_pick(pick, market):
    """
    True only for a Core 1 Over pick on this market.

    picks.csv also holds Core 2 (Under 3.5) rows for the same fixtures.
    Matching on date and teams alone made those rows count as "already
    logged", so a fixture at 66.5% was shown as a qualified Over 1.5 pick.
    """
    if str(pick.get("note", "")).upper().startswith("CORE2_UNDER35"):
        return False

    try:
        return abs(float(pick.get("market", "")) - float(market)) < 1e-4
    except (TypeError, ValueError):
        return False


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
            if _is_core1_pick(pick, market)
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
                "kickoff_utc": fixture["dt"].isoformat(),
            }

            if fixture["dt"] <= bc.NOW + timedelta(minutes=KICKOFF_BUFFER_MIN):
                entry.update({
                    "decision": "started",
                    "reason": "Kickoff has passed or is inside the buffer.",
                })

                output_fixtures.append(entry)
                continue

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
                "point": round(probability, 4),
                "low": round(result["low"], 4),
                "high": round(result["high"], 4),
                "upper": round(upper_bound, 4),
                "factors": result.get("factors", {}),
                "notes": result.get("notes", []),
                "sheet": result.get("sheet", []),
            })

            output_fixtures.append(entry)

        # Do not write picks.csv during a deferred review pass.
        if new_picks and not args.defer_picks:
            bc.write_picks(picks)
            bc.write_html_report(picks)

        review_pending = sum(
            1
            for fixture in output_fixtures
            if fixture.get("decision") == "review-window"
        )

        snapshot = {
            "generated_at": bc.NOW.isoformat(),
            "window": {
                "from": str(d0),
                "to": str(d1 - timedelta(days=1)),
            },
            "threshold": threshold,
            "market": market,
            "leagues": bc.LEAGUES,
            "fixtures": output_fixtures,
            "picks": picks,
            "context_added": added_context,
            "scanned": len(output_fixtures),
            "leagues_empty": [
                league
                for league in leagues
                if not pools.get(league)
            ],
            "owner_pending": 0,
            "context_ready": True,
            "pick_logging_deferred": bool(args.defer_picks),
            "review_pending": review_pending,
        }

        return (
            snapshot,
            output_fixtures,
            added_context,
            new_picks,
        )

    added_total = 0

    for attempt in range(4):
        if use_github:
            # Always pull the latest owner-maintained files first.
            gh_sync.pull("context.csv")
            gh_sync.pull("picks.csv")

        (
            snapshot,
            output_fixtures,
            added_context,
            new_picks,
        ) = build()

        try:
            if use_github:
                if added_context:
                    gh_sync.push(
                        "context.csv",
                        (
                            "Barbadox: append new fixtures "
                            "for the five-minute review window"
                        ),
                    )

                    added_total += added_context
                    added_context = 0

                if new_picks and not args.defer_picks:
                    gh_sync.push(
                        "picks.csv",
                        f"Barbadox: log {new_picks} qualifying pick(s)",
                    )

            added_total += added_context
            break

        except gh_sync.Conflict as error:
            print(
                f"GitHub file {error} changed while processing. "
                f"Re-reading and retrying ({attempt + 1}/4)."
            )

    else:
        raise SystemExit(
            "Could not save to GitHub after four attempts. "
            "The file kept changing. Run again."
        )

    snapshot["context_added"] = added_total
    snapshot["github"] = "synced" if use_github else "off"

    SNAPSHOT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    SNAPSHOT_FILE.write_text(
        json.dumps(snapshot, indent=1),
        encoding="utf-8",
    )

    logged_count = sum(
        1
        for fixture in output_fixtures
        if fixture.get("decision") == "logged"
    )

    print(
        f"Snapshot written: {SNAPSHOT_FILE} "
        f"({len(output_fixtures)} fixtures, "
        f"{logged_count} logged or previously logged)."
    )

    print(f"New picks written this pass: {new_picks}.")

    if args.defer_picks:
        print(
            "Deferred pass complete. "
            "The server must decide whether to wait and rerun."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Export the BARBADOX model snapshot for the console UI"
        )
    )

    parser.add_argument(
        "--date",
        default=None,
        help="Start date YYYY-MM-DD; defaults to today.",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to scan; default is 7.",
    )

    parser.add_argument(
        "--leagues",
        default=",".join(bc.LEAGUES),
        help="Comma-separated league keys; defaults to all.",
    )

    parser.add_argument(
        "--market",
        type=float,
        default=bc.CFG["market"],
        help="Goals line; defaults to CFG.",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=bc.CFG["threshold"],
        help="Pick threshold; defaults to CFG.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached data.",
    )

    parser.add_argument(
        "--defer-picks",
        action="store_true",
        help="Do not log new picks during the initial review pass.",
    )

    export(parser.parse_args())
