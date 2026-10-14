#!/usr/bin/env python3
"""
Barbadox Core 2 - Under 3.5 goals - walk-forward calibration check.

What it does
  1. Pulls finished matches from football-data.org (v4) for each league/season.
  2. Walks forward through matches in date order. Every prediction uses ONLY
     matches played on earlier dates in the SAME season.
  3. Model: shrunk attack/defence Poisson.
     P(Under 3.5) = P(total goals <= 3).
     K is tuned only on seasons BEFORE the one being tested.
  4. Anti-overconfidence layers:
       a) Season-level baseline.
       b) Calibration fitted on earlier matches.
       c) Safety haircut based on earlier similar predictions.
       d) Minimum-history requirements.
  5. Reports qualified matches, calibration, threshold sweeps, Brier scores,
     baseline Brier scores, Brier skill, per-league statistics, and CSV output.

Environment variables:
  FOOTBALL_DATA_API_KEY   API token; also reads FOOTBALL_DATA_TOKEN,
                          FOOTBALL_API_KEY, API_KEY
  LEAGUES                 Default: PL,PD,FL1,BL1,SA
  TEST_SEASONS            Default: 2024,2025,2026
  WARMUP_SEASONS          Default: 2023
  THRESHOLD               Default: 0.75
  SAFETY_Z                Default: 1.0; 0 disables the haircut
  UPCOMING_DAYS           Default: 7; 0 disables upcoming fixtures
  REPORT_DIR              Default: reports
"""

import csv
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.football-data.org/v4"

LEAGUES = [
    x.strip()
    for x in os.getenv(
        "LEAGUES", "PL,PD,FL1,BL1,SA"
    ).split(",")
    if x.strip()
]

TEST_SEASONS = [
    int(x)
    for x in os.getenv(
        "TEST_SEASONS", "2024,2025,2026"
    ).split(",")
    if x.strip()
]

WARMUP_SEASONS = [
    int(x)
    for x in os.getenv("WARMUP_SEASONS", "2023").split(",")
    if x.strip()
]

THRESHOLD = float(os.getenv("THRESHOLD", "0.75"))
SAFETY_Z = float(os.getenv("SAFETY_Z", "1.0"))
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
REPORT_DIR = os.getenv("REPORT_DIR", "reports")

GOAL_LINE = 3
MIN_GAMES = 5

K_GRID = [0, 10, 20, 30, 45, 60, 80, 120]
K_DEFAULT = 60

MIN_HISTORY = 120
NEIGHBOURS = 150
MIN_NEIGHBOURS = 60
RIDGE = 4.0

BASE_PRIOR_N = 30
BASE_DEFAULT = 0.65


# ---------------------------------------------------------------------
# MATHS HELPERS
# ---------------------------------------------------------------------

def pois_cdf(k, lam):
    lam = max(lam, 1e-9)
    term = math.exp(-lam)
    total = term

    for i in range(1, k + 1):
        term *= lam / i
        total += term

    return min(max(total, 0.0), 1.0)


def pois_logpmf(k, lam):
    lam = max(lam, 1e-9)

    return (
        -lam
        + k * math.log(lam)
        - math.lgamma(k + 1)
    )


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)

    return math.log(p / (1 - p))


def sigmoid(x):
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))

    e = math.exp(x)

    return e / (1.0 + e)


def wilson_lower(hits, n, z):
    if n == 0:
        return 0.0

    if z <= 0:
        return hits / n

    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)

    m = z * math.sqrt(
        p * (1 - p) / n
        + z * z / (4 * n * n)
    )

    return (c - m) / d


# ---------------------------------------------------------------------
# PROBABILITY EVALUATION
# ---------------------------------------------------------------------

def probability_metrics(items, probability_key):
    """
    Evaluate probability forecasts against binary outcomes.

    Brier score:
        Mean squared error of probability forecasts.
        Lower is better.

    Observed rate:
        Actual proportion of Under 3.5 outcomes.

    Mean probability:
        Average predicted probability for the same matches.
    """
    usable = []

    for row in items:
        probability = row.get(probability_key)
        actual = row.get("y")

        if probability is None or actual is None:
            continue

        try:
            probability = float(probability)
            actual = int(actual)
        except (TypeError, ValueError):
            continue

        if not 0 <= probability <= 1:
            continue

        if actual not in (0, 1):
            continue

        usable.append((probability, actual))

    if not usable:
        return None

    n = len(usable)

    brier = sum(
        (p - y) ** 2
        for p, y in usable
    ) / n

    observed = sum(
        y for p, y in usable
    ) / n

    mean_probability = sum(
        p for p, y in usable
    ) / n

    return {
        "n": n,
        "brier": brier,
        "observed_rate": observed,
        "mean_probability": mean_probability,
    }


def baseline_probability_metrics(items):
    """
    Evaluate the season-baseline probability.

    IMPORTANT:
    row['off'] is a logit, not a probability.
    Convert it with sigmoid() before computing Brier scores.
    """
    usable = []

    for row in items:
        if row.get("off") is None or row.get("y") is None:
            continue

        try:
            baseline_probability = sigmoid(
                float(row["off"])
            )
            actual = int(row["y"])
        except (TypeError, ValueError, OverflowError):
            continue

        if actual not in (0, 1):
            continue

        usable.append((baseline_probability, actual))

    if not usable:
        return None

    n = len(usable)

    return {
        "n": n,
        "brier": sum(
            (p - y) ** 2
            for p, y in usable
        ) / n,
        "observed_rate": sum(
            y for p, y in usable
        ) / n,
        "mean_probability": sum(
            p for p, y in usable
        ) / n,
    }


def brier_skill(model_brier, baseline_brier):
    """
    Positive skill means the model improves on the baseline.
    Zero means equal Brier performance.
    Negative skill means the model performs worse.
    """
    if model_brier is None or baseline_brier is None:
        return None

    if baseline_brier <= 0:
        return None

    return 1 - model_brier / baseline_brier


# ---------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------

def api_key():
    for name in (
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_DATA_TOKEN",
        "FOOTBALL_API_KEY",
        "API_KEY",
    ):
        value = os.getenv(name)

        if value:
            return value

    sys.exit(
        "No API key found. Set FOOTBALL_DATA_API_KEY "
        "and pass it to this step."
    )


def fetch_season(code, season, key):
    import requests

    url = f"{API}/competitions/{code}/matches"

    for _ in range(6):
        response = requests.get(
            url,
            headers={"X-Auth-Token": key},
            params={"season": season},
            timeout=60,
        )

        print(
            f"  API GET /competitions/{code}/matches "
            f"-> HTTP {response.status_code}"
        )

        if response.status_code == 200:
            return response.json().get("matches", [])

        if response.status_code == 429:
            try:
                wait = int(
                    response.headers.get("Retry-After", "60")
                ) + 2
            except ValueError:
                wait = 62

            print(f"  rate limited, waiting {wait}s")
            time.sleep(wait)

        elif response.status_code in (400, 403, 404):
            print(
                f"  {code} {season} unavailable on this "
                "plan/token - skipping"
            )
            return []

        else:
            time.sleep(5)

    return []


def normalise(raw, league, season):
    out = []

    for match in raw:
        full_time = (
            (match.get("score") or {}).get("fullTime")
            or {}
        )

        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        if not home.get("id") or not away.get("id"):
            continue

        utc = match.get("utcDate")

        if not utc:
            continue

        out.append({
            "league": league,
            "season": season,
            "date": utc[:10],
            "utc": utc,
            "home_id": home["id"],
            "away_id": away["id"],
            "home": home.get("name") or str(home["id"]),
            "away": away.get("name") or str(away["id"]),
            "status": match.get("status", ""),
            "hg": full_time.get("home"),
            "ag": full_time.get("away"),
        })

    return out


def load_matches():
    key = api_key()

    seasons = sorted(
        set(WARMUP_SEASONS + TEST_SEASONS)
    )

    print(
        "Testing seasons: "
        + ", ".join(
            f"{season}-{str(season + 1)[2:]}"
            for season in TEST_SEASONS
        )
    )

    print(
        f"Fetching {len(seasons)} seasons of raw data total "
        "(warm-up seasons feed tuning/calibration only)."
    )

    matches = []

    for league in LEAGUES:
        for season in seasons:
            print(f"  fetching {league} {season}...")

            matches += normalise(
                fetch_season(league, season, key),
                league,
                season,
            )

            # Respect the football-data.org free-tier request rate.
            time.sleep(6.5)

    return matches


# ---------------------------------------------------------------------
# MODEL
# ---------------------------------------------------------------------

class SeasonState:
    """Running totals updated only after all matches on a date."""

    def __init__(self):
        self.t = {}
        self.H = 0
        self.A = 0
        self.N = 0
        self.U = 0

    def feats(self, home_id, away_id):
        home = self.t.get(home_id, [0, 0, 0])
        away = self.t.get(away_id, [0, 0, 0])

        if (
            self.N == 0
            or home[2] < MIN_GAMES
            or away[2] < MIN_GAMES
        ):
            return None

        league_average = (
            self.H + self.A
        ) / (2 * self.N)

        if league_average <= 0:
            return None

        return {
            "hf": home[0],
            "ha": home[1],
            "nh": home[2],
            "af": away[0],
            "aa": away[1],
            "na": away[2],
            "L": league_average,
            "hm": self.H / self.N,
            "am": self.A / self.N,
            "bu": self.U,
            "bn": self.N,
        }

    def add(self, match):
        home = self.t.setdefault(
            match["home_id"], [0, 0, 0]
        )

        away = self.t.setdefault(
            match["away_id"], [0, 0, 0]
        )

        home[0] += match["hg"]
        home[1] += match["ag"]
        home[2] += 1

        away[0] += match["ag"]
        away[1] += match["hg"]
        away[2] += 1

        self.H += match["hg"]
        self.A += match["ag"]
        self.N += 1

        self.U += int(
            match["hg"] + match["ag"] <= GOAL_LINE
        )


def lam_total(features, K):
    league_average = features["L"]

    def strength(goals, games):
        return (
            (goals + K * league_average)
            / (games + K)
        ) / league_average

    lam_home = (
        strength(features["hf"], features["nh"])
        * strength(features["aa"], features["na"])
        * features["hm"]
    )

    lam_away = (
        strength(features["af"], features["na"])
        * strength(features["ha"], features["nh"])
        * features["am"]
    )

    return lam_home + lam_away


def build_rows(matches):
    by_league_season = defaultdict(list)

    for match in matches:
        by_league_season[
            (match["league"], match["season"])
        ].append(match)

    rows = []
    states = {}

    for key, season_matches in by_league_season.items():
        state = SeasonState()

        finished = sorted(
            (
                match
                for match in season_matches
                if (
                    match["status"] == "FINISHED"
                    and match["hg"] is not None
                    and match["ag"] is not None
                )
            ),
            key=lambda match: (
                match["date"],
                match["utc"],
            ),
        )

        i = 0

        while i < len(finished):
            j = i

            while (
                j < len(finished)
                and finished[j]["date"] == finished[i]["date"]
            ):
                j += 1

            day = finished[i:j]

            # First generate predictions using earlier dates only.
            for match in day:
                rows.append(dict(
                    match,
                    f=state.feats(
                        match["home_id"],
                        match["away_id"],
                    ),
                    tot=match["hg"] + match["ag"],
                ))

            # Then update the state with that date's results.
            for match in day:
                state.add(match)

            i = j

        states[key] = state

    return rows, states


def tune_k(rows):
    usable = [
        row for row in rows
        if row["f"] is not None
    ]

    if len(usable) < 150:
        return K_DEFAULT

    best = None

    for K in K_GRID:
        nll = sum(
            -pois_logpmf(
                row["tot"],
                lam_total(row["f"], K),
            )
            for row in usable
        )

        if best is None or nll < best[1]:
            best = (K, nll)

    return best[0]


def season_base(features, prior):
    return (
        features["bu"] + BASE_PRIOR_N * prior
    ) / (
        features["bn"] + BASE_PRIOR_N
    )


def fit_slope(data):
    """Fit a calibration slope using past observations only."""
    b = 1.0

    for _ in range(40):
        gradient = 0.0
        hessian = 0.0

        for offset, x, actual in data:
            probability = sigmoid(offset + b * x)

            gradient += (
                probability - actual
            ) * x

            hessian += (
                probability * (1 - probability) * x * x
            )

        gradient += RIDGE * (b - 1.0)
        hessian += RIDGE

        change = gradient / hessian
        b -= change

        if abs(change) < 1e-9:
            break

    return min(max(b, 0.0), 1.0)


def make_features(row, prior):
    baseline = season_base(row["f"], prior)

    row["off"] = logit(baseline)
    row["x"] = logit(row["p_raw"]) - row["off"]


def guard(probability, calibration_history):
    """
    Conservative lower confidence bound based on similar past predictions.
    """
    if len(calibration_history) < MIN_NEIGHBOURS:
        return None

    neighbours = sorted(
        calibration_history,
        key=lambda item: abs(
            item["p_cal"] - probability
        ),
    )[:NEIGHBOURS]

    hits = sum(
        item["y"] for item in neighbours
    )

    return min(
        probability,
        wilson_lower(
            hits,
            len(neighbours),
            SAFETY_Z,
        ),
    )


def walk_forward(rows):
    seasons = sorted({
        row["season"] for row in rows
    })

    # K for a season uses only rows from earlier seasons.
    k_by = {
        season: tune_k([
            row for row in rows
            if row["season"] < season
        ])
        for season in seasons
    }

    model = [
        row for row in rows
        if row["f"] is not None
    ]

    for row in model:
        row["p_raw"] = pois_cdf(
            GOAL_LINE,
            lam_total(
                row["f"],
                k_by[row["season"]],
            ),
        )

        row["y"] = int(
            row["tot"] <= GOAL_LINE
        )

        row["p_cal"] = None
        row["p_final"] = None

    model.sort(
        key=lambda row: (
            row["date"],
            row["utc"],
        )
    )

    history = []
    calibration_history = []
    ysum = 0
    i = 0

    while i < len(model):
        j = i

        while (
            j < len(model)
            and model[j]["date"] == model[i]["date"]
        ):
            j += 1

        day = model[i:j]

        prior = (
            ysum / len(history)
            if history
            else BASE_DEFAULT
        )

        for row in day:
            make_features(row, prior)

        slope = (
            fit_slope([
                (h["off"], h["x"], h["y"])
                for h in history
            ])
            if len(history) >= MIN_HISTORY
            else None
        )

        # Predict the entire date before learning its results.
        for row in day:
            if slope is not None:
                row["slope"] = slope

                row["p_cal"] = sigmoid(
                    row["off"] + slope * row["x"]
                )

                row["p_final"] = guard(
                    row["p_cal"],
                    calibration_history,
                )

        # Only after predictions are complete do we add outcomes.
        for row in day:
            history.append(row)
            ysum += row["y"]

            if row["p_cal"] is not None:
                calibration_history.append(row)

        i = j

    return model, k_by


# ---------------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------------

def longest_losing_run(sequence):
    best = 0
    run = 0

    for hit in sequence:
        run = 0 if hit else run + 1
        best = max(best, run)

    return best


def print_probability_diagnostics(scored):
    """
    Evaluate final model forecasts against the season-baseline forecasts.

    These metrics are diagnostic only. They do not alter predictions.
    """
    model_metrics = probability_metrics(
        scored,
        "p_final",
    )

    baseline_metrics = baseline_probability_metrics(
        scored,
    )

    print("\nProbability diagnostics (all scored test matches)")

    if model_metrics is None:
        print("  No final probabilities available.")
        return

    print(f"  Scored matches: {model_metrics['n']}")
    print(
        f"  Model mean probability: "
        f"{model_metrics['mean_probability'] * 100:.2f}%"
    )
    print(
        f"  Model observed Under 3.5 rate: "
        f"{model_metrics['observed_rate'] * 100:.2f}%"
    )
    print(
        f"  Model Brier score: "
        f"{model_metrics['brier']:.5f}"
    )

    if baseline_metrics is None:
        print("  Baseline metrics unavailable.")
        return

    skill = brier_skill(
        model_metrics["brier"],
        baseline_metrics["brier"],
    )

    print(
        f"  Baseline mean probability: "
        f"{baseline_metrics['mean_probability'] * 100:.2f}%"
    )
    print(
        f"  Baseline Brier score: "
        f"{baseline_metrics['brier']:.5f}"
    )

    if skill is not None:
        print(f"  Brier skill: {skill:+.5f}")

        if skill > 0:
            print(
                "  Interpretation: model beats the "
                "season-baseline forecast on Brier score."
            )
        elif skill < 0:
            print(
                "  Interpretation: model is worse than "
                "the season-baseline forecast on Brier score."
            )
        else:
            print(
                "  Interpretation: model matches the "
                "season-baseline forecast on Brier score."
            )


def report(model, rows):
    test = [
        row for row in model
        if row["season"] in TEST_SEASONS
    ]

    scored = [
        row for row in test
        if row["p_final"] is not None
    ]

    test_all = [
        row for row in rows
        if row["season"] in TEST_SEASONS
    ]

    skipped = len(test_all) - len(scored)

    print("\nWalking forward through finished matches...\n")

    print(
        f"{len(scored)} matches checked, "
        f"{skipped} skipped "
        "(not enough prior data at the time)"
    )

    cleared = sorted(
        [
            row for row in scored
            if row["p_final"] >= THRESHOLD
        ],
        key=lambda row: (
            row["date"],
            row["utc"],
        ),
    )

    hits = sum(row["y"] for row in cleared)

    print(
        f"{len(cleared)} would have cleared "
        f"{THRESHOLD * 100:.1f}% "
        "(final, after calibration + safety haircut)"
    )

    if cleared:
        hit_rate = hits / len(cleared)

        print(
            f"{hits}/{len(cleared)} hit -> "
            f"{hit_rate * 100:.1f}% "
            f"(break-even odds "
            f"{len(cleared) / max(hits, 1):.2f})"
        )

        print(
            "Longest losing run among cleared: "
            f"{longest_losing_run([r['y'] for r in cleared])}"
        )

        mean_final = sum(
            row["p_final"] for row in cleared
        ) / len(cleared)

        mean_calibrated = sum(
            row["p_cal"] for row in cleared
        ) / len(cleared)

        gap = mean_calibrated - hit_rate

        print(
            f"Average final probability "
            f"{mean_final * 100:.1f}% | "
            f"calibrated {mean_calibrated * 100:.1f}% | "
            f"actual {hit_rate * 100:.1f}%"
        )

        if gap > 0.03:
            print(
                "WARNING: calibrated probabilities exceed "
                f"the actual hit rate by {gap * 100:.1f} points."
            )
        else:
            print(
                "Overconfidence check: calibrated probability "
                "is not more than 3 points above the actual rate."
            )

    print_probability_diagnostics(scored)

    print("\nBy season (cleared matches)")

    for season in TEST_SEASONS:
        cleared_season = [
            row for row in cleared
            if row["season"] == season
        ]

        all_season = [
            row for row in scored
            if row["season"] == season
        ]

        if not all_season:
            print(f"  {season}: no scored matches")
            continue

        base_rate = sum(
            row["y"] for row in all_season
        ) / len(all_season)

        line = (
            f"  {season}-{str(season + 1)[2:]}: "
            f"all matches {len(all_season)}, "
            f"Under 3.5 rate {base_rate * 100:.1f}%"
        )

        if cleared_season:
            season_hits = sum(
                row["y"] for row in cleared_season
            )

            line += (
                f" | cleared {len(cleared_season)}, "
                f"hit {season_hits}/{len(cleared_season)} "
                f"= {season_hits / len(cleared_season) * 100:.1f}%"
            )
        else:
            line += " | cleared 0"

        print(line)

    print("\nBy league (cleared matches)")

    for league in LEAGUES:
        league_cleared = [
            row for row in cleared
            if row["league"] == league
        ]

        league_scored = [
            row for row in scored
            if row["league"] == league
        ]

        if not league_scored:
            print(f"  {league}: no scored matches")
            continue

        actual_rate = sum(
            row["y"] for row in league_scored
        ) / len(league_scored)

        line = (
            f"  {league}: scored {len(league_scored)}, "
            f"actual Under 3.5 rate {actual_rate * 100:.1f}%"
        )

        if league_cleared:
            league_hits = sum(
                row["y"] for row in league_cleared
            )

            line += (
                f" | cleared {len(league_cleared)}, "
                f"hit {league_hits}/{len(league_cleared)} "
                f"= {league_hits / len(league_cleared) * 100:.1f}%"
            )
        else:
            line += " | cleared 0"

        print(line)

    print(
        "\nCalibration table "
        "(all scored matches, grouped by final probability)"
    )

    print("  bucket        n   avg raw  avg final  actual")

    edges = [
        0.0, 0.55, 0.60, 0.65,
        0.70, 0.75, 1.01,
    ]

    for low, high in zip(edges, edges[1:]):
        group = [
            row for row in scored
            if low <= row["p_final"] < high
        ]

        if not group:
            continue

        n = len(group)

        print(
            f"  {low:.2f}-{min(high, 1.0):.2f} "
            f"{n:4d}   "
            f"{sum(r['p_raw'] for r in group) / n * 100:5.1f}%    "
            f"{sum(r['p_final'] for r in group) / n * 100:5.1f}%   "
            f"{sum(r['y'] for r in group) / n * 100:5.1f}%"
        )

    print("\nThreshold sweep (final probability)")

    for threshold in (
        0.55, 0.60, 0.65, 0.70, 0.75, 0.80
    ):
        group = sorted(
            [
                row for row in scored
                if row["p_final"] >= threshold
            ],
            key=lambda row: (
                row["date"],
                row["utc"],
            ),
        )

        if not group:
            print(f"  >= {threshold:.2f}: n=0")
            continue

        group_hits = sum(
            row["y"] for row in group
        )

        print(
            f"  >= {threshold:.2f}: n={len(group):4d} "
            f"hit {group_hits}/{len(group)} "
            f"= {group_hits / len(group) * 100:.1f}% "
            f"break-even odds "
            f"{len(group) / max(group_hits, 1):.2f} "
            f"longest losing run "
            f"{longest_losing_run([r['y'] for r in group])}"
        )

    os.makedirs(REPORT_DIR, exist_ok=True)

    path = os.path.join(
        REPORT_DIR,
        "core2_results.csv",
    )

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)

        writer.writerow([
            "date",
            "league",
            "season",
            "home",
            "away",
            "hg",
            "ag",
            "p_raw",
            "p_cal",
            "p_final",
            "baseline_probability",
            "hit",
            "cleared",
        ])

        for row in sorted(
            scored,
            key=lambda r: (r["date"], r["utc"]),
        ):
            writer.writerow([
                row["date"],
                row["league"],
                row["season"],
                row["home"],
                row["away"],
                row["hg"],
                row["ag"],
                f"{row['p_raw']:.4f}",
                f"{row['p_cal']:.4f}",
                f"{row['p_final']:.4f}",
                f"{sigmoid(row['off']):.4f}",
                row["y"],
                int(row["p_final"] >= THRESHOLD),
            ])

    print(f"\nWrote {path}")


# ---------------------------------------------------------------------
# UPCOMING FIXTURES
# ---------------------------------------------------------------------

def upcoming(matches, states, rows, model, k_by):
    if UPCOMING_DAYS <= 0:
        return

    latest = max(TEST_SEASONS)

    today = datetime.now(timezone.utc).date()
    end = today + __import__("datetime").timedelta(
        days=UPCOMING_DAYS
    )

    fixtures = [
        match for match in matches
        if (
            match["season"] == latest
            and match["status"] in ("SCHEDULED", "TIMED")
            and today.isoformat() <= match["date"] <= end.isoformat()
        )
    ]

    print(
        f"\nUpcoming fixtures (next {UPCOMING_DAYS} days)"
    )

    if not fixtures:
        print("  none found")
        return

    done = [
        row for row in model
        if row["p_cal"] is not None
    ]

    if len(model) < MIN_HISTORY:
        print("  not enough history yet to calibrate")
        return

    prior = sum(
        row["y"] for row in model
    ) / len(model)

    slope = fit_slope([
        (row["off"], row["x"], row["y"])
        for row in model
    ])

    K = (
        k_by.get(latest)
        or tune_k([
            row for row in rows
            if row["season"] < latest
        ])
    )

    for match in sorted(
        fixtures,
        key=lambda item: item["utc"],
    ):
        state = states.get(
            (match["league"], latest)
        )

        features = (
            state.feats(
                match["home_id"],
                match["away_id"],
            )
            if state
            else None
        )

        if features is None:
            print(
                f"  {match['date']} {match['league']:<4} "
                f"{match['home']} vs {match['away']} "
                "- not enough games yet"
            )
            continue

        p_raw = pois_cdf(
            GOAL_LINE,
            lam_total(features, K),
        )

        offset = logit(
            season_base(features, prior)
        )

        p_cal = sigmoid(
            offset + slope * (
                logit(p_raw) - offset
            )
        )

        p_final = guard(
            p_cal,
            done,
        )

        if p_final is None:
            print(
                f"  {match['date']} {match['league']:<4} "
                f"{match['home']} vs {match['away']} "
                "- not enough history"
            )
            continue

        flag = (
            "CLEARS"
            if p_final >= THRESHOLD
            else "below"
        )

        print(
            f"  {match['date']} {match['league']:<4} "
            f"{match['home']} vs {match['away']} "
            f"{p_final * 100:.1f}% "
            f"(raw {p_raw * 100:.1f}%) "
            f"fair odds {1 / p_final:.2f} {flag}"
        )


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------

def run(matches):
    rows, states = build_rows(matches)

    model, k_by = walk_forward(rows)

    print(f"Tuned shrinkage K by season: {k_by}")

    report(model, rows)

    upcoming(
        matches,
        states,
        rows,
        model,
        k_by,
    )


def main():
    print("Barbadox Core 2 - Under 3.5 goals")

    if not 0 < THRESHOLD < 1:
        sys.exit("THRESHOLD must be between 0 and 1.")

    if SAFETY_Z < 0:
        sys.exit("SAFETY_Z cannot be negative.")

    run(load_matches())


if __name__ == "__main__":
    main()
