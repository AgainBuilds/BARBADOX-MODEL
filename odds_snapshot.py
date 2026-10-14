#!/usr/bin/env python3
"""Fetch pre-match bookmaker odds from The Odds API for upcoming Barbadox picks.

Writes odds_snapshot.csv next to picks.csv. Rows already in the snapshot are
preserved when the API fails, so a bad run never erases price history.
The API key is read from the ODDS_API_KEY environment variable and is never
printed, stored, or committed.

Usage (inside the slip tracker workflow, before barbadox_slips.py):
    python odds_snapshot.py

Notes on honesty:
- The Odds API's "totals" market usually carries only the main line
  (typically Over/Under 2.5). Prices for the 1.5 and 3.5 lines exist only
  when the bookmaker offers them, so many fixtures will have no usable price.
  Missing prices are simply not recorded; nothing is estimated.
- Prices are pre-match snapshots, not closing lines.
"""
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.the-odds-api.com/v4"
SPORTS = {
    "PL": "soccer_epl",
    "PD": "soccer_spain_la_liga",
    "FL1": "soccer_france_ligue_one",
    "BL1": "soccer_germany_bundesliga",
    "SA": "soccer_italy_serie_a",
}
REGIONS = os.getenv("ODDS_REGIONS", "eu").strip() or "eu"
ROOT = Path(__file__).resolve().parent
PICKS = ROOT / "picks.csv"
SNAPSHOT = ROOT / "odds_snapshot.csv"
FIELDS = ["date", "league", "home", "away", "kickoff", "selection",
          "point", "bookmaker", "price", "retrieved_at"]


def norm(s):
    return "".join(c for c in str(s).lower() if c.isalnum())


def read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def teams_match(a, b):
    a, b = norm(a), norm(b)
    return a == b or (a and b and (a in b or b in a))


def snap_key(o):
    return (str(o.get("date", ""))[:10], str(o.get("league", "")).upper(),
            norm(o.get("home")), norm(o.get("away")),
            str(o.get("selection", "")).upper(), str(o.get("point", "")),
            str(o.get("bookmaker", "")).lower())


def main():
    api_key = os.getenv("ODDS_API_KEY", "").strip()
    if not api_key:
        print("::error::Missing ODDS_API_KEY. Add the repository secret "
              "ODDS_API_KEY (free key: https://the-odds-api.com) under "
              "Settings > Secrets and variables > Actions.")
        sys.exit(1)

    picks = read(PICKS)
    today = datetime.now(timezone.utc).date().isoformat()
    wanted = {}  # (league, date) -> list of pick rows
    for p in picks:
        d = str(p.get("date", ""))[:10]
        lg = str(p.get("league", "")).strip().upper()
        if d < today or p.get("result"):
            continue
        if lg in SPORTS:
            wanted.setdefault((lg, d), []).append(p)

    if not wanted:
        print("No upcoming unsettled picks need odds today.")
        return

    new_rows = []
    failures = 0
    leagues = sorted({lg for lg, _ in wanted})

    for lg in leagues:
        sport = SPORTS[lg]
        try:
            r = requests.get(
                f"{API}/sports/{sport}/odds",
                params={
                    "apiKey": api_key,
                    "regions": REGIONS,
                    "markets": "totals",
                    "oddsFormat": "decimal",
                },
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"::error::The Odds API request failed for {sport}: {e}")
            failures += 1
            continue

        print(f"{sport} -> HTTP {r.status_code}; quota remaining: "
              f"{r.headers.get('x-requests-remaining', '?')}")

        if r.status_code == 401:
            print("::error::ODDS_API_KEY rejected (HTTP 401). Check the key value.")
            failures += 1
            continue
        if r.status_code == 429:
            print("::error::The Odds API rate limit reached (HTTP 429). "
                  "Snapshot not updated for this league.")
            failures += 1
            continue
        if not r.ok:
            print(f"::error::The Odds API HTTP {r.status_code} for {sport}.")
            failures += 1
            continue

        for ev in r.json() or []:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            kickoff = ev.get("commence_time", "")
            d = str(kickoff)[:10]
            targets = [p for p in wanted.get((lg, d), [])
                       if teams_match(home, p.get("home"))
                       and teams_match(away, p.get("away"))]
            if not targets:
                continue
            for bm in ev.get("bookmakers", []):
                bmk = bm.get("key", "")
                for mk in bm.get("markets", []):
                    if mk.get("key") != "totals":
                        continue
                    point = mk.get("point")
                    if point is None:
                        continue
                    for out in mk.get("outcomes", []):
                        name = str(out.get("name", "")).strip().upper()
                        if name not in ("OVER", "UNDER"):
                            continue
                        try:
                            price = float(out.get("price"))
                        except (TypeError, ValueError):
                            continue
                        if price <= 1.01:
                            continue
                        new_rows.append({
                            "date": d,
                            "league": lg,
                            "home": targets[0].get("home", ""),
                            "away": targets[0].get("away", ""),
                            "kickoff": kickoff,
                            "selection": f"{name} {point}",
                            "point": str(point),
                            "bookmaker": bmk,
                            "price": f"{price:.2f}",
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        })

    if new_rows:
        existing = {snap_key(o): o for o in read(SNAPSHOT)}
        for o in new_rows:
            existing[snap_key(o)] = o
        rows = sorted(existing.values(),
                      key=lambda o: (o.get("date", ""), o.get("league", ""),
                                     norm(o.get("home")), norm(o.get("away")),
                                     o.get("selection", ""), o.get("bookmaker", "")))
        with SNAPSHOT.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"Odds snapshot updated: {len(new_rows)} new prices, "
              f"{len(rows)} total rows.")
    else:
        print("No matching totals prices returned for today's picks. "
              "This is common: the API usually lists the 2.5 main line, "
              "not 1.5 or 3.5. Nothing was estimated.")

    if failures:
        print("Prior snapshot rows preserved for leagues that failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
