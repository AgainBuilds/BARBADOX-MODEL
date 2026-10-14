# BARBADOX 3+1 SLIP TRACKER

Updated: 2026-10-14 13:31 UTC

## Settlement summary
- Slips recorded: **0**
- Confirmed hits: **0**
- Confirmed losses: **0**
- Pending slips: **0**
- Settled hit rate: **not available yet**

## Odds coverage
- Legs with recorded bookmaker odds: **0 / 0**
- Slips with all four prices recorded: **0**
- Bookmaker prices come from The Odds API snapshot at slip generation time. Missing markets (the 1.5/3.5 lines are not always offered) are left blank, never estimated.

## Money (only fully-priced slips)
- No fully-priced slip has settled yet. Stake, returns, and ROI appear only once real odds and results both exist.

No complete slip exists yet.
Need 3 eligible Core 1 Over 1.5 picks at ≥79% and 1 eligible Core 2 Under 3.5 pick at ≥75%. Run Core 2 before running this workflow.

## Settlement rules
- HIT means all four legs are graded HIT from actual scores.
- One MISS makes the slip MISS. Pending legs are never counted as wins.
- VOID is used only when no leg lost and at least one leg is void; voided slips are assumed to return the stake.
- Combined odds are the product of the four recorded decimal prices and are labelled best-available when the prices come from different bookmakers.
- Fair odds = 1 / model probability; they are model-derived, not bookmaker odds.
- Model probability alone does not establish profitability.
