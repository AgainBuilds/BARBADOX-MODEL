#!/usr/bin/env python3
"""
Barbadox Core 2 - Under 3.5 goals - walk-forward calibration check.

What it does
  1. Pulls finished matches from football-data.org (v4) for each league/season.
  2. Walks forward through them in date order. Every prediction uses ONLY matches
     played on earlier dates in the SAME season (no previous-season stats in the
     team ratings, no future results).
  3. Model: shrunk attack/defence Poisson.  Expected goals for each side come from
     team goals scored/conceded so far, pulled toward the league average (K).
     P(Under 3.5) = P(total goals <= 3), with total goals ~ Poisson(lam_home+lam_away).
     K is tuned only on seasons BEFORE the one being tested.
  4. Anti-overconfidence layers (all walk-forward, never see the match being scored):
       a) Season level: the baseline is this league-season's Under 3.5 rate so far
          (blended with earlier seasons while the season is young), so a high- or
          low-scoring season does not fool the model.
       b) Calibration: how far a match sits above/below that baseline is multiplied by a
          factor fitted on earlier matches and capped at 1.0, so calibration can pull
          predictions toward the baseline but never push them further away.
       c) Safety haircut: the final probability is the LOWER confidence bound of how
          often similar earlier predictions actually hit (SAFETY_Z=0 disables).
       d) A match cannot clear until enough earlier history exists.
  5. Prints every match that clears THRESHOLD with HIT/MISS, then a calibration table,
     a threshold sweep, and (optionally) upcoming fixtures.

Environment variables (all optional except the API key)
  FOOTBALL_DATA_API_KEY   football-data.org token (also reads FOOTBALL_DATA_TOKEN, FOOTBALL_API_KEY, API_KEY)
  LEAGUES                 comma list of competition codes, default "PL,PD,FL1,BL1,SA"
  TEST_SEASONS            start years of seasons to test, default "2024,2025,2026" (3 seasons)
  WARMUP_SEASONS          extra earlier seasons used only for tuning/calibration, default "2023"
  THRESHOLD               final-probability cutoff, default 0.75
  SAFETY_Z                haircut strength, default 1.0 (0 = off)
  UPCOMING_DAYS           list upcoming fixtures this many days ahead, default 7 (0 = off)
  REPORT_DIR              where the CSV is written, default "reports"
"""
import csv
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

API = "https://api.football-data.org/v4"

LEAGUES = [x.strip() for x in os.getenv("LEAGUES", "PL,PD,FL1,BL1,SA").split(",") if x.strip()]
TEST_SEASONS = [int(x) for x in os.getenv("TEST_SEASONS", "2024,2025,2026").split(",") if x.strip()]
WARMUP_SEASONS = [int(x) for x in os.getenv("WARMUP_SEASONS", "2023").split(",") if x.strip()]
THRESHOLD = float(os.getenv("THRESHOLD", "0.75"))
SAFETY_Z = float(os.getenv("SAFETY_Z", "1.0"))
UPCOMING_DAYS = int(os.getenv("UPCOMING_DAYS", "7"))
REPORT_DIR = os.getenv("REPORT_DIR", "reports")

GOAL_LINE = 3            # Under 3.5  ==  3 goals or fewer
MIN_GAMES = 5            # each team needs this many earlier games in the season
K_GRID = [0, 10, 20, 30, 45, 60, 80, 120]
K_DEFAULT = 60           # used when there is not enough earlier data to tune K
MIN_HISTORY = 120        # earlier matches needed before calibration switches on
NEIGHBOURS = 150         # similar-probability earlier matches used for the haircut
MIN_NEIGHBOURS = 60
RIDGE = 4.0              # pulls calibration toward "no change"
BASE_PRIOR_N = 30        # weight (in matches) of earlier seasons in the season baseline
BASE_DEFAULT = 0.65      # baseline used before any history exists


# ----------------------------------------------------------------- maths helpers
def pois_cdf(k, lam):
    lam = max(lam, 1e-9)
    term = math.exp(-lam)
    s = term
    for i in range(1, k + 1):
        term *= lam / i
        s += term
    return min(max(s, 0.0), 1.0)


def pois_logpmf(k, lam):
    lam = max(lam, 1e-9)
    return -lam + k * math.log(lam) - math.lgamma(k + 1)


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


# ----------------------------------------------------------------------- data
def api_key():
    for name in ("FOOTBALL_DATA_API_KEY", "FOOTBALL_DATA_TOKEN", "FOOTBALL_API_KEY", "API_KEY"):
        v = os.getenv(name)
        if v:
            return v
    sys.exit("No API key found. Set FOOTBALL_DATA_API_KEY (repo secret) and pass it to this step.")


def fetch_season(code, season, key):
    import requests
    url = f"{API}/competitions/{code}/matches"
    for _ in range(6):
        r = requests.get(url, headers={"X-Auth-Token": key}, params={"season": season}, timeout=60)
        print(f"  API GET /competitions/{code}/matches -> HTTP {r.status_code}")
        if r.status_code == 200:
            return r.json().get("matches", [])
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "60")) + 2
            print(f"  rate limited, waiting {wait}s")
            time.sleep(wait)
        elif r.status_code in (400, 403, 404):
            print(f"  {code} {season} not available on this plan/token - skipping")
            return []
        else:
            time.sleep(5)
    return []


def normalise(raw, league, season):
    out = []
    for m in raw:
        ft = (m.get("score") or {}).get("fullTime") or {}
        out.append({
            "league": league, "season": season,
            "date": m["utcDate"][:10], "utc": m["utcDate"],
            "home_id": m["homeTeam"]["id"], "away_id": m["awayTeam"]["id"],
            "home": m["homeTeam"].get("name") or str(m["homeTeam"]["id"]),
            "away": m["awayTeam"].get("name") or str(m["awayTeam"]["id"]),
            "status": m.get("status", ""), "hg": ft.get("home"), "ag": ft.get("away"),
        })
    return out


def load_matches():
    key = api_key()
    seasons = sorted(set(WARMUP_SEASONS + TEST_SEASONS))
    print(f"Testing seasons: {', '.join(f'{s}-{str(s + 1)[2:]}' for s in TEST_SEASONS)}")
    print(f"Fetching {len(seasons)} seasons of raw data total "
          f"(warm-up seasons only feed tuning and calibration, they aren't tested)...")
    matches = []
    for lg in LEAGUES:
        for s in seasons:
            print(f"  fetching {lg} {s}...")
            matches += normalise(fetch_season(lg, s, key), lg, s)
            time.sleep(6.5)  # free tier: 10 requests/minute
    return matches


# ---------------------------------------------------------------------- model
class SeasonState:
    """Running totals for one league-season. Updated only after a date is finished."""

    def __init__(self):
        self.t = {}          # team id -> [goals_for, goals_against, games]
        self.H = self.A = self.N = self.U = 0

    def feats(self, hid, aid):
        h = self.t.get(hid, [0, 0, 0])
        a = self.t.get(aid, [0, 0, 0])
        if self.N == 0 or h[2] < MIN_GAMES or a[2] < MIN_GAMES:
            return None
        L = (self.H + self.A) / (2 * self.N)
        if L <= 0:
            return None
        return {"hf": h[0], "ha": h[1], "nh": h[2], "af": a[0], "aa": a[1], "na": a[2],
                "L": L, "hm": self.H / self.N, "am": self.A / self.N, "bu": self.U, "bn": self.N}

    def add(self, m):
        h = self.t.setdefault(m["home_id"], [0, 0, 0])
        a = self.t.setdefault(m["away_id"], [0, 0, 0])
        h[0] += m["hg"]; h[1] += m["ag"]; h[2] += 1
        a[0] += m["ag"]; a[1] += m["hg"]; a[2] += 1
        self.H += m["hg"]; self.A += m["ag"]; self.N += 1
        self.U += int(m["hg"] + m["ag"] <= GOAL_LINE)


def lam_total(f, K):
    L = f["L"]

    def sh(s, n):
        return ((s + K * L) / (n + K)) / L

    lam_h = sh(f["hf"], f["nh"]) * sh(f["aa"], f["na"]) * f["hm"]
    lam_a = sh(f["af"], f["na"]) * sh(f["ha"], f["nh"]) * f["am"]
    return lam_h + lam_a


def build_rows(matches):
    by = defaultdict(list)
    for m in matches:
        by[(m["league"], m["season"])].append(m)
    rows, states = [], {}
    for key, ms in by.items():
        st = SeasonState()
        fin = sorted((m for m in ms if m["status"] == "FINISHED" and m["hg"] is not None and m["ag"] is not None),
                     key=lambda m: (m["date"], m["utc"]))
        i = 0
        while i < len(fin):
            j = i
            while j < len(fin) and fin[j]["date"] == fin[i]["date"]:
                j += 1
            day = fin[i:j]
            for m in day:                       # predict first ...
                rows.append(dict(m, f=st.feats(m["home_id"], m["away_id"]), tot=m["hg"] + m["ag"]))
            for m in day:                       # ... then learn
                st.add(m)
            i = j
        states[key] = st
    return rows, states


def tune_k(rows):
    use = [r for r in rows if r["f"] is not None]
    if len(use) < 150:
        return K_DEFAULT
    best = None
    for K in K_GRID:
        nll = sum(-pois_logpmf(r["tot"], lam_total(r["f"], K)) for r in use)
        if best is None or nll < best[1]:
            best = (K, nll)
    return best[0]


def season_base(f, prior):
    """Under 3.5 rate so far this league-season, blended with earlier seasons while it is young."""
    return (f["bu"] + BASE_PRIOR_N * prior) / (f["bn"] + BASE_PRIOR_N)


def fit_slope(data):
    """data = (offset, x, y). Fit y ~ sigmoid(offset + b*x), ridge toward b=1, then cap b to [0, 1]."""
    b = 1.0
    for _ in range(40):
        g = h = 0.0
        for off, x, y in data:
            p = sigmoid(off + b * x)
            g += (p - y) * x
            h += p * (1 - p) * x * x
        g += RIDGE * (b - 1.0)
        h += RIDGE
        db = g / h
        b -= db
        if abs(db) < 1e-9:
            break
    return min(max(b, 0.0), 1.0)


def make_features(r, prior):
    base = season_base(r["f"], prior)
    off = logit(base)
    r["off"] = off
    r["x"] = logit(r["p_raw"]) - off


def guard(p_cal, cal_hist):
    """Lower confidence bound of how often similar earlier predictions really hit."""
    if len(cal_hist) < MIN_NEIGHBOURS:
        return None
    nb = sorted(cal_hist, key=lambda h: abs(h["p_cal"] - p_cal))[:NEIGHBOURS]
    hits = sum(h["y"] for h in nb)
    return min(p_cal, wilson_lower(hits, len(nb), SAFETY_Z))


def walk_forward(rows):
    seasons = sorted({r["season"] for r in rows})
    k_by = {s: tune_k([r for r in rows if r["season"] < s]) for s in seasons}
    model = [r for r in rows if r["f"] is not None]
    for r in model:
        r["p_raw"] = pois_cdf(GOAL_LINE, lam_total(r["f"], k_by[r["season"]]))
        r["y"] = int(r["tot"] <= GOAL_LINE)
        r["p_cal"] = r["p_final"] = None
    model.sort(key=lambda r: (r["date"], r["utc"]))
    hist, cal_hist = [], []
    ysum = 0
    i = 0
    while i < len(model):
        j = i
        while j < len(model) and model[j]["date"] == model[i]["date"]:
            j += 1
        prior = ysum / len(hist) if hist else BASE_DEFAULT
        day = model[i:j]
        for r in day:
            make_features(r, prior)
        b = fit_slope([(h["off"], h["x"], h["y"]) for h in hist]) if len(hist) >= MIN_HISTORY else None
        for r in day:
            if b is not None:
                r["slope"] = b
                r["p_cal"] = sigmoid(r["off"] + b * r["x"])
                r["p_final"] = guard(r["p_cal"], cal_hist)
        for r in day:
            hist.append(r)
            ysum += r["y"]
            if r["p_cal"] is not None:
                cal_hist.append(r)
        i = j
    return model, k_by


# -------------------------------------------------------------------- reports
def longest_losing_run(seq):
    best = run = 0
    for y in seq:
        run = 0 if y else run + 1
        best = max(best, run)
    return best


def report(model, rows):
    test = [r for r in model if r["season"] in TEST_SEASONS]
    scored = [r for r in test if r["p_final"] is not None]
    test_all = [r for r in rows if r["season"] in TEST_SEASONS]
    skipped = len(test_all) - len(scored)
    print("\nWalking forward through finished matches...\n")
    print(f"{len(scored)} matches checked, {skipped} skipped (not enough prior data at the time)")
    cleared = sorted([r for r in scored if r["p_final"] >= THRESHOLD], key=lambda r: (r["date"], r["utc"]))
    hits = sum(r["y"] for r in cleared)
    print(f"{len(cleared)} would have cleared {THRESHOLD * 100:.1f}% (final, after calibration + safety haircut)")
    if cleared:
        print(f"{hits}/{len(cleared)} of those hit -> {hits / len(cleared) * 100:.0f}%   "
              f"(break-even odds {len(cleared) / max(hits, 1):.2f})")
        print(f"longest losing run among cleared: {longest_losing_run([r['y'] for r in cleared])}")
        mean_pred = sum(r["p_final"] for r in cleared) / len(cleared)
        mean_cal = sum(r["p_cal"] for r in cleared) / len(cleared)
        gap = mean_cal - hits / len(cleared)
        print(f"average final probability {mean_pred * 100:.1f}% | calibrated {mean_cal * 100:.1f}% | actual {hits / len(cleared) * 100:.1f}%")
        if gap > 0.03:
            print(f"WARNING: still overconfident by {gap * 100:.1f} points on cleared matches - raise SAFETY_Z or THRESHOLD")
        else:
            print("Overconfidence check: OK (calibrated probability is not above the actual hit rate by more than 3 points)")
    print()
    for r in cleared:
        print(f"  {r['date']} {r['league']:<4} {r['home']} vs {r['away']}  {r['p_final'] * 100:.1f}%  "
              f"{'HIT' if r['y'] else 'MISS'}  ({r['hg']}-{r['ag']})")

    print("\nBy season (cleared matches)")
    for s in TEST_SEASONS:
        c = [r for r in cleared if r["season"] == s]
        allm = [r for r in scored if r["season"] == s]
        if allm:
            base = sum(r["y"] for r in allm) / len(allm)
            line = f"  {s}-{str(s + 1)[2:]}: all matches {len(allm)}, Under 3.5 rate {base * 100:.1f}%"
            if c:
                line += f" | cleared {len(c)}, hit {sum(r['y'] for r in c)}/{len(c)} = {sum(r['y'] for r in c) / len(c) * 100:.0f}%"
            else:
                line += " | cleared 0"
            print(line)

    print("\nCalibration table (all scored matches, grouped by final probability)")
    print("  bucket        n   avg raw  avg final  actual")
    edges = [0.0, 0.55, 0.60, 0.65, 0.70, 0.75, 1.01]
    for lo, hi in zip(edges, edges[1:]):
        g = [r for r in scored if lo <= r["p_final"] < hi]
        if g:
            print(f"  {lo:.2f}-{min(hi, 1.0):.2f}  {len(g):4d}   {sum(r['p_raw'] for r in g) / len(g) * 100:5.1f}%    "
                  f"{sum(r['p_final'] for r in g) / len(g) * 100:5.1f}%   {sum(r['y'] for r in g) / len(g) * 100:5.1f}%")

    print("\nThreshold sweep (final probability)")
    for t in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        g = sorted([r for r in scored if r["p_final"] >= t], key=lambda r: (r["date"], r["utc"]))
        if g:
            h = sum(r["y"] for r in g)
            print(f"  >= {t:.2f}: n={len(g):4d}  hit {h}/{len(g)} = {h / len(g) * 100:4.1f}%  "
                  f"break-even odds {len(g) / max(h, 1):.2f}  longest losing run {longest_losing_run([r['y'] for r in g])}")
        else:
            print(f"  >= {t:.2f}: n=   0")

    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "core2_results.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "league", "season", "home", "away", "hg", "ag", "p_raw", "p_cal", "p_final", "hit", "cleared"])
        for r in sorted(scored, key=lambda r: (r["date"], r["utc"])):
            w.writerow([r["date"], r["league"], r["season"], r["home"], r["away"], r["hg"], r["ag"],
                        f"{r['p_raw']:.4f}", f"{r['p_cal']:.4f}", f"{r['p_final']:.4f}", r["y"],
                        int(r["p_final"] >= THRESHOLD)])
    print(f"\nWrote {path}")


def upcoming(matches, states, rows, model, k_by):
    if UPCOMING_DAYS <= 0:
        return
    latest = max(TEST_SEASONS)
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=UPCOMING_DAYS)
    fixtures = [m for m in matches if m["season"] == latest and m["status"] in ("SCHEDULED", "TIMED")
                and today.isoformat() <= m["date"] <= end.isoformat()]
    print(f"\nUpcoming fixtures (next {UPCOMING_DAYS} days)")
    if not fixtures:
        print("  none found")
        return
    done = [r for r in model if r["p_cal"] is not None]
    if len(model) < MIN_HISTORY:
        print("  not enough history yet to calibrate")
        return
    prior = sum(r["y"] for r in model) / len(model)
    b = fit_slope([(r["off"], r["x"], r["y"]) for r in model])
    K = k_by.get(latest) or tune_k([r for r in rows if r["season"] < latest])
    for m in sorted(fixtures, key=lambda m: m["utc"]):
        st = states.get((m["league"], latest))
        f = st.feats(m["home_id"], m["away_id"]) if st else None
        if f is None:
            print(f"  {m['date']} {m['league']:<4} {m['home']} vs {m['away']}  - not enough games yet")
            continue
        p_raw = pois_cdf(GOAL_LINE, lam_total(f, K))
        off = logit(season_base(f, prior))
        p_cal = sigmoid(off + b * (logit(p_raw) - off))
        p_fin = guard(p_cal, done)
        if p_fin is None:
            print(f"  {m['date']} {m['league']:<4} {m['home']} vs {m['away']}  - not enough history")
            continue
        flag = "CLEARS" if p_fin >= THRESHOLD else "below"
        print(f"  {m['date']} {m['league']:<4} {m['home']} vs {m['away']}  {p_fin * 100:.1f}% "
              f"(raw {p_raw * 100:.1f}%)  fair odds {1 / p_fin:.2f}  {flag}")


def run(matches):
    rows, states = build_rows(matches)
    model, k_by = walk_forward(rows)
    print(f"Tuned shrinkage K by season: {k_by}")
    report(model, rows)
    upcoming(matches, states, rows, model, k_by)


def main():
    print("Barbadox Core 2 - Under 3.5 goals")
    run(load_matches())


if __name__ == "__main__":
    main()
