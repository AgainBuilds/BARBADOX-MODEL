#!/usr/bin/env python3
"""
Blue: the universal team-balance system for BARBADOX.

Rules:
- Every team starts at 0.
- Failed recommendation: both teams receive -2.
- Successful recommendation: each participating team recovers +1, capped at 0.
- One universal balance across OVER 1.5 and UNDER 3.5.
- Adjusted probability = original probability + home balance + away balance.
- Thresholds remain 80% (Core 1) and 60% (Core 2).
- Balances update chronologically. Same-day settlements are applied at
  day's end, so a fixture only sees settlements from strictly earlier days.

Storage (both live in the repository so they survive Render redeploys):
- blue_ledger.csv: append-only settlement record (source of truth).
- blue_balances.csv: derived current balances, recomputed from the ledger.
- blue_dropped.csv: append-only record of picks BLUE vetoed (the raw
  probability cleared the entry bar but the Blue-adjusted probability
  did not). The daily review grades these against real results, so the
  console's BLUE tracker can show whether each veto would have hit.
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER_FILE = ROOT / "blue_ledger.csv"
BALANCES_FILE = ROOT / "blue_balances.csv"
DROPPED_FILE = ROOT / "blue_dropped.csv"
PICKS_FILE = ROOT / "picks.csv"

SUCCESS_DELTA = 1.0
FAILURE_DELTA = -2.0
RECOVERY_CAP = 0.0

LEDGER_FIELDS = [
    "date", "league", "home", "away", "market",
    "result", "settled_at",
]
BALANCE_FIELDS = ["team", "balance", "updated_at"]
DROPPED_FIELDS = [
    "date", "league", "home", "away", "market", "side",
    "p_raw", "p_blue", "bar", "balance_home", "balance_away",
    "dropped_at", "hg", "ag", "result",
]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def norm(name):
    """Normalise a team name to a stable ledger key."""
    return "".join(
        character.lower()
        for character in str(name or "")
        if character.isalnum()
    )


def _read_rows(path):
    if not path.exists():
        return []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # Atomic replacement prevents partially written CSV files.
    temporary.replace(path)


def _settlement_key(row):
    """
    A recommendation is identified by fixture, market, and date.

    The market is part of the key so one fixture can settle both an
    OVER 1.5 and an UNDER 3.5 recommendation independently.
    """
    return (
        str(row.get("date", ""))[:10],
        str(row.get("league", "")).upper().strip(),
        norm(row.get("home")),
        norm(row.get("away")),
        str(row.get("market", "")).strip(),
    )


def _dropped_key(row):
    """
    A vetoed pick is identified the same way as a settlement: fixture,
    market, and date. This makes drop logging idempotent no matter how
    many pipelines (daily run, console export, Core 2) see the fixture.
    """
    return _settlement_key(row)


def _settled_pick_rows(picks_file=PICKS_FILE):
    """Rows from picks.csv with a final HIT or MISS result.

    Historical backtest rows (note CORE1_OVER15|HISTORICAL,
    CORE2_UNDER35|HISTORICAL) are excluded: the ledger records live
    BARBADOX recommendations only, so the balance starts empty on
    deployment day and only real recommendations move it.
    """
    rows = []

    for row in _read_rows(picks_file):
        result = str(row.get("result", "")).strip().upper()

        if result not in ("HIT", "MISS"):
            continue

        if not row.get("date") or not row.get("home") or not row.get("away"):
            continue

        note = str(row.get("note", "")).strip().upper()

        if "HISTORICAL" in note:
            continue

        rows.append(row)

    return rows


def sync_ledger(picks_file=PICKS_FILE, ledger_file=LEDGER_FILE):
    """
    Sync settled live recommendations into the ledger.

    - Appends settled recommendations that are not in the ledger yet.
      Idempotent: re-running never double-counts a settlement.
    - Prunes ledger rows that no longer correspond to a settled live
      (non historical) pick. This self-heals a ledger that was
      populated from the historical backfill: those rows are removed
      and the balances are recomputed from live recommendations only.

    Returns (added, pruned).
    """
    ledger = _read_rows(ledger_file)
    known = {_settlement_key(row) for row in ledger}

    settled_rows = _settled_pick_rows(picks_file)
    live_keys = {_settlement_key(row) for row in settled_rows}

    pruned = [
        row for row in ledger
        if _settlement_key(row) not in live_keys
    ]

    kept = [
        row for row in ledger
        if _settlement_key(row) in live_keys
    ]

    added = []

    for row in settled_rows:
        key = _settlement_key(row)

        if key in known:
            continue

        entry = {
            "date": str(row.get("date", ""))[:10],
            "league": str(row.get("league", "")).strip(),
            "home": row.get("home", ""),
            "away": row.get("away", ""),
            "market": str(row.get("market", "")).strip(),
            "result": str(row.get("result", "")).strip().upper(),
            "settled_at": _utc_now(),
        }

        added.append(entry)
        known.add(key)

    if added or pruned:
        _write_rows(
            ledger_file,
            LEDGER_FIELDS,
            kept + added,
        )

    return added, pruned


def _apply_settlement(balances, home, away, success):
    """Apply one recommendation outcome to both participating teams."""
    for team in (norm(home), norm(away)):
        current = balances.get(team, 0.0)

        if success:
            # Recovery is capped at 0: teams never go positive.
            balances[team] = min(
                current + SUCCESS_DELTA,
                RECOVERY_CAP,
            )
        else:
            balances[team] = current + FAILURE_DELTA


_replay_cache = {}


def invalidate_cache():
    _replay_cache.clear()


def replay(as_of=None):
    """
    Rebuild balances by replaying the ledger chronologically.

    Same-day settlements are applied together at that day's end. A
    fixture kicking off on date D therefore only sees settlements
    dated strictly before D: pass as_of=D to exclude same-day and
    later settlements.
    """
    cache_key = as_of if as_of is not None else "__all__"

    if cache_key in _replay_cache:
        return _replay_cache[cache_key]

    by_day = {}

    for row in _read_rows(LEDGER_FILE):
        day = str(row.get("date", ""))[:10]
        by_day.setdefault(day, []).append(row)

    balances = {}

    for day in sorted(by_day):
        if as_of is not None and day >= as_of:
            break

        # All of a day's settlements apply together, in ledger order.
        for row in by_day[day]:
            _apply_settlement(
                balances,
                row.get("home"),
                row.get("away"),
                str(row.get("result", "")).strip().upper() == "HIT",
            )

    _replay_cache[cache_key] = balances
    return balances


def balances_for(home, away, as_of=None):
    balances = replay(as_of)

    return (
        balances.get(norm(home), 0.0),
        balances.get(norm(away), 0.0),
    )


def adjust(home, away, probability, as_of=None):
    """
    Blue-adjusted probability: original + home balance + away balance,
    clamped to [0, 1].

    Balances are never positive (recovery is capped at 0), so Blue can
    only lower a probability, never inflate one. That is intentional.
    """
    home_balance, away_balance = balances_for(home, away, as_of)

    adjusted = (
        float(probability)
        + home_balance
        + away_balance
    )

    return min(max(adjusted, 0.0), 1.0)


def write_balances(balances_file=BALANCES_FILE):
    """Recompute and persist the current balance snapshot."""
    balances = replay()

    rows = [
        {
            "team": team,
            "balance": f"{value:.4f}",
            "updated_at": _utc_now(),
        }
        for team, value in sorted(balances.items())
    ]

    _write_rows(balances_file, BALANCE_FIELDS, rows)
    return len(rows)


def settle(push=False):
    """
    Settle the ledger from picks.csv and refresh the balance file.

    Returns the number of newly settled recommendations.
    Safe to run repeatedly: settlement is idempotent, and any ledger
    rows that do not match a settled live pick (for example the
    historical backfill ingested on first run) are pruned.
    """
    invalidate_cache()
    added, pruned = sync_ledger()
    write_balances()

    if (added or pruned) and push:
        import gh_sync

        if gh_sync.enabled():
            message = (
                "Barbadox BLUE: settle "
                + str(len(added))
                + " recommendation(s)"
            )

            if pruned:
                message += (
                    ", prune "
                    + str(len(pruned))
                    + " historical backfill row(s)"
                )

            gh_sync.push("blue_ledger.csv", message)
            gh_sync.push("blue_balances.csv", message)

    return len(added)


def read_dropped(dropped_file=DROPPED_FILE):
    """All BLUE-vetoed pick rows (graded and pending)."""
    return _read_rows(dropped_file)


def log_dropped(
    date,
    league,
    home,
    away,
    market,
    p_raw,
    p_blue,
    bar,
    side,
    dropped_file=DROPPED_FILE,
):
    """
    Record a pick BLUE vetoed: the raw probability cleared the entry
    bar but the Blue-adjusted probability did not.

    Idempotent: a vetoed fixture is only recorded once, no matter how
    many pipelines see it. Returns True when a new row was written.

    `side` is "OVER" or "UNDER" and decides how the row is graded
    later (OVER: total goals above the line; UNDER: total below it).
    """
    row = {
        "date": str(date)[:10],
        "league": str(league).strip(),
        "home": home,
        "away": away,
        "market": str(market).strip(),
        "side": str(side).strip().upper(),
    }

    rows = _read_rows(dropped_file)

    if _dropped_key(row) in {_dropped_key(existing) for existing in rows}:
        return False

    balance_home, balance_away = balances_for(
        home,
        away,
        as_of=row["date"],
    )

    row.update({
        "p_raw": f"{float(p_raw):.4f}",
        "p_blue": f"{float(p_blue):.4f}",
        "bar": f"{float(bar):.4f}",
        "balance_home": f"{balance_home:.1f}",
        "balance_away": f"{balance_away:.1f}",
        "dropped_at": _utc_now(),
        "hg": "",
        "ag": "",
        "result": "",
    })

    rows.append(row)
    _write_rows(dropped_file, DROPPED_FIELDS, rows)
    return True


def grade_dropped(finder, dropped_file=DROPPED_FILE):
    """
    Grade BLUE-vetoed picks against real results.

    `finder(home, away, date)` must return None while the result is
    not known yet, or a dict {"hg", "ag", "status"}. A HIT means the
    veto was wrong (the pick would have won); a MISS means the veto
    saved a leg. Returns the number of newly graded rows.
    """
    rows = _read_rows(dropped_file)
    graded = 0

    for row in rows:
        if row.get("result"):
            continue

        info = finder(row.get("home"), row.get("away"), row.get("date"))

        if not info:
            continue

        status = str(info.get("status", "")).strip().upper()

        if status == "POSTPONED":
            row["result"] = "POSTPONED"
            graded += 1
            continue

        if info.get("hg") is None or info.get("ag") is None:
            continue

        try:
            total = int(info["hg"]) + int(info["ag"])
            line = float(row.get("market", ""))
        except (TypeError, ValueError):
            continue

        is_under = str(row.get("side", "")).strip().upper() == "UNDER"

        hit = total < line if is_under else total > line

        row["hg"] = info["hg"]
        row["ag"] = info["ag"]
        row["result"] = "HIT" if hit else "MISS"
        graded += 1

    if graded:
        _write_rows(dropped_file, DROPPED_FIELDS, rows)

    return graded


def _show():
    balances = replay()

    if not balances:
        print("BLUE: no settlements in the ledger yet. All teams at 0.")
        return

    negative = {
        team: value
        for team, value in balances.items()
        if value < 0
    }

    print(
        "BLUE: "
        + str(len(negative))
        + " of "
        + str(len(balances))
        + " team(s) carry a negative balance."
    )

    for team, value in sorted(negative.items()):
        print(f"  {team}: {value:+.1f}")


def _show_dropped():
    rows = read_dropped()

    if not rows:
        print("BLUE: no picks vetoed yet.")
        return

    graded = [
        row for row in rows
        if row.get("result") in ("HIT", "MISS")
    ]
    hits = [row for row in graded if row["result"] == "HIT"]

    print(
        "BLUE: "
        + str(len(rows))
        + " pick(s) vetoed, "
        + str(len(graded))
        + " graded, "
        + str(len(hits))
        + " would have hit."
    )

    for row in sorted(
        rows,
        key=lambda item: str(item.get("date", "")),
        reverse=True,
    ):
        print(
            "  "
            + str(row.get("date", ""))
            + " "
            + str(row.get("home", ""))
            + " vs "
            + str(row.get("away", ""))
            + " ["
            + str(row.get("side", ""))
            + " "
            + str(row.get("market", ""))
            + "] raw "
            + str(row.get("p_raw", ""))
            + " -> blue "
            + str(row.get("p_blue", ""))
            + " (bar "
            + str(row.get("bar", ""))
            + ") "
            + (str(row.get("result", "")) or "PENDING")
        )


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "show"

    if command == "settle":
        push = "--push" in sys.argv[2:]
        count = settle(push=push)
        print(f"BLUE: settled {count} new recommendation(s).")
        _show()

    elif command == "show":
        _show()

    elif command == "dropped":
        _show_dropped()

    else:
        sys.exit(
            "Usage: python blue_balance.py [settle [--push] | show | dropped]"
        )


if __name__ == "__main__":
    main()
