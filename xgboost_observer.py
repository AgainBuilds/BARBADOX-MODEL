
#!/usr/bin/env python3
"""
BARBADOX XGBOOST OBSERVER

This observer performs three separate tasks:

1. Analyses actual current-season generated slips from slips_browser.csv.
2. Analyses historical Core 1 and Core 2 backtest results.
3. Compares current slip failures against historical backtest failures.

It also trains a secondary XGBoost model when sufficient historical
data is available.

IMPORTANT:
- It does not modify Core 1.
- It does not modify Core 2.
- It does not modify predictions.
- It does not modify slip generation.
- It does not modify the slip tracker.
- It only reads existing data and writes observer reports.
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


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


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
    """
    Normalize club names for comparison.

    This handles punctuation, accents and common suffixes.
    It cannot guarantee that every different provider alias
    for the same club will be recognized.
    """

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


def market_key(value):
    value = clean(value).upper()

    aliases = {
        "OVER 1.5 GOALS": "OVER 1.5",
        "OVER 1.5": "OVER 1.5",
        "O1.5": "OVER 1.5",
        "CORE 1": "OVER 1.5",

        "UNDER 3.5 GOALS": "UNDER 3.5",
        "UNDER 3.5": "UNDER 3.5",
        "U3.5": "UNDER 3.5",
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
        print(f"WARNING: Missing file: {path}")
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

            # Pending selections must not become losses.
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
    """
    Reads the actual slips_browser.csv archive.

    Only individual legs explicitly marked LOST are counted
    as failed legs.

    A lost accumulator does not automatically make every
    selection inside it a losing selection.

    Pending legs are excluded.
    """

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

                # A WON slip can supply WON when a leg's
                # individual result is absent.
                #
                # Never infer that every leg LOST simply
                # because the overall accumulator LOST.
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
    """
    Deduplicates identical fixture/date/market selections.

    This is used for historical team rates.
    """

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

                    item["failed_fixtures"].add(
                        key
                    )

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
    """
    Current archive analysis.

    appearances:
        Number of settled leg appearances.

    failed_legs:
        Number of legs explicitly marked LOST.

    failed_slips:
        Number of distinct lost slips containing a
        failed leg involving the team.

    A team is not blamed for another team's winning leg.
    """

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
# CURRENT VS HISTORICAL COMPARISON
# ============================================================

def compare_current_with_backtest(
    current_rows,
    current_ranking,
    historical_rows,
    historical_ranking
):
    """
    Compares:
    1. Teams in both top-20 rankings.
    2. Exact fixture/date/market overlaps.
    """

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

def train_xgboost(rows):
    """
    Secondary model.

    Uses chronological training/testing to reduce leakage.
    Does not modify the team rankings or betting model.
    """

    if len(rows) < MIN_XGBOOST_ROWS:

        return (
            "XGBoost not trained: only "
            f"{len(rows)} settled selections. "
            f"At least {MIN_XGBOOST_ROWS} required."
        )

    if len({
        row["hit"]
        for row in rows
    }) < 2:

        return (
            "XGBoost not trained: historical data "
            "contains only one outcome class."
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
            "XGBoost dependencies unavailable: "
            f"{error}. Install requirements-observer.txt."
        )

    data = []

    for row in rows:

        date = row["date"]

        data.append({
            "market": row["market"],
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

    split = int(
        len(frame) * 0.8
    )

    train = frame.iloc[:split]
    test = frame.iloc[split:]

    if (
        len(test) < 20
        or train["hit"].nunique() < 2
    ):

        return (
            "XGBoost not trained: insufficient "
            "chronological holdout data."
        )

    categorical = [
        "market",
        "home",
        "away",
        "season"
    ]

    numeric = [
        "month",
        "year"
    ]

    features = categorical + numeric

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

    model.fit(
        train[features],
        train["hit"]
    )

    probabilities = model.predict_proba(
        test[features]
    )[:, 1]

    predictions = (
        probabilities >= 0.5
    ).astype(int)

    metrics = [
        f"Training selections: {len(train)}",
        f"Test selections: {len(test)}",
        (
            "Accuracy: "
            f"{accuracy_score(test['hit'], predictions):.3f}"
        ),
        (
            "Brier score: "
            f"{brier_score_loss(test['hit'], probabilities):.3f}"
        )
    ]

    if test["hit"].nunique() == 2:

        metrics.append(
            "ROC-AUC: "
            f"{roc_auc_score(test['hit'], probabilities):.3f}"
        )

    return (
        "XGBoost trained and evaluated.\n"
        + "\n".join(metrics)
    )


# ============================================================
# REPORT FORMATTING
# ============================================================

def format_current_ranking(ranking):

    lines = [
        "## Current-season slip team ranking",
        "",
        "| Team | Settled legs | Failed legs | Failed slips | Leg failure rate |",
        "|---|---:|---:|---:|---:|"
    ]

    if not ranking:

        return lines + [
            "",
            "No settled current-season slip legs found.",
            ""
        ]

    for item in ranking[:20]:

        lines.append(
            f"| {item['team']} "
            f"| {item['appearances']} "
            f"| {item['failed_legs']} "
            f"| {item['failed_slips']} "
            f"| {item['failure_rate']:.1%} |"
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
        row
        for row in all_current
        if row["season"] == current_season
    ]

    current_ranking = (
        current_slip_team_analysis(current)
    )

    historical_ranking = (
        analyse_teams(historical)
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
    # HISTORICAL COVERAGE
    # --------------------------------------------------------

    seasons = sorted({
        row["season"]
        for row in historical
        if row["season"] != "Unknown"
    })

    # --------------------------------------------------------
    # XGBOOST
    # --------------------------------------------------------

    xgb_result = train_xgboost(
        historical
    )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    current_slip_count = len({
        row["slip_id"]
        for row in current
        if row.get("slip_id")
    })

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
        "",
        "## CURRENT-SEASON SLIP ANALYSIS",
        "",
        "Only individual legs explicitly marked LOST count as failed legs.",
        "A winning leg in a lost accumulator is not blamed for the accumulator failure.",
        "Pending legs are excluded.",
        "",
    ]

    report += format_current_ranking(
        current_ranking
    )

    report += format_historical_ranking(
        historical_ranking
    )

    report += format_comparison(
        team_overlaps,
        exact_overlaps
    )

    report += [
        "## XGBOOST OBSERVATION",
        "",
        xgb_result,
        "",
        "## INTERPRETATION",
        "",
        "- Current slip analysis uses slips_browser.csv.",
        "- Current and historical rankings are calculated separately.",
        "- Failed slips count distinct slip IDs.",
        "- Current failure rates use settled leg appearances as the denominator.",
        "- Historical rankings use settled backtest selections.",
        "- Team names are normalized for comparison.",
        "- Exact overlap requires the same date, market and fixture.",
        "- Team association is descriptive, not proof of causation.",
        "- Pending selections are excluded.",
        "- No Core 1 or Core 2 prediction logic is modified.",
        "",
    ]

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

    print(f"\nSaved: {timestamped}")
    print(f"Saved: {latest}")


if __name__ == "__main__":
    main()
