#!/usr/bin/env python3
"""
BARBADOX model snapshot exporter — the bridge between backend and console.
Runs the SAME pipeline as barbadox_core.py run (imports it, no duplicated
math) and writes docs/data.json: every fixture with its actual internals —
lambdas, core/form/base probabilities, upper-bound ceiling, threshold
decision, factor sheet, notes — plus all logged picks.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import barbadox_core as bc

BASE_DIR = Path(__file__).resolve().parent
SNAPSHOT_FILE = BASE_DIR / "docs" / "data.json"


def _pct_from(sheet_line):
    """'1 form since season start: 84.0% | games 5/6' -> 0.84"""
    try:
        s = sheet_line.split(":")[1].strip().split("%")[0]
        return round(float(s) / 100, 4)
    except (IndexError, ValueError):
        return None


def export(args):
    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in bc.LEAGUES]
    if bad:
        sys.exit(f"Unknown league key(s): {', '.join(bad)}")

    print("Loading data...")
    pools = bc.load_for_leagues(leagues, args.refresh)
    env = bc.Env(pools)

    tz = timedelta(hours=bc.CFG["kickoff_tz_hours"])
    d0 = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else (bc.NOW + tz).date())
    d1 = d0 + timedelta(days=args.days)

    fixtures = []
    for lg in leagues:
        for m in pools.get(lg, []):
            loc = m["dt"] + tz
            if not (d0 <= loc.date() < d1):
                continue
            if m["status"] not in ("SCHEDULED", "TIMED"):
                continue
            item = dict(m)
            item["league"] = lg
            item["ldate"] = loc.strftime("%Y-%m-%d")
            item["ltime"] = loc.strftime("%H:%M")
            fixtures.append(item)

    threshold = args.threshold
    market = args.market

    # context.csv: created on first run, then APPEND-ONLY (owner rows are never rewritten).
    ctx, added_context = bc.sync_context(fixtures, env, market, threshold)
    if added_context:
        print("!" * 70)
        print(f"!!! OWNER WARNING: {added_context} new match(es) appended to context.csv.")
        print("!!! WAIT 5 MINUTES for the owner to review it and set checked=1.")
        print("!!! Unconfirmed matches cannot become picks.")
        print("!" * 70)

    picks = bc.read_picks()
    logged_keys = {(p["date"], bc.norm(p["home"]), bc.norm(p["away"])) for p in picks}
    new_picks = 0

    out_fixtures = []
    for fx in sorted(fixtures, key=lambda x: (x["ldate"], x["ltime"])):
        row = ctx.get((fx["ldate"], fx["hk"], fx["ak"]))
        res = bc.analyze(fx, row, env, market)
        entry = {
            "date": fx["ldate"], "time": fx["ltime"], "league": fx["league"],
            "home": fx["home"], "away": fx["away"],
            "checked": bool(row) and str(row.get("checked", "")).strip() == "1",
        }
        if res["p"] is None:
            entry.update({"decision": "skipped", "reason": res.get("reason", "")})
            out_fixtures.append(entry)
            continue

        key = (fx["ldate"], fx["hk"], fx["ak"])
        ready = bool(row) and str(row.get("checked", "")).strip() == "1"
        if key in logged_keys:
            decision = "logged"
        elif ready and res["p"] >= threshold:
            picks.append(bc.make_pick(fx, res, row, market))
            logged_keys.add(key)
            new_picks += 1
            decision = "logged"
        elif not ready and res["upper"] >= threshold:
            decision = "pending-owner"
        else:
            decision = "below-line"

        p_form = p_base = None
        for line in res["sheet"]:
            if line.startswith("1 form"):
                p_form = _pct_from(line)
            elif line.startswith("2 historical"):
                p_base = _pct_from(line)

        entry.update({
            "decision": decision,
            "lam_h": round(res["lam_h"], 4),
            "lam_a": round(res["lam_a"], 4),
            "core": round(res["core"], 4),
            "p_form": p_form,
            "p_base": p_base,
            "point": round(res["p"], 4),
            "low": round(res["low"], 4),
            "high": round(res["high"], 4),
            "upper": round(res["upper"], 4),
            "factors": res["factors"],
            "notes": res["notes"],
            "sheet": res["sheet"],
        })
        out_fixtures.append(entry)

    if new_picks:
        bc.write_picks(picks)
        bc.write_html_report(picks)
    owner_pending = sum(1 for f in out_fixtures if f.get("decision") == "pending-owner")
    snapshot = {
        "generated_at": bc.NOW.isoformat(),
        "window": {"from": str(d0), "to": str(d1 - timedelta(days=1))},
        "threshold": threshold,
        "market": market,
        "leagues": bc.LEAGUES,
        "fixtures": out_fixtures,
        "picks": picks,
        "context_added": added_context,
        "owner_pending": owner_pending,
        "context_ready": owner_pending == 0,
    }
    SNAPSHOT_FILE.parent.mkdir(exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    n_logged = sum(1 for f in out_fixtures if f.get("decision") == "logged")
    print(f"Snapshot written: {SNAPSHOT_FILE} ({len(out_fixtures)} fixtures, {n_logged} logged).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Export the BARBADOX model snapshot for the console UI")
    ap.add_argument("--date", default=None, help="start date YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=3, help="scan window (default 3, same as run)")
    ap.add_argument("--leagues", default=",".join(bc.LEAGUES), help="league keys (default all)")
    ap.add_argument("--market", type=float, default=bc.CFG["market"], help="goals line (default from CFG)")
    ap.add_argument("--threshold", type=float, default=bc.CFG["threshold"], help="default from CFG (0.79)")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    export(ap.parse_args())
