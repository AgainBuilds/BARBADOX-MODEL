# BARBADOX HISTORICAL 3+1 SLIP BACKTEST

Generated: 2026-10-18 22:50 UTC

## How to read this

- Historical slips are reconstructed per calendar day from the merged, leakage-aware walk-forward records of both cores.
- NO bookmaker odds are used. Fair odds shown are 1/probability (model-derived). No stake, return, or ROI is claimed, because no real prices exist for these matches.
- The 0.80 / 0.75 thresholds were chosen with knowledge of this data; hit rates below are an upper bound, not independent validation.
- Core 1 historical probabilities use factors 1-2 only (Poisson core); live picks also use factors 3-5, so live results can differ.
- Legs in one slip are correlated (shared leagues and matchdays); these are not independent probabilities.

## Overall

- Historical Core 1 Over 1.5 picks in picks.csv (settled): **1382**, hits **1123** (81.3%)
- Historical Core 2 Under 3.5 picks in picks.csv (settled): **395**, hits **321** (81.3%)
- Days with a reconstructable 3+1 slip: **111**
- Slips HIT (all four legs): **54**
- Slips MISS (at least one leg): **57**
- Slip hit rate: **48.6%**
- Average product of the four leg probabilities: **52.2%** (model's own expectation of slip hit rate)
- Break-even combined price at this hit rate: **2.06** (any real combined bookmaker price must exceed this to be +EV)

## Legs inside slips

- Over 1.5 legs: **333**, hits **283** (85.0%)
- Under 3.5 legs: **111**, hits **88** (79.3%)

If the four-leg hit rate is close to the product of leg probabilities, the legs are behaving roughly independently at these thresholds. If it is clearly lower, the legs are negatively compounding.

## By season

| Season | Slips | Hits |
|---|---:|---:|
| 2024-25 | 62 | 33 |
| 2025-26 | 49 | 21 |

## Every slip

### 2024-09-21 — **HIT** (fair combined odds 1.85)
1. Over 1.5: SV Werder Bremen vs FC Bayern München (BL1, 89.9%, 0-5, HIT)
2. Over 1.5: Aston Villa FC vs Wolverhampton Wanderers FC (PL, 87.5%, 3-1, HIT)
3. Over 1.5: West Ham United FC vs Chelsea FC (PL, 87.2%, 0-3, HIT)
4. Under 3.5: Real Valladolid CF vs Real Sociedad de Fútbol (PD, 78.9%, 0-0, HIT)

### 2024-09-22 — **HIT** (fair combined odds 1.92)
1. Over 1.5: Villarreal CF vs FC Barcelona (PD, 91.2%, 1-5, HIT)
2. Over 1.5: FC Internazionale Milano vs AC Milan (SA, 85.6%, 1-2, HIT)
3. Over 1.5: Olympique Lyonnais vs Olympique de Marseille (FL1, 84.6%, 2-3, HIT)
4. Under 3.5: Getafe CF vs CD Leganés (PD, 78.6%, 1-1, HIT)

### 2024-09-27 — **HIT** (fair combined odds 2.10)
1. Over 1.5: Borussia Dortmund vs VfL Bochum 1848 (BL1, 87.6%, 4-2, HIT)
2. Over 1.5: Paris Saint-Germain FC vs Stade Rennais FC 1901 (FL1, 85.1%, 3-1, HIT)
3. Over 1.5: AJ Auxerre vs Stade Brestois 29 (FL1, 80.5%, 3-0, HIT)
4. Under 3.5: Real Valladolid CF vs RCD Mallorca (PD, 79.4%, 1-2, HIT)

### 2024-09-28 — **HIT** (fair combined odds 2.03)
1. Over 1.5: Brentford FC vs West Ham United FC (PL, 86.6%, 1-1, HIT)
2. Over 1.5: FC Bayern München vs Bayer 04 Leverkusen (BL1, 85.1%, 1-1, HIT)
3. Over 1.5: Chelsea FC vs Brighton & Hove Albion FC (PL, 84.2%, 4-2, HIT)
4. Under 3.5: Getafe CF vs Deportivo Alavés (PD, 79.4%, 2-0, HIT)

### 2024-09-29 — **HIT** (fair combined odds 2.13)
1. Over 1.5: Holstein Kiel vs Eintracht Frankfurt (BL1, 85.6%, 2-4, HIT)
2. Over 1.5: TSG 1899 Hoffenheim vs SV Werder Bremen (BL1, 85.3%, 3-4, HIT)
3. Over 1.5: Manchester United FC vs Tottenham Hotspur FC (PL, 82.2%, 0-3, HIT)
4. Under 3.5: AS Roma vs Venezia FC (SA, 78.2%, 2-1, HIT)

### 2024-10-05 — **HIT** (fair combined odds 1.74)
1. Over 1.5: Bayer 04 Leverkusen vs Holstein Kiel (BL1, 94.4%, 2-2, HIT)
2. Over 1.5: Real Madrid CF vs Villarreal CF (PD, 87.2%, 2-0, HIT)
3. Over 1.5: Stade Rennais FC 1901 vs AS Monaco FC (FL1, 86.6%, 1-2, HIT)
4. Under 3.5: RCD Espanyol de Barcelona vs RCD Mallorca (PD, 80.8%, 2-1, HIT)

### 2024-10-06 — **HIT** (fair combined odds 1.74)
1. Over 1.5: VfB Stuttgart vs TSG 1899 Hoffenheim (BL1, 94.0%, 1-1, HIT)
2. Over 1.5: Eintracht Frankfurt vs FC Bayern München (BL1, 88.7%, 3-3, HIT)
3. Over 1.5: ACF Fiorentina vs AC Milan (SA, 85.5%, 2-1, HIT)
4. Under 3.5: Real Sociedad de Fútbol vs Club Atlético de Madrid (PD, 80.8%, 1-1, HIT)

### 2024-10-19 — **HIT** (fair combined odds 1.74)
1. Over 1.5: TSG 1899 Hoffenheim vs VfL Bochum 1848 (BL1, 90.3%, 3-1, HIT)
2. Over 1.5: Paris Saint-Germain FC vs RC Strasbourg Alsace (FL1, 89.8%, 4-2, HIT)
3. Over 1.5: FC Bayern München vs VfB Stuttgart (BL1, 87.8%, 4-0, HIT)
4. Under 3.5: Girona FC vs Real Sociedad de Fútbol (PD, 80.7%, 0-1, HIT)

### 2024-10-20 — **MISS** (fair combined odds 2.02)
1. Over 1.5: Wolverhampton Wanderers FC vs Manchester City FC (PL, 87.3%, 1-2, HIT)
2. Over 1.5: Liverpool FC vs Chelsea FC (PL, 84.3%, 2-1, HIT)
3. Over 1.5: Villarreal CF vs Getafe CF (PD, 83.4%, 1-1, HIT)
4. Under 3.5: Club Atlético de Madrid vs CD Leganés (PD, 80.8%, 3-1, MISS)

### 2024-10-27 — **MISS** (fair combined odds 1.73)
1. Over 1.5: VfL Bochum 1848 vs FC Bayern München (BL1, 93.2%, 0-5, HIT)
2. Over 1.5: 1. FC Heidenheim 1846 vs TSG 1899 Hoffenheim (BL1, 88.5%, 0-0, MISS)
3. Over 1.5: Olympique Lyonnais vs AJ Auxerre (FL1, 87.4%, 2-2, HIT)
4. Under 3.5: Getafe CF vs Valencia CF (PD, 80.1%, 1-1, HIT)

### 2024-11-02 — **MISS** (fair combined odds 1.91)
1. Over 1.5: Holstein Kiel vs 1. FC Heidenheim 1846 (BL1, 87.4%, 1-0, MISS)
2. Over 1.5: Eintracht Frankfurt vs VfL Bochum 1848 (BL1, 86.8%, 7-2, HIT)
3. Over 1.5: VfL Wolfsburg vs FC Augsburg (BL1, 86.0%, 1-1, HIT)
4. Under 3.5: Girona FC vs CD Leganés (PD, 80.1%, 4-3, MISS)

### 2024-11-03 — **MISS** (fair combined odds 1.88)
1. Over 1.5: FC Barcelona vs RCD Espanyol de Barcelona (PD, 89.4%, 3-1, HIT)
2. Over 1.5: FC Internazionale Milano vs Venezia FC (SA, 88.0%, 1-0, MISS)
3. Over 1.5: Borussia Mönchengladbach vs SV Werder Bremen (BL1, 85.1%, 4-1, HIT)
4. Under 3.5: Athletic Club vs Real Betis Balompié (PD, 79.4%, 1-1, HIT)

### 2024-11-09 — **HIT** (fair combined odds 1.86)
1. Over 1.5: VfL Bochum 1848 vs Bayer 04 Leverkusen (BL1, 90.5%, 1-1, HIT)
2. Over 1.5: SV Werder Bremen vs Holstein Kiel (BL1, 87.6%, 2-1, HIT)
3. Over 1.5: Angers SCO vs Paris Saint-Germain FC (FL1, 87.2%, 2-4, HIT)
4. Under 3.5: CD Leganés vs Sevilla FC (PD, 77.6%, 1-0, HIT)

### 2024-11-10 — **MISS** (fair combined odds 1.77)
1. Over 1.5: Olympique Lyonnais vs AS Saint-Étienne (FL1, 90.5%, 1-0, MISS)
2. Over 1.5: Tottenham Hotspur FC vs Ipswich Town FC (PL, 88.8%, 1-2, HIT)
3. Over 1.5: FC Augsburg vs TSG 1899 Hoffenheim (BL1, 87.8%, 0-0, MISS)
4. Under 3.5: Getafe CF vs Girona FC (PD, 80.1%, 0-1, HIT)

### 2024-11-23 — **MISS** (fair combined odds 1.72)
1. Over 1.5: VfB Stuttgart vs VfL Bochum 1848 (BL1, 94.0%, 2-0, HIT)
2. Over 1.5: Eintracht Frankfurt vs SV Werder Bremen (BL1, 89.0%, 1-0, MISS)
3. Over 1.5: TSG 1899 Hoffenheim vs RB Leipzig (BL1, 86.6%, 4-3, HIT)
4. Under 3.5: UD Las Palmas vs RCD Mallorca (PD, 80.1%, 2-3, MISS)

### 2024-11-24 — **HIT** (fair combined odds 2.19)
1. Over 1.5: Como 1907 vs ACF Fiorentina (SA, 83.7%, 0-2, HIT)
2. Over 1.5: Holstein Kiel vs 1. FSV Mainz 05 (BL1, 83.5%, 0-3, HIT)
3. Over 1.5: CA Osasuna vs Villarreal CF (PD, 82.1%, 2-2, HIT)
4. Under 3.5: Athletic Club vs Real Sociedad de Fútbol (PD, 79.4%, 1-0, HIT)

### 2024-11-30 — **MISS** (fair combined odds 1.73)
1. Over 1.5: Borussia Dortmund vs FC Bayern München (BL1, 91.3%, 1-1, HIT)
2. Over 1.5: Brentford FC vs Leicester City FC (PL, 89.7%, 4-1, HIT)
3. Over 1.5: FC Barcelona vs UD Las Palmas (PD, 89.1%, 1-2, HIT)
4. Under 3.5: Real Valladolid CF vs Club Atlético de Madrid (PD, 79.4%, 0-5, MISS)

### 2024-12-01 — **HIT** (fair combined odds 2.02)
1. Over 1.5: Villarreal CF vs Girona FC (PD, 86.9%, 2-2, HIT)
2. Over 1.5: Chelsea FC vs Aston Villa FC (PL, 85.8%, 3-0, HIT)
3. Over 1.5: Olympique de Marseille vs AS Monaco FC (FL1, 83.1%, 2-1, HIT)
4. Under 3.5: Real Sociedad de Fútbol vs Real Betis Balompié (PD, 80.1%, 2-0, HIT)

### 2024-12-07 — **MISS** (fair combined odds 1.83)
1. Over 1.5: FC Bayern München vs 1. FC Heidenheim 1846 (BL1, 89.0%, 4-2, HIT)
2. Over 1.5: Holstein Kiel vs RB Leipzig (BL1, 88.6%, 0-2, HIT)
3. Over 1.5: Brentford FC vs Newcastle United FC (PL, 88.1%, 4-2, HIT)
4. Under 3.5: AS Roma vs US Lecce (SA, 78.6%, 4-1, MISS)

### 2024-12-08 — **MISS** (fair combined odds 2.09)
1. Over 1.5: Tottenham Hotspur FC vs Chelsea FC (PL, 86.7%, 3-4, HIT)
2. Over 1.5: ACF Fiorentina vs Cagliari Calcio (SA, 83.6%, 1-0, MISS)
3. Over 1.5: TSG 1899 Hoffenheim vs SC Freiburg (BL1, 83.2%, 1-1, HIT)
4. Under 3.5: CD Leganés vs Real Sociedad de Fútbol (PD, 79.4%, 0-3, HIT)

### 2024-12-14 — **MISS** (fair combined odds 2.06)
1. Over 1.5: Borussia Mönchengladbach vs Holstein Kiel (BL1, 87.5%, 4-1, HIT)
2. Over 1.5: Newcastle United FC vs Leicester City FC (PL, 86.5%, 4-0, HIT)
3. Over 1.5: 1. FSV Mainz 05 vs FC Bayern München (BL1, 85.4%, 2-1, HIT)
4. Under 3.5: Udinese Calcio vs SSC Napoli (SA, 75.1%, 1-3, MISS)

### 2024-12-15 — **MISS** (fair combined odds 1.93)
1. Over 1.5: FC Barcelona vs CD Leganés (PD, 87.6%, 0-1, MISS)
2. Over 1.5: Borussia Dortmund vs TSG 1899 Hoffenheim (BL1, 86.8%, 1-1, HIT)
3. Over 1.5: Chelsea FC vs Brentford FC (PL, 85.8%, 2-1, HIT)
4. Under 3.5: Club Atlético de Madrid vs Getafe CF (PD, 79.4%, 1-0, HIT)

### 2024-12-21 — **HIT** (fair combined odds 1.91)
1. Over 1.5: TSG 1899 Hoffenheim vs Borussia Mönchengladbach (BL1, 88.2%, 1-2, HIT)
2. Over 1.5: Brentford FC vs Nottingham Forest FC (PL, 86.2%, 0-2, HIT)
3. Over 1.5: Eintracht Frankfurt vs 1. FSV Mainz 05 (BL1, 85.8%, 1-3, HIT)
4. Under 3.5: Getafe CF vs RCD Mallorca (PD, 80.1%, 0-1, HIT)

### 2024-12-22 — **HIT** (fair combined odds 2.08)
1. Over 1.5: Leicester City FC vs Wolverhampton Wanderers FC (PL, 85.3%, 0-3, HIT)
2. Over 1.5: Tottenham Hotspur FC vs Liverpool FC (PL, 84.9%, 3-6, HIT)
3. Over 1.5: VfL Wolfsburg vs Borussia Dortmund (BL1, 84.7%, 1-3, HIT)
4. Under 3.5: AC Monza vs Juventus FC (SA, 78.6%, 1-2, HIT)

### 2024-12-29 — **HIT** (fair combined odds 1.92)
1. Over 1.5: Tottenham Hotspur FC vs Wolverhampton Wanderers FC (PL, 92.0%, 2-2, HIT)
2. Over 1.5: West Ham United FC vs Liverpool FC (PL, 87.2%, 0-5, HIT)
3. Over 1.5: Leicester City FC vs Manchester City FC (PL, 82.7%, 0-2, HIT)
4. Under 3.5: Everton FC vs Nottingham Forest FC (PL, 78.6%, 0-2, HIT)

### 2025-01-04 — **MISS** (fair combined odds 1.85)
1. Over 1.5: Aston Villa FC vs Leicester City FC (PL, 89.4%, 2-1, HIT)
2. Over 1.5: Tottenham Hotspur FC vs Newcastle United FC (PL, 89.4%, 1-2, HIT)
3. Over 1.5: Olympique Lyonnais vs Montpellier HSC (FL1, 86.5%, 1-0, MISS)
4. Under 3.5: Venezia FC vs Empoli FC (SA, 78.1%, 1-1, HIT)

### 2025-01-05 — **HIT** (fair combined odds 2.20)
1. Over 1.5: Angers SCO vs Stade Brestois 29 (FL1, 85.4%, 2-0, HIT)
2. Over 1.5: RC Strasbourg Alsace vs AJ Auxerre (FL1, 83.2%, 3-1, HIT)
3. Over 1.5: AS Roma vs SS Lazio (SA, 80.6%, 2-0, HIT)
4. Under 3.5: US Lecce vs Genoa CFC (SA, 79.3%, 0-0, HIT)

### 2025-01-11 — **MISS** (fair combined odds 1.70)
1. Over 1.5: Borussia Mönchengladbach vs FC Bayern München (BL1, 90.6%, 0-1, MISS)
2. Over 1.5: TSG 1899 Hoffenheim vs VfL Wolfsburg (BL1, 90.2%, 0-1, MISS)
3. Over 1.5: SC Freiburg vs Holstein Kiel (BL1, 88.3%, 3-2, HIT)
4. Under 3.5: Empoli FC vs US Lecce (SA, 81.5%, 1-3, MISS)

### 2025-01-12 — **MISS** (fair combined odds 1.87)
1. Over 1.5: Paris Saint-Germain FC vs AS Saint-Étienne (FL1, 95.6%, 2-1, HIT)
2. Over 1.5: Venezia FC vs FC Internazionale Milano (SA, 84.5%, 0-1, MISS)
3. Over 1.5: FC Augsburg vs VfB Stuttgart (BL1, 82.1%, 0-1, MISS)
4. Under 3.5: UD Las Palmas vs Getafe CF (PD, 80.8%, 1-2, HIT)

### 2025-01-18 — **HIT** (fair combined odds 1.83)
1. Over 1.5: Brentford FC vs Liverpool FC (PL, 91.5%, 0-2, HIT)
2. Over 1.5: FC Bayern München vs VfL Wolfsburg (BL1, 89.4%, 3-2, HIT)
3. Over 1.5: Bayer 04 Leverkusen vs Borussia Mönchengladbach (BL1, 89.2%, 3-1, HIT)
4. Under 3.5: CD Leganés vs Club Atlético de Madrid (PD, 75.1%, 1-0, HIT)

### 2025-01-19 — **HIT** (fair combined odds 1.93)
1. Over 1.5: Olympique de Marseille vs RC Strasbourg Alsace (FL1, 86.5%, 1-1, HIT)
2. Over 1.5: SV Werder Bremen vs FC Augsburg (BL1, 85.8%, 0-2, HIT)
3. Over 1.5: Angers SCO vs AJ Auxerre (FL1, 85.6%, 2-0, HIT)
4. Under 3.5: Valencia CF vs Real Sociedad de Fútbol (PD, 81.5%, 1-0, HIT)

### 2025-01-25 — **HIT** (fair combined odds 1.82)
1. Over 1.5: SC Freiburg vs FC Bayern München (BL1, 90.5%, 1-2, HIT)
2. Over 1.5: Borussia Dortmund vs SV Werder Bremen (BL1, 87.5%, 2-2, HIT)
3. Over 1.5: Paris Saint-Germain FC vs Stade de Reims (FL1, 86.9%, 1-1, HIT)
4. Under 3.5: RCD Mallorca vs Real Betis Balompié (PD, 80.0%, 0-1, HIT)

### 2025-01-26 — **HIT** (fair combined odds 1.76)
1. Over 1.5: Tottenham Hotspur FC vs Leicester City FC (PL, 92.5%, 1-2, HIT)
2. Over 1.5: TSG 1899 Hoffenheim vs Eintracht Frankfurt (BL1, 87.8%, 2-2, HIT)
3. Over 1.5: Aston Villa FC vs West Ham United FC (PL, 85.0%, 1-1, HIT)
4. Under 3.5: Real Sociedad de Fútbol vs Getafe CF (PD, 82.2%, 0-3, HIT)

### 2025-02-01 — **HIT** (fair combined odds 1.56)
1. Over 1.5: FC Bayern München vs Holstein Kiel (BL1, 96.1%, 4-3, HIT)
2. Over 1.5: Villarreal CF vs Real Valladolid CF (PD, 91.1%, 5-1, HIT)
3. Over 1.5: VfB Stuttgart vs Borussia Mönchengladbach (BL1, 88.2%, 1-2, HIT)
4. Under 3.5: Getafe CF vs Sevilla FC (PD, 82.9%, 0-0, HIT)

### 2025-02-02 — **MISS** (fair combined odds 1.64)
1. Over 1.5: FC Barcelona vs Deportivo Alavés (PD, 90.3%, 1-0, MISS)
2. Over 1.5: Brentford FC vs Tottenham Hotspur FC (PL, 90.0%, 0-2, HIT)
3. Over 1.5: Bayer 04 Leverkusen vs TSG 1899 Hoffenheim (BL1, 89.5%, 3-1, HIT)
4. Under 3.5: CA Osasuna vs Real Sociedad de Fútbol (PD, 83.7%, 2-1, HIT)

### 2025-02-08 — **MISS** (fair combined odds 1.89)
1. Over 1.5: VfL Wolfsburg vs Bayer 04 Leverkusen (BL1, 90.0%, 0-0, MISS)
2. Over 1.5: SC Freiburg vs 1. FC Heidenheim 1846 (BL1, 85.8%, 1-0, MISS)
3. Over 1.5: Borussia Dortmund vs VfB Stuttgart (BL1, 84.7%, 1-2, HIT)
4. Under 3.5: Torino FC vs Genoa CFC (SA, 80.8%, 1-1, HIT)

### 2025-02-09 — **HIT** (fair combined odds 1.93)
1. Over 1.5: Holstein Kiel vs VfL Bochum 1848 (BL1, 87.8%, 2-2, HIT)
2. Over 1.5: Angers SCO vs Olympique de Marseille (FL1, 85.9%, 0-2, HIT)
3. Over 1.5: Sevilla FC vs FC Barcelona (PD, 82.9%, 1-4, HIT)
4. Under 3.5: Deportivo Alavés vs Getafe CF (PD, 82.9%, 0-1, HIT)

### 2025-02-15 — **MISS** (fair combined odds 1.78)
1. Over 1.5: Olympique de Marseille vs AS Saint-Étienne (FL1, 90.2%, 5-1, HIT)
2. Over 1.5: Bayer 04 Leverkusen vs FC Bayern München (BL1, 89.7%, 0-0, MISS)
3. Over 1.5: VfB Stuttgart vs VfL Wolfsburg (BL1, 87.5%, 1-2, HIT)
4. Under 3.5: Crystal Palace FC vs Everton FC (PL, 79.2%, 1-2, HIT)

### 2025-02-16 — **HIT** (fair combined odds 1.72)
1. Over 1.5: Eintracht Frankfurt vs Holstein Kiel (BL1, 94.0%, 3-1, HIT)
2. Over 1.5: Liverpool FC vs Wolverhampton Wanderers FC (PL, 89.0%, 2-1, HIT)
3. Over 1.5: SV Werder Bremen vs TSG 1899 Hoffenheim (BL1, 84.4%, 1-3, HIT)
4. Under 3.5: Real Betis Balompié vs Real Sociedad de Fútbol (PD, 82.2%, 3-0, HIT)

### 2025-02-22 — **HIT** (fair combined odds 1.81)
1. Over 1.5: Holstein Kiel vs Bayer 04 Leverkusen (BL1, 92.5%, 0-2, HIT)
2. Over 1.5: VfL Wolfsburg vs VfL Bochum 1848 (BL1, 87.6%, 1-1, HIT)
3. Over 1.5: UD Las Palmas vs FC Barcelona (PD, 87.2%, 0-2, HIT)
4. Under 3.5: 1. FSV Mainz 05 vs FC St. Pauli 1910 (BL1, 78.3%, 2-0, HIT)

### 2025-02-23 — **HIT** (fair combined odds 1.83)
1. Over 1.5: FC Bayern München vs Eintracht Frankfurt (BL1, 88.1%, 4-0, HIT)
2. Over 1.5: TSG 1899 Hoffenheim vs VfB Stuttgart (BL1, 87.7%, 1-1, HIT)
3. Over 1.5: Olympique Lyonnais vs Paris Saint-Germain FC (FL1, 85.8%, 2-3, HIT)
4. Under 3.5: Getafe CF vs Real Betis Balompié (PD, 82.2%, 1-2, HIT)

### 2025-03-01 — **MISS** (fair combined odds 1.92)
1. Over 1.5: Girona FC vs RC Celta de Vigo (PD, 88.1%, 2-2, HIT)
2. Over 1.5: Atalanta BC vs Venezia FC (SA, 87.4%, 0-0, MISS)
3. Over 1.5: SV Werder Bremen vs VfL Wolfsburg (BL1, 85.7%, 1-2, HIT)
4. Under 3.5: Rayo Vallecano de Madrid vs Sevilla FC (PD, 78.9%, 1-1, HIT)

### 2025-03-02 — **MISS** (fair combined odds 2.11)
1. Over 1.5: Olympique de Marseille vs FC Nantes (FL1, 84.7%, 2-0, HIT)
2. Over 1.5: Olympique Lyonnais vs Stade Brestois 29 (FL1, 82.5%, 2-1, HIT)
3. Over 1.5: 1. FC Union Berlin vs Holstein Kiel (BL1, 82.4%, 0-1, MISS)
4. Under 3.5: CD Leganés vs Getafe CF (PD, 82.2%, 1-0, HIT)

### 2025-03-08 — **MISS** (fair combined odds 1.72)
1. Over 1.5: FC Bayern München vs VfL Bochum 1848 (BL1, 94.7%, 2-3, HIT)
2. Over 1.5: Bayer 04 Leverkusen vs SV Werder Bremen (BL1, 90.1%, 0-2, HIT)
3. Over 1.5: Holstein Kiel vs VfB Stuttgart (BL1, 88.2%, 2-2, HIT)
4. Under 3.5: US Lecce vs AC Milan (SA, 77.2%, 2-3, MISS)

### 2025-03-09 — **MISS** (fair combined odds 1.75)
1. Over 1.5: Chelsea FC vs Leicester City FC (PL, 89.6%, 1-0, MISS)
2. Over 1.5: TSG 1899 Hoffenheim vs 1. FC Heidenheim 1846 (BL1, 88.2%, 1-1, HIT)
3. Over 1.5: Tottenham Hotspur FC vs AFC Bournemouth (PL, 88.0%, 2-2, HIT)
4. Under 3.5: Getafe CF vs Club Atlético de Madrid (PD, 82.2%, 2-1, HIT)

### 2025-03-15 — **HIT** (fair combined odds 1.89)
1. Over 1.5: Villarreal CF vs Real Madrid CF (PD, 87.9%, 1-2, HIT)
2. Over 1.5: Manchester City FC vs Brighton & Hove Albion FC (PL, 86.2%, 2-2, HIT)
3. Over 1.5: Angers SCO vs AS Monaco FC (FL1, 86.0%, 0-2, HIT)
4. Under 3.5: RCD Mallorca vs RCD Espanyol de Barcelona (PD, 81.0%, 2-1, HIT)

### 2025-03-16 — **HIT** (fair combined odds 1.84)
1. Over 1.5: Paris Saint-Germain FC vs Olympique de Marseille (FL1, 88.1%, 3-1, HIT)
2. Over 1.5: 1. FC Heidenheim 1846 vs Holstein Kiel (BL1, 87.1%, 3-1, HIT)
3. Over 1.5: VfB Stuttgart vs Bayer 04 Leverkusen (BL1, 85.4%, 3-4, HIT)
4. Under 3.5: CA Osasuna vs Getafe CF (PD, 82.9%, 1-2, HIT)

### 2025-03-29 — **MISS** (fair combined odds 1.82)
1. Over 1.5: Holstein Kiel vs SV Werder Bremen (BL1, 90.5%, 0-3, HIT)
2. Over 1.5: AS Saint-Étienne vs Paris Saint-Germain FC (FL1, 89.3%, 1-6, HIT)
3. Over 1.5: Eintracht Frankfurt vs VfB Stuttgart (BL1, 86.2%, 1-0, MISS)
4. Under 3.5: RCD Espanyol de Barcelona vs Club Atlético de Madrid (PD, 78.9%, 1-1, HIT)

### 2025-03-30 — **HIT** (fair combined odds 2.18)
1. Over 1.5: FC Barcelona vs Girona FC (PD, 85.9%, 4-1, HIT)
2. Over 1.5: Borussia Dortmund vs 1. FSV Mainz 05 (BL1, 82.5%, 3-1, HIT)
3. Over 1.5: FC Internazionale Milano vs Udinese Calcio (SA, 82.1%, 2-1, HIT)
4. Under 3.5: Getafe CF vs Villarreal CF (PD, 79.0%, 1-2, HIT)

### 2025-04-06 — **MISS** (fair combined odds 1.94)
1. Over 1.5: Brentford FC vs Chelsea FC (PL, 87.6%, 0-0, MISS)
2. Over 1.5: Tottenham Hotspur FC vs Southampton FC (PL, 85.4%, 3-1, HIT)
3. Over 1.5: Atalanta BC vs SS Lazio (SA, 84.6%, 0-1, MISS)
4. Under 3.5: Real Valladolid CF vs Getafe CF (PD, 81.5%, 0-4, MISS)

### 2025-04-12 — **MISS** (fair combined odds 1.77)
1. Over 1.5: FC Bayern München vs Borussia Dortmund (BL1, 90.4%, 2-2, HIT)
2. Over 1.5: CD Leganés vs FC Barcelona (PD, 89.3%, 0-1, MISS)
3. Over 1.5: AS Monaco FC vs Olympique de Marseille (FL1, 86.1%, 3-0, HIT)
4. Under 3.5: Real Sociedad de Fútbol vs RCD Mallorca (PD, 81.5%, 0-2, HIT)

### 2025-04-13 — **MISS** (fair combined odds 1.93)
1. Over 1.5: VfB Stuttgart vs SV Werder Bremen (BL1, 90.2%, 1-2, HIT)
2. Over 1.5: Eintracht Frankfurt vs 1. FC Heidenheim 1846 (BL1, 86.4%, 3-0, HIT)
3. Over 1.5: Chelsea FC vs Ipswich Town FC (PL, 83.4%, 2-2, HIT)
4. Under 3.5: Athletic Club vs Rayo Vallecano de Madrid (PD, 79.9%, 3-1, MISS)

### 2025-04-19 — **HIT** (fair combined odds 1.69)
1. Over 1.5: Paris Saint-Germain FC vs Le Havre AC (FL1, 90.9%, 2-1, HIT)
2. Over 1.5: FC Barcelona vs RC Celta de Vigo (PD, 90.6%, 4-3, HIT)
3. Over 1.5: RB Leipzig vs Holstein Kiel (BL1, 89.6%, 1-1, HIT)
4. Under 3.5: RCD Mallorca vs CD Leganés (PD, 80.1%, 0-0, HIT)

### 2025-04-20 — **MISS** (fair combined odds 1.84)
1. Over 1.5: Leicester City FC vs Liverpool FC (PL, 87.8%, 0-1, MISS)
2. Over 1.5: AS Saint-Étienne vs Olympique Lyonnais (FL1, 87.8%, 2-1, HIT)
3. Over 1.5: Borussia Dortmund vs Borussia Mönchengladbach (BL1, 87.4%, 3-2, HIT)
4. Under 3.5: Empoli FC vs Venezia FC (SA, 80.8%, 2-2, MISS)

### 2025-04-27 — **MISS** (fair combined odds 2.13)
1. Over 1.5: Olympique de Marseille vs Stade Brestois 29 (FL1, 86.4%, 4-1, HIT)
2. Over 1.5: Villarreal CF vs RCD Espanyol de Barcelona (PD, 82.7%, 1-0, MISS)
3. Over 1.5: Liverpool FC vs Tottenham Hotspur FC (PL, 82.0%, 5-1, HIT)
4. Under 3.5: SSC Napoli vs Torino FC (SA, 80.1%, 2-0, HIT)

### 2025-05-03 — **HIT** (fair combined odds 1.85)
1. Over 1.5: Real Valladolid CF vs FC Barcelona (PD, 92.0%, 1-2, HIT)
2. Over 1.5: AS Saint-Étienne vs AS Monaco FC (FL1, 86.8%, 1-3, HIT)
3. Over 1.5: Borussia Dortmund vs VfL Wolfsburg (BL1, 86.0%, 4-0, HIT)
4. Under 3.5: US Lecce vs SSC Napoli (SA, 78.6%, 0-1, HIT)

### 2025-05-04 — **HIT** (fair combined odds 1.94)
1. Over 1.5: Real Madrid CF vs RC Celta de Vigo (PD, 89.1%, 3-2, HIT)
2. Over 1.5: West Ham United FC vs Tottenham Hotspur FC (PL, 84.3%, 1-1, HIT)
3. Over 1.5: SC Freiburg vs Bayer 04 Leverkusen (BL1, 83.6%, 2-2, HIT)
4. Under 3.5: Real Sociedad de Fútbol vs Athletic Club (PD, 82.2%, 0-0, HIT)

### 2025-05-10 — **MISS** (fair combined odds 1.63)
1. Over 1.5: FC Bayern München vs Borussia Mönchengladbach (BL1, 93.5%, 2-0, HIT)
2. Over 1.5: Montpellier HSC vs Paris Saint-Germain FC (FL1, 92.9%, 1-4, HIT)
3. Over 1.5: Southampton FC vs Manchester City FC (PL, 86.6%, 0-0, MISS)
4. Under 3.5: Valencia CF vs Getafe CF (PD, 81.5%, 3-0, HIT)

### 2025-05-11 — **MISS** (fair combined odds 2.08)
1. Over 1.5: Bayer 04 Leverkusen vs Borussia Dortmund (BL1, 85.0%, 2-4, HIT)
2. Over 1.5: Newcastle United FC vs Chelsea FC (PL, 84.0%, 2-0, HIT)
3. Over 1.5: VfB Stuttgart vs FC Augsburg (BL1, 83.3%, 4-0, HIT)
4. Under 3.5: SSC Napoli vs Genoa CFC (SA, 80.8%, 2-2, MISS)

### 2025-05-17 — **HIT** (fair combined odds 1.60)
1. Over 1.5: Borussia Dortmund vs Holstein Kiel (BL1, 93.2%, 3-0, HIT)
2. Over 1.5: TSG 1899 Hoffenheim vs FC Bayern München (BL1, 93.0%, 0-4, HIT)
3. Over 1.5: Paris Saint-Germain FC vs AJ Auxerre (FL1, 91.3%, 3-1, HIT)
4. Under 3.5: FC St. Pauli 1910 vs VfL Bochum 1848 (BL1, 78.8%, 0-2, HIT)

### 2025-05-18 — **HIT** (fair combined odds 2.12)
1. Over 1.5: FC Barcelona vs Villarreal CF (PD, 88.8%, 2-3, HIT)
2. Over 1.5: Brentford FC vs Fulham FC (PL, 82.6%, 2-3, HIT)
3. Over 1.5: FC Internazionale Milano vs SS Lazio (SA, 80.5%, 2-2, HIT)
4. Under 3.5: Cagliari Calcio vs Venezia FC (SA, 80.1%, 3-0, HIT)

### 2025-05-25 — **HIT** (fair combined odds 1.99)
1. Over 1.5: Tottenham Hotspur FC vs Brighton & Hove Albion FC (PL, 88.8%, 1-4, HIT)
2. Over 1.5: Villarreal CF vs Sevilla FC (PD, 86.1%, 4-2, HIT)
3. Over 1.5: Southampton FC vs Arsenal FC (PL, 84.3%, 1-2, HIT)
4. Under 3.5: Torino FC vs AS Roma (SA, 78.0%, 0-2, HIT)

### 2025-09-27 — **MISS** (fair combined odds 2.00)
1. Over 1.5: Paris Saint-Germain FC vs AJ Auxerre (FL1, 87.4%, 2-0, HIT)
2. Over 1.5: FC Lorient vs AS Monaco FC (FL1, 86.8%, 3-1, HIT)
3. Over 1.5: Tottenham Hotspur FC vs Wolverhampton Wanderers FC (PL, 85.3%, 1-1, HIT)
4. Under 3.5: Leeds United FC vs AFC Bournemouth (PL, 77.2%, 2-2, MISS)

### 2025-09-28 — **MISS** (fair combined odds 2.00)
1. Over 1.5: SC Freiburg vs TSG 1899 Hoffenheim (BL1, 87.0%, 1-1, HIT)
2. Over 1.5: OGC Nice vs Paris FC (FL1, 86.1%, 1-1, HIT)
3. Over 1.5: FC Barcelona vs Real Sociedad de Fútbol (PD, 84.3%, 2-1, HIT)
4. Under 3.5: Aston Villa FC vs Fulham FC (PL, 79.3%, 3-1, MISS)

### 2025-10-04 — **MISS** (fair combined odds 1.97)
1. Over 1.5: Eintracht Frankfurt vs FC Bayern München (BL1, 93.2%, 0-3, HIT)
2. Over 1.5: Bayer 04 Leverkusen vs 1. FC Union Berlin (BL1, 83.8%, 2-0, HIT)
3. Over 1.5: Borussia Dortmund vs RB Leipzig (BL1, 82.0%, 1-1, HIT)
4. Under 3.5: SS Lazio vs Torino FC (SA, 79.5%, 3-3, MISS)

### 2025-10-05 — **HIT** (fair combined odds 1.96)
1. Over 1.5: AS Monaco FC vs OGC Nice (FL1, 88.2%, 2-2, HIT)
2. Over 1.5: Wolverhampton Wanderers FC vs Brighton & Hove Albion FC (PL, 86.1%, 1-1, HIT)
3. Over 1.5: Sevilla FC vs FC Barcelona (PD, 85.4%, 4-1, HIT)
4. Under 3.5: Udinese Calcio vs Cagliari Calcio (SA, 78.6%, 1-1, HIT)

### 2025-10-18 — **HIT** (fair combined odds 1.83)
1. Over 1.5: FC Bayern München vs Borussia Dortmund (BL1, 90.5%, 2-1, HIT)
2. Over 1.5: FC Barcelona vs Girona FC (PD, 90.0%, 2-1, HIT)
3. Over 1.5: Olympique de Marseille vs Le Havre AC (FL1, 87.5%, 6-2, HIT)
4. Under 3.5: AC Pisa 1909 vs Hellas Verona FC (SA, 76.5%, 0-0, HIT)

### 2025-10-19 — **HIT** (fair combined odds 2.09)
1. Over 1.5: FC Lorient vs Stade Brestois 29 (FL1, 89.0%, 3-3, HIT)
2. Over 1.5: SC Freiburg vs Eintracht Frankfurt (BL1, 87.0%, 2-2, HIT)
3. Over 1.5: Toulouse FC vs FC Metz (FL1, 81.4%, 4-0, HIT)
4. Under 3.5: AC Milan vs ACF Fiorentina (SA, 75.8%, 2-1, HIT)

### 2025-10-25 — **HIT** (fair combined odds 1.94)
1. Over 1.5: Borussia Mönchengladbach vs FC Bayern München (BL1, 89.4%, 0-3, HIT)
2. Over 1.5: Stade Brestois 29 vs Paris Saint-Germain FC (FL1, 86.8%, 0-3, HIT)
3. Over 1.5: Brentford FC vs Liverpool FC (PL, 86.8%, 3-2, HIT)
4. Under 3.5: US Cremonese vs Atalanta BC (SA, 76.5%, 1-1, HIT)

### 2025-10-26 — **MISS** (fair combined odds 2.12)
1. Over 1.5: Real Madrid CF vs FC Barcelona (PD, 86.8%, 2-1, HIT)
2. Over 1.5: Lille OSC vs FC Metz (FL1, 83.5%, 6-1, HIT)
3. Over 1.5: Olympique Lyonnais vs RC Strasbourg Alsace (FL1, 82.7%, 2-1, HIT)
4. Under 3.5: CA Osasuna vs RC Celta de Vigo (PD, 78.6%, 2-3, MISS)

### 2025-10-29 — **MISS** (fair combined odds 1.84)
1. Over 1.5: FC Lorient vs Paris Saint-Germain FC (FL1, 92.4%, 1-1, HIT)
2. Over 1.5: Le Havre AC vs Stade Brestois 29 (FL1, 87.8%, 1-0, MISS)
3. Over 1.5: Paris FC vs Olympique Lyonnais (FL1, 85.0%, 3-3, HIT)
4. Under 3.5: Juventus FC vs Udinese Calcio (SA, 78.6%, 3-1, MISS)

### 2025-11-01 — **MISS** (fair combined odds 1.80)
1. Over 1.5: AS Monaco FC vs Paris FC (FL1, 90.3%, 0-1, MISS)
2. Over 1.5: FC Bayern München vs Bayer 04 Leverkusen (BL1, 90.0%, 3-0, HIT)
3. Over 1.5: Paris Saint-Germain FC vs OGC Nice (FL1, 87.5%, 1-0, MISS)
4. Under 3.5: Udinese Calcio vs Atalanta BC (SA, 78.3%, 1-0, HIT)

### 2025-11-02 — **MISS** (fair combined odds 2.04)
1. Over 1.5: Levante UD vs RC Celta de Vigo (PD, 87.7%, 1-2, HIT)
2. Over 1.5: VfL Wolfsburg vs TSG 1899 Hoffenheim (BL1, 85.5%, 2-3, HIT)
3. Over 1.5: Stade Brestois 29 vs Olympique Lyonnais (FL1, 84.1%, 0-0, MISS)
4. Under 3.5: Deportivo Alavés vs RCD Espanyol de Barcelona (PD, 77.8%, 2-1, HIT)

### 2025-11-08 — **MISS** (fair combined odds 1.89)
1. Over 1.5: Olympique de Marseille vs Stade Brestois 29 (FL1, 91.6%, 3-0, HIT)
2. Over 1.5: 1. FC Union Berlin vs FC Bayern München (BL1, 86.3%, 2-2, HIT)
3. Over 1.5: TSG 1899 Hoffenheim vs RB Leipzig (BL1, 84.4%, 3-1, HIT)
4. Under 3.5: Sunderland AFC vs Arsenal FC (PL, 79.4%, 2-2, MISS)

### 2025-11-09 — **MISS** (fair combined odds 2.01)
1. Over 1.5: Eintracht Frankfurt vs 1. FSV Mainz 05 (BL1, 89.0%, 1-0, MISS)
2. Over 1.5: RC Celta de Vigo vs FC Barcelona (PD, 84.9%, 2-4, HIT)
3. Over 1.5: Manchester City FC vs Liverpool FC (PL, 84.5%, 3-0, HIT)
4. Under 3.5: Bologna FC 1909 vs SSC Napoli (SA, 78.0%, 2-0, HIT)

### 2025-11-22 — **MISS** (fair combined odds 1.99)
1. Over 1.5: VfL Wolfsburg vs Bayer 04 Leverkusen (BL1, 89.3%, 1-3, HIT)
2. Over 1.5: Paris Saint-Germain FC vs Le Havre AC (FL1, 84.7%, 3-0, HIT)
3. Over 1.5: FC Bayern München vs SC Freiburg (BL1, 84.7%, 6-2, HIT)
4. Under 3.5: CA Osasuna vs Real Sociedad de Fútbol (PD, 78.5%, 1-3, MISS)

### 2025-11-23 — **HIT** (fair combined odds 2.21)
1. Over 1.5: RB Leipzig vs SV Werder Bremen (BL1, 86.2%, 2-0, HIT)
2. Over 1.5: Stade Brestois 29 vs FC Metz (FL1, 84.0%, 3-2, HIT)
3. Over 1.5: Lille OSC vs Paris FC (FL1, 81.6%, 4-2, HIT)
4. Under 3.5: Real Oviedo vs Rayo Vallecano de Madrid (PD, 76.5%, 0-0, HIT)

### 2025-11-29 — **MISS** (fair combined odds 1.89)
1. Over 1.5: AS Monaco FC vs Paris Saint-Germain FC (FL1, 88.6%, 1-0, MISS)
2. Over 1.5: Brentford FC vs Burnley FC (PL, 88.3%, 3-1, HIT)
3. Over 1.5: TSG 1899 Hoffenheim vs FC Augsburg (BL1, 86.0%, 3-0, HIT)
4. Under 3.5: Juventus FC vs Cagliari Calcio (SA, 78.6%, 2-1, HIT)

### 2025-11-30 — **HIT** (fair combined odds 1.90)
1. Over 1.5: FC Lorient vs OGC Nice (FL1, 88.0%, 3-1, HIT)
2. Over 1.5: Eintracht Frankfurt vs VfL Wolfsburg (BL1, 87.2%, 1-1, HIT)
3. Over 1.5: West Ham United FC vs Liverpool FC (PL, 87.0%, 0-2, HIT)
4. Under 3.5: Atalanta BC vs ACF Fiorentina (SA, 78.6%, 2-0, HIT)

### 2025-12-06 — **MISS** (fair combined odds 1.98)
1. Over 1.5: FC Augsburg vs Bayer 04 Leverkusen (BL1, 87.3%, 2-0, HIT)
2. Over 1.5: VfB Stuttgart vs FC Bayern München (BL1, 87.1%, 0-5, HIT)
3. Over 1.5: RB Leipzig vs Eintracht Frankfurt (BL1, 86.9%, 6-0, HIT)
4. Under 3.5: US Sassuolo Calcio vs ACF Fiorentina (SA, 76.5%, 3-1, MISS)

### 2025-12-07 — **MISS** (fair combined odds 2.06)
1. Over 1.5: Borussia Dortmund vs TSG 1899 Hoffenheim (BL1, 85.3%, 2-0, HIT)
2. Over 1.5: FC Lorient vs Olympique Lyonnais (FL1, 85.3%, 1-0, MISS)
3. Over 1.5: Real Madrid CF vs RC Celta de Vigo (PD, 84.0%, 0-2, HIT)
4. Under 3.5: SSC Napoli vs Juventus FC (SA, 79.4%, 2-1, HIT)

### 2025-12-13 — **MISS** (fair combined odds 2.06)
1. Over 1.5: Eintracht Frankfurt vs FC Augsburg (BL1, 87.9%, 1-0, MISS)
2. Over 1.5: Stade Rennais FC 1901 vs Stade Brestois 29 (FL1, 84.7%, 3-1, HIT)
3. Over 1.5: FC Barcelona vs CA Osasuna (PD, 84.4%, 2-0, HIT)
4. Under 3.5: Getafe CF vs RCD Espanyol de Barcelona (PD, 77.2%, 0-1, HIT)

### 2025-12-14 — **MISS** (fair combined odds 1.79)
1. Over 1.5: FC Bayern München vs 1. FSV Mainz 05 (BL1, 90.9%, 2-2, HIT)
2. Over 1.5: Olympique de Marseille vs AS Monaco FC (FL1, 90.7%, 1-0, MISS)
3. Over 1.5: Brentford FC vs Leeds United FC (PL, 87.0%, 1-1, HIT)
4. Under 3.5: Bologna FC 1909 vs Juventus FC (SA, 78.0%, 0-1, HIT)

### 2025-12-20 — **MISS** (fair combined odds 2.04)
1. Over 1.5: VfB Stuttgart vs TSG 1899 Hoffenheim (BL1, 86.3%, 0-0, MISS)
2. Over 1.5: RB Leipzig vs Bayer 04 Leverkusen (BL1, 86.1%, 1-3, HIT)
3. Over 1.5: Hamburger SV vs Eintracht Frankfurt (BL1, 85.6%, 1-1, HIT)
4. Under 3.5: Real Oviedo vs RC Celta de Vigo (PD, 77.2%, 0-0, HIT)

### 2026-01-03 — **HIT** (fair combined odds 2.09)
1. Over 1.5: Lille OSC vs Stade Rennais FC 1901 (FL1, 84.9%, 0-2, HIT)
2. Over 1.5: RCD Espanyol de Barcelona vs FC Barcelona (PD, 84.9%, 0-2, HIT)
3. Over 1.5: Brighton & Hove Albion FC vs Burnley FC (PL, 84.3%, 2-0, HIT)
4. Under 3.5: Genoa CFC vs AC Pisa 1909 (SA, 78.6%, 1-1, HIT)

### 2026-01-04 — **HIT** (fair combined odds 1.91)
1. Over 1.5: FC Lorient vs FC Metz (FL1, 89.0%, 1-1, HIT)
2. Over 1.5: Olympique de Marseille vs FC Nantes (FL1, 86.8%, 0-2, HIT)
3. Over 1.5: Paris Saint-Germain FC vs Paris FC (FL1, 86.8%, 2-1, HIT)
4. Under 3.5: Le Havre AC vs Angers SCO (FL1, 78.0%, 2-1, HIT)

### 2026-01-17 — **MISS** (fair combined odds 1.97)
1. Over 1.5: TSG 1899 Hoffenheim vs Bayer 04 Leverkusen (BL1, 91.1%, 1-0, MISS)
2. Over 1.5: RB Leipzig vs FC Bayern München (BL1, 86.6%, 1-5, HIT)
3. Over 1.5: VfL Wolfsburg vs 1. FC Heidenheim 1846 (BL1, 85.0%, 1-1, HIT)
4. Under 3.5: SSC Napoli vs US Sassuolo Calcio (SA, 75.8%, 1-0, HIT)

### 2026-01-18 — **HIT** (fair combined odds 2.05)
1. Over 1.5: Real Sociedad de Fútbol vs FC Barcelona (PD, 87.9%, 2-1, HIT)
2. Over 1.5: RC Strasbourg Alsace vs FC Metz (FL1, 85.1%, 2-1, HIT)
3. Over 1.5: Olympique Lyonnais vs Stade Brestois 29 (FL1, 83.8%, 2-1, HIT)
4. Under 3.5: RC Celta de Vigo vs Rayo Vallecano de Madrid (PD, 78.0%, 3-0, HIT)

### 2026-01-24 — **MISS** (fair combined odds 1.84)
1. Over 1.5: FC Bayern München vs FC Augsburg (BL1, 94.4%, 1-2, HIT)
2. Over 1.5: Eintracht Frankfurt vs TSG 1899 Hoffenheim (BL1, 87.9%, 1-3, HIT)
3. Over 1.5: Bayer 04 Leverkusen vs SV Werder Bremen (BL1, 87.0%, 1-0, MISS)
4. Under 3.5: Valencia CF vs RCD Espanyol de Barcelona (PD, 75.1%, 3-2, MISS)

### 2026-01-25 — **HIT** (fair combined odds 2.08)
1. Over 1.5: FC Barcelona vs Real Oviedo (PD, 90.2%, 3-0, HIT)
2. Over 1.5: Borussia Mönchengladbach vs VfB Stuttgart (BL1, 84.9%, 0-3, HIT)
3. Over 1.5: Lille OSC vs RC Strasbourg Alsace (FL1, 80.5%, 1-4, HIT)
4. Under 3.5: US Sassuolo Calcio vs US Cremonese (SA, 78.0%, 1-0, HIT)

### 2026-01-31 — **HIT** (fair combined odds 1.87)
1. Over 1.5: Eintracht Frankfurt vs Bayer 04 Leverkusen (BL1, 90.7%, 1-3, HIT)
2. Over 1.5: AS Monaco FC vs Stade Rennais FC 1901 (FL1, 87.0%, 4-0, HIT)
3. Over 1.5: Wolverhampton Wanderers FC vs AFC Bournemouth (PL, 86.2%, 0-2, HIT)
4. Under 3.5: Real Oviedo vs Girona FC (PD, 78.6%, 1-0, HIT)

### 2026-02-01 — **MISS** (fair combined odds 2.22)
1. Over 1.5: Borussia Dortmund vs 1. FC Heidenheim 1846 (BL1, 84.7%, 3-2, HIT)
2. Over 1.5: OGC Nice vs Stade Brestois 29 (FL1, 83.7%, 2-2, HIT)
3. Over 1.5: Angers SCO vs FC Metz (FL1, 82.3%, 1-0, MISS)
4. Under 3.5: Como 1907 vs Atalanta BC (SA, 77.2%, 0-0, HIT)

### 2026-02-07 — **HIT** (fair combined odds 2.02)
1. Over 1.5: FC Barcelona vs RCD Mallorca (PD, 88.0%, 3-0, HIT)
2. Over 1.5: VfL Wolfsburg vs Borussia Dortmund (BL1, 86.6%, 1-2, HIT)
3. Over 1.5: Borussia Mönchengladbach vs Bayer 04 Leverkusen (BL1, 86.3%, 1-1, HIT)
4. Under 3.5: Arsenal FC vs Sunderland AFC (PL, 75.3%, 3-0, HIT)

### 2026-02-08 — **MISS** (fair combined odds 2.07)
1. Over 1.5: FC Bayern München vs TSG 1899 Hoffenheim (BL1, 90.8%, 5-1, HIT)
2. Over 1.5: Paris Saint-Germain FC vs Olympique de Marseille (FL1, 82.5%, 5-0, HIT)
3. Over 1.5: OGC Nice vs AS Monaco FC (FL1, 81.7%, 0-0, MISS)
4. Under 3.5: Bologna FC 1909 vs Parma Calcio 1913 (SA, 78.9%, 0-1, HIT)

### 2026-02-21 — **MISS** (fair combined odds 1.68)
1. Over 1.5: FC Bayern München vs Eintracht Frankfurt (BL1, 96.7%, 3-2, HIT)
2. Over 1.5: Paris Saint-Germain FC vs FC Metz (FL1, 92.3%, 3-0, HIT)
3. Over 1.5: West Ham United FC vs AFC Bournemouth (PL, 88.7%, 0-0, MISS)
4. Under 3.5: Cagliari Calcio vs SS Lazio (SA, 75.1%, 0-0, HIT)

### 2026-02-22 — **HIT** (fair combined odds 1.95)
1. Over 1.5: FC Barcelona vs Levante UD (PD, 90.0%, 3-0, HIT)
2. Over 1.5: 1. FC Heidenheim 1846 vs VfB Stuttgart (BL1, 85.1%, 3-3, HIT)
3. Over 1.5: Villarreal CF vs Valencia CF (PD, 84.7%, 2-1, HIT)
4. Under 3.5: Atalanta BC vs SSC Napoli (SA, 79.1%, 2-1, HIT)

### 2026-02-28 — **HIT** (fair combined odds 2.09)
1. Over 1.5: FC Barcelona vs Villarreal CF (PD, 86.2%, 4-1, HIT)
2. Over 1.5: FC Internazionale Milano vs Genoa CFC (SA, 85.8%, 2-0, HIT)
3. Over 1.5: Borussia Dortmund vs FC Bayern München (BL1, 85.7%, 2-3, HIT)
4. Under 3.5: Hellas Verona FC vs SSC Napoli (SA, 75.3%, 1-2, HIT)

### 2026-03-01 — **MISS** (fair combined odds 1.99)
1. Over 1.5: Olympique de Marseille vs Olympique Lyonnais (FL1, 86.2%, 3-2, HIT)
2. Over 1.5: Paris FC vs OGC Nice (FL1, 86.0%, 1-0, MISS)
3. Over 1.5: Eintracht Frankfurt vs SC Freiburg (BL1, 85.7%, 2-0, HIT)
4. Under 3.5: Torino FC vs SS Lazio (SA, 79.1%, 2-0, HIT)

### 2026-03-08 — **HIT** (fair combined odds 2.09)
1. Over 1.5: Villarreal CF vs Elche CF (PD, 86.5%, 2-1, HIT)
2. Over 1.5: Racing Club de Lens vs FC Metz (FL1, 83.8%, 3-0, HIT)
3. Over 1.5: OGC Nice vs Stade Rennais FC 1901 (FL1, 83.6%, 0-4, HIT)
4. Under 3.5: Genoa CFC vs AS Roma (SA, 79.1%, 2-1, HIT)

### 2026-03-14 — **HIT** (fair combined odds 1.89)
1. Over 1.5: TSG 1899 Hoffenheim vs VfL Wolfsburg (BL1, 88.2%, 1-1, HIT)
2. Over 1.5: Bayer 04 Leverkusen vs FC Bayern München (BL1, 87.5%, 1-1, HIT)
3. Over 1.5: AS Monaco FC vs Stade Brestois 29 (FL1, 87.0%, 2-0, HIT)
4. Under 3.5: SSC Napoli vs US Lecce (SA, 78.5%, 2-1, HIT)

### 2026-03-21 — **MISS** (fair combined odds 1.84)
1. Over 1.5: FC Bayern München vs 1. FC Union Berlin (BL1, 91.5%, 4-0, HIT)
2. Over 1.5: 1. FC Heidenheim 1846 vs Bayer 04 Leverkusen (BL1, 87.4%, 3-3, HIT)
3. Over 1.5: VfL Wolfsburg vs SV Werder Bremen (BL1, 85.5%, 0-1, MISS)
4. Under 3.5: RCD Espanyol de Barcelona vs Getafe CF (PD, 79.4%, 1-2, HIT)

### 2026-03-22 — **MISS** (fair combined odds 2.03)
1. Over 1.5: Stade Rennais FC 1901 vs FC Metz (FL1, 87.0%, 0-0, MISS)
2. Over 1.5: FC Barcelona vs Rayo Vallecano de Madrid (PD, 85.5%, 1-0, MISS)
3. Over 1.5: Olympique de Marseille vs Lille OSC (FL1, 85.0%, 1-2, HIT)
4. Under 3.5: Paris FC vs Le Havre AC (FL1, 78.0%, 3-2, MISS)

### 2026-04-04 — **HIT** (fair combined odds 2.08)
1. Over 1.5: SC Freiburg vs FC Bayern München (BL1, 89.1%, 2-3, HIT)
2. Over 1.5: Bayer 04 Leverkusen vs VfL Wolfsburg (BL1, 85.0%, 6-3, HIT)
3. Over 1.5: Club Atlético de Madrid vs FC Barcelona (PD, 84.4%, 1-2, HIT)
4. Under 3.5: Hellas Verona FC vs ACF Fiorentina (SA, 75.1%, 0-1, HIT)

### 2026-04-11 — **MISS** (fair combined odds 1.83)
1. Over 1.5: VfL Wolfsburg vs Eintracht Frankfurt (BL1, 91.0%, 1-2, HIT)
2. Over 1.5: FC Barcelona vs RCD Espanyol de Barcelona (PD, 88.7%, 4-1, HIT)
3. Over 1.5: Borussia Dortmund vs Bayer 04 Leverkusen (BL1, 86.1%, 0-1, MISS)
4. Under 3.5: AJ Auxerre vs FC Nantes (FL1, 78.6%, 0-0, HIT)

### 2026-04-19 — **MISS** (fair combined odds 2.02)
1. Over 1.5: FC Bayern München vs VfB Stuttgart (BL1, 94.2%, 4-2, HIT)
2. Over 1.5: RC Strasbourg Alsace vs Stade Rennais FC 1901 (FL1, 82.6%, 0-3, HIT)
3. Over 1.5: SC Freiburg vs 1. FC Heidenheim 1846 (BL1, 80.9%, 2-1, HIT)
4. Under 3.5: Aston Villa FC vs Sunderland AFC (PL, 78.8%, 4-3, MISS)

### 2026-04-25 — **HIT** (fair combined odds 2.07)
1. Over 1.5: 1. FC Köln vs Bayer 04 Leverkusen (BL1, 85.7%, 1-2, HIT)
2. Over 1.5: FC Augsburg vs Eintracht Frankfurt (BL1, 85.7%, 1-1, HIT)
3. Over 1.5: 1. FSV Mainz 05 vs FC Bayern München (BL1, 84.5%, 3-4, HIT)
4. Under 3.5: Bologna FC 1909 vs AS Roma (SA, 78.0%, 0-2, HIT)

### 2026-04-26 — **MISS** (fair combined odds 2.12)
1. Over 1.5: Olympique de Marseille vs OGC Nice (FL1, 89.6%, 1-1, HIT)
2. Over 1.5: FC Lorient vs RC Strasbourg Alsace (FL1, 84.0%, 2-3, HIT)
3. Over 1.5: Paris FC vs Lille OSC (FL1, 82.8%, 0-1, MISS)
4. Under 3.5: AC Milan vs Juventus FC (SA, 75.8%, 0-0, HIT)

### 2026-05-02 — **HIT** (fair combined odds 1.81)
1. Over 1.5: FC Bayern München vs 1. FC Heidenheim 1846 (BL1, 95.4%, 3-3, HIT)
2. Over 1.5: TSG 1899 Hoffenheim vs VfB Stuttgart (BL1, 89.8%, 3-3, HIT)
3. Over 1.5: CA Osasuna vs FC Barcelona (PD, 85.2%, 1-2, HIT)
4. Under 3.5: Atalanta BC vs Genoa CFC (SA, 75.8%, 0-0, HIT)

### 2026-05-03 — **HIT** (fair combined odds 2.18)
1. Over 1.5: SC Freiburg vs VfL Wolfsburg (BL1, 85.5%, 1-1, HIT)
2. Over 1.5: Olympique Lyonnais vs Stade Rennais FC 1901 (FL1, 82.6%, 4-2, HIT)
3. Over 1.5: Paris FC vs Stade Brestois 29 (FL1, 82.5%, 4-0, HIT)
4. Under 3.5: US Sassuolo Calcio vs AC Milan (SA, 78.6%, 2-0, HIT)

### 2026-05-10 — **MISS** (fair combined odds 2.10)
1. Over 1.5: Paris Saint-Germain FC vs Stade Brestois 29 (FL1, 88.9%, 1-0, MISS)
2. Over 1.5: FC Barcelona vs Real Madrid CF (PD, 82.1%, 2-0, HIT)
3. Over 1.5: AS Monaco FC vs Lille OSC (FL1, 81.8%, 0-1, MISS)
4. Under 3.5: US Cremonese vs AC Pisa 1909 (SA, 79.7%, 3-0, HIT)

### 2026-05-17 — **HIT** (fair combined odds 1.81)
1. Over 1.5: Olympique de Marseille vs Stade Rennais FC 1901 (FL1, 91.0%, 3-1, HIT)
2. Over 1.5: FC Internazionale Milano vs Hellas Verona FC (SA, 87.7%, 1-1, HIT)
3. Over 1.5: FC Barcelona vs Real Betis Balompié (PD, 86.6%, 3-1, HIT)
4. Under 3.5: Como 1907 vs Parma Calcio 1913 (SA, 79.8%, 1-0, HIT)
