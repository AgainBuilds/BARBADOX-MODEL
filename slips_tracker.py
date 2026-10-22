#!/usr/bin/env python3
"""BARBADOX slips tracker.

Counts how many slips the program has given and whether each one
hit or failed. Reads slip_history.csv (written by barbadox_slips.py)
and returns a JSON-ready summary plus per-slip details.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "slip_history.csv"


def _read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean(value):
    return "" if value is None else str(value)


def tracker_data():
    """Return the slips summary and per-slip details as a dict."""
    rows = _read(HISTORY)
    groups = {}
    for r in rows:
        groups.setdefault(_clean(r.get("slip_id")), []).append(r)

    slips = []
    hits = misses = pending = voids = 0
    staked = returned = profit = 0.0

    for sid, legs in groups.items():
        legs.sort(key=lambda r: int(r.get("leg_no") or 0))
        first = legs[0]
        result = _clean(first.get("slip_result")).upper() or "PENDING"

        if result == "HIT":
            hits += 1
        elif result == "MISS":
            misses += 1
        elif result == "VOID":
            voids += 1
        else:
            pending += 1

        staked += _f(first.get("stake"))
        returned += _f(first.get("actual_return"))
        profit += _f(first.get("profit"))

        slips.append({
            "slip_id": sid,
            "slip_no": _clean(first.get("slip_no")) or sid,
            "generated_at": _clean(first.get("generated_at")),
            "result": result,
            "combined_odds": _clean(first.get("combined_odds")),
            "stake": _f(first.get("stake")),
            "potential_return": _f(first.get("potential_return")),
            "actual_return": _f(first.get("actual_return")),
            "profit": _f(first.get("profit")),
            "legs": [{
                "leg_no": _clean(leg.get("leg_no")),
                "date": _clean(leg.get("date")),
                "league": _clean(leg.get("league")),
                "home": _clean(leg.get("home")),
                "away": _clean(leg.get("away")),
                "selection": _clean(leg.get("selection")),
                "probability": _f(leg.get("probability")),
                "bookmaker_odds": _clean(leg.get("bookmaker_odds")),
                "score": (_clean(leg.get("hg")) + "-" + _clean(leg.get("ag")))
                    if _clean(leg.get("hg")) and _clean(leg.get("ag")) else "",
                "leg_result": _clean(leg.get("leg_result")) or "PENDING",
            } for leg in legs],
        })

    slips.sort(key=lambda x: x["generated_at"], reverse=True)
    settled = hits + misses
    hit_rate = (hits / settled) if settled else None
    roi = (profit / staked) if staked else None

    return {
        "total_slips": len(groups),
        "hits": hits,
        "failed": misses,
        "voids": voids,
        "pending": pending,
        "hit_rate": hit_rate,
        "staked": round(staked, 2),
        "returned": round(returned, 2),
        "profit": round(profit, 2),
        "roi": roi,
        "legs_recorded": len(rows),
        "slips": slips,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(tracker_data(), indent=2))
