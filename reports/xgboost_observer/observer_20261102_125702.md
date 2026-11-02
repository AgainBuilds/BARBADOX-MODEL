# BARBADOX XGBOOST OBSERVER

Generated: 2026-11-02 12:57 UTC
Current season: 2026/2027

## DATA COVERAGE

- Core 1 settled selections: 1265
- Core 2 settled selections: 984
- Historical unique selections: 2249
- Historical seasons found: 2024/2025, 2025/2026, 2026/2027
- Current slip data: Current slip endpoint not configured.

Four-season coverage is only claimed if four actual backtest seasons are present in the source files.

## CURRENT-SEASON SLIP ANALYSIS

A team is associated with a failed selection when it appears in the failed fixture. This does not prove that the team caused the slip to fail.

## Current-season team ranking

No settled selections available.

## Historical backtest team ranking

| Team | Appearances | Failed | Failure rate | Slips affected |
|---|---:|---:|---:|---:|
| ACF Fiorentina | 55 | 18 | 32.7% | 0 |
| Udinese Calcio | 54 | 16 | 29.6% | 0 |
| AS Roma | 54 | 15 | 27.8% | 0 |
| Atalanta BC | 57 | 15 | 26.3% | 0 |
| Bologna FC 1909 | 50 | 14 | 28.0% | 0 |
| Hellas Verona FC | 51 | 14 | 27.5% | 0 |
| Juventus FC | 56 | 14 | 25.0% | 0 |
| Cagliari Calcio | 60 | 14 | 23.3% | 0 |
| AFC Bournemouth | 43 | 13 | 30.2% | 0 |
| AC Milan | 52 | 13 | 25.0% | 0 |
| AC Pisa 1909 | 37 | 12 | 32.4% | 0 |
| SV Werder Bremen | 51 | 12 | 23.5% | 0 |
| Torino FC | 51 | 12 | 23.5% | 0 |
| Lille OSC | 31 | 11 | 35.5% | 0 |
| Arsenal FC | 32 | 11 | 34.4% | 0 |
| Everton FC | 33 | 11 | 33.3% | 0 |
| Brentford FC | 39 | 11 | 28.2% | 0 |
| Chelsea FC | 48 | 11 | 22.9% | 0 |
| Newcastle United FC | 50 | 11 | 22.0% | 0 |
| FC Internazionale Milano | 50 | 11 | 22.0% | 0 |

## XGBOOST OBSERVATION

XGBoost trained and evaluated.
Training selections: 1799
Test selections: 450
Accuracy: 0.807
Brier score: 0.156
ROC-AUC: 0.542

## INTERPRETATION

- Pending selections are excluded.
- Repeated fixtures are deduplicated for team failure rates.
- Both teams in a failed fixture are associated with the failure.
- Team rankings are descriptive, not causal.
- XGBoost is not trained when data is insufficient.
- No Core 1 or Core 2 logic is modified.
