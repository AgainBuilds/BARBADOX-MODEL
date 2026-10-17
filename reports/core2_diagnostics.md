# BARBADOX CORE 2.2 — UNDER 3.5 DIAGNOSTICS

Generated: 2026-10-17 01:03 UTC
Model: Negative Binomial
Threshold: 80.0%
Safety z: 1.35

## Coverage

- Historical test matches: **3802**
- Historical matches with raw probabilities: **2838**
- Qualified historical picks: **0**
- Rejected or unscored historical rows: **3802**
- Upcoming fixtures evaluated: **0**
- Qualified upcoming fixtures: **0**

## Historical performance

- Under 3.5 base rate: **69.31%**
- Raw Brier score: **0.20860**
- Calibrated Brier score: **0.21167**
- Qualified pick hit rate: n/a

## Rejection reasons

| Reason | Count |
|---|---:|
| expected_total_goals_above_filter | 2405 |
| insufficient_team_or_league_history | 964 |
| below_threshold | 400 |
| guard_insufficient_history | 33 |

## Important limitations

- A qualified pick is not proof of a reliable probability.
- The threshold is a selection rule, not a guarantee.
- Calibration and the Wilson guard depend on earlier recorded predictions.
- Historical performance must be checked on a genuinely unseen period.
- Inspect sample size and Brier scores alongside hit rate.

All historical rows, including rejected and unscored fixtures, are retained in `core2_results.csv`.
