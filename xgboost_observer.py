
#!/usr/bin/env python3
"""
BARBADOX XGBOOST OBSERVER
========================

Independent analysis of:

1. Core 1: OVER 1.5 goals
2. Core 2: UNDER 3.5 goals

Features:
- Historical backtest analysis.
- Current-season slip analysis.
- Market-specific team failure rankings.
- Independent XGBoost models.
- Chronological model evaluation.
- Brier score and baseline comparison.
- Current versus historical comparison.
- Individual failed-selection market identification.
- Markdown report generation.

This observer does not modify the Core 1 or Core 2
prediction engines or slip generation.
"""

import csv
import json
import os
import re
import unicodedata

from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

CORE1_FILE = ROOT / "reports" / "core1_results.csv"
CORE2_FILE = ROOT / "reports" / "core2_results.csv"
SLIPS_FILE = ROOT / "slips_browser.csv"

REPORT_DIR = ROOT / "reports" / "xgboost_observer"

SEASON_START_MONTH = int(
    os.getenv("OBSERVER_SEASON_START_MONTH", "7")
)

SEASON_START_DAY = int(
    os.getenv("OBSERVER_SEASON_START_DAY", "1")
)

MIN_XGBOOST_ROWS = 150

MARKETS = (
    "OVER 1.5",
    "UNDER 3.5"
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "")
    ).strip()


def get_value(row, *keys):

    row_lower = {
        str(k).lower(): v
        for k, v in row.items()
    }

    for key in keys:

        value = row_lower.get(key.lower())

        if value is not None and clean(value):
            return clean(value)

    return ""


def parse_date(value):

    value = clean(value)

    if not value:
        return None

    value = value.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(value)

    except ValueError:

        try:
            return datetime.fromisoformat(value[:10])

        except ValueError:
            return None


def get_season(date):

    if date is None:
        return "Unknown"

    if (
        date.month,
        date.day
    ) >= (
        SEASON_START_MONTH,
        SEASON_START_DAY
    ):

        start_year = date.year

    else:

        start_year = date.year - 1

    return f"{start_year}/{start_year + 1}"


def team_key(name):

    value = unicodedata.normalize(
        "NFKD",
        clean(name)
    )

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = value.lower()
    value = value.replace("&", " and ")

    value = re.sub(
        r"[^a-z0-9 ]",
        " ",
        value
    )

    ignored = {
        "fc",
        "cf",
        "afc",
        "sc",
        "ac",
        "as",
        "ss",
        "club",
        "football",
        "calcio",
        "the"
    }

    words = [
        word
        for word in value.split()
        if word not in ignored
    ]

    return " ".join(words)


# ============================================================
# MARKET NORMALIZATION
# ============================================================

def market_key(value):

    value = clean(value).upper()

    aliases = {

        "OVER 1.5 GOALS": "OVER 1.5",
        "OVER 1.5": "OVER 1.5",
        "O1.5": "OVER 1.5",
        "O 1.5": "OVER 1.5",
        "CORE 1": "OVER 1.5",

        "UNDER 3.5 GOALS": "UNDER 3.5",
        "UNDER 3.5": "UNDER 3.5",
        "U3.5": "UNDER 3.5",
        "U 3.5": "UNDER 3.5",
        "CORE 2": "UNDER 3.5"

    }

    return aliases.get(value, value)


# ============================================================
# FIXTURE EXTRACTION
# ============================================================

def get_teams(row):

    home = get_value(
        row,
        "home_team",
        "hometeam",
        "home",
        "team_home"
    )

    away = get_value(
        row,
        "away_team",
        "awayteam",
        "away",
        "team_away"
    )

    if home and away:
        return home, away

    fixture = get_value(
        row,
        "fixture",
        "match",
        "match_name",
        "teams"
    )

    for separator in [
        " vs ",
        " v ",
        " - ",
        " – ",
        " — "
    ]:

        if separator in fixture:

            home, away = fixture.split(
                separator,
                1
            )

            return clean(home), clean(away)

    return "", ""


def parse_outcome(value):

    value = clean(value).lower()

    if value in {
        "1",
        "true",
        "yes",
        "won",
        "win",
        "hit"
    }:

        return 1

    if value in {
        "0",
        "false",
        "no",
        "lost",
        "loss",
        "miss"
    }:

        return 0

    return None


# ============================================================
# HISTORICAL BACKTEST READER
# ============================================================

def read_backtest(path, market):

    if not path.exists():

        print(
            f"WARNING: Missing file: {path}"
        )

        return []

    selections = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            cleared = get_value(
                row,
                "cleared",
                "qualified",
                "selected"
            )

            if cleared and cleared.lower() not in {
                "1",
                "true",
                "yes",
                "cleared",
                "qualified"
            }:

                continue

            outcome = parse_outcome(
                get_value(
                    row,
                    "hit",
                    "won",
                    "result",
                    "outcome"
                )
            )

            if outcome is None:
                continue

            home, away = get_teams(row)

            if not home or not away:
                continue

            date = parse_date(
                get_value(
                    row,
                    "date",
                    "match_date",
                    "utc_date",
                    "kickoff",
                    "fixture_date"
                )
            )

            selections.append({

                "market": market,

                "home": home,

                "away": away,

                "hit": outcome,

                "date": date,

                "season": get_season(date),

                "slip_id": "",

                "source": path.name

            })

    return selections


# ============================================================
# CURRENT SLIP ARCHIVE READER
# ============================================================

def read_current_slip_archive():

    if not SLIPS_FILE.exists():

        return [], (
            f"Archive not found: {SLIPS_FILE.name}"
        )

    selections = []

    with SLIPS_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for slip in reader:

            slip_id = (
                clean(slip.get("id"))
                or clean(slip.get("number"))
            )

            slip_status = clean(
                slip.get("status")
            ).upper()

            raw_legs = slip.get("legs", "")

            if not raw_legs:
                continue

            try:

                legs = json.loads(raw_legs)

            except (
                json.JSONDecodeError,
                TypeError
            ):

                print(
                    "WARNING: Could not parse legs "
                    f"for slip {slip_id}"
                )

                continue

            if isinstance(legs, dict):
                legs = [legs]

            if not isinstance(legs, list):
                continue

            for leg in legs:

                if not isinstance(leg, dict):
                    continue

                leg_status = clean(
                    leg.get("result")
                    or leg.get("status")
                    or leg.get("outcome")
                ).upper()

                if (
                    not leg_status
                    and slip_status == "WON"
                ):

                    leg_status = "WON"

                if leg_status not in {
                    "WON",
                    "LOST"
                }:

                    continue

                home = clean(leg.get("home"))
                away = clean(leg.get("away"))

                if not home or not away:
                    continue

                date = parse_date(
                    leg.get("date")
                    or leg.get("kickoff")
                    or slip.get("created_at")
                )

                selections.append({

                    "market": (
                        clean(leg.get("market"))
                        or "Unknown market"
                    ),

                    "home": home,

                    "away": away,

                    "hit": (
                        1
                        if leg_status == "WON"
                        else 0
                    ),

                    "date": date,

                    "season": get_season(date),

                    "slip_id": slip_id,

                    "slip_number": clean(
                        slip.get("number")
                    ),

                    "slip_status": slip_status,

                    "leg_status": leg_status,

                    "source": "slips_browser.csv"

                })

    return selections, (
        f"Read {len(selections)} settled legs "
        "from slips_browser.csv."
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def fixture_key(row):

    date_key = (
        row["date"].date().isoformat()
        if row.get("date")
        else ""
    )

    return (

        market_key(row["market"]),

        team_key(row["home"]),

        team_key(row["away"]),

        date_key

    )


def deduplicate(rows):

    seen = set()
    output = []

    for row in rows:

        key = fixture_key(row)

        if key not in seen:

            seen.add(key)
            output.append(row)

    return output


# ============================================================
# HISTORICAL TEAM ANALYSIS
# ============================================================

def analyse_teams(rows):

    stats = defaultdict(
        lambda: {

            "appearances": 0,

            "won": 0,

            "failed": 0,

            "fixtures": set(),

            "failed_fixtures": set(),

            "slips_affected": set()

        }
    )

    for row in rows:

        key = fixture_key(row)

        for team in [
            row["home"],
            row["away"]
        ]:

            normalized = team_key(team)

            if not normalized:
                continue

            item = stats[normalized]

            if key not in item["fixtures"]:

                item["fixtures"].add(key)

                item["appearances"] += 1

                if row["hit"] == 1:

                    item["won"] += 1

                else:

                    item["failed"] += 1

                    item["failed_fixtures"].add(key)

            if (
                row["hit"] == 0
                and row.get("slip_id")
            ):

                item["slips_affected"].add(
                    row["slip_id"]
                )

    results = []

    for normalized, item in stats.items():

        appearances = item["appearances"]

        failure_rate = (
            item["failed"] / appearances
            if appearances
            else 0
        )

        results.append({

            "team": normalized,

            "team_key": normalized,

            "appearances": appearances,

            "won": item["won"],

            "failed": item["failed"],

            "failure_rate": failure_rate,

            "unique_failed_fixtures": len(
                item["failed_fixtures"]
            ),

            "slips_affected": len(
                item["slips_affected"]
            )

        })

    return sorted(
        results,
        key=lambda item: (

            -item["failed"],

            -item["failure_rate"],

            -item["appearances"]

        )
    )


# ============================================================
# CURRENT SLIP TEAM ANALYSIS
# ============================================================

def current_slip_team_analysis(rows):

    stats = {}

    for row in rows:

        for team in (
            row["home"],
            row["away"]
        ):

            normalized = team_key(team)

            if not normalized:
                continue

            if normalized not in stats:

                stats[normalized] = {

                    "team": team,

                    "team_key": normalized,

                    "appearances": 0,

                    "won_legs": 0,

                    "failed_legs": 0,

                    "failed_slips": set(),

                    "slips_seen": set()

                }

            item = stats[normalized]

            item["appearances"] += 1

            if row["hit"] == 1:

                item["won_legs"] += 1

            else:

                item["failed_legs"] += 1

                if row.get("slip_id"):

                    item["failed_slips"].add(
                        row["slip_id"]
                    )

            if row.get("slip_id"):

                item["slips_seen"].add(
                    row["slip_id"]
                )

    ranking = []

    for normalized, item in stats.items():

        appearances = item["appearances"]

        failed = item["failed_legs"]

        ranking.append({

            "team": item["team"],

            "team_key": normalized,

            "appearances": appearances,

            "won_legs": item["won_legs"],

            "failed_legs": failed,

            "failure_rate": (
                failed / appearances
                if appearances
                else 0
            ),

            "failed_slips": len(
                item["failed_slips"]
            ),

            "slips_seen": len(
                item["slips_seen"]
            )

        })

    return sorted(
        ranking,
        key=lambda item: (

            -item["failed_slips"],

            -item["failed_legs"],

            -item["failure_rate"],

            -item["appearances"]

        )
    )


# ============================================================
# MARKET-SPECIFIC TEAM ANALYSIS
# ============================================================

def analyse_teams_by_market(rows):

    results = {}

    for market in MARKETS:

        market_rows = [

            row for row in rows

            if market_key(row["market"]) == market

        ]

        results[market] = analyse_teams(
            deduplicate(market_rows)
        )

    return results


def current_teams_by_market(rows):

    results = {}

    for market in MARKETS:

        market_rows = [

            row for row in rows

            if market_key(row["market"]) == market

        ]

        results[market] = current_slip_team_analysis(
            market_rows
        )

    return results


# ============================================================
# CURRENT VS HISTORICAL COMPARISON
# ============================================================

def compare_current_with_backtest(
    current_rows,
    current_ranking,
    historical_rows,
    historical_ranking
):

    current_top = {

        item["team_key"]: item

        for item in current_ranking[:20]

    }

    historical_top = {

        item["team_key"]: item

        for item in historical_ranking[:20]

    }

    overlap_keys = (
        set(current_top)
        & set(historical_top)
    )

    team_overlaps = []

    for key in sorted(overlap_keys):

        current_item = current_top[key]

        historical_item = historical_top[key]

        team_overlaps.append({

            "team": current_item["team"],

            "current_failed_slips": (
                current_item["failed_slips"]
            ),

            "current_failed_legs": (
                current_item["failed_legs"]
            ),

            "historical_failed": (
                historical_item["failed"]
            ),

            "historical_rate": (
                historical_item["failure_rate"]
            )

        })

    historical_fixtures = defaultdict(list)

    for row in historical_rows:

        key = fixture_key(row)

        historical_fixtures[key].append(row)

    exact_overlaps = []

    for row in current_rows:

        key = fixture_key(row)

        matches = historical_fixtures.get(
            key,
            []
        )

        for historical in matches:

            exact_overlaps.append({

                "date": key[3],

                "market": key[0],

                "fixture": (
                    f"{row['home']} vs {row['away']}"
                ),

                "current_result": (
                    "WON"
                    if row["hit"] == 1
                    else "LOST"
                ),

                "historical_result": (
                    "WON"
                    if historical["hit"] == 1
                    else "LOST"
                )

            })

    return team_overlaps, exact_overlaps


# ============================================================
# XGBOOST MODEL
# ============================================================

def train_xgboost(rows, target_market):
    """
    Train an independent XGBoost model for one market.

    Each model receives only its own market's data.

    Target:
        1 = selection won
        0 = selection lost

    Uses chronological training/testing.
    """

    market_rows = [

        row for row in rows

        if market_key(row["market"]) == target_market

    ]

    if len(market_rows) < MIN_XGBOOST_ROWS:

        return (

            f"{target_market}: NOT TRAINED\n"

            f"Available selections: {len(market_rows)}\n"

            f"Required selections: {MIN_XGBOOST_ROWS}"

        )

    if len({
        row["hit"]
        for row in market_rows
    }) < 2:

        return (

            f"{target_market}: NOT TRAINED\n"

            "Only one outcome class exists."

        )

    try:

        import pandas as pd

        from sklearn.compose import ColumnTransformer

        from sklearn.preprocessing import OneHotEncoder

        from sklearn.pipeline import Pipeline

        from sklearn.impute import SimpleImputer

        from sklearn.metrics import (
            accuracy_score,
            brier_score_loss,
            roc_auc_score
        )

        from xgboost import XGBClassifier

    except ImportError as error:

        return (

            f"{target_market}: DEPENDENCIES UNAVAILABLE\n"

            f"{error}\n"

            "Install requirements-observer.txt."

        )

    # --------------------------------------------------------
    # BUILD DATASET
    # --------------------------------------------------------

    data = []

    for row in market_rows:

        date = row["date"]

        data.append({

            "home": team_key(row["home"]),

            "away": team_key(row["away"]),

            "season": row["season"],

            "month": (
                date.month
                if date
                else None
            ),

            "year": (
                date.year
                if date
                else None
            ),

            "date_sort": (
                date.timestamp()
                if date
                else 0
            ),

            "hit": row["hit"]

        })

    frame = pd.DataFrame(data)

    frame = frame.sort_values(
        "date_sort"
    )

    # --------------------------------------------------------
    # CHRONOLOGICAL SPLIT
    # --------------------------------------------------------

    split = int(
        len(frame) * 0.8
    )

    train = frame.iloc[:split]

    test = frame.iloc[split:]

    if (

        len(test) < 20

        or train["hit"].nunique() < 2

        or test["hit"].nunique() < 2

    ):

        return (

            f"{target_market}: NOT TRAINED\n"

            "Insufficient chronological holdout data "

            "containing both outcomes."

        )

    # --------------------------------------------------------
    # FEATURES
    # --------------------------------------------------------

    categorical = [
        "home",
        "away",
        "season"
    ]

    numeric = [
        "month",
        "year"
    ]

    features = categorical + numeric

    # --------------------------------------------------------
    # PREPROCESSING
    # --------------------------------------------------------

    preprocessing = ColumnTransformer([

        (

            "categorical",

            Pipeline([

                (

                    "imputer",

                    SimpleImputer(
                        strategy="most_frequent"
                    )

                ),

                (

                    "encoder",

                    OneHotEncoder(
                        handle_unknown="ignore"
                    )

                )

            ]),

            categorical

        ),

        (

            "numeric",

            Pipeline([

                (

                    "imputer",

                    SimpleImputer(
                        strategy="median"
                    )

                )

            ]),

            numeric

        )

    ])

    # --------------------------------------------------------
    # MODEL
    # --------------------------------------------------------

    model = Pipeline([

        (

            "preprocessing",

            preprocessing

        ),

        (

            "xgboost",

            XGBClassifier(

                n_estimators=250,

                max_depth=3,

                learning_rate=0.04,

                subsample=0.85,

                colsample_bytree=0.85,

                objective="binary:logistic",

                eval_metric="logloss",

                random_state=42,

                n_jobs=2

            )

        )

    ])

    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

    model.fit(
        train[features],
        train["hit"]
    )

    # --------------------------------------------------------
    # TEST
    # --------------------------------------------------------

    probabilities = model.predict_proba(
        test[features]
    )[:, 1]

    predictions = (
        probabilities >= 0.5
    ).astype(int)

    # --------------------------------------------------------
    # BASELINE
    # --------------------------------------------------------

    baseline_probability = float(
        train["hit"].mean()
    )

    baseline_probabilities = [
        baseline_probability
    ] * len(test)

    # --------------------------------------------------------
    # METRICS
    # --------------------------------------------------------

    accuracy = accuracy_score(
        test["hit"],
        predictions
    )

    brier = brier_score_loss(
        test["hit"],
        probabilities
    )

    baseline_brier = brier_score_loss(
        test["hit"],
        baseline_probabilities
    )

    metrics = [

        f"MARKET: {target_market}",

        "",

        f"Total selections: {len(frame)}",

        f"Training selections: {len(train)}",

        f"Testing selections: {len(test)}",

        "",

        f"Training hit rate: {train['hit'].mean():.3f}",

        f"Testing hit rate: {test['hit'].mean():.3f}",

        "",

        f"Accuracy: {accuracy:.3f}",

        f"Brier score: {brier:.3f}",

        f"Baseline Brier score: {baseline_brier:.3f}",

        (

            "Brier improvement: "

            f"{baseline_brier - brier:.3f}"

        )

    ]

    if test["hit"].nunique() == 2:

        auc = roc_auc_score(
            test["hit"],
            probabilities
        )

        metrics.append(
            f"ROC-AUC: {auc:.3f}"
        )

    metrics += [

        "",

        "INTERPRETATION",

        "- Lower Brier score is better.",

        "- A negative Brier improvement means the baseline performed better.",

        "- ROC-AUC measures discrimination.",

        "- Accuracy alone is insufficient.",

        "- These are historical evaluation metrics, not guaranteed future performance."

    ]

    return "\n".join(metrics)


# ============================================================
# REPORT FORMATTING
# ============================================================

def format_current_ranking(ranking, rows):
    """
    Combined current-season ranking.

    The failed-leg columns are now separated by market.
    This prevents OVER 1.5 and UNDER 3.5 failures from
    being mixed together without identification.
    """

    market_counts = defaultdict(
        lambda: {
            "settled": 0,
            "failed": 0,
            "failed_slips": set()
        }
    )

    # Build market-specific counts for every team.
    for row in rows:

        market = market_key(
            row.get("market", "")
        )

        if market not in MARKETS:
            market = "UNKNOWN"

        for team in (
            row["home"],
            row["away"]
        ):

            key = team_key(team)

            if not key:
                continue

            item = market_counts[
                (key, market)
            ]

            item["settled"] += 1

            if row["hit"] == 0:

                item["failed"] += 1

                if row.get("slip_id"):

                    item["failed_slips"].add(
                        row["slip_id"]
                    )

    lines = [

        "## Current-season slip team ranking",

        "",

        "Failures are separated according to the market attached to each individual leg.",

        "",

        "| Team | Settled legs | OVER 1.5 failed | UNDER 3.5 failed | Unknown-market failed | Total failed | Failed slips | Total failure rate |",

        "|---|---:|---:|---:|---:|---:|---:|---:|"

    ]

    if not ranking:

        return lines + [

            "",

            "No settled current-season slip legs found.",

            ""

        ]

    for item in ranking[:20]:

        key = item["team_key"]

        over_failed = market_counts[
            (key, "OVER 1.5")
        ]["failed"]

        under_failed = market_counts[
            (key, "UNDER 3.5")
        ]["failed"]

        unknown_failed = market_counts[
            (key, "UNKNOWN")
        ]["failed"]

        lines.append(

            f"| {item['team']} "

            f"| {item['appearances']} "

            f"| {over_failed} "

            f"| {under_failed} "

            f"| {unknown_failed} "

            f"| {item['failed_legs']} "

            f"| {item['failed_slips']} "

            f"| {item['failure_rate']:.1%} |"

        )

    lines.append("")

    return lines


# ============================================================
# INDIVIDUAL FAILED SELECTION REPORT
# ============================================================

def format_failed_leg_details(rows):
    """
    Lists every failed current-season selection.

    Each row explicitly identifies:
    - Fixture
    - Date
    - Market
    - Result
    - Slip ID

    Unrecognized market labels are displayed rather than
    silently being classified as OVER or UNDER.
    """

    lines = [

        "## Current-season failed selections — market identification",

        "",

        "| Date | Fixture | Market | Result | Slip ID |",

        "|---|---|---|---|---|"

    ]

    failed_rows = [

        row for row in rows

        if row.get("hit") == 0

    ]

    failed_rows.sort(
        key=lambda row: (
            row.get("date").isoformat()
            if row.get("date")
            else "",
            row.get("home", ""),
            row.get("away", "")
        )
    )

    if not failed_rows:

        lines.append(
            "| No failed settled selections | - | - | - | - |"
        )

    for row in failed_rows:

        date = (

            row["date"].strftime("%Y-%m-%d")

            if row.get("date")

            else "Unknown date"

        )

        market = market_key(
            row.get("market", "")
        )

        if not market:
            market = "UNKNOWN"

        elif market not in MARKETS:

            market = f"UNRECOGNIZED: {market}"

        fixture = (
            f"{row['home']} vs {row['away']}"
        )

        slip_id = (
            row.get("slip_id")
            or "N/A"
        )

        lines.append(

            f"| {date} "

            f"| {fixture} "

            f"| {market} "

            f"| LOST "

            f"| {slip_id} |"

        )

    lines.append("")

    return lines


def format_historical_ranking(ranking):

    lines = [

        "## Historical backtest team ranking",

        "",

        "| Team | Appearances | Failed selections | Failure rate |",

        "|---|---:|---:|---:|"

    ]

    if not ranking:

        return lines + [

            "",

            "No historical settled selections found.",

            ""

        ]

    for item in ranking[:20]:

        lines.append(

            f"| {item['team']} "

            f"| {item['appearances']} "

            f"| {item['failed']} "

            f"| {item['failure_rate']:.1%} |"

        )

    lines.append("")

    return lines


# ============================================================
# MARKET-SPECIFIC REPORT FORMATTING
# ============================================================

def format_market_rankings(
    title,
    rankings,
    current=False
):

    lines = [

        f"## {title}",

        ""

    ]

    for market in MARKETS:

        lines += [

            f"### {market}",

            ""

        ]

        ranking = rankings.get(
            market,
            []
        )

        if current:

            lines += [

                "| Team | Settled legs | Failed legs | Failed slips | Failure rate |",

                "|---|---:|---:|---:|---:|"

            ]

            for item in ranking[:20]:

                lines.append(

                    f"| {item['team']} "

                    f"| {item['appearances']} "

                    f"| {item['failed_legs']} "

                    f"| {item['failed_slips']} "

                    f"| {item['failure_rate']:.1%} |"

                )

        else:

            lines += [

                "| Team | Appearances | Failed selections | Failure rate |",

                "|---|---:|---:|---:|"

            ]

            for item in ranking[:20]:

                lines.append(

                    f"| {item['team']} "

                    f"| {item['appearances']} "

                    f"| {item['failed']} "

                    f"| {item['failure_rate']:.1%} |"

                )

        if not ranking:

            if current:

                lines.append(
                    "| No settled data available | - | - | - | - |"
                )

            else:

                lines.append(
                    "| No settled data available | - | - | - |"
                )

        lines.append("")

    return lines


# ============================================================
# COMPARISON REPORT
# ============================================================

def format_comparison(
    team_overlaps,
    exact_overlaps
):

    lines = [

        "## Current slips vs historical backtest",

        "",

        "### Teams appearing in both top-20 rankings",

        "",

        "| Team | Current failed slips | Current failed legs | Historical failures | Historical failure rate |",

        "|---|---:|---:|---:|---:|"

    ]

    if team_overlaps:

        for item in team_overlaps:

            lines.append(

                f"| {item['team']} "

                f"| {item['current_failed_slips']} "

                f"| {item['current_failed_legs']} "

                f"| {item['historical_failed']} "

                f"| {item['historical_rate']:.1%} |"

            )

    else:

        lines.append(
            "| No overlapping teams in the top 20 | - | - | - | - |"
        )

    lines += [

        "",

        "### Exact fixture, date and market overlaps",

        "",

        "| Date | Fixture | Market | Current slip leg | Historical backtest |",

        "|---|---|---|---|---|"

    ]

    if exact_overlaps:

        for item in exact_overlaps:

            lines.append(

                f"| {item['date']} "

                f"| {item['fixture']} "

                f"| {item['market']} "

                f"| {item['current_result']} "

                f"| {item['historical_result']} |"

            )

    else:

        lines.append(
            "| No exact fixture/date/market overlaps found | - | - | - | - |"
        )

    lines.append("")

    return lines


# ============================================================
# MAIN OBSERVER
# ============================================================

def main():

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    now = datetime.now(timezone.utc)

    current_season = get_season(now)

    # --------------------------------------------------------
    # HISTORICAL DATA
    # --------------------------------------------------------

    core1 = read_backtest(
        CORE1_FILE,
        "OVER 1.5"
    )

    core2 = read_backtest(
        CORE2_FILE,
        "UNDER 3.5"
    )

    historical = deduplicate(
        core1 + core2
    )

    # --------------------------------------------------------
    # CURRENT SLIP ARCHIVE
    # --------------------------------------------------------

    all_current, current_note = (
        read_current_slip_archive()
    )

    current = [

        row for row in all_current

        if row["season"] == current_season

    ]

    # --------------------------------------------------------
    # COMBINED RANKINGS
    # --------------------------------------------------------

    current_ranking = current_slip_team_analysis(
        current
    )

    historical_ranking = analyse_teams(
        historical
    )

    # --------------------------------------------------------
    # MARKET-SPECIFIC RANKINGS
    # --------------------------------------------------------

    current_market_rankings = (
        current_teams_by_market(current)
    )

    historical_market_rankings = (
        analyse_teams_by_market(historical)
    )

    # --------------------------------------------------------
    # COMPARISON
    # --------------------------------------------------------

    team_overlaps, exact_overlaps = (
        compare_current_with_backtest(
            current,
            current_ranking,
            historical,
            historical_ranking
        )
    )

    # --------------------------------------------------------
    # MARKET-SPECIFIC COMPARISON
    # --------------------------------------------------------

    market_comparisons = {}

    for market in MARKETS:

        market_current = [

            row for row in current

            if market_key(row["market"]) == market

        ]

        market_historical = [

            row for row in historical

            if market_key(row["market"]) == market

        ]

        market_comparisons[market] = (
            compare_current_with_backtest(
                market_current,
                current_market_rankings[market],
                market_historical,
                historical_market_rankings[market]
            )
        )

    # --------------------------------------------------------
    # HISTORICAL COVERAGE
    # --------------------------------------------------------

    seasons = sorted({

        row["season"]

        for row in historical

        if row["season"] != "Unknown"

    })

    # --------------------------------------------------------
    # INDEPENDENT XGBOOST MODELS
    # --------------------------------------------------------

    xgb_results = [

        train_xgboost(
            historical,
            "OVER 1.5"
        ),

        train_xgboost(
            historical,
            "UNDER 3.5"
        )

    ]

    # --------------------------------------------------------
    # DATA COUNTS
    # --------------------------------------------------------

    current_slip_count = len({

        row["slip_id"]

        for row in current

        if row.get("slip_id")

    })

    current_over_count = sum(

        1 for row in current

        if market_key(row["market"]) == "OVER 1.5"

    )

    current_under_count = sum(

        1 for row in current

        if market_key(row["market"]) == "UNDER 3.5"

    )

    current_unknown_count = sum(

        1 for row in current

        if market_key(row["market"]) not in MARKETS

    )

    # --------------------------------------------------------
    # REPORT HEADER
    # --------------------------------------------------------

    report = [

        "# BARBADOX XGBOOST OBSERVER",

        "",

        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",

        f"Current season: {current_season}",

        "",

        "## DATA COVERAGE",

        "",

        f"- Core 1 historical settled selections: {len(core1)}",

        f"- Core 2 historical settled selections: {len(core2)}",

        f"- Historical unique selections: {len(historical)}",

        f"- Historical seasons found: {', '.join(seasons) if seasons else 'None'}",

        f"- Current archive: {current_note}",

        f"- Current-season settled slip legs: {len(current)}",

        f"- Current-season slips represented: {current_slip_count}",

        f"- Current OVER 1.5 legs: {current_over_count}",

        f"- Current UNDER 3.5 legs: {current_under_count}",

        f"- Current unrecognized-market legs: {current_unknown_count}",

        "",

        "## MARKET DEFINITIONS",

        "",

        "- Core 1 = OVER 1.5 goals.",

        "- Core 2 = UNDER 3.5 goals.",

        "- Each market is analysed independently.",

        "- Combined rankings are retained for comparison.",

        "- Every current failed leg is listed with its market label.",

        "",

        "## CURRENT-SEASON SLIP ANALYSIS",

        "",

        "Only individual legs explicitly marked LOST count as failed legs.",

        "A winning leg in a lost accumulator is not blamed for the accumulator failure.",

        "Pending legs are excluded.",

        "Unknown or unrecognized market labels are not automatically classified as OVER or UNDER.",

        ""

    ]

    # --------------------------------------------------------
    # COMBINED REPORTS
    # --------------------------------------------------------

    report += format_current_ranking(
        current_ranking,
        current
    )

    # New: list every failed selection and its market.
    report += format_failed_leg_details(
        current
    )

    report += format_historical_ranking(
        historical_ranking
    )

    # --------------------------------------------------------
    # MARKET-SPECIFIC REPORTS
    # --------------------------------------------------------

    report += format_market_rankings(

        "CURRENT-SEASON MARKET-SPECIFIC TEAM ANALYSIS",

        current_market_rankings,

        current=True

    )

    report += format_market_rankings(

        "HISTORICAL MARKET-SPECIFIC TEAM ANALYSIS",

        historical_market_rankings,

        current=False

    )

    # --------------------------------------------------------
    # COMBINED COMPARISON
    # --------------------------------------------------------

    report += format_comparison(
        team_overlaps,
        exact_overlaps
    )

    # --------------------------------------------------------
    # MARKET-SPECIFIC COMPARISONS
    # --------------------------------------------------------

    for market in MARKETS:

        overlaps, exact = market_comparisons[market]

        report += [

            f"## {market} CURRENT VS HISTORICAL COMPARISON",

            ""

        ]

        report += format_comparison(
            overlaps,
            exact
        )

    # --------------------------------------------------------
    # XGBOOST RESULTS
    # --------------------------------------------------------

    report += [

        "## MARKET-SPECIFIC XGBOOST OBSERVATION",

        ""

    ]

    report += xgb_results

    report += [

        "",

        "## INTERPRETATION",

        "",

        "- OVER 1.5 and UNDER 3.5 have separate model training datasets.",

        "- Current market rankings use settled slips only.",

        "- Historical market rankings use settled backtest selections.",

        "- Failed slips count distinct slip IDs.",

        "- Current failure rates use settled leg appearances as the denominator.",

        "- Historical rankings use settled backtest selections.",

        "- Team names are normalized for comparison.",

        "- Exact overlap requires the same date, market and fixture.",

        "- Team association is descriptive, not proof of causation.",

        "- Pending selections are excluded.",

        "- Unknown-market selections are reported separately.",

        "- XGBoost metrics are historical evaluation results, not guarantees.",

        "- Brier score should be compared with the baseline.",

        "- No Core 1 or Core 2 prediction logic is modified.",

        ""

    ]

    # --------------------------------------------------------
    # SAVE REPORTS
    # --------------------------------------------------------

    content = "\n".join(report)

    timestamp = now.strftime(
        "%Y%m%d_%H%M%S"
    )

    timestamped = (
        REPORT_DIR
        / f"observer_{timestamp}.md"
    )

    latest = (
        REPORT_DIR
        / "latest.md"
    )

    timestamped.write_text(
        content,
        encoding="utf-8"
    )

    latest.write_text(
        content,
        encoding="utf-8"
    )

    print(content)

    print(
        f"\nSaved: {timestamped}"
    )

    print(
        f"Saved: {latest}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
