#!/usr/bin/env python3
"""
BARBADOX CORE 2.2 — UNDER 3.5 GOALS

Outputs:
  reports/matches.csv
  reports/core2_results.csv
  reports/core2_upcoming.csv
  reports/core2_diagnostics.md

Every historical test match is exported, including rejected and unscored
matches. Upcoming fixtures are also exported, whether or not they qualify.

No target hit rate is guaranteed. Evaluate calibration, sample size,
Brier score, and out-of-sample performance before trusting selections.
"""

import csv
import math
import os
import sys
import time

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


API = "https://api.football-data.org/v4"

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / os.getenv("REPORT_DIR", "reports")

LEAGUES = [
    x.strip()
    for x in os.getenv(
        "LEAGUES", "PL,PD,FL1,BL1,SA"
    ).split(",")
    if x.strip()
]

TEST_SEASONS = sorted({
    int(x)
    for x in os.getenv(
        "TEST_SEASONS", "2024,2025,2026"
    ).split(",")
    if x.strip()
})

WARMUP_SEASONS = sorted({
    int(x)
    for x in os.getenv("WARMUP_SEASONS", "2023").split(",")
    if x.strip()
})

THRESHOLD = float(os.getenv("THRESHOLD", "0.80"))
SAFETY_Z = float(os.getenv("SAFETY_Z", "1.35"))
UPCOMING_DAYS = max(0, int(os.getenv("UPCOMING_DAYS", "7")))

# Half-life measured in years of match history.
HALF_LIFE = max(0.25, float(os.getenv("HALF_LIFE", "7.5")))
DECAY_PER_DAY = math.log(2) / (HALF_LIFE * 365.25)

MIN_GAMES = int(os.getenv("MIN_GAMES", "6"))
MIN_HISTORY = int(os.getenv("MIN_HISTORY", "90"))
NEIGHBOURS = int(os.getenv("NEIGHBOURS", "100"))
MIN_NEIGHBOURS = int(os.getenv("MIN_NEIGHBOURS", "40"))

BASE_PRIOR_N = float(os.getenv("BASE_PRIOR_N", "20"))
BASE_DEFAULT = float(os.getenv("BASE_DEFAULT", "0.60"))

K_GRID = [
    float(x)
    for x in os.getenv(
        "K_GRID", "25,40,60,90,130"
    ).split(",")
    if x.strip()
]

USE_NB = os.getenv("USE_NB", "1").strip() == "1"
NB_R = max(0.5, float(os.getenv("NB_R", "12")))


# ============================================================
# API
# ============================================================

def api_key():
    names = (
        "FOOTBALL_DATA_API_KEY",
        "FOOTBALL_DATA_TOKEN",
        "FOOTBALL_API_KEY",
        "API_KEY",
        "FOOTBALL_DATA_KEY",
    )

    for name in names:
        value = os.getenv(name)
        if value:
            return value

    raise SystemExit(
        "Missing football-data.org API key. "
        "Set FOOTBALL_DATA_API_KEY in GitHub Secrets."
    )


def fetch_season(code, season, key):
    import requests

    url = f"{API}/competitions/{code}/matches"

    for attempt in range(5):
        try:
            response = requests.get(
                url,
                headers={"X-Auth-Token": key},
                params={"season": season},
                timeout=45,
            )
        except requests.RequestException as exc:
            print(f"Network error {code}/{season}: {exc}")
            time.sleep(4)
            continue

        print(
            f"API {code} season={season}: "
            f"HTTP {response.status_code}"
        )

        if response.status_code == 200:
            return response.json().get("matches", [])

        if response.status_code in (400, 403, 404):
            print(f"Skipping unavailable {code}/{season}")
            return []

        if response.status_code == 429:
            header = response.headers.get("Retry-After", "30")

            try:
                wait = min(65, int(header))
            except ValueError:
                wait = 30

            print(f"Rate limited; waiting {wait + 1}s")
            time.sleep(wait + 1)

        else:
            time.sleep(5 * (attempt + 1))

    return []


def normalize(raw, league, season):
    rows = []

    for match in raw:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        score = (
            (match.get("score") or {}).get("fullTime")
            or {}
        )

        utc = match.get("utcDate")

        if not utc or not home.get("id") or not away.get("id"):
            continue

        rows.append({
            "date": utc[:10],
            "utc": utc,
            "league": league,
            "season": season,
            "home_id": str(home["id"]),
            "away_id": str(away["id"]),
            "home": home.get("name") or str(home["id"]),
            "away": away.get("name") or str(away["id"]),
            "status": match.get("status", ""),
            "hg": score.get("home"),
            "ag": score.get("away"),
            "match_id": match.get("id", ""),
        })

    return rows


def load_matches():
    key = api_key()
    seasons = sorted(set(TEST_SEASONS + WARMUP_SEASONS))
    matches = []

    for league in LEAGUES:
        for season in seasons:
            print(f"Fetching {league} {season}...")

            matches.extend(
                normalize(
                    fetch_season(league, season, key),
                    league,
                    season,
                )
            )

            # Respect the football-data.org request limit.
            time.sleep(6.5)

    return matches


# ============================================================
# PROBABILITY MATHEMATICS
# ============================================================

def sigmoid(x):
    if x >= 0:
        e = math.exp(-min(x, 700))
        return 1.0 / (1.0 + e)

    e = math.exp(max(x, -700))
    return e / (1.0 + e)


def logit(p):
    p = min(1 - 1e-8, max(1e-8, p))
    return math.log(p / (1.0 - p))


def poisson_pmf(k, lam):
    lam = max(1e-9, lam)

    return math.exp(
        -lam
        + k * math.log(lam)
        - math.lgamma(k + 1)
    )


def negative_binomial_pmf(k, mu, r):
    mu = max(1e-9, mu)
    r = max(0.5, r)

    return math.exp(
        math.lgamma(k + r)
        - math.lgamma(r)
        - math.lgamma(k + 1)
        + r * math.log(r / (r + mu))
        + k * math.log(mu / (r + mu))
    )


def dixon_coles_tau(x, y, lh, la, rho):
    """
    Standard low-score Dixon-Coles correction.
    """

    if x == 0 and y == 0:
        tau = 1 - lh * la * rho

    elif x == 0 and y == 1:
        tau = 1 + lh * rho

    elif x == 1 and y == 0:
        tau = 1 + la * rho

    elif x == 1 and y == 1:
        tau = 1 - rho

    else:
        tau = 1.0

    return max(1e-6, tau)


def probability_under35(lh, la, rho=-0.07):
    """
    Calculate P(total goals <= 3).

    The Poisson version uses Dixon-Coles low-score corrections.
    The negative-binomial version uses NB marginals without a
    Dixon-Coles correction.
    """

    total = 0.0

    for home_goals in range(4):
        for away_goals in range(4 - home_goals):

            if USE_NB:
                ph = negative_binomial_pmf(
                    home_goals, lh, NB_R
                )
                pa = negative_binomial_pmf(
                    away_goals, la, NB_R
                )
                correction = 1.0

            else:
                ph = poisson_pmf(home_goals, lh)
                pa = poisson_pmf(away_goals, la)

                correction = dixon_coles_tau(
                    home_goals,
                    away_goals,
                    lh,
                    la,
                    rho,
                )

            total += ph * pa * correction

    return min(1.0, max(0.0, total))


def wilson_lower(hits, n, z=1.35):
    """
    Wilson lower confidence bound for a binomial proportion.
    """

    if n <= 0:
        return 0.0

    p = hits / n
    z2 = z * z
    denominator = 1 + z2 / n

    center = p + z2 / (2 * n)

    margin = z * math.sqrt(
        (p * (1 - p) + z2 / (4 * n)) / n
    )

    return (center - margin) / denominator


# ============================================================
# CALIBRATION
# ============================================================

def fit_logit_slope(pairs, ridge=2.0, steps=250, lr=0.025):
    """
    Fit logistic calibration parameters using prior predictions only.
    """

    if len(pairs) < 50:
        return 1.0, 0.0

    slope = 1.0
    intercept = 0.0

    for _ in range(steps):
        grad_slope = ridge * (slope - 1.0)
        grad_intercept = 0.0

        for p, outcome in pairs:
            x = logit(p)

            z = max(
                -25,
                min(25, intercept + slope * x),
            )

            predicted = sigmoid(z)

            grad_slope += (predicted - outcome) * x
            grad_intercept += predicted - outcome

        n = len(pairs)

        slope -= lr * grad_slope / n
        intercept -= lr * grad_intercept / n

        slope = min(3.0, max(0.15, slope))
        intercept = min(2.0, max(-2.0, intercept))

    return slope, intercept


def isotonic_predict(train_pairs, target):
    """
    Pool Adjacent Violators isotonic regression.

    train_pairs contains (probability, outcome).
    """

    if len(train_pairs) < 30:
        return target

    points = sorted(
        (
            min(1.0, max(0.0, float(p))),
            int(y),
        )
        for p, y in train_pairs
    )

    blocks = []

    for p, y in points:

        blocks.append({
            "xmin": p,
            "xmax": p,
            "sum": float(y),
            "weight": 1,
        })

        while len(blocks) >= 2:
            a = blocks[-2]
            b = blocks[-1]

            mean_a = a["sum"] / a["weight"]
            mean_b = b["sum"] / b["weight"]

            if mean_a <= mean_b:
                break

            blocks.pop()
            blocks.pop()

            blocks.append({
                "xmin": a["xmin"],
                "xmax": b["xmax"],
                "sum": a["sum"] + b["sum"],
                "weight": a["weight"] + b["weight"],
            })

    for block in blocks:
        if target <= block["xmax"]:
            return block["sum"] / block["weight"]

    return blocks[-1]["sum"] / blocks[-1]["weight"]


def calibrate(raw_probability, prior_pairs):
    """
    Fit calibration only on predictions from earlier dates.

    Returns:
      calibrated probability, slope, intercept, method
    """

    if len(prior_pairs) < 50:
        return (
            raw_probability,
            1.0,
            0.0,
            "insufficient_history",
        )

    slope, intercept = fit_logit_slope(prior_pairs)

    logit_probability = sigmoid(
        intercept + slope * logit(raw_probability)
    )

    transformed_history = [
        (
            sigmoid(intercept + slope * logit(p)),
            y,
        )
        for p, y in prior_pairs
    ]

    calibrated = isotonic_predict(
        transformed_history,
        logit_probability,
    )

    return (
        min(0.999, max(0.001, calibrated)),
        slope,
        intercept,
        "logit_plus_isotonic",
    )


# ============================================================
# LEAKAGE-AWARE TEAM STATE
# ============================================================

class TeamState:
    """
    Stores exponentially decayed team and league statistics.

    All matches on the same date must be predicted before their
    scores are added to this state.
    """

    def __init__(self):
        self.teams = {}

        self.home_goals = 0.0
        self.away_goals = 0.0
        self.n = 0.0

        self.last_date = None

    def advance(self, date):
        """
        Apply time decay from the previous state date to this date.

        This method is required by add() and is included explicitly
        to avoid the missing-method runtime error in the earlier ZIP.
        """

        if self.last_date is None:
            self.last_date = date
            return

        try:
            previous = datetime.fromisoformat(self.last_date)
            current = datetime.fromisoformat(date)
            elapsed_days = max(
                0,
                (current - previous).days,
            )
        except ValueError:
            elapsed_days = 0

        if elapsed_days:
            factor = math.exp(
                -DECAY_PER_DAY * elapsed_days
            )

            for team in self.teams.values():
                team[0] *= factor
                team[1] *= factor
                team[2] *= factor

            self.home_goals *= factor
            self.away_goals *= factor
            self.n *= factor

        self.last_date = date

    def features(self, match):
        home = self.teams.get(
            match["home_id"],
            [0.0, 0.0, 0.0],
        )

        away = self.teams.get(
            match["away_id"],
            [0.0, 0.0, 0.0],
        )

        if (
            home[2] < MIN_GAMES
            or away[2] < MIN_GAMES
            or self.n < MIN_GAMES * 2
        ):
            return None

        home_mean = (
            self.home_goals + BASE_DEFAULT * BASE_PRIOR_N
        ) / (self.n + BASE_PRIOR_N)

        away_mean = (
            self.away_goals + BASE_DEFAULT * BASE_PRIOR_N
        ) / (self.n + BASE_PRIOR_N)

        overall = max(
            0.15,
            (home_mean + away_mean) / 2,
        )

        home_advantage = min(
            0.35,
            max(
                -0.05,
                (home_mean - away_mean)
                / max(0.3, overall),
            ),
        )

        home_for = (
            home[0] + overall * 5
        ) / (home[2] + 5)

        home_against = (
            home[1] + overall * 5
        ) / (home[2] + 5)

        away_for = (
            away[0] + overall * 5
        ) / (away[2] + 5)

        away_against = (
            away[1] + overall * 5
        ) / (away[2] + 5)

        return {
            "home_games": home[2],
            "away_games": away[2],
            "home_for": home_for,
            "home_against": home_against,
            "away_for": away_for,
            "away_against": away_against,
            "home_mean": home_mean,
            "away_mean": away_mean,
            "overall": overall,
            "home_adv": home_advantage,
            "league_matches": self.n,
        }

    def lambdas(self, features, k):
        """
        Estimate expected home and away goals.

        k controls shrinkage toward league-average scoring rates.
        """

        overall = max(0.1, features["overall"])

        attack_home = features["home_for"] / overall
        defence_away = features["away_against"] / overall

        attack_away = features["away_for"] / overall
        defence_home = features["home_against"] / overall

        shrink_home = (
            features["home_games"]
            / (features["home_games"] + k)
        )

        shrink_away = (
            features["away_games"]
            / (features["away_games"] + k)
        )

        attack_home = 1 + shrink_home * (attack_home - 1)
        defence_away = 1 + shrink_away * (defence_away - 1)

        attack_away = 1 + shrink_away * (attack_away - 1)
        defence_home = 1 + shrink_home * (defence_home - 1)

        home_factor = 1 + features["home_adv"] * 0.5

        lh = (
            features["home_mean"]
            * attack_home
            * defence_away
            * home_factor
        )

        la = (
            features["away_mean"]
            * attack_away
            * defence_home
            / max(0.1, home_factor)
        )

        return (
            min(4.5, max(0.08, lh)),
            min(4.5, max(0.08, la)),
        )

    def add(self, match):
        """
        Add a finished match after predictions for its date are made.
        """

        self.advance(match["date"])

        home = self.teams.setdefault(
            match["home_id"],
            [0.0, 0.0, 0.0],
        )

        away = self.teams.setdefault(
            match["away_id"],
            [0.0, 0.0, 0.0],
        )

        home[0] += match["hg"]
        home[1] += match["ag"]
        home[2] += 1

        away[0] += match["ag"]
        away[1] += match["hg"]
        away[2] += 1

        self.home_goals += match["hg"]
        self.away_goals += match["ag"]
        self.n += 1


# ============================================================
# MODEL TUNING AND FILTERS
# ============================================================

def estimate_rho(history):
    if len(history) < 80:
        return -0.07

    n = len(history)

    low00 = sum(
        r["hg"] == 0 and r["ag"] == 0
        for r in history
    ) / n

    low01 = sum(
        r["hg"] == 0 and r["ag"] == 1
        for r in history
    ) / n

    low10 = sum(
        r["hg"] == 1 and r["ag"] == 0
        for r in history
    ) / n

    low11 = sum(
        r["hg"] == 1 and r["ag"] == 1
        for r in history
    ) / n

    rho = -0.07 + 0.5 * (
        (low00 + low11) - (low01 + low10)
    )

    return min(0.05, max(-0.15, rho))


def choose_k(history):
    """
    Choose shrinkage from prior history only.

    This is a limited heuristic tuning step, not a full refit
    of the goal model for every possible K.
    """

    if len(history) < 80:
        return 60.0

    # Conservative default until a dedicated rolling K-validation
    # procedure is implemented.
    return min(
        K_GRID,
        key=lambda k: abs(k - 60.0),
    )


def guard_probability(probability, calibration_history):
    """
    Compare the forecast with the nearest prior calibrated outcomes.
    """

    if len(calibration_history) < MIN_HISTORY:
        return None, "guard_insufficient_history"

    neighbours = sorted(
        calibration_history,
        key=lambda row: abs(row[0] - probability),
    )[:NEIGHBOURS]

    if len(neighbours) < MIN_NEIGHBOURS:
        return None, "guard_insufficient_neighbours"

    hits = sum(y for _, y in neighbours)

    lower = wilson_lower(
        hits,
        len(neighbours),
        SAFETY_Z,
    )

    return min(probability, lower), (
        f"wilson_guard_n{len(neighbours)}_lb{lower:.4f}"
    )


def group_dates(rows):
    groups = defaultdict(list)

    for row in rows:
        groups[row["date"]].append(row)

    return [
        groups[date]
        for date in sorted(groups)
    ]


# ============================================================
# HISTORICAL WALK-FORWARD REPLAY
# ============================================================

def evaluate_historical(matches):
    """
    All fixtures on a date are predicted before that date's results
    enter the model or calibration history.
    """

    finished = [
        m for m in matches
        if m["status"] == "FINISHED"
        and m["hg"] is not None
        and m["ag"] is not None
    ]

    finished.sort(
        key=lambda m: (
            m["date"],
            m["utc"],
            m["league"],
            m["season"],
        )
    )

    states = {}
    season_history = defaultdict(list)

    output = []
    global_history = []
    calibration_history = []

    for day in group_dates(finished):
        day_rows = []

        # Advance states before predicting fixtures on this date.
        for match in day:
            state = states.setdefault(
                (match["league"], match["season"]),
                TeamState(),
            )
            state.advance(match["date"])

        # Predict the whole day before updating any match results.
        for match in day:
            key = (match["league"], match["season"])
            state = states[key]

            features = state.features(match)

            lh = la = raw = calibrated = final = None
            slope = intercept = None

            rho = estimate_rho(season_history[key])

            reason = "not_test_season"

            if match["season"] not in TEST_SEASONS:
                day_rows.append((match, None))
                continue

            if features is None:
                reason = "insufficient_team_or_league_history"

            else:
                k = choose_k(season_history[key])

                lh, la = state.lambdas(features, k)

                raw = probability_under35(
                    lh,
                    la,
                    rho,
                )

                prior_pairs = [
                    (r["p_raw"], r["y"])
                    for r in global_history
                ]

                calibrated, slope, intercept, _ = calibrate(
                    raw,
                    prior_pairs,
                )

                guarded, guard_reason = guard_probability(
                    calibrated,
                    calibration_history,
                )

                if (
                    features["home_games"] < MIN_GAMES
                    or features["away_games"] < MIN_GAMES
                ):
                    reason = "team_history_below_minimum"

                elif lh + la > 2.45:
                    reason = "expected_total_goals_above_filter"

                elif guarded is None:
                    reason = guard_reason

                else:
                    final = guarded

                    if final >= THRESHOLD:
                        reason = "QUALIFIED"
                    else:
                        reason = "below_threshold"

            outcome = int(
                match["hg"] + match["ag"] <= 3
            )

            row = {
                "date": match["date"],
                "utc": match["utc"],
                "league": match["league"],
                "season": match["season"],
                "home": match["home"],
                "away": match["away"],
                "home_id": match["home_id"],
                "away_id": match["away_id"],
                "hg": match["hg"],
                "ag": match["ag"],
                "total_goals": match["hg"] + match["ag"],
                "y": outcome,
                "lambda_home": round(lh, 5) if lh is not None else "",
                "lambda_away": round(la, 5) if la is not None else "",
                "lambda_total": round(lh + la, 5) if lh is not None else "",
                "rho": round(rho, 5),
                "p_raw": round(raw, 6) if raw is not None else "",
                "p_cal": round(calibrated, 6) if calibrated is not None else "",
                "p_final": round(final, 6) if final is not None else "",
                "calibration_slope": round(slope, 5) if slope is not None else "",
                "calibration_intercept": round(intercept, 5) if intercept is not None else "",
                "cleared": int(
                    final is not None and final >= THRESHOLD
                ),
                "filter_reason": reason,
                "model": (
                    "Core2.2_NB"
                    if USE_NB
                    else "Core2.2_DC_Poisson"
                ),
            }

            day_rows.append((match, row))

        # Only now do results from this date enter model history.
        for match, row in day_rows:
            key = (match["league"], match["season"])

            season_history[key].append(match)
            states[key].add(match)

            if row is None:
                continue

            output.append(row)

            if row["p_raw"] != "":
                global_history.append({
                    "p_raw": float(row["p_raw"]),
                    "y": row["y"],
                })

                calibration_history.append((
                    float(row["p_cal"]),
                    row["y"],
                ))

    return output, finished


# ============================================================
# UPCOMING FIXTURES
# ============================================================

def evaluate_upcoming(matches, historical_rows):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=UPCOMING_DAYS)

    fixtures = []

    excluded_statuses = {
        "FINISHED",
        "CANCELLED",
        "POSTPONED",
        "AWARDED",
    }

    for match in matches:
        if match["status"] in excluded_statuses:
            continue

        try:
            dt = datetime.fromisoformat(
                match["utc"].replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if now <= dt <= end:
            fixtures.append(match)

    finished = [
        m for m in matches
        if m["status"] == "FINISHED"
        and m["hg"] is not None
        and m["ag"] is not None
    ]

    output = []

    for fixture in sorted(fixtures, key=lambda m: m["utc"]):
        history = [
            m for m in finished
            if m["league"] == fixture["league"]
            and m["season"] == fixture["season"]
            and m["utc"] < fixture["utc"]
        ]

        state = TeamState()

        for match in sorted(
            history,
            key=lambda m: (m["date"], m["utc"]),
        ):
            state.add(match)

        features = state.features(fixture)

        lh = la = raw = calibrated = final = None
        rho = estimate_rho(history)

        if features is None:
            reason = "insufficient_team_or_league_history"

        else:
            k = choose_k(history)
            lh, la = state.lambdas(features, k)

            raw = probability_under35(lh, la, rho)

            prior_pairs = [
                (float(r["p_raw"]), int(r["y"]))
                for r in historical_rows
                if r.get("p_raw") not in ("", None)
                and r.get("y") not in ("", None)
            ]

            calibrated, _, _, _ = calibrate(
                raw,
                prior_pairs,
            )

            calibration_pairs = [
                (float(r["p_cal"]), int(r["y"]))
                for r in historical_rows
                if r.get("p_cal") not in ("", None)
                and r.get("y") not in ("", None)
            ]

            guarded, guard_reason = guard_probability(
                calibrated,
                calibration_pairs,
            )

            if lh + la > 2.45:
                reason = "expected_total_goals_above_filter"

            elif guarded is None:
                reason = guard_reason

            else:
                final = guarded

                reason = (
                    "QUALIFIED"
                    if final >= THRESHOLD
                    else "below_threshold"
                )

        output.append({
            "date": fixture["date"],
            "utc": fixture["utc"],
            "league": fixture["league"],
            "season": fixture["season"],
            "home": fixture["home"],
            "away": fixture["away"],
            "home_id": fixture["home_id"],
            "away_id": fixture["away_id"],
            "lambda_home": round(lh, 5) if lh is not None else "",
            "lambda_away": round(la, 5) if la is not None else "",
            "lambda_total": round(lh + la, 5) if lh is not None else "",
            "rho": round(rho, 5),
            "p_raw": round(raw, 6) if raw is not None else "",
            "p_cal": round(calibrated, 6) if calibrated is not None else "",
            "p_final": round(final, 6) if final is not None else "",
            "cleared": int(
                final is not None and final >= THRESHOLD
            ),
            "filter_reason": reason,
            "model": (
                "Core2.2_NB"
                if USE_NB
                else "Core2.2_DC_Poisson"
            ),
        })

    return output


# ============================================================
# REPORTING
# ============================================================

def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)

    if fields is None:
        fields = []

        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def brier_score(rows, probability_key):
    values = []

    for row in rows:
        try:
            p = float(row[probability_key])
            y = int(row["y"])
        except (ValueError, TypeError, KeyError):
            continue

        values.append((p - y) ** 2)

    if not values:
        return None

    return sum(values) / len(values)


def write_report(historical, upcoming):
    scored = [
        row for row in historical
        if row.get("p_raw") not in ("", None)
    ]

    selected = [
        row for row in historical
        if str(row.get("cleared")) == "1"
    ]

    hit_count = sum(
        int(row["y"])
        for row in selected
    )

    selected_count = len(selected)

    base_rate = (
        sum(int(row["y"]) for row in scored) / len(scored)
        if scored else 0.0
    )

    raw_brier = brier_score(scored, "p_raw")
    calibrated_brier = brier_score(scored, "p_cal")

    reasons = defaultdict(int)

    for row in historical:
        reasons[row.get("filter_reason") or "unknown"] += 1

    lines = [
        "# BARBADOX CORE 2.2 — UNDER 3.5 DIAGNOSTICS",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        f"Model: {'Negative Binomial' if USE_NB else 'Dixon-Coles Poisson'}",
        f"Threshold: {THRESHOLD:.1%}",
        f"Safety z: {SAFETY_Z}",
        "",
        "## Coverage",
        "",
        f"- Historical test matches: **{len(historical)}**",
        f"- Historical matches with raw probabilities: **{len(scored)}**",
        f"- Qualified historical picks: **{selected_count}**",
        f"- Rejected or unscored historical rows: **{len(historical) - selected_count}**",
        f"- Upcoming fixtures evaluated: **{len(upcoming)}**",
        f"- Qualified upcoming fixtures: **{sum(str(r.get('cleared')) == '1' for r in upcoming)}**",
        "",
        "## Historical performance",
        "",
        f"- Under 3.5 base rate: **{base_rate:.2%}**",
        f"- Raw Brier score: **{raw_brier:.5f}**" if raw_brier is not None else "- Raw Brier score: n/a",
        f"- Calibrated Brier score: **{calibrated_brier:.5f}**" if calibrated_brier is not None else "- Calibrated Brier score: n/a",
        (
            f"- Qualified pick hit rate: **{hit_count / selected_count:.2%}** "
            f"({hit_count}/{selected_count})"
            if selected_count
            else "- Qualified pick hit rate: n/a"
        ),
        "",
        "## Rejection reasons",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]

    for reason, count in sorted(
        reasons.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {reason} | {count} |")

    lines += [
        "",
        "## Important limitations",
        "",
        "- A qualified pick is not proof of a reliable probability.",
        "- The threshold is a selection rule, not a guarantee.",
        "- Calibration and the Wilson guard depend on earlier recorded predictions.",
        "- Historical performance must be checked on a genuinely unseen period.",
        "- Inspect sample size and Brier scores alongside hit rate.",
        "",
        "All historical rows, including rejected and unscored fixtures, are retained in `core2_results.csv`.",
        "",
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    (REPORT_DIR / "core2_diagnostics.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


# ============================================================
# MAIN
# ============================================================

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    matches = load_matches()

    completed = [
        m for m in matches
        if m["status"] == "FINISHED"
        and m["hg"] is not None
        and m["ag"] is not None
    ]

    write_csv(
        REPORT_DIR / "matches.csv",
        completed,
        [
            "date", "utc", "league", "season",
            "home", "away", "hg", "ag",
            "home_id", "away_id", "match_id",
        ],
    )

    historical, _ = evaluate_historical(matches)

    upcoming = (
        evaluate_upcoming(matches, historical)
        if UPCOMING_DAYS > 0
        else []
    )

    write_csv(
        REPORT_DIR / "core2_results.csv",
        historical,
    )

    write_csv(
        REPORT_DIR / "core2_upcoming.csv",
        upcoming,
    )

    write_report(historical, upcoming)

    selected = [
        row for row in historical
        if str(row.get("cleared")) == "1"
    ]

    print()
    print("BARBADOX CORE 2.2 FINISHED")
    print(f"Historical rows: {len(historical)}")
    print(f"Qualified historical picks: {len(selected)}")
    print(f"Upcoming fixtures: {len(upcoming)}")
    print(
        "Qualified upcoming fixtures: "
        f"{sum(str(r.get('cleared')) == '1' for r in upcoming)}"
    )

    print()
    print("Reports saved:")
    print("reports/matches.csv")
    print("reports/core2_results.csv")
    print("reports/core2_upcoming.csv")
    print("reports/core2_diagnostics.md")


if __name__ == "__main__":
    main()
