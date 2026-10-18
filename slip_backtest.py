#!/usr/bin/env python3
"""Reconstruct historical 3+1 slips from the merged historical records of both cores
and report how they would have performed. Reads picks.csv; writes
reports/slip_backtest.md.

Slip reconstruction policy (per calendar day, chronological):
- Eligible Over legs: CORE1_OVER15|HISTORICAL rows with probability >= 0.80, settled.
- Eligible Under legs: CORE2_UNDER35|HISTORICAL rows with probability >= 0.75, settled.
- One slip per day: the three highest-probability Over legs on distinct fixtures plus
  the highest-probability Under leg on a fourth distinct fixture.
- A day with fewer than 3 eligible Overs or no eligible Under produces no slip.
- A slip HITs only if all four legs hit; one MISS loses the slip. (Voids do not exist
  in historical data: every row is graded from a finished match.)

This differs from the live slip tracker in two documented ways:
1. Live slips may combine legs across different days (any future date); this backtest
   groups strictly by day, which is the conservative reading of "a slip you could
   have placed that morning".
2. Live Core 1 picks use all five factors; historical Core 1 probabilities come from
   the leakage-aware Poisson-core replay (factors 1-2 only). Live performance can
   differ from these numbers in either direction.

Honesty rules printed in the report:
- No bookmaker odds are used anywhere: no combined odds, stake, return, or ROI is
  claimed. Only model-derived fair odds (1/p) are shown, and the break-even price of
  each slip is reported.
- The 0.80/0.75 thresholds were themselves chosen in hindsight over data like this,
  so hit rates here are an upper bound, not an independent validation.
- Legs in a slip are correlated (shared leagues, matchdays); hit rates are not
  independent coin flips.
"""

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PICKS = ROOT / "picks.csv"
OUT = ROOT / "reports" / "slip_backtest.md"

OVER_T = 0.80
UNDER_T = 0.75


def read(path):
    if not path.exists():
        return []

    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def norm(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def is_core1_hist(r):
    return str(r.get("note", "")).strip().upper().startswith(
        "CORE1_OVER15"
    )


def is_core2_hist(r):
    return str(r.get("note", "")).strip().upper().startswith(
        "CORE2_UNDER35"
    )


def settled(r):
    res = str(r.get("result", "")).strip().upper()
    return res in ("HIT", "MISS")


def prob(r):
    try:
        p = float(r.get("probability", ""))
        return p if 0 < p <= 1 else None
    except (TypeError, ValueError):
        return None


def fixture(r):
    return (
        str(r.get("date", ""))[:10],
        str(r.get("league", "")).upper().strip(),
        norm(r.get("home")),
        norm(r.get("away")),
    )


def build_slips(picks):
    by_day = defaultdict(lambda: {"over": [], "under": []})

    for r in picks:
        if not settled(r):
            continue

        p = prob(r)
        if p is None:
            continue

        d = str(r.get("date", ""))[:10]

        if is_core1_hist(r) and p >= OVER_T:
            by_day[d]["over"].append(r)
        elif is_core2_hist(r) and p >= UNDER_T:
            by_day[d]["under"].append(r)

    slips = []

    for d in sorted(by_day):
        overs = sorted(
            by_day[d]["over"],
            key=lambda r: (-prob(r), fixture(r)),
        )
        unders = sorted(
            by_day[d]["under"],
            key=lambda r: (-prob(r), fixture(r)),
        )

        # Select the top 3 Over legs from distinct fixtures.
        top = []
        seen = set()

        for r in overs:
            if fixture(r) in seen:
                continue

            seen.add(fixture(r))
            top.append(r)

            if len(top) == 3:
                break

        # Under leg must be a fourth, distinct fixture.
        under = next(
            (u for u in unders if fixture(u) not in seen),
            None,
        )

        if len(top) < 3 or under is None:
            continue

        legs = top + [under]
        probs = [prob(r) for r in legs]
        outcomes = [
            str(r.get("result", "")).strip().upper()
            for r in legs
        ]

        slips.append({
            "date": d,
            "legs": legs,
            "probs": probs,
            "outcomes": outcomes,
            "result": (
                "HIT"
                if all(o == "HIT" for o in outcomes)
                else "MISS"
            ),
            "product": (
                probs[0] * probs[1] * probs[2] * probs[3]
            ),
        })

    return slips


def season_of(date):
    y, m = int(date[:4]), int(date[5:7])
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def fmt(r):
    return (
        f"{r.get('home')} vs {r.get('away')} "
        f"({r.get('league')}, "
        f"{float(r.get('probability') or 0):.1%}, "
        f"{r.get('hg')}-{r.get('ag')}, "
        f"{str(r.get('result', '')).upper()})"
    )


def main():
    picks = read(PICKS)

    core1 = [r for r in picks if is_core1_hist(r)]
    core2 = [r for r in picks if is_core2_hist(r)]
    slips = build_slips(picks)

    hits = sum(1 for s in slips if s["result"] == "HIT")
    losses = len(slips) - hits

    def stats(rows):
        st = [r for r in rows if settled(r)]
        h = sum(
            1 for r in st
            if str(r.get("result", "")).upper() == "HIT"
        )
        return len(st), h

    c1_n, c1_h = stats(core1)
    c2_n, c2_h = stats(core2)

    over_legs = [o for s in slips for o in s["outcomes"][:3]]
    under_legs = [s["outcomes"][3] for s in slips]

    over_hits = sum(1 for o in over_legs if o == "HIT")
    under_hits = sum(1 for o in under_legs if o == "HIT")

    by_season = defaultdict(lambda: [0, 0])

    for s in slips:
        season = season_of(s["date"])
        by_season[season][0] += 1

        if s["result"] == "HIT":
            by_season[season][1] += 1

    avg_product = (
        sum(s["product"] for s in slips) / len(slips)
        if slips else 0.0
    )

    lines = [
        "# BARBADOX HISTORICAL 3+1 SLIP BACKTEST",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        "",
        "## How to read this",
        "",
        "- Historical slips are reconstructed per calendar day from the merged, "
        "leakage-aware walk-forward records of both cores.",
        "- NO bookmaker odds are used. Fair odds shown are 1/probability "
        "(model-derived). No stake, return, or ROI is claimed, because no "
        "real prices exist for these matches.",
        "- The 0.80 / 0.75 thresholds were chosen with knowledge of this data; "
        "hit rates below are an upper bound, not independent validation.",
        "- Core 1 historical probabilities use factors 1-2 only (Poisson core); "
        "live picks also use factors 3-5, so live results can differ.",
        "- Legs in one slip are correlated (shared leagues and matchdays); "
        "these are not independent probabilities.",
        "",
    ]

    lines += [
        "## Overall",
        "",
        f"- Historical Core 1 Over 1.5 picks in picks.csv (settled): "
        f"**{c1_n}**, hits **{c1_h}**"
        + (f" ({c1_h/c1_n:.1%})" if c1_n else ""),
        f"- Historical Core 2 Under 3.5 picks in picks.csv (settled): "
        f"**{c2_n}**, hits **{c2_h}**"
        + (f" ({c2_h/c2_n:.1%})" if c2_n else ""),
        f"- Days with a reconstructable 3+1 slip: **{len(slips)}**",
        f"- Slips HIT (all four legs): **{hits}**",
        f"- Slips MISS (at least one leg): **{losses}**",
        (
            f"- Slip hit rate: **{hits/len(slips):.1%}**"
            if slips else "- Slip hit rate: n/a"
        ),
        (
            f"- Average product of the four leg probabilities: "
            f"**{avg_product:.1%}** "
            f"(model's own expectation of slip hit rate)"
            if slips else ""
        ),
        (
            f"- Break-even combined price at this hit rate: "
            f"**{1/(hits/len(slips)):.2f}** "
            f"(any real combined bookmaker price must exceed this "
            f"to be +EV)"
            if hits else ""
        ),
        "",
    ]

    lines += [
        "## Legs inside slips",
        "",
        f"- Over 1.5 legs: **{len(over_legs)}**, hits **{over_hits}**"
        + (
            f" ({over_hits/len(over_legs):.1%})"
            if over_legs else ""
        ),
        f"- Under 3.5 legs: **{len(under_legs)}**, hits **{under_hits}**"
        + (
            f" ({under_hits/len(under_legs):.1%})"
            if under_legs else ""
        ),
        "",
        "If the four-leg hit rate is close to the product of leg "
        "probabilities, the legs are behaving roughly independently "
        "at these thresholds. If it is clearly lower, the legs are "
        "negatively compounding.",
        "",
    ]

    lines += [
        "## By season",
        "",
        "| Season | Slips | Hits |",
        "|---|---:|---:|",
    ]

    for season in sorted(by_season):
        n, h = by_season[season]
        lines.append(f"| {season} | {n} | {h} |")

    lines.append("")
    lines += ["## Every slip", ""]

    for s in slips:
        fair = 1.0

        for p in s["probs"]:
            fair *= 1 / p

        lines.append(
            f"### {s['date']} — **{s['result']}** "
            f"(fair combined odds {fair:.2f})"
        )

        for i, r in enumerate(s["legs"], 1):
            tag = "Under 3.5" if i == 4 else "Over 1.5"
            lines.append(f"{i}. {tag}: {fmt(r)}")

        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print(
        f"Historical slips reconstructed: {len(slips)} | "
        f"hits: {hits} | misses: {losses}"
    )

    if slips:
        print(
            f"Slip hit rate: {hits/len(slips):.1%} | "
            f"avg product of leg probs: {avg_product:.1%}"
        )

    print(f"Report: {OUT}")


if __name__ == "__main__":
    main()
