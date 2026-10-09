#!/usr/bin/env python3
"""
Barbadox's Model (core, standalone)
====================================
Football Over 1.5 goals model. Leagues: Premier League, La Liga, Ligue 1, Bundesliga,
Serie A, Champions League, and (if API_FOOTBALL_KEY is set) the Saudi League.

This is the ORIGINAL model, nothing more:
    1. Recent form. Poisson goal expectancy from each team's current-season home/away
       goals for and against, versus the league average.
    2. Historical baseline. The same Poisson check over the team's previous ~38 league
       matches. 1 and 2 are blended (current form gets more weight as the season goes on).
    3. Formation and structure. Adjustment from a hand-entered "formation effect" score
       (-2 to +2): the formation now versus the shape the team wins and scores in.
    4. Squad rotation, injuries, fixture congestion. Every missing player is rated by
       importance (top scorer / first-choice keeper matters far more than a squad player).
    5. Derby or rivalry. Widens the confidence range instead of moving the point estimate.
    Game-state check (two-sided, informational): does the favourite usually keep scoring
    after taking a lead, does the underdog usually respond after going behind. A risk flag,
    not a hard override.
    Field temperature is logged for every pick and never changes a probability.

Factors 3-5 and the game-state check are OPTIONAL. If you never touch context.csv, the
model still runs on factors 1+2 alone and says so plainly in the factor sheet. Nothing
here calls out to an LLM, a search API, or any paid service. The only network calls are
to football-data.org (free tier) for fixtures and results.

USAGE
    python barbadox_core.py run                        # today + next 3 days, all leagues
    python barbadox_core.py run --date 2026-10-10 --days 3
    python barbadox_core.py run --leagues PL,PD --threshold 0.79
    python barbadox_core.py review                      # grade logged picks against results

SETUP (once)
    pip install -r requirements.txt
    Set FOOTBALL_DATA_KEY as an environment variable (free key:
    https://www.football-data.org/client/register). Optionally set API_FOOTBALL_KEY
    (free at api-football.com) to also cover the Saudi League.

FILLING IN FACTORS 3-5 (optional, by hand)
    `run` rebuilds context.csv once per day with only fixtures that already clear the
    threshold (core probability). Same-day re-runs only append newly qualified ones.
    Edit a row on GitHub (or locally), then set checked=1. Leave fields blank to leave
    that factor unadjusted. See README.md for the exact columns and what each means.

NOTE ON THE ADJUSTMENT SIZES
    The numbers in CFG (absences, rotation, formation, derby spread) are starting values
    carried over unchanged from the original model, not independently fitted. Tune them
    against your own picks.csv and results over time if you want to.
"""
import argparse
import csv
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTEXT_FILE = BASE_DIR / "context.csv"
PICKS_FILE = BASE_DIR / "picks.csv"

API_BASE = os.environ.get("BARBADOX_API_BASE", "https://api.football-data.org/v4")
MIN_CALL_GAP = float(os.environ.get("BARBADOX_MIN_INTERVAL", "6.5"))  # free tier: 10 calls/min

LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "FL1": "Ligue 1",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "CL": "Champions League",
    "SAUDI": "Saudi League",
}
API_CODES = {"PL", "PD", "FL1", "BL1", "SA", "CL"}
DOMESTIC = ["PL", "PD", "FL1", "BL1", "SA", "SAUDI"]
SKIP_STATUSES = ("POSTPONED", "SUSPENDED", "CANCELLED", "IN_PLAY", "PAUSED")

CFG = {
    "threshold": 0.79,
    "market": 1.5,
    # factors 1 and 2: Poisson core
    "baseline_games": 38,
    "shrink_games": 12,
    "form_half_weight_games": 10,
    "default_mu_home": 1.50,
    "default_mu_away": 1.20,
    "min_games_for_mu": 40,
    "min_baseline_games": 20,
    # factor 4: absences, share of goal expectancy
    "att_loss": {1: 0.01, 2: 0.04, 3: 0.08},
    "att_cap": 0.20,
    "def_gain": {1: 0.01, 2: 0.03, 3: 0.06},
    "gk_gain": {1: 0.02, 2: 0.05, 3: 0.09},
    "def_cap": 0.15,
    "rotation_step": 0.03,
    # factor 3: formation
    "formation_step": 0.025,
    # factor 5 + game-state check
    "base_spread": 0.08,
    "derby_spread": 0.18,
    "settle_penalty": 0.03,
    "gs_min_events": 2,
    "gs_settle_rate": 0.34,
    "cross_league_penalty": 0.02,
    # misc
    "cache_hours": 3,
    "kickoff_tz_hours": int(os.environ.get("BARBADOX_TZ_HOURS", "1")),
}

NOW = datetime.now(timezone.utc)
CURRENT_SEASON = NOW.year if NOW.month >= 7 else NOW.year - 1


def season_of(dt):
    return dt.year if dt.month >= 7 else dt.year - 1


def season_start(season):
    return datetime(season, 7, 1, tzinfo=timezone.utc)


def norm(name):
    return " ".join(str(name).lower().split())


def parse_dt(s):
    s = str(s).strip().replace("Z", "+00:00")
    if len(s) <= 10:
        s += "T12:00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def geti(row, key):
    try:
        v = str((row or {}).get(key, "")).strip()
        return int(float(v)) if v != "" else None
    except ValueError:
        return None


def pct(x):
    return f"{x * 100:.1f}%"


# ----------------------------------------------------------------------------
# Data layer: football-data.org (free tier) only. No LLM, no search API.
# ----------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


_last_call = [0.0]


def api_get(path, params=None):
    if requests is None:
        sys.exit("Missing dependency. Run: pip install -r requirements.txt")
    key = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
    if not key:
        sys.exit("No API key found. Set the FOOTBALL_DATA_KEY environment variable "
                  "(free at https://www.football-data.org/client/register).")
    for attempt in range(3):
        wait = MIN_CALL_GAP - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        r = requests.get(API_BASE + path, headers={"X-Auth-Token": key}, params=params, timeout=30)
        print(f"  API GET {path} -> HTTP {r.status_code}")
        if r.status_code == 429:
            time.sleep(30)
            continue
        if r.status_code in (400, 403, 404):
            raise ApiError(f"HTTP {r.status_code} (your plan may not include this competition/season)",
                           status=r.status_code)
        if not r.ok:
            raise ApiError(f"HTTP {r.status_code}", status=r.status_code)
        return r.json()
    raise ApiError("rate limited, try again in a minute")


def fetch_api(league, season):
    data = api_get(f"/competitions/{league}/matches", {"season": season})
    out = []
    for m in data.get("matches", []):
        if not (m.get("homeTeam") or {}).get("name") or not (m.get("awayTeam") or {}).get("name"):
            continue
        sc = m.get("score") or {}
        ft = sc.get("regularTime") or sc.get("fullTime") or {}
        out.append({"date": m["utcDate"], "home": m["homeTeam"]["name"], "away": m["awayTeam"]["name"],
                    "hg": ft.get("home"), "ag": ft.get("away"), "status": m["status"]})
    return out


APIFOOTBALL_BASE = "https://v3.football.api-sports.io"
APIFOOTBALL_IDS = {"SAUDI": 307}
_AF_STATUS = {"FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED", "NS": "SCHEDULED", "TBD": "SCHEDULED",
              "PST": "POSTPONED", "SUSP": "SUSPENDED", "INT": "SUSPENDED",
              "1H": "IN_PLAY", "HT": "IN_PLAY", "2H": "IN_PLAY", "ET": "IN_PLAY", "BT": "IN_PLAY",
              "P": "IN_PLAY", "LIVE": "IN_PLAY"}


def fetch_apifootball(league, season):
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    time.sleep(1.0)
    r = requests.get(APIFOOTBALL_BASE + "/fixtures", headers={"x-apisports-key": key},
                      params={"league": APIFOOTBALL_IDS[league], "season": season}, timeout=30)
    if r.status_code in (401, 403):
        raise ApiError("API-Football key rejected", status=403)
    if not r.ok:
        raise ApiError(f"API-Football HTTP {r.status_code}", status=r.status_code)
    j = r.json()
    if j.get("errors"):
        raise ApiError("API-Football: " + str(j["errors"])[:200], status=403)
    out = []
    for m in j.get("response", []):
        fx, t, g = m["fixture"], m["teams"], m.get("goals") or {}
        st = _AF_STATUS.get(fx["status"]["short"], "CANCELLED")
        ft = (m.get("score") or {}).get("fulltime") or {}
        hg = ft.get("home") if ft.get("home") is not None else g.get("home")
        ag = ft.get("away") if ft.get("away") is not None else g.get("away")
        out.append({"date": fx["date"], "home": t["home"]["name"], "away": t["away"]["name"],
                    "hg": hg if st == "FINISHED" else None, "ag": ag if st == "FINISHED" else None,
                    "status": st})
    return out


def league_fetcher(league):
    if league in API_CODES:
        return fetch_api
    if league in APIFOOTBALL_IDS and os.environ.get("API_FOOTBALL_KEY", "").strip():
        return fetch_apifootball
    return None


def prep(m):
    m = dict(m)
    m["dt"] = parse_dt(m["date"])
    m["hk"] = norm(m["home"])
    m["ak"] = norm(m["away"])
    m["finished"] = (m.get("status") == "FINISHED" and m.get("hg") is not None and m.get("ag") is not None)
    return m


def load_league(league, season, refresh):
    DATA_DIR.mkdir(exist_ok=True)
    fetcher = league_fetcher(league)
    matches = []
    if fetcher:
        path = DATA_DIR / f"{league}_{season}.json"
        import json as _json
        current = season == CURRENT_SEASON
        fresh = path.exists() and (not refresh)
        if fresh and current:
            age = time.time() - path.stat().st_mtime
            fresh = age < CFG["cache_hours"] * 3600
        if fresh:
            matches = _json.loads(path.read_text(encoding="utf-8"))
        else:
            try:
                print(f"  fetching {league} {season}...")
                matches = fetcher(league, season)
                path.write_text(_json.dumps(matches), encoding="utf-8")
            except ApiError as e:
                print(f"  ! {league} {season}: {e}")
                if path.exists():
                    matches = _json.loads(path.read_text(encoding="utf-8"))
    return [prep(m) for m in matches]


def load_for_leagues(leagues, refresh=False):
    needed = [x for x in dict.fromkeys(leagues) if x in LEAGUES]
    if "CL" in needed:
        for lg in DOMESTIC:
            if lg not in needed:
                needed.append(lg)
    pools = {lg: [] for lg in LEAGUES}
    for lg in needed:
        ms = []
        for season in (CURRENT_SEASON - 1, CURRENT_SEASON):
            ms += load_league(lg, season, refresh)
        pools[lg] = ms
    return pools


# ----------------------------------------------------------------------------
# Poisson core (factors 1 and 2) -- unchanged math from the original model
# ----------------------------------------------------------------------------
def p_over(total_lambda, line):
    k = int(math.floor(line))
    p_le = sum(math.exp(-total_lambda) * total_lambda ** i / math.factorial(i) for i in range(k + 1))
    return 1.0 - p_le


def league_mu(matches):
    fin = [m for m in matches if m["finished"]]
    if len(fin) < CFG["min_games_for_mu"]:
        return CFG["default_mu_home"], CFG["default_mu_away"]
    return (sum(m["hg"] for m in fin) / len(fin), sum(m["ag"] for m in fin) / len(fin))


def split(team, ms):
    s = dict(hgf=0, hga=0, hn=0, agf=0, aga=0, an=0)
    for m in ms:
        if m["hk"] == team:
            s["hgf"] += m["hg"]; s["hga"] += m["ag"]; s["hn"] += 1
        else:
            s["agf"] += m["ag"]; s["aga"] += m["hg"]; s["an"] += 1
    return s


def shrunk_strengths(sp, mu_h, mu_a):
    k = CFG["shrink_games"]
    n_all = sp["hn"] + sp["an"]
    att_all = ((sp["hgf"] / mu_h + sp["agf"] / mu_a) + k) / (n_all + k)
    def_all = ((sp["hga"] / mu_a + sp["aga"] / mu_h) + k) / (n_all + k)
    return {
        "att_h": (sp["hgf"] / mu_h + k * att_all) / (sp["hn"] + k),
        "def_h": (sp["hga"] / mu_a + k * def_all) / (sp["hn"] + k),
        "att_a": (sp["agf"] / mu_a + k * att_all) / (sp["an"] + k),
        "def_a": (sp["aga"] / mu_h + k * def_all) / (sp["an"] + k),
    }


def expected_goals(sh, sa, mu_h, mu_a):
    lam_h = sh["att_h"] * sa["def_a"] * mu_h
    lam_a = sa["att_a"] * sh["def_h"] * mu_a
    return lam_h, lam_a


class Env:
    def __init__(self, pools):
        self.pools = pools
        self.home_league = {}
        allm = []
        for lg in DOMESTIC:
            for m in pools.get(lg, []):
                allm.append((m["dt"], lg, m))
        allm.sort(key=lambda x: x[0], reverse=True)
        for _, lg, m in allm:
            for t in (m["hk"], m["ak"]):
                self.home_league.setdefault(t, lg)
        self.mu = {lg: league_mu(pools.get(lg, [])) for lg in LEAGUES}

    def league_for_team(self, team):
        return self.home_league.get(team)

    def strength(self, team, league):
        ms = [m for m in self.pools.get(league, []) if m["finished"] and team in (m["hk"], m["ak"])]
        ms.sort(key=lambda m: m["dt"])
        cs = season_start(CURRENT_SEASON)
        base = [m for m in ms if m["dt"] < cs][-CFG["baseline_games"]:]
        form = [m for m in ms if m["dt"] >= cs]
        mu_h, mu_a = self.mu[league]
        sb = shrunk_strengths(split(team, base), mu_h, mu_a)
        sf = shrunk_strengths(split(team, form), mu_h, mu_a)
        nb, nf = len(base), len(form)
        w = 1.0 if nb == 0 else nf / (nf + CFG["form_half_weight_games"])
        blend = {k: w * sf[k] + (1 - w) * sb[k] for k in sf}
        return {"form": sf, "base": sb, "blend": blend}, {"n_base": nb, "n_form": nf, "w": w}


# ----------------------------------------------------------------------------
# Factors 3-5 + game-state check (from context.csv, hand-entered, all optional)
# ----------------------------------------------------------------------------
ROLES = ("FWD", "CRE", "DM", "DEF", "GK")
ROLE_ATTACK = ("FWD", "CRE")


def parse_absences(text):
    out = []
    t = str(text or "").strip()
    if not t or t.lower() == "none":
        return out
    for part in t.split(";"):
        bits = [x.strip() for x in part.split(":")]
        if len(bits) < 3:
            continue
        role = bits[1].upper()
        try:
            imp = max(1, min(3, int(float(bits[2]))))
        except ValueError:
            continue
        if role not in ROLES:
            continue
        out.append({"name": bits[0], "role": role, "imp": imp})
    return out


def absence_effects(absences):
    att = sum(CFG["att_loss"][a["imp"]] for a in absences if a["role"] in ROLE_ATTACK)
    dfn = sum((CFG["gk_gain"] if a["role"] == "GK" else CFG["def_gain"])[a["imp"]]
              for a in absences if a["role"] not in ROLE_ATTACK)
    return min(att, CFG["att_cap"]), min(dfn, CFG["def_cap"])


def settles(taken, extended):
    return (taken is not None and extended is not None and taken >= CFG["gs_min_events"]
            and extended / taken <= CFG["gs_settle_rate"])


def folds(trailing, responded):
    return (trailing is not None and responded is not None and trailing >= CFG["gs_min_events"]
            and responded / trailing <= CFG["gs_settle_rate"])


def analyze(fix, row, env, market):
    """The original 5-factor model. No research step, no LLM, no 'expanded factors'."""
    h, a, lg = fix["hk"], fix["ak"], fix["league"]
    notes, sheet = [], []
    penalty = 0.0

    if lg == "CL":
        hl, al = env.league_for_team(h), env.league_for_team(a)
        if not hl or not al:
            return {"p": None, "reason": "no domestic league identity found for a CL team"}
        mu_h, mu_a = env.mu["CL"]
        penalty = CFG["cross_league_penalty"]
        notes.append("CL: strengths come from each team's domestic league")
    else:
        hl = al = lg
        mu_h, mu_a = env.mu[lg]

    sh, nh = env.strength(h, hl)
    sa, na = env.strength(a, al)
    if nh["n_base"] + nh["n_form"] == 0 or na["n_base"] + na["n_form"] == 0:
        return {"p": None, "reason": "no match data for one of the teams"}

    lam = {k: expected_goals(sh[k], sa[k], mu_h, mu_a) for k in ("form", "base", "blend")}
    lam_h, lam_a = lam["blend"]
    core = p_over(lam_h + lam_a, market)
    p_form = p_over(sum(lam["form"]), market)
    p_base = p_over(sum(lam["base"]), market)

    sheet.append(f"1 form since season start: {pct(p_form)} | games {nh['n_form']}/{na['n_form']}")
    sheet.append(f"2 historical baseline:     {pct(p_base)} | games {nh['n_base']}/{na['n_base']}")
    sheet.append(f"  core (blended):          {pct(core)}")
    if abs(p_form - p_base) >= 0.08:
        notes.append(f"checks 1 and 2 disagree by {abs(p_form - p_base) * 100:.0f} pts")

    # Best-case ceiling from factors 3-4, BEFORE spending any time on research.
    # Attacking absences and rotation only ever lower a side's lambda, so the best case has
    # none of those. The only things that can raise total lambda above the core are: the
    # opponent missing defenders/keeper (def_cap, capped) and a maximally favourable formation
    # effect (+2, formation_step) for both sides. Under this model's multiplicative structure
    # that ceiling is exact, not approximate: see test_upper_bound.py.
    max_up = (1 + CFG["def_cap"]) * (1 + 2 * CFG["formation_step"]) - 1
    upper = p_over((lam_h + lam_a) * (1 + max_up), market) - penalty

    R = row or {}
    ready = str(R.get("checked", "")).strip() == "1"

    def side(prefix):
        ab = parse_absences(R.get(f"{prefix}_absences"))
        att_loss, def_gain = absence_effects(ab)
        rot = min(max(geti(R, f"{prefix}_rotation") or 0, 0), 2)
        fe = min(max(geti(R, f"{prefix}_formation_effect") or 0, -2), 2)
        return ab, att_loss, def_gain, rot, fe

    hab, h_att, h_def, h_rot, h_fe = side("home")
    aab, a_att, a_def, a_rot, a_fe = side("away")
    lh = lam_h * (1 - h_att) * (1 - CFG["rotation_step"] * h_rot) * (1 + CFG["formation_step"] * h_fe) * (1 + a_def)
    la = lam_a * (1 - a_att) * (1 - CFG["rotation_step"] * a_rot) * (1 + CFG["formation_step"] * a_fe) * (1 + h_def)
    lh, la = max(0.05, lh), max(0.05, la)

    if ready:
        def asheet(ab, att_loss, def_gain, rot):
            who = "none" if not ab else ", ".join(f"{x['name']} ({x['role']}, imp {x['imp']})" for x in ab)
            return f"{who} | goals -{att_loss*100:.0f}% / opp +{def_gain*100:.0f}% | rotation {rot}"
        sheet.append(f"3 formation effect: home {h_fe:+d} | away {a_fe:+d}")
        sheet.append(f"4 home absences: {asheet(hab, h_att, h_def, h_rot)}")
        sheet.append(f"  away absences: {asheet(aab, a_att, a_def, a_rot)}")
    else:
        notes.append("factors 3-4 not entered in context.csv (checked=0): core-only")

    derby = geti(R, "derby") == 1
    fav, dog = ("home", "away") if lh >= la else ("away", "home")
    f_taken, f_ext = geti(R, f"{fav}_leads_taken"), geti(R, f"{fav}_leads_extended")
    d_trail, d_resp = geti(R, f"{dog}_trailing"), geti(R, f"{dog}_responded")
    risk = settles(f_taken, f_ext) and folds(d_trail, d_resp)
    if ready:
        sheet.append(f"5 derby: {'YES, range widened' if derby else 'no'}")
        if f_taken is not None or d_trail is not None:
            sheet.append(f"  game state: favourite ({fav}) leads {f_ext or 0}/{f_taken or 0} extended | "
                         f"underdog ({dog}) deficits {d_resp or 0}/{d_trail or 0} answered"
                         f"{' -> RISK, both settle' if risk else ''}")

    spread = CFG["derby_spread"] if (derby or risk) else CFG["base_spread"]
    total = lh + la
    point = p_over(total, market) - penalty
    low = p_over(total * (1 - spread), market) - penalty
    high = p_over(total * (1 + spread), market)
    if derby:
        notes.append("derby: range widened")
    if risk:
        point -= CFG["settle_penalty"]
        low -= CFG["settle_penalty"]
        notes.append("game-state risk: favourite settles, underdog folds")

    if nh["n_form"] + na["n_form"] < 8:
        notes.append("thin current-season sample")
    baseline_ok = min(nh["n_base"], na["n_base"]) >= CFG["min_baseline_games"]
    if not baseline_ok:
        notes.append(f"partial: only {nh['n_base']}/{na['n_base']} baseline games")

    temp = str(R.get("field_temp_c", "")).strip()
    if ready:
        sheet.append(f"  field temperature: {temp + 'C' if temp else 'not confirmed'} (logged only)")
    notes.append("low/high are a rough xG sensitivity band, not a confidence interval")

    parts = [f"core {core*100:.1f}", f"form {p_form*100:.0f}", f"base {p_base*100:.0f}"]
    if derby:
        parts.append("derby")
    if risk:
        parts.append("settle-risk")

    return {
        "p": point, "low": low, "high": high, "core": core, "upper": upper,
        "lam_h": lh, "lam_a": la,
        "notes": notes, "sheet": sheet, "factors": " | ".join(parts),
        "baseline_ok": baseline_ok, "verified": ready and baseline_ok,
        "n": f"form {nh['n_form']}/{na['n_form']} base {nh['n_base']}/{na['n_base']}",
    }


# ----------------------------------------------------------------------------
# context.csv / picks.csv
# ----------------------------------------------------------------------------
CTX_FIELDS = [
    "date", "league", "home", "away", "checked", "derby", "field_temp_c",
    "home_absences", "home_rotation", "home_formation_effect",
    "home_leads_taken", "home_leads_extended", "home_trailing", "home_responded",
    "away_absences", "away_rotation", "away_formation_effect",
    "away_leads_taken", "away_leads_extended", "away_trailing", "away_responded",
]
PICK_FIELDS = ["date", "league", "home", "away", "market", "probability", "core_probability",
               "low", "high", "field_temp_c", "factors", "logged_at", "hg", "ag", "result", "note"]


def read_csv_rows(path, fields):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def read_context():
    out = {}
    for r in read_csv_rows(CONTEXT_FILE, CTX_FIELDS):
        out[(r["date"], norm(r["home"]), norm(r["away"]))] = r
    return out


def write_context(ctx):
    write_csv_rows(CONTEXT_FILE, CTX_FIELDS, list(ctx.values()))


def read_picks():
    return read_csv_rows(PICKS_FILE, PICK_FIELDS)


def write_picks(rows):
    write_csv_rows(PICKS_FILE, PICK_FIELDS, rows)


# ----------------------------------------------------------------------------
# Output screen: one static HTML file, no server, no JS framework, nothing fetched
# from anywhere. GitHub Pages serves it as-is. See README for how to turn it on.
# ----------------------------------------------------------------------------
DOCS_DIR = BASE_DIR / "docs"
HTML_FILE = DOCS_DIR / "index.html"


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def write_html_report(picks):
    DOCS_DIR.mkdir(exist_ok=True)
    rows = sorted(picks, key=lambda p: p["date"], reverse=True)
    graded = [p for p in rows if p["result"] in ("HIT", "MISS")]
    hits = [p for p in graded if p["result"] == "HIT"]
    hit_rate = (len(hits) / len(graded) * 100) if graded else 0.0
    pending = [p for p in rows if not p["result"]]

    def row_html(p):
        result = p["result"] or "pending"
        cls = {"HIT": "hit", "MISS": "miss", "POSTPONED": "postponed"}.get(result, "pending")
        score = f"{p['hg']}-{p['ag']}" if p.get("hg") not in ("", None) else "-"
        prob = f"{float(p['probability']) * 100:.1f}%"
        return (f'<div class="pick {cls}">'
                f'<div class="pick-top"><span class="date">{_esc(p["date"])}</span>'
                f'<span class="league">{_esc(p["league"])}</span>'
                f'<span class="badge">{_esc(result)}</span></div>'
                f'<div class="match">{_esc(p["home"])} vs {_esc(p["away"])}</div>'
                f'<div class="pick-bottom"><span>Over {_esc(p["market"])}: {prob}</span>'
                f'<span>{score}</span></div></div>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Barbadox's Model</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 0 auto;
         padding: 16px; background: Canvas; color: CanvasText; }}
  h1 {{ font-size: 1.3rem; margin-bottom: 4px; }}
  .updated {{ color: GrayText; font-size: 0.85rem; margin-bottom: 16px; }}
  .summary {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
  .stat {{ background: color-mix(in srgb, CanvasText 6%, Canvas); border-radius: 10px;
          padding: 10px 14px; flex: 1; min-width: 100px; text-align: center; }}
  .stat .n {{ font-size: 1.4rem; font-weight: 700; display: block; }}
  .stat .l {{ font-size: 0.75rem; color: GrayText; }}
  .pick {{ border-radius: 10px; padding: 10px 14px; margin-bottom: 8px;
          background: color-mix(in srgb, CanvasText 5%, Canvas); border-left: 4px solid GrayText; }}
  .pick.hit {{ border-left-color: #2e9e44; }}
  .pick.miss {{ border-left-color: #d14343; }}
  .pick.postponed {{ border-left-color: #c9a227; }}
  .pick-top {{ display: flex; justify-content: space-between; font-size: 0.8rem; color: GrayText; }}
  .badge {{ font-weight: 600; text-transform: uppercase; font-size: 0.72rem; }}
  .hit .badge {{ color: #2e9e44; }}
  .miss .badge {{ color: #d14343; }}
  .match {{ font-weight: 600; margin: 4px 0; }}
  .pick-bottom {{ display: flex; justify-content: space-between; font-size: 0.9rem; }}
  .empty {{ color: GrayText; text-align: center; padding: 40px 0; }}
</style>
</head>
<body>
<h1>Barbadox's Model</h1>
<div class="updated">Updated {_esc(NOW.strftime("%Y-%m-%d %H:%M UTC"))}</div>
<div class="summary">
  <div class="stat"><span class="n">{len(hits)}/{len(graded)}</span><span class="l">hit</span></div>
  <div class="stat"><span class="n">{hit_rate:.0f}%</span><span class="l">hit rate</span></div>
  <div class="stat"><span class="n">{len(pending)}</span><span class="l">pending</span></div>
</div>
{"".join(row_html(p) for p in rows) if rows else '<div class="empty">No picks logged yet.</div>'}
</body>
</html>
"""
    HTML_FILE.write_text(html, encoding="utf-8")


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
def cmd_run(args):
    leagues = [x.strip().upper() for x in args.leagues.split(",") if x.strip()]
    bad = [x for x in leagues if x not in LEAGUES]
    if bad:
        sys.exit(f"Unknown league key(s): {', '.join(bad)}. Valid: {', '.join(LEAGUES)}")

    print("Loading data...")
    pools = load_for_leagues(leagues, args.refresh)
    env = Env(pools)

    tz = timedelta(hours=CFG["kickoff_tz_hours"])
    d0 = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else (NOW + tz).date())
    d1 = d0 + timedelta(days=args.days)

    fixtures = []
    for lg in leagues:
        for m in pools.get(lg, []):
            loc = m["dt"] + tz
            if not (d0 <= loc.date() < d1):
                continue
            if m["status"] not in ("SCHEDULED", "TIMED"):
                continue
            item = dict(m)
            item["league"] = lg
            item["ldate"] = loc.strftime("%Y-%m-%d")
            item["ltime"] = loc.strftime("%H:%M")
            fixtures.append(item)

    print(f"\nBARBADOX'S MODEL | Over {args.market} | threshold {pct(args.threshold)} | "
          f"{d0} to {d1 - timedelta(days=1)} (UTC{CFG['kickoff_tz_hours']:+d})")

    for lg in leagues:
        if not pools.get(lg):
            print(f"! {lg}: no data loaded (check FOOTBALL_DATA_KEY / API_FOOTBALL_KEY, plan, season).")

    if not fixtures:
        print("No playable fixtures found in that window.")
        return

    # context.csv is fully rebuilt at most once per calendar day (kickoff TZ).
    # Only fixtures whose core probability already clears the threshold get a row.
    # User-filled rows (checked=1) for fixtures still in the window are preserved.
    # Same-day re-runs only append newly qualified fixtures; past dates are dropped
    # on the daily rebuild so the file stays small and GitHub-friendly to edit.
    # The file is ALWAYS written so it never goes missing after a run.
    _tz = timedelta(hours=CFG["kickoff_tz_hours"])
    today_str = (NOW + _tz).date().isoformat()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp_path = DATA_DIR / "context_stamp.txt"
    last_stamp = stamp_path.read_text().strip() if stamp_path.exists() else ""

    old_ctx = read_context()
    fixture_by_key = {(fx["ldate"], fx["hk"], fx["ak"]): fx for fx in fixtures}

    if last_stamp != today_str:
        ctx = {}
        added = 0
        kept_filled = 0
        for key, fx in fixture_by_key.items():
            _probe = analyze(fx, None, env, args.market)
            if _probe["p"] is None or _probe["p"] < args.threshold:
                continue
            if key in old_ctx and str(old_ctx[key].get("checked", "")).strip() == "1":
                ctx[key] = old_ctx[key]
                kept_filled += 1
            else:
                row = {k: "" for k in CTX_FIELDS}
                row.update({"date": fx["ldate"], "league": fx["league"], "home": fx["home"],
                            "away": fx["away"], "checked": "0"})
                ctx[key] = row
                added += 1
        write_context(ctx)
        stamp_path.write_text(today_str + "\n")
        print(f"\ncontext.csv refreshed for {today_str}: {len(ctx)} threshold fixture(s) "
              f"({added} blank, {kept_filled} already filled). "
              f"Only picks at/above {pct(args.threshold)} are listed — edit on GitHub, set checked=1.")
    else:
        ctx = dict(old_ctx)
        # Drop rows for fixtures no longer in the window / past dates
        live_keys = set(fixture_by_key.keys())
        ctx = {k: v for k, v in ctx.items() if k in live_keys}
        added = 0
        for key, fx in fixture_by_key.items():
            if key in ctx:
                continue
            _probe = analyze(fx, None, env, args.market)
            if _probe["p"] is None or _probe["p"] < args.threshold:
                continue
            row = {k: "" for k in CTX_FIELDS}
            row.update({"date": fx["ldate"], "league": fx["league"], "home": fx["home"],
                        "away": fx["away"], "checked": "0"})
            ctx[key] = row
            added += 1
        # Always write so context.csv never disappears after a run
        write_context(ctx)
        if added:
            print(f"\n{added} new threshold fixture(s) added to context.csv "
                  f"(daily refresh already done for {today_str}).")
        else:
            print(f"\ncontext.csv kept ({len(ctx)} threshold fixture(s) for {today_str}).")

    picks = read_picks()
    logged_keys = {(p["date"], norm(p["home"]), norm(p["away"])) for p in picks}

    print()
    kept = 0
    for fx in sorted(fixtures, key=lambda x: (x["ldate"], x["ltime"])):
        row = ctx.get((fx["ldate"], fx["hk"], fx["ak"]))
        res = analyze(fx, row, env, args.market)
        print(f"{fx['ldate']} {fx['ltime']} {fx['league']:<5} {fx['home']} vs {fx['away']}")
        if res["p"] is None:
            print(f"  skipped: {res['reason']}")
            continue

        ready = bool(row) and str(row.get("checked", "")).strip() == "1"
        if not ready and res["upper"] < args.threshold:
            print(f"  core {pct(res['core'])}, best case (max absences + formation) {pct(res['upper'])} "
                  f"-- can't reach {pct(args.threshold)} even then. No need to fill in context.csv.")
            print()
            continue
        if not ready and res["upper"] >= args.threshold:
            print(f"  note: core {pct(res['core'])} alone isn't enough, but best case reaches "
                  f"{pct(res['upper'])} -- worth filling in factors 3-5 in context.csv")

        for line in res["sheet"]:
            print(f"  {line}")
        for note in res["notes"]:
            print(f"  note: {note}")
        print(f"  => {pct(res['p'])} (core {pct(res['core'])}, range {pct(res['low'])}-{pct(res['high'])})")

        key = (fx["ldate"], norm(fx["home"]), norm(fx["away"]))
        if res["p"] >= args.threshold and key not in logged_keys:
            picks.append({
                "date": fx["ldate"], "league": fx["league"], "home": fx["home"], "away": fx["away"],
                "market": args.market, "probability": f"{res['p']:.4f}", "core_probability": f"{res['core']:.4f}",
                "low": f"{res['low']:.4f}", "high": f"{res['high']:.4f}",
                "field_temp_c": (row or {}).get("field_temp_c", ""), "factors": res["factors"],
                "logged_at": NOW.isoformat(), "hg": "", "ag": "", "result": "", "note": "",
            })
            logged_keys.add(key)
            kept += 1
            print(f"  LOGGED (>= {pct(args.threshold)})")
        print()

    if kept:
        write_picks(picks)
    write_html_report(picks)
    print(f"Logged {kept} new pick(s) to picks.csv.")

    tz = timedelta(hours=CFG["kickoff_tz_hours"])
    today = (NOW + tz).date()
    unplayed = [p for p in picks if not p["result"]
                and datetime.strptime(p["date"], "%Y-%m-%d").date() >= today]
    if unplayed:
        print(f"\nSlip ready: {len(unplayed)} pick(s) waiting to be played. Run the Slip button.")
    else:
        print("\nSlip: nothing to show yet, no unplayed picks logged.")


def build_index(pools):
    index = {}
    for ms in pools.values():
        for m in ms:
            index.setdefault((m["hk"], m["ak"]), []).append(m)
    return index


def grade_rows(rows, index):
    tz = timedelta(hours=CFG["kickoff_tz_hours"])
    today = (NOW + tz).date()
    for p in rows:
        if p.get("result"):
            continue
        try:
            pdate = datetime.strptime(p["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        cands = index.get((norm(p["home"]), norm(p["away"])), [])
        near = [m for m in cands if abs(((m["dt"] + tz).date() - pdate).days) <= 1]
        fin = [m for m in near if m["finished"]]
        if fin:
            m = fin[0]
            p["hg"], p["ag"] = m["hg"], m["ag"]
            p["result"] = "HIT" if m["hg"] + m["ag"] > float(p["market"]) else "MISS"
            continue
        if pdate >= today:
            continue
        postponed = [m for m in near if m["status"] == "POSTPONED"]
        if postponed:
            p["result"] = "POSTPONED"
            p["note"] = "postponed"


def cmd_review(args):
    picks = read_picks()
    if not picks:
        print("No picks logged yet.")
        return
    leagues = sorted({p["league"] for p in picks if p["league"] in LEAGUES})
    print("Loading results...")
    pools = load_for_leagues(leagues, refresh=True)
    index = build_index(pools)
    grade_rows(picks, index)
    write_picks(picks)
    write_html_report(picks)

    graded = [p for p in picks if p["result"] in ("HIT", "MISS")]
    hits = [p for p in graded if p["result"] == "HIT"]
    pending = [p for p in picks if not p["result"]]
    print(f"\n{len(hits)}/{len(graded)} hit "
          f"({(len(hits)/len(graded)*100 if graded else 0):.0f}%), {len(pending)} pending")
    for p in sorted(picks, key=lambda x: x["date"]):
        tag = p["result"] or "pending"
        score = f"{p['hg']}-{p['ag']}" if p.get("hg") not in ("", None) else ""
        print(f"  {p['date']} {p['league']:<5} {p['home']} vs {p['away']}  {pct(float(p['probability']))}  "
              f"{tag} {score}")


SLIP_FILE = BASE_DIR / "slip.md"


def cmd_slip(args):
    """Turns today's logged, unplayed picks into one clean, final list. No new math,
    no odds, no stakes, just the picks that are actually ready to act on right now."""
    picks = read_picks()
    tz = timedelta(hours=CFG["kickoff_tz_hours"])
    today = (NOW + tz).date()
    ready = [p for p in picks if not p["result"]
             and datetime.strptime(p["date"], "%Y-%m-%d").date() >= today]
    ready.sort(key=lambda p: (p["date"], p["league"]))

    lines = [f"# Barbadox Slip", f"Generated {NOW.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    if not ready:
        lines.append("Nothing ready. Run the Run button first, or wait for upcoming fixtures.")
    else:
        lines.append(f"{len(ready)} pick(s):")
        lines.append("")
        for p in ready:
            lines.append(f"- **{p['date']} {p['league']}** — {p['home']} vs {p['away']} — "
                         f"Over {p['market']}: **{float(p['probability']) * 100:.1f}%**")
    SLIP_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"BARBADOX SLIP -- {len(ready)} pick(s)")
    print(f"Generated {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n")
    if not ready:
        print("Nothing ready. Run the Run button first, or wait for upcoming fixtures.")
    for p in ready:
        print(f"{p['date']} {p['league']:<5} {p['home']} vs {p['away']}")
        print(f"  Over {p['market']} goals -- {float(p['probability']) * 100:.1f}%\n")


def main():
    ap = argparse.ArgumentParser(description="Barbadox's Model (core, standalone)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="analyze fixtures and log picks >= threshold")
    pr.add_argument("--date", default=None, help="YYYY-MM-DD, default today")
    pr.add_argument("--days", type=int, default=3)
    pr.add_argument("--leagues", default=",".join(LEAGUES.keys()))
    pr.add_argument("--threshold", type=float, default=CFG["threshold"])
    pr.add_argument("--market", type=float, default=CFG["market"])
    pr.add_argument("--refresh", action="store_true", help="bypass the local cache")
    pr.set_defaults(func=cmd_run)

    pv = sub.add_parser("review", help="grade logged picks against real results")
    pv.set_defaults(func=cmd_review)

    ps = sub.add_parser("slip", help="turn today's unplayed logged picks into one clean list")
    ps.set_defaults(func=cmd_slip)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
