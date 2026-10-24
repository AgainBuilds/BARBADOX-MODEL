#!/usr/bin/env python3
"""Build and settle 3+1 slips from picks.csv.

Attaches real bookmaker prices from odds_snapshot.csv (written by
odds_snapshot.py / The Odds API) when available. Combined odds are
calculated only when every leg has a recorded price. This script never
invents or estimates odds.

Slip-building rules (v2):
- Only fixtures that have not kicked off are used. If picks.csv carries a full
  kickoff timestamp (columns: kickoff_utc, kickoff, utc_date or datetime), a
  fixture must start at least KICKOFF_BUFFER_MINUTES from now. If only a date is
  known, only fixtures on a LATER UTC date qualify (set ALLOW_TODAY_NO_TIME=1 to
  override, which is unsafe).
- Over legs need probability >= CORE1_SLIP_THRESHOLD, Under legs >= CORE2_SLIP_THRESHOLD.
- A fixture appears in at most one slip, including slips still PENDING from
  earlier runs, so one wrong leg cannot sink several slips.
- All four legs fall inside one matchday window (SLIP_WINDOW_DAYS, default 1 day
  of spread) so a slip can be graded promptly.
- If not enough qualifying legs exist, fewer slips are made. Nothing is padded.

Money rules:
- stake, potential and actual returns are recorded only for slips where
  all four legs have prices.
- PENDING slips show combined odds and potential return, never profit.
- VOID slips are assumed to return the stake (simplified void policy).
- ROI is reported only over settled, fully-priced slips.
"""

import csv, hashlib, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PICKS = ROOT / "picks.csv"
HISTORY = ROOT / "slip_history.csv"
REPORT = ROOT / "slip.md"
ODDS = ROOT / "odds_snapshot.csv"

OVER = float(os.getenv("CORE1_SLIP_THRESHOLD", "0.80"))
UNDER = float(os.getenv("CORE2_SLIP_THRESHOLD", "0.60"))
MAX_NEW = max(0, int(os.getenv("MAX_NEW_SLIPS", "3")))
STAKE = float(os.getenv("STAKE", "10"))
CURRENCY = os.getenv("STAKE_CURRENCY", "")
PREFERRED = [b.strip().lower() for b in os.getenv("PREFERRED_BOOKMAKERS", "pinnacle").split(",") if b.strip()]

BUFFER_MIN = max(0, int(os.getenv("KICKOFF_BUFFER_MINUTES", "30")))
WINDOW_DAYS = max(0, int(os.getenv("SLIP_WINDOW_DAYS", "1")))
ALLOW_TODAY_NO_TIME = os.getenv("ALLOW_TODAY_NO_TIME", "0") == "1"
KICKOFF_COLS = ("kickoff_utc", "kickoff", "utc_date", "datetime")

FIELDS = ["slip_id", "generated_at", "slip_no", "leg_no", "date", "league", "home", "away", "selection", "market",
          "probability", "fair_odds", "bookmaker_odds", "bookmaker", "odds_policy", "odds_retrieved_at",
          "combined_odds", "combined_policy", "stake", "potential_return", "actual_return", "profit", "source",
          "hg", "ag", "leg_result", "slip_result"]


def read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def core2(r):
    return (str(r.get("note", "")).upper().startswith("CORE2_UNDER35")
            or str(r.get("selection", "")).upper() == "UNDER 3.5"
            or (str(r.get("market", "")) == "3.5" and "UNDER" in str(r.get("factors", "")).upper()))


def pkey(r):
    return (str(r.get("date", ""))[:10], str(r.get("league", "")).upper().strip(),
            norm(r.get("home")), norm(r.get("away")), "3.5" if core2(r) else "1.5")


def fixture_key(r):
    """Identity of a match, independent of market."""
    return pkey(r)[:4]


def leg_result(r):
    res = str(r.get("result", "")).strip().upper()
    if res in ("HIT", "MISS", "VOID"):
        return res
    if res == "POSTPONED":
        return "VOID"
    try:
        hg, ag = int(r.get("hg", "")), int(r.get("ag", ""))
    except (TypeError, ValueError):
        return "PENDING"
    return ("HIT" if hg + ag <= 3 else "MISS") if core2(r) else ("HIT" if hg + ag >= 2 else "MISS")


def parse_kickoff(r):
    """Full kickoff timestamp as aware UTC datetime, or None if only a date/time-of-day is known."""
    for c in KICKOFF_COLS:
        v = str(r.get(c, "") or "").strip()
        if len(v) < 16 or ("T" not in v and " " not in v):
            continue
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def eligible(r, today, now):
    date = str(r.get("date", ""))[:10]
    if not date or date < today or leg_result(r) != "PENDING":
        return False
    ko = parse_kickoff(r)
    if ko is not None:
        return ko > now + timedelta(minutes=BUFFER_MIN)
    # Date only: a match today may already be played, so require a later date.
    return date > today or ALLOW_TODAY_NO_TIME


def candidates(picks, today, now):
    overs, unders, seen = [], [], set()
    for r in picks:
        if not eligible(r, today, now):
            continue
        try:
            p = float(r.get("probability", ""))
        except (ValueError, TypeError):
            continue
        if not (0 < p <= 1):
            continue
        k = pkey(r)
        if k in seen:
            continue
        if core2(r):
            if p >= UNDER:
                unders.append(r)
                seen.add(k)
        else:
            try:
                market = float(r.get("market", ""))
            except (ValueError, TypeError):
                continue
            if abs(market - 1.5) < 1e-4 and p >= OVER:
                overs.append(r)
                seen.add(k)
    overs.sort(key=lambda r: (-float(r["probability"]), r["date"], r["league"]))
    unders.sort(key=lambda r: (-float(r["probability"]), r["date"], r["league"]))
    return overs, unders


def sid(legs):
    raw = "|".join("|".join(map(str, pkey(r))) for r in legs)
    return hashlib.sha256(raw.encode()).hexdigest()[:12].upper()


def read_odds():
    if not ODDS.exists():
        return []
    with ODDS.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def teams_match(a, b):
    a, b = norm(a), norm(b)
    return a == b or (a and b and (a in b or b in a))


def find_odds(rows, r):
    is_u = core2(r)
    sel = "UNDER 3.5" if is_u else "OVER 1.5"
    point = "3.5" if is_u else "1.5"
    cand = []
    for o in rows:
        if str(o.get("selection", "")).upper() != sel or str(o.get("point", "")).strip() != point:
            continue
        if str(o.get("date", ""))[:10] != str(r.get("date", ""))[:10]:
            continue
        if not teams_match(o.get("home"), r.get("home")) or not teams_match(o.get("away"), r.get("away")):
            continue
        try:
            price = float(o.get("price"))
        except (TypeError, ValueError):
            continue
        if price > 1.01:
            cand.append((price, str(o.get("bookmaker", "")), str(o.get("retrieved_at", ""))))
    if not cand:
        return None
    for bk in PREFERRED:
        pref = [c for c in cand if c[1].lower() == bk]
        if pref:
            price, bm, ts = max(pref, key=lambda c: c[0])
            return price, bm, "preferred", ts
    price, bm, ts = max(cand, key=lambda c: c[0])
    return price, bm, "best_available", ts


def attach_odds(leg, r, odds_rows):
    """Record the price once, at slip generation time, and never change it."""
    if leg.get("bookmaker_odds") not in ("", None):
        return leg
    if str(leg.get("leg_result", "PENDING")).upper() != "PENDING":
        return leg
    found = find_odds(odds_rows, r)
    if found:
        price, bm, pol, ts = found
        leg["bookmaker_odds"] = f"{price:.2f}"
        leg["bookmaker"] = bm
        leg["odds_policy"] = pol
        leg["odds_retrieved_at"] = ts
    return leg


def refresh(history, picks):
    bykey = {pkey(r): r for r in picks}
    groups = {}
    for h in history:
        k = (str(h.get("date", ""))[:10], str(h.get("league", "")).upper().strip(),
             norm(h.get("home")), norm(h.get("away")),
             "3.5" if str(h.get("selection", "")).upper() == "UNDER 3.5" else "1.5")
        current = bykey.get(k)
        if current:
            outcome = leg_result(current)
            if outcome != "PENDING":
                h["leg_result"] = outcome
                h["hg"] = current.get("hg", "")
                h["ag"] = current.get("ag", "")
        groups.setdefault(h.get("slip_id", ""), []).append(h)
    for rows in groups.values():
        outcomes = [str(r.get("leg_result", "PENDING")).upper() for r in rows]
        if "MISS" in outcomes:
            overall = "MISS"
        elif len(rows) == 4 and all(x == "HIT" for x in outcomes):
            overall = "HIT"
        elif len(rows) == 4 and all(x in ("HIT", "VOID") for x in outcomes) and "VOID" in outcomes:
            overall = "VOID"
        else:
            overall = "PENDING"
        for r in rows:
            r["slip_result"] = overall
    return history


def make_leg(slip_id, created, slip_no, n, r, odds_rows):
    is_u = core2(r)
    p = float(r["probability"])
    leg = {"slip_id": slip_id, "generated_at": created, "slip_no": slip_no, "leg_no": n,
           "date": str(r.get("date", ""))[:10], "league": r.get("league", ""), "home": r.get("home", ""),
           "away": r.get("away", ""),
           "selection": "UNDER 3.5" if is_u else "OVER 1.5", "market": "3.5" if is_u else "1.5",
           "probability": f"{p:.4f}", "fair_odds": f"{1 / p:.3f}" if p > 0 else "",
           "bookmaker_odds": "", "bookmaker": "", "odds_policy": "", "odds_retrieved_at": "",
           "combined_odds": "", "combined_policy": "", "stake": "", "potential_return": "", "actual_return": "",
           "profit": "",
           "source": "Core 2" if is_u else "Core 1",
           "hg": r.get("hg", ""), "ag": r.get("ag", ""), "leg_result": "PENDING", "slip_result": "PENDING"}
    return attach_odds(leg, r, odds_rows)


def pending_fixture_keys(history):
    """Fixtures already sitting in an unsettled slip. They must not be reused."""
    used = set()
    for h in history:
        if str(h.get("slip_result", "PENDING")).upper() == "PENDING":
            used.add((str(h.get("date", ""))[:10], str(h.get("league", "")).upper().strip(),
                      norm(h.get("home")), norm(h.get("away"))))
    return used


def generate(history, picks, today, odds_rows, now=None):
    now = now or datetime.now(timezone.utc)
    overs, unders = candidates(picks, today, now)
    used = pending_fixture_keys(history)
    existing = {r.get("slip_id", "") for r in history}
    created = now.isoformat()
    made = 0

    def free(r):
        return fixture_key(r) not in used

    # Earliest matchday first, so slips settle sooner.
    for d in sorted({str(r["date"])[:10] for r in overs}):
        end = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")

        def in_window(r, d=d, end=end):
            return d <= str(r["date"])[:10] <= end

        while made < MAX_NEW:
            legs = [r for r in overs if in_window(r) and free(r)][:3]
            if len(legs) < 3:
                break
            under = next((r for r in unders if in_window(r) and free(r)), None)
            if under is None:
                break
            slip = legs + [under]
            ident = sid(slip)
            for r in slip:
                used.add(fixture_key(r))
            if ident in existing:
                continue
            slip_no = f"{today}-{ident[:6]}"
            for i, r in enumerate(slip, 1):
                history.append(make_leg(ident, created, slip_no, i, r, odds_rows))
            existing.add(ident)
            made += 1
        if made >= MAX_NEW:
            break
    print(f"New slips: {made}; eligible Core 1 Over 1.5: {len(overs)}; eligible Core 2 Under 3.5: {len(unders)}")
    return history


def price_of(row):
    try:
        p = float(row.get("bookmaker_odds", ""))
        return p if p > 1.01 else None
    except (TypeError, ValueError):
        return None


def settlement(history):
    """Derive combined odds and money per slip. Recomputed from stored leg
    prices each run, so reruns never duplicate or corrupt results."""
    groups = {}
    for r in history:
        groups.setdefault(r.get("slip_id", ""), []).append(r)
    staked = returned = 0.0
    priced = settled_priced = 0
    for rows in groups.values():
        res = str(rows[0].get("slip_result", "PENDING")).upper()
        prices = [price_of(r) for r in rows]
        complete = len(rows) == 4 and all(p is not None for p in prices)
        for r in rows:
            r["combined_odds"] = ""
            r["combined_policy"] = ""
            r["stake"] = ""
            r["potential_return"] = ""
            r["actual_return"] = ""
            r["profit"] = ""
        if not complete:
            continue
        combined = 1.0
        for p in prices:
            combined *= p
        books = {str(r.get("bookmaker", "")).lower() for r in rows}
        policy = f"single bookmaker ({next(iter(books))})" if len(books) == 1 else "best-available combination"
        gross = STAKE * combined
        if res == "HIT":
            ret = gross
        elif res == "MISS":
            ret = 0.0
        elif res == "VOID":
            ret = STAKE
        else:
            ret = None
        for r in rows:
            r["combined_odds"] = f"{combined:.2f}"
            r["combined_policy"] = policy
            r["stake"] = f"{STAKE:.2f}"
            r["potential_return"] = f"{gross:.2f}"
            if ret is not None:
                r["actual_return"] = f"{ret:.2f}"
                r["profit"] = f"{ret - STAKE:.2f}"
        priced += 1
        if ret is not None:
            settled_priced += 1
            staked += STAKE
            returned += ret
    return {"priced": priced, "settled_priced": settled_priced, "staked": staked, "returned": returned}


def money(x):
    return f"{CURRENCY}{x:,.2f}" if CURRENCY else f"{x:,.2f}"


def render(history, totals):
    groups = {}
    for r in history:
        groups.setdefault(r["slip_id"], []).append(r)
    settled = [g for g in groups.values() if g and g[0].get("slip_result") in ("HIT", "MISS", "VOID")]
    hits = sum(g[0]["slip_result"] == "HIT" for g in settled)
    losses = sum(g[0]["slip_result"] == "MISS" for g in settled)
    pending = sum(g[0].get("slip_result") == "PENDING" for g in groups.values())
    legs_total = sum(len(g) for g in groups.values())
    legs_priced = sum(1 for g in groups.values() for r in g if price_of(r) is not None)
    profit = totals["returned"] - totals["staked"]
    roi = profit / totals["staked"] if totals["staked"] > 0 else None
    lines = ["# BARBADOX 3+1 SLIP TRACKER", "", f"Updated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", "",
             "## Settlement summary",
             f"- Slips recorded: **{len(groups)}**", f"- Confirmed hits: **{hits}**",
             f"- Confirmed losses: **{losses}**", f"- Pending slips: **{pending}**",
             f"- Settled hit rate (voids excluded): **{hits / (hits + losses):.1%}**" if hits + losses
             else "- Settled hit rate: **not available yet**", "",
             "## Odds coverage",
             f"- Legs with recorded bookmaker odds: **{legs_priced} / {legs_total}**",
             f"- Slips with all four prices recorded: **{totals['priced']}**",
             "- Bookmaker prices come from The Odds API snapshot at slip generation time. Missing markets "
             "(the 1.5/3.5 lines are not always offered) are left blank, never estimated.", "",
             "## Money (only fully-priced slips)"]
    if totals["settled_priced"]:
        lines += [f"- Settled fully-priced slips: **{totals['settled_priced']}**",
                  f"- Total staked: **{money(totals['staked'])}**",
                  f"- Total returned: **{money(totals['returned'])}**",
                  f"- Profit/loss: **{money(profit)}**",
                  f"- ROI: **{roi:+.1%}**" if roi is not None else "- ROI: **n/a**"]
    else:
        lines += ["- No fully-priced slip has settled yet. Stake, returns, and ROI appear only once real odds "
                  "and results both exist."]
    lines += [""]
    if not groups:
        lines += ["No complete slip exists yet.",
                  "Need 3 eligible Core 1 Over 1.5 picks at ≥80% and 1 eligible Core 2 Under 3.5 pick at ≥60%, "
                  "all on upcoming fixtures in the same matchday window and not already in a pending slip. "
                  "Run Core 2 before running this workflow.", ""]
    for ident, rows in sorted(groups.items(), key=lambda item: item[1][0].get("generated_at", ""), reverse=True):
        first = rows[0]
        lines += [f"## Slip {first.get('slip_no', ident)} — **{first.get('slip_result', 'PENDING')}**", "",
                  "| Leg | Match | Pick | Probability | Fair odds | Bookmaker odds | Book | Actual score | Result |",
                  "|---:|---|---|---:|---:|---:|---|---|---|"]
        for r in sorted(rows, key=lambda x: int(x.get("leg_no", 0) or 0)):
            score = (f"{r.get('hg')}–{r.get('ag')}"
                     if r.get("hg") not in ("", None) and r.get("ag") not in ("", None) else "—")
            bo = r.get("bookmaker_odds") or "—"
            bk = r.get("bookmaker") or "—"
            lines.append(f"| {r.get('leg_no')} | {r.get('home')} vs {r.get('away')} ({r.get('date')}) | "
                         f"{r.get('selection')} | {float(r.get('probability') or 0):.1%} | "
                         f"{r.get('fair_odds') or '—'} | {bo} | {bk} | {score} | {r.get('leg_result')} |")
        if first.get("combined_odds"):
            lines += ["", f"**Combined odds: {first.get('combined_odds')}** ({first.get('combined_policy')}) — "
                          f"stake {money(STAKE)}, potential return {money(float(first.get('potential_return') or 0))}."]
            if first.get("actual_return") not in ("", None):
                lines.append(f"Actual return: {money(float(first['actual_return']))} — "
                             f"profit {money(float(first['profit']))}.")
            else:
                lines.append("Not settled yet; no profit is claimed while any leg is pending.")
        else:
            lines += ["", "No combined odds: at least one leg has no recorded bookmaker price."]
        lines.append("")
    lines += ["## Settlement rules",
              "- HIT means all four legs are graded HIT from actual scores.",
              "- One MISS makes the slip MISS. Pending legs are never counted as wins.",
              "- VOID is used only when no leg lost and at least one leg is void; voided slips are assumed to "
              "return the stake.",
              "- Combined odds are the product of the four recorded decimal prices and are labelled "
              "best-available when the prices come from different bookmakers.",
              "- Fair odds = 1 / model probability; they are model-derived, not bookmaker odds.",
              "- Model probability alone does not establish profitability.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    picks = read(PICKS)
    odds_rows = read_odds()
    history = refresh(read(HISTORY), picks)
    for h in history:
        attach_odds(h, h, odds_rows)
    history = generate(history, picks, today, odds_rows, now)
    history = refresh(history, picks)
    totals = settlement(history)
    write(HISTORY, FIELDS, history)
    render(history, totals)
    priced_legs = sum(1 for r in history if price_of(r) is not None)
    print(f"Report: {REPORT}")
    print(f"Permanent slip history: {HISTORY}")
    print(f"Legs with bookmaker odds: {priced_legs}/{len(history)}; "
          f"fully-priced settled slips: {totals['settled_priced']}")


if __name__ == "__main__":
    main()
