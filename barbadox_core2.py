#!/usr/bin/env python3
"""
Barbadox Core 2 v2 - Under 3.5 goals - walk-forward calibration check.

What changed from v1
  1. Team strengths are fitted JOINTLY (opponent-adjusted attack/defence with
     a Gamma prior), replacing the product of marginal shrunk ratios.
     (Won 19 of 20 synthetic seeds, paired Brier +0.0034.)
  2. Negative-binomial predictive is OPTIONAL (USE_NB=1). It did not help in
     the synthetic ablation, so the default is Poisson on the joint strengths.
  3. Calibration now has a walk-forward, shrunk LEAGUE OFFSET on top of the
     slope, learned only from earlier matches. (Core 1 logs showed Serie A and
     Ligue 1 far more overconfident than the other leagues.)
  4. Optional probability cap (P_CAP) because probabilities above ~0.86 were
     not informative in Core 1.
  5. Writes reports/matches.csv (all finished matches) for offline backtests,
     and prints the overconfidence gap (avg p minus hit rate) everywhere.

Walk-forward rules are unchanged: every prediction uses ONLY matches played on
earlier dates in the SAME season; tuning and calibration use earlier data only.

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
  K_JOINT                 Default: 30   prior strength of the joint fit
  USE_NB                  Default: 0    1 = negative-binomial predictive
  LEAGUE_RIDGE            Default: 25   shrinkage of league offsets (higher =
                                        smaller offsets); <0 disables them
  P_CAP                   Default: 1.0  caps final probability (e.g. 0.86)
"""

import csv
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

API = "https://api.football-data.org/v4"

LEAGUES = [
    x.strip()
    for x in os.getenv("LEAGUES", "PL,PD,FL1,BL1,SA").split(",")
    if x.strip()
]
TEST_SEASONS = [
    int(x)
    for x in os.getenv("TEST_SEASONS", "2024,2025,2026").split(",")
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

K_JOINT = float(os.getenv("K_JOINT", "30"))
USE_NB = os.getenv("USE_NB", "0") == "1"
LEAGUE_RIDGE = float(os.getenv("LEAGUE_RIDGE", "25"))
P_CAP = float(os.getenv("P_CAP", "1.0"))

GOAL_LINE = 3
MIN_GAMES = 5

MIN_HISTORY = 120
NEIGHBOURS = 150
MIN_NEIGHBOURS = 60
RIDGE = 4.0
MIN_LEAGUE_N = 60

BASE_PRIOR_N = 30
BASE_DEFAULT = 0.65

V0_GRID = [0.0, 0.01, 0.02, 0.04]
C_GRID = [0.0, 0.3, 0.6, 1.0, 1.5]


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


def nb_cdf(k, mu, v):
    """Negative binomial CDF, mean mu, variance mu + v*mu^2."""
    mu = max(mu, 1e-9)
    if v < 1e-9:
        return pois_cdf(k, mu)
    r = 1.0 / v
    q = mu / (r + mu)
    term = (r / (r + mu)) ** r
    total = term
    for i in range(k):
        term *= (i + r) / (i + 1) * q
        total += term
    return min(max(total, 0.0), 1.0)


def nb_logpmf(k, mu, v):
    mu = max(mu, 1e-9)
    if v < 1e-9:
        return -mu + k * math.log(mu) - math.lgamma(k + 1)
    r = 1.0 / v
    return (
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(r / (r + mu))
        + k * math.log(mu / (r + mu))
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
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d


# ---------------------------------------------------------------------
# PROBABILITY EVALUATION
# ---------------------------------------------------------------------

def probability_metrics(items, probability_key):
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
        if not 0 <= probability <= 1 or actual not in (0, 1):
            continue
        usable.append((probability, actual))
    if not usable:
        return None
    n = len(usable)
    return {
        "n": n,
        "brier": sum((p - y) ** 2 for p, y in usable) / n,
        "observed_rate": sum(y for p, y in usable) / n,
        "mean_probability": sum(p for p, y in usable) / n,
    }


def baseline_probability_metrics(items):
    """row['off'] is a logit: convert with sigmoid() before scoring."""
    usable = []
    for row in items:
        if row.get("off") is None or row.get("y") is None:
            continue
        try:
            p = sigmoid(float(row["off"]))
            y = int(row["y"])
        except (TypeError, ValueError, OverflowError):
            continue
        if y not in (0, 1):
            continue
        usable.append((p, y))
    if not usable:
        return None
    n = len(usable)
    return {
        "n": n,
        "brier": sum((p - y) ** 2 for p, y in usable) / n,
        "observed_rate": sum(y for p, y in usable) / n,
        "mean_probability": sum(p for p, y in usable) / n,
    }


def brier_skill(model_brier, baseline_brier):
    if model_brier is None or baseline_brier is None or baseline_brier <= 0:
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
                wait = int(response.headers.get("Retry-After", "60")) + 2
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
        full_time = (match.get("score") or {}).get("fullTime") or {}
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
    seasons = sorted(set(WARMUP_SEASONS + TEST_SEASONS))
    print(
        "Testing seasons: "
        + ", ".join(f"{s}-{str(s + 1)[2:]}" for s in TEST_SEASONS)
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
                fetch_season(league, season, key), league, season
            )
            time.sleep(6.5)  # football-data.org free-tier rate limit
    return matches


def dump_matches(matches):
    """All finished matches, for offline backtests and ablations."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "matches.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "league", "season", "home", "away", "hg", "ag"])
        for m in sorted(matches, key=lambda m: (m["date"], m["utc"])):
            if m["status"] == "FINISHED" and m["hg"] is not None \
                    and m["ag"] is not None:
                w.writerow([m[k] for k in (
                    "date", "league", "season", "home", "away", "hg", "ag")])
    print(f"Wrote {path}")


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
        if self.N == 0 or home[2] < MIN_GAMES or away[2] < MIN_GAMES:
            return None
        league_average = (self.H + self.A) / (2 * self.N)
        if league_average <= 0:
            return None
        return {
            "hf": home[0], "ha": home[1], "nh": home[2],
            "af": away[0], "aa": away[1], "na": away[2],
            "L": league_average,
            "hm": self.H / self.N,
            "am": self.A / self.N,
            "bu": self.U,
            "bn": self.N,
        }

    def add(self, match):
        home = self.t.setdefault(match["home_id"], [0, 0, 0])
        away = self.t.setdefault(match["away_id"], [0, 0, 0])
        home[0] += match["hg"]
        home[1] += match["ag"]
        home[2] += 1
        away[0] += match["ag"]
        away[1] += match["hg"]
        away[2] += 1
        self.H += match["hg"]
        self.A += match["ag"]
        self.N += 1
        self.U += int(match["hg"] + match["ag"] <= GOAL_LINE)


class JointState:
    """
    Opponent-adjusted attack/defence strengths.

      lambda_home = hm * att[home] * dfn[away]
      lambda_away = am * att[away] * dfn[home]

    Each strength has a Gamma prior with mean 1 and weight K_JOINT games'
    worth of league-average goals. Solved by damped fixed-point iteration,
    warm-started from the previous fit.
    """

    def __init__(self, K=K_JOINT):
        self.K = K
        self.m = []
        self.games = {}
        self.gs = defaultdict(float)
        self.gc = defaultdict(float)
        self.att = defaultdict(lambda: 1.0)
        self.dfn = defaultdict(lambda: 1.0)
        self.H = 0.0
        self.A = 0.0
        self.hm = self.am = 0.0
        self.dirty = False

    def add(self, h, a, hg, ag):
        self.m.append((h, a, hg, ag))
        self.games[h] = self.games.get(h, 0) + 1
        self.games[a] = self.games.get(a, 0) + 1
        self.gs[h] += hg
        self.gc[h] += ag
        self.gs[a] += ag
        self.gc[a] += hg
        self.H += hg
        self.A += ag
        self.dirty = True

    def _fit(self, iters=12):
        n = len(self.m)
        hm, am = self.H / n, self.A / n
        L = (hm + am) / 2
        pk = self.K * L
        for _ in range(iters):
            ea = defaultdict(float)
            ed = defaultdict(float)
            for h, a, _, _ in self.m:
                ea[h] += hm * self.dfn[a]
                ea[a] += am * self.dfn[h]
                ed[h] += am * self.att[a]
                ed[a] += hm * self.att[h]
            for t in self.games:
                na = (self.gs[t] + pk) / (ea[t] + pk)
                nd = (self.gc[t] + pk) / (ed[t] + pk)
                self.att[t] = 0.5 * self.att[t] + 0.5 * na
                self.dfn[t] = 0.5 * self.dfn[t] + 0.5 * nd
        self.hm, self.am = hm, am
        self.dirty = False

    def feats(self, h, a):
        if (
            not self.m
            or self.games.get(h, 0) < MIN_GAMES
            or self.games.get(a, 0) < MIN_GAMES
        ):
            return None
        if self.dirty:
            self._fit()
        lh = self.hm * self.att[h] * self.dfn[a]
        la = self.am * self.att[a] * self.dfn[h]
        return {
            "lam": lh + la,
            "g": 0.5 * (self.games[h] + self.games[a]),
        }


class State2(SeasonState):
    """SeasonState (baseline counts) + JointState (expected goals)."""

    def __init__(self):
        super().__init__()
        self.js = JointState()

    def feats(self, home_id, away_id):
        f = super().feats(home_id, away_id)
        if f is None:
            return None
        j = self.js.feats(home_id, away_id)
        if j is None:
            return None
        f.update(j)
        return f

    def add(self, match):
        super().add(match)
        self.js.add(
            match["home_id"], match["away_id"], match["hg"], match["ag"]
        )


def v_eff(f, nbpar):
    v0, c = nbpar
    return v0 + c / max(f["g"], 1.0)


def raw_prob(f, nbpar):
    """P(total goals <= GOAL_LINE) from the joint strengths."""
    if USE_NB:
        return nb_cdf(GOAL_LINE, f["lam"], v_eff(f, nbpar))
    return pois_cdf(GOAL_LINE, f["lam"])


def tune_nb(rows):
    """Choose (v0, c) by NLL on EARLIER seasons only. Only used if USE_NB."""
    use = [r for r in rows if r["f"] is not None]
    if len(use) < 150:
        return (0.02, 0.6)
    best = None
    for v0 in V0_GRID:
        for c in C_GRID:
            nll = -sum(
                nb_logpmf(r["tot"], r["f"]["lam"], v_eff(r["f"], (v0, c)))
                for r in use
            )
            if best is None or nll < best[0]:
                best = (nll, v0, c)
    return (best[1], best[2])


def build_rows(matches):
    by_league_season = defaultdict(list)
    for match in matches:
        by_league_season[(match["league"], match["season"])].append(match)

    rows = []
    states = {}

    for key, season_matches in by_league_season.items():
        state = State2()
        finished = sorted(
            (
                m for m in season_matches
                if m["status"] == "FINISHED"
                and m["hg"] is not None
                and m["ag"] is not None
            ),
            key=lambda m: (m["date"], m["utc"]),
        )
        i = 0
        while i < len(finished):
            j = i
            while j < len(finished) and finished[j]["date"] == finished[i]["date"]:
                j += 1
            day = finished[i:j]

            # Predict using earlier dates only...
            for match in day:
                rows.append(dict(
                    match,
                    f=state.feats(match["home_id"], match["away_id"]),
                    tot=match["hg"] + match["ag"],
                ))
            # ...then learn that date's results.
            for match in day:
                state.add(match)
            i = j
        states[key] = state

    return rows, states


def season_base(features, prior):
    return (
        features["bu"] + BASE_PRIOR_N * prior
    ) / (features["bn"] + BASE_PRIOR_N)


def fit_slope(data):
    """Calibration slope (ridge toward 1), past observations only."""
    b = 1.0
    for _ in range(40):
        gradient = 0.0
        hessian = 0.0
        for offset, x, actual in data:
            probability = sigmoid(offset + b * x)
            gradient += (probability - actual) * x
            hessian += probability * (1 - probability) * x * x
        gradient += RIDGE * (b - 1.0)
        hessian += RIDGE
        change = gradient / hessian
        b -= change
        if abs(change) < 1e-9:
            break
    return min(max(b, 0.0), 1.0)


def league_deltas(history, slope):
    """
    Shrunk per-league logit offsets from earlier matches only.
    One ridge-penalised Newton step from zero:
        delta = sum(y - p) / (sum p(1-p) + LEAGUE_RIDGE)
    """
    if LEAGUE_RIDGE < 0:
        return {}
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for h in history:
        p = sigmoid(h["off"] + slope * h["x"])
        a = acc[h["league"]]
        a[0] += h["y"] - p
        a[1] += p * (1 - p)
        a[2] += 1
    out = {}
    for league, (resid, weight, n) in acc.items():
        out[league] = (
            resid / (weight + LEAGUE_RIDGE) if n >= MIN_LEAGUE_N else 0.0
        )
    return out


def make_features(row, prior):
    baseline = season_base(row["f"], prior)
    row["off"] = logit(baseline)
    row["x"] = logit(row["p_raw"]) - row["off"]


def guard(probability, calibration_history):
    """Conservative lower confidence bound from similar past predictions."""
    if len(calibration_history) < MIN_NEIGHBOURS:
        return None
    neighbours = sorted(
        calibration_history,
        key=lambda item: abs(item["p_cal"] - probability),
    )[:NEIGHBOURS]
    hits = sum(item["y"] for item in neighbours)
    bound = min(
        probability,
        wilson_lower(hits, len(neighbours), SAFETY_Z),
    )
    return min(bound, P_CAP)


def walk_forward(rows):
    seasons = sorted({row["season"] for row in rows})

    nb_by = {
        season: (
            tune_nb([r for r in rows if r["season"] < season])
            if USE_NB else (0.0, 0.0)
        )
        for season in seasons
    }

    model = [row for row in rows if row["f"] is not None]

    for row in model:
        row["p_raw"] = raw_prob(row["f"], nb_by[row["season"]])
        row["y"] = int(row["tot"] <= GOAL_LINE)
        row["p_cal"] = None
        row["p_final"] = None

    model.sort(key=lambda row: (row["date"], row["utc"]))

    history = []
    calibration_history = []
    ysum = 0
    i = 0

    while i < len(model):
        j = i
        while j < len(model) and model[j]["date"] == model[i]["date"]:
            j += 1
        day = model[i:j]

        prior = ysum / len(history) if history else BASE_DEFAULT

        for row in day:
            make_features(row, prior)

        slope = (
            fit_slope([(h["off"], h["x"], h["y"]) for h in history])
            if len(history) >= MIN_HISTORY
            else None
        )
        deltas = league_deltas(history, slope) if slope is not None else {}

        # Predict the whole date before learning its results.
        for row in day:
            if slope is not None:
                row["slope"] = slope
                row["delta"] = deltas.get(row["league"], 0.0)
                row["p_cal"] = sigmoid(
                    row["off"] + slope * row["x"] + row["delta"]
                )
                row["p_final"] = guard(row["p_cal"], calibration_history)

        for row in day:
            history.append(row)
            ysum += row["y"]
            if row["p_cal"] is not None:
                calibration_history.append(row)

        i = j

    return model, nb_by


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
    model_metrics = probability_metrics(scored, "p_final")
    baseline_metrics = baseline_probability_metrics(scored)

    print("\nProbability diagnostics (all scored test matches)")

    if model_metrics is None:
        print("  No final probabilities available.")
        return

    print(f"  Scored matches: {model_metrics['n']}")
    print(f"  Model mean probability: "
          f"{model_metrics['mean_probability'] * 100:.2f}%")
    print(f"  Model observed Under 3.5 rate: "
          f"{model_metrics['observed_rate'] * 100:.2f}%")
    print(f"  Model Brier score: {model_metrics['brier']:.5f}")

    if baseline_metrics is None:
        print("  Baseline metrics unavailable.")
        return

    skill = brier_skill(model_metrics["brier"], baseline_metrics["brier"])
    print(f"  Baseline mean probability: "
          f"{baseline_metrics['mean_probability'] * 100:.2f}%")
    print(f"  Baseline Brier score: {baseline_metrics['brier']:.5f}")

    if skill is not None:
        print(f"  Brier skill: {skill:+.5f}")
        if skill > 0:
            print("  Interpretation: model beats the season-baseline "
                  "forecast on Brier score.")
        elif skill < 0:
            print("  Interpretation: model is worse than the "
                  "season-baseline forecast on Brier score.")
        else:
            print("  Interpretation: model matches the season-baseline "
                  "forecast on Brier score.")


def gap_text(group, key="p_cal"):
    n = len(group)
    if not n:
        return "n=0"
    mp = sum(r[key] for r in group) / n
    hr = sum(r["y"] for r in group) / n
    return f"avg p {mp * 100:.1f}% hit {hr * 100:.1f}% gap {(mp - hr) * 100:+.1f}"


def report(model, rows):
    test = [row for row in model if row["season"] in TEST_SEASONS]
    scored = [row for row in test if row["p_final"] is not None]
    test_all = [row for row in rows if row["season"] in TEST_SEASONS]
    skipped = len(test_all) - len(scored)

    print("\nWalking forward through finished matches...\n")
    print(f"{len(scored)} matches checked, {skipped} skipped "
          "(not enough prior data at the time)")

    cleared = sorted(
        [row for row in scored if row["p_final"] >= THRESHOLD],
        key=lambda row: (row["date"], row["utc"]),
    )
    hits = sum(row["y"] for row in cleared)

    print(f"{len(cleared)} would have cleared {THRESHOLD * 100:.1f}% "
          "(final, after calibration + safety haircut)")

    if cleared:
        hit_rate = hits / len(cleared)
        print(f"{hits}/{len(cleared)} hit -> {hit_rate * 100:.1f}% "
              f"(break-even odds {len(cleared) / max(hits, 1):.2f})")
        print("Longest losing run among cleared: "
              f"{longest_losing_run([r['y'] for r in cleared])}")

        mean_final = sum(r["p_final"] for r in cleared) / len(cleared)
        mean_calibrated = sum(r["p_cal"] for r in cleared) / len(cleared)
        gap = mean_calibrated - hit_rate

        print(f"Average final probability {mean_final * 100:.1f}% | "
              f"calibrated {mean_calibrated * 100:.1f}% | "
              f"actual {hit_rate * 100:.1f}%")
        print(f"OVERCONFIDENCE GAP (avg calibrated p - hit rate): "
              f"{gap * 100:+.1f} points")

        if gap > 0.03:
            print("WARNING: calibrated probabilities exceed the actual "
                  f"hit rate by {gap * 100:.1f} points.")
        else:
            print("Overconfidence check: calibrated probability is not "
                  "more than 3 points above the actual rate.")

    print_probability_diagnostics(scored)

    print("\nBy season (cleared matches)")
    for season in TEST_SEASONS:
        cleared_season = [r for r in cleared if r["season"] == season]
        all_season = [r for r in scored if r["season"] == season]
        if not all_season:
            print(f"  {season}: no scored matches")
            continue
        base_rate = sum(r["y"] for r in all_season) / len(all_season)
        line = (f"  {season}-{str(season + 1)[2:]}: "
                f"all matches {len(all_season)}, "
                f"Under 3.5 rate {base_rate * 100:.1f}%")
        if cleared_season:
            sh = sum(r["y"] for r in cleared_season)
            line += (f" | cleared {len(cleared_season)}, "
                     f"hit {sh}/{len(cleared_season)} "
                     f"= {sh / len(cleared_season) * 100:.1f}% "
                     f"({gap_text(cleared_season)})")
        else:
            line += " | cleared 0"
        print(line)

    print("\nBy league (cleared matches)")
    for league in LEAGUES:
        lc = [r for r in cleared if r["league"] == league]
        ls = [r for r in scored if r["league"] == league]
        if not ls:
            print(f"  {league}: no scored matches")
            continue
        actual_rate = sum(r["y"] for r in ls) / len(ls)
        line = (f"  {league}: scored {len(ls)}, "
                f"actual Under 3.5 rate {actual_rate * 100:.1f}%")
        if lc:
            lh = sum(r["y"] for r in lc)
            line += (f" | cleared {len(lc)}, hit {lh}/{len(lc)} "
                     f"= {lh / len(lc) * 100:.1f}% ({gap_text(lc)})")
        else:
            line += " | cleared 0"
        print(line)

    print("\nCalibration table "
          "(all scored matches, grouped by final probability)")
    print("  bucket        n   avg raw  avg final  actual")
    edges = [0.0, 0.55, 0.60, 0.65, 0.70, 0.75, 1.01]
    for low, high in zip(edges, edges[1:]):
        group = [r for r in scored if low <= r["p_final"] < high]
        if not group:
            continue
        n = len(group)
        print(f"  {low:.2f}-{min(high, 1.0):.2f} {n:4d}   "
              f"{sum(r['p_raw'] for r in group) / n * 100:5.1f}%    "
              f"{sum(r['p_final'] for r in group) / n * 100:5.1f}%   "
              f"{sum(r['y'] for r in group) / n * 100:5.1f}%")

    print("\nThreshold sweep (final probability)")
    for threshold in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        group = sorted(
            [r for r in scored if r["p_final"] >= threshold],
            key=lambda r: (r["date"], r["utc"]),
        )
        if not group:
            print(f"  >= {threshold:.2f}: n=0")
            continue
        gh = sum(r["y"] for r in group)
        print(f"  >= {threshold:.2f}: n={len(group):4d} "
              f"hit {gh}/{len(group)} = {gh / len(group) * 100:.1f}% "
              f"break-even odds {len(group) / max(gh, 1):.2f} "
              f"longest losing run "
              f"{longest_losing_run([r['y'] for r in group])} "
              f"({gap_text(group)})")

    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "core2_results.csv")

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "date", "league", "season", "home", "away", "hg", "ag",
            "p_raw", "p_cal", "p_final", "baseline_probability",
            "league_delta", "hit", "cleared",
        ])
        for row in sorted(scored, key=lambda r: (r["date"], r["utc"])):
            writer.writerow([
                row["date"], row["league"], row["season"],
                row["home"], row["away"], row["hg"], row["ag"],
                f"{row['p_raw']:.4f}",
                f"{row['p_cal']:.4f}",
                f"{row['p_final']:.4f}",
                f"{sigmoid(row['off']):.4f}",
                f"{row.get('delta', 0.0):.4f}",
                row["y"],
                int(row["p_final"] >= THRESHOLD),
            ])

    print(f"\nWrote {path}")


# ---------------------------------------------------------------------
# UPCOMING FIXTURES
# ---------------------------------------------------------------------

def upcoming(matches, states, rows, model, nb_by):
    if UPCOMING_DAYS <= 0:
        return

    latest = max(TEST_SEASONS)
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=UPCOMING_DAYS)

    fixtures = [
        m for m in matches
        if m["season"] == latest
        and m["status"] in ("SCHEDULED", "TIMED")
        and today.isoformat() <= m["date"] <= end.isoformat()
    ]

    print(f"\nUpcoming fixtures (next {UPCOMING_DAYS} days)")

    if not fixtures:
        print("  none found")
        return

    done = [row for row in model if row["p_cal"] is not None]

    if len(model) < MIN_HISTORY:
        print("  not enough history yet to calibrate")
        return

    prior = sum(row["y"] for row in model) / len(model)
    slope = fit_slope([(r["off"], r["x"], r["y"]) for r in model])
    deltas = league_deltas(model, slope)
    nbpar = nb_by.get(latest, (0.02, 0.6))

    for match in sorted(fixtures, key=lambda item: item["utc"]):
        state = states.get((match["league"], latest))
        features = (
            state.feats(match["home_id"], match["away_id"]) if state else None
        )
        if features is None:
            print(f"  {match['date']} {match['league']:<4} "
                  f"{match['home']} vs {match['away']} "
                  "- not enough games yet")
            continue

        p_raw = raw_prob(features, nbpar)
        offset = logit(season_base(features, prior))
        p_cal = sigmoid(
            offset
            + slope * (logit(p_raw) - offset)
            + deltas.get(match["league"], 0.0)
        )
        p_final = guard(p_cal, done)

        if p_final is None:
            print(f"  {match['date']} {match['league']:<4} "
                  f"{match['home']} vs {match['away']} "
                  "- not enough history")
            continue

        flag = "CLEARS" if p_final >= THRESHOLD else "below"
        print(f"  {match['date']} {match['league']:<4} "
              f"{match['home']} vs {match['away']} "
              f"{p_final * 100:.1f}% (raw {p_raw * 100:.1f}%) "
              f"fair odds {1 / p_final:.2f} {flag}")


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------

def run(matches):
    dump_matches(matches)

    rows, states = build_rows(matches)
    model, nb_by = walk_forward(rows)

    if USE_NB:
        print(f"Tuned negative-binomial (v0, c) by season: {nb_by}")
    else:
        print("Predictive: Poisson on joint strengths (USE_NB=0)")
    print(f"K_JOINT={K_JOINT}  LEAGUE_RIDGE={LEAGUE_RIDGE}  P_CAP={P_CAP}")

    report(model, rows)
    upcoming(matches, states, rows, model, nb_by)


def main():
    print("Barbadox Core 2 v2 - Under 3.5 goals")
    if not 0 < THRESHOLD < 1:
        sys.exit("THRESHOLD must be between 0 and 1.")
    if SAFETY_Z < 0:
        sys.exit("SAFETY_Z cannot be negative.")
    run(load_matches())


if __name__ == "__main__":
    main()
