# BARBADOX XGBOOST OBSERVER

Generated: 2026-11-02 16:16 UTC
Current season: 2026/2027

## DATA COVERAGE

- Core 1 historical settled selections: 1265
- Core 2 historical settled selections: 984
- Historical unique selections: 2249
- Historical seasons found: 2024/2025, 2025/2026, 2026/2027
- Current archive: Read 102 settled legs from slips_browser.csv.
- Current-season settled slip legs: 102
- Current-season slips represented: 29

## CURRENT-SEASON SLIP ANALYSIS

Only individual legs explicitly marked LOST count as failed legs.
A winning leg in a lost accumulator is not blamed for the accumulator failure.
Pending legs are excluded.

## Current-season slip team ranking

| Team | Settled legs | Failed legs | Failed slips | Leg failure rate |
|---|---:|---:|---:|---:|
| AS Roma | 3 | 3 | 3 | 100.0% |
| Manchester City FC | 3 | 3 | 3 | 100.0% |
| Brighton & Hove Albion FC | 3 | 3 | 3 | 100.0% |
| Paris FC | 2 | 2 | 2 | 100.0% |
| Cagliari Calcio | 3 | 2 | 2 | 66.7% |
| AS Monaco FC | 4 | 2 | 2 | 50.0% |
| RC Deportivo La Coruña | 1 | 1 | 1 | 100.0% |
| Villarreal CF | 1 | 1 | 1 | 100.0% |
| Coventry City FC | 1 | 1 | 1 | 100.0% |
| Sunderland AFC | 1 | 1 | 1 | 100.0% |
| Hull City AFC | 1 | 1 | 1 | 100.0% |
| Ipswich Town FC | 1 | 1 | 1 | 100.0% |
| Getafe CF | 1 | 1 | 1 | 100.0% |
| Sevilla FC | 1 | 1 | 1 | 100.0% |
| Eintracht Frankfurt | 2 | 1 | 1 | 50.0% |
| RCD Espanyol de Barcelona | 3 | 1 | 1 | 33.3% |
| Borussia Dortmund | 3 | 1 | 1 | 33.3% |
| Club Atlético de Madrid | 3 | 1 | 1 | 33.3% |
| SSC Napoli | 5 | 1 | 1 | 20.0% |
| FC Internazionale Milano | 8 | 0 | 0 | 0.0% |

## Historical backtest team ranking

| Team | Appearances | Failed selections | Failure rate |
|---|---:|---:|---:|
| acf fiorentina | 55 | 18 | 32.7% |
| udinese | 54 | 16 | 29.6% |
| roma | 54 | 15 | 27.8% |
| atalanta bc | 57 | 15 | 26.3% |
| bologna 1909 | 50 | 14 | 28.0% |
| hellas verona | 51 | 14 | 27.5% |
| juventus | 56 | 14 | 25.0% |
| cagliari | 60 | 14 | 23.3% |
| bournemouth | 43 | 13 | 30.2% |
| milan | 52 | 13 | 25.0% |
| pisa 1909 | 37 | 12 | 32.4% |
| sv werder bremen | 51 | 12 | 23.5% |
| torino | 51 | 12 | 23.5% |
| lille osc | 31 | 11 | 35.5% |
| arsenal | 32 | 11 | 34.4% |
| everton | 33 | 11 | 33.3% |
| brentford | 39 | 11 | 28.2% |
| chelsea | 48 | 11 | 22.9% |
| newcastle united | 50 | 11 | 22.0% |
| internazionale milano | 50 | 11 | 22.0% |

## Current slips vs historical backtest

### Teams appearing in both top-20 rankings

| Team | Current failed slips | Current failed legs | Historical failures | Historical failure rate |
|---|---:|---:|---:|---:|
| Cagliari Calcio | 2 | 2 | 14 | 23.3% |
| FC Internazionale Milano | 0 | 0 | 11 | 22.0% |
| AS Roma | 3 | 3 | 15 | 27.8% |

### Exact fixture, date and market overlaps

| Date | Fixture | Market | Current slip leg | Historical backtest |
|---|---|---|---|---|
| No exact fixture/date/market overlaps found | - | - | - | - |

## XGBOOST OBSERVATION

XGBoost trained and evaluated.
Training selections: 1799
Test selections: 450
Accuracy: 0.804
Brier score: 0.156
ROC-AUC: 0.543

## INTERPRETATION

- Current slip analysis uses slips_browser.csv.
- Current and historical rankings are calculated separately.
- Failed slips count distinct slip IDs.
- Current failure rates use settled leg appearances as the denominator.
- Historical rankings use settled backtest selections.
- Team names are normalized for comparison.
- Exact overlap requires the same date, market and fixture.
- Team association is descriptive, not proof of causation.
- Pending selections are excluded.
- No Core 1 or Core 2 prediction logic is modified.
