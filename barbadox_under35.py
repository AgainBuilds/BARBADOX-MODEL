#!/usr/bin/env python3
"""
Barbadox Core 2 (Under 3.5) - live feed for the slips.

This does NOT change the Core 2 maths. It imports barbadox_core2.py as it is and uses
its own functions (Poisson model, season baseline, calibration, safety haircut), then
applies them to the upcoming fixtures and writes docs/under35.json for the console.

Same data as the Over 1.5 run: it reuses barbadox_core's loader and its data/ cache,
so right after a normal run it makes no extra API calls.

It never touches picks.csv, context.csv or docs/data.json.

USAGE
    python barbadox_under35.py                      # today + next 3 days
    python barbadox_under35.py --days 3 --threshold 0.60

ENVIRONMENT (optional)
    UNDER35_THRESHOLD   final-probability cutoff, default 0.75
    SAFETY_Z            Core 2 haircut strength, default 1.0 (read by barbadox_core2)
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
DEFAULT_LEAGUES = "PL,PD,FL1,BL1,SA"   # same five leagues Core 2 was built and checked on
DEFAULT_THRESHOLD = float(os.environ.get("UNDER35_THRESHOLD", "0.75"))


def load_history(leagues):
    """Last season + this season for each league, in the shape Core 2 expects."""
    out, empty = [], []
    for lg in leagues:
        got = 0
        for season in (bc.CURRENT_SEASON - 1, bc.CURRENT_SEASON):
            for m in bc.load_league(lg, season, False):
                got += 1
                out.append({
                    "league": lg, "season": season,
                    "date": m["date"][:10], "utc": m["date"],
                    "home_id": m["hk"], "away_id": m["ak"],   # team name stands in for the id
                    "home": m["home"], "away": m["away"],
                    "status": m.get("status", ""), "hg": m.get("hg"), "ag": m.get("ag"),
                    "dt": m["dt"],
                })
        if not got:
            empty.append(lg)
    return out, empty


def analyse(matches, threshold, d0, d1):
    """Returns (status, reason, fixtures). Mirrors the upcoming() logic inside barbadox_core2."""
    tz = timedelta(hours=bc.CFG["kickoff_tz_hours"])
    latest = bc.CURRENT_SEASON

    fixtures = []
    for m in matches:
        if m["season"] != latest or m["status"] not in ("SCHEDULED", "TIMED"):
            continue
        loc = m["dt"] + tz
        if d0 <= loc.date() < d1:
            fixtures.append((loc, m))
    fixtures.sort(key=lambda x: x[0])
    if not fixtures:
        return "ok", "no fixtures in the window", []

    rows, states = c2.build_rows(matches)
    model, k_by = c2.walk_forward(rows)
    if len(model) < c2.MIN_HISTORY:
        return "no-history", "not enough finished matches to calibrate yet", []

    prior = sum(r["y"] for r in model) / len(model)
    b = c2.fit_slope([(r["off"], r["x"], r["y"]) for r in model])
    done = [r for r in model if r["p_cal"] is not None]
    K = k_by[latest] if latest in k_by else c2.tune_k([r for r in rows if r["season"] < latest])

    out = []
    for loc, m in fixtures:
        entry = {"date": loc.strftime("%Y-%m-%d"), "time": loc.strftime("%H:%M"),
                 "league": m["league"], "home": m["home"], "away": m["away"]}
        st = states.get((m["league"], latest))
        f = st.feats(m["home_id"], m["away_id"]) if st else None
        if f is None:
            entry.update({"decision": "skipped", "reason": "not enough games yet"})
            out.append(entry)
            continue
        p_raw = c2.pois_cdf(c2.GOAL_LINE, c2.lam_total(f, K))
        off = c2.logit(c2.season_base(f, prior))
        p_cal = c2.sigmoid(off + b * (c2.logit(p_raw) - off))
        p_fin = c2.guard(p_cal, done)
        if p_fin is None:
            entry.update({"decision": "skipped", "reason": "not enough history"})
            out.append(entry)
            continue
        entry.update({
            "decision": "qualified" if p_fin >= threshold else "below-line",
            "p_raw": round(p_raw, 4), "p_cal": round(p_cal, 4), "p_final": round(p_fin, 4),
        })
        out.append(entry)
    return "ok", "", out


def main():
    ap = argparse.ArgumentParser(description="Barbadox Core 2 (Under 3.5) live feed")
    ap.add_argument("--date", default=None, help="start date YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=3, help="scan window (default 3, same as run)")
    ap.add_argument("--leagues", default=DEFAULT_LEAGUES)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()

    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in bc.LEAGUES]
    if bad:
        sys.exit(f"Unknown league key(s): {', '.join(bad)}")

    tz = timedelta(hours=bc.CFG["kickoff_tz_hours"])
    d0 = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else (bc.NOW + tz).date())
    d1 = d0 + timedelta(days=args.days)

    print("CORE 2 (UNDER 3.5): loading data...")
    matches, empty = load_history(leagues)
    status, reason, fixtures = analyse(matches, args.threshold, d0, d1)

    snapshot = {
        "generated_at": bc.NOW.isoformat(),
        "window": {"from": str(d0), "to": str(d1 - timedelta(days=1))},
        "model": "Core 2 (Under 3.5)", "market": 3.5, "threshold": args.threshold,
        "status": status, "reason": reason,
        "scanned": len(fixtures), "leagues_empty": empty,
        "fixtures": fixtures,
    }
    OUT_FILE.parent.mkdir(exist_ok=True)
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    tmp.replace(OUT_FILE)   # all-or-nothing, a half-written file can never be served

    q = [f for f in fixtures if f["decision"] == "qualified"]
    print(f"CORE 2 (UNDER 3.5): {len(fixtures)} fixture(s) scanned, {len(q)} cleared "
          f"{args.threshold * 100:.0f}%. Status: {status}{' (' + reason + ')' if reason else ''}.")
    top = sorted(q, key=lambda x: -x["p_final"])[:5]
    for f in top:
        print(f"  {f['date']} {f['league']:<4} {f['home']} vs {f['away']}  {f['p_final'] * 100:.1f}%")
    if len(q) > len(top):
        print(f"  ... and {len(q) - len(top)} more in docs/under35.json")
    if empty:
        print("CORE 2 (UNDER 3.5): no data from: " + ", ".join(empty))


if __name__ == "__main__":
    main()
