# BARBADOX HISTORICAL 3+1 SLIP BACKTEST

Generated: 2026-10-17 01:03 UTC

## How to read this
- Historical slips are reconstructed per calendar day from the merged, leakage-aware walk-forward records of both cores.
- NO bookmaker odds are used. Fair odds shown are 1/probability (model-derived). No stake, return, or ROI is claimed, because no real prices exist for these matches.
- The 0.79 / 0.75 thresholds were chosen with knowledge of this data; hit rates below are an upper bound, not independent validation.
- Core 1 historical probabilities use factors 1-2 only (Poisson core); live picks also use factors 3-5, so live results can differ.
- Legs in one slip are correlated (shared leagues and matchdays); these are not independent probabilities.

## Overall

- Historical Core 1 Over 1.5 picks in picks.csv (settled): **1382**, hits **1123** (81.3%)
- Historical Core 2 Under 3.5 picks in picks.csv (settled): **0**, hits **0**
- Days with a reconstructable 3+1 slip: **0**
- Slips HIT (all four legs): **0**
- Slips MISS (at least one leg): **0**
- Slip hit rate: n/a



## Legs inside slips

- Over 1.5 legs: **0**, hits **0**
- Under 3.5 legs: **0**, hits **0**

If the four-leg hit rate is close to the product of leg probabilities, the legs are behaving roughly independently at these thresholds. If it is clearly lower, the legs are negatively compounding.

## By season

| Season | Slips | Hits |
|---|---:|---:|

## Every slip
