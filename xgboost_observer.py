
#!/usr/bin/env python3
"""
BARBADOX XGBOOST OBSERVER

Read-only observer:
1. Finds teams most associated with failed current-season slips.
2. Finds teams most associated with failed selections across historical
   Core 1 and Core 2 backtests.
3. Trains an XGBoost model when enough labelled data exists.
4. Generates a report every time it runs.

It does NOT modify Core 1, Core 2, predictions or slip generation.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

CORE1_FILE = ROOT / "reports" / "core1_results.csv"
CORE2_FILE = ROOT / "reports" / "core2_results.csv"

REPORT_DIR = ROOT / "reports" / "xgboost_observer"

SEASON_START_MONTH = int(
    os.getenv("OBSERVER_SEASON_START_MONTH", "7")
)

SEASON_START_DAY = int(
    os.getenv("OBSERVER_SEASON_START_DAY", "1")
)


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
            home, away = fixture.split(separator, 1)
            return clean(home), clean(away)

    return "", ""


def parse_outcome(value):
    value = clean(value).lower()

    if value in {
        "1", "true", "yes", "won",
        "win", "hit"
    }:
        return 1

    if value in {
        "0", "false", "no", "lost",
        "loss", "miss"
    }:
        return 0

    return None


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
                "1", "true", "yes",
                "cleared", "qualified"
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

            # Never treat pending selections as losses.
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


def fetch_current_slips():
    """
    Reads the existing slip-history endpoint.

    The endpoint URL is configured through GitHub Secrets.
    Its actual JSON structure must be verified against Barbadox's
    /api/slip-history response before relying on this parser.
    """

    url = os.getenv("BARBADOX_SLIP_HISTORY_URL", "")
    token = os.getenv("BARBADOX_SLIP_HISTORY_TOKEN", "")

    if not url:
        return [], "Current slip endpoint not configured."

    headers = {
        "Accept": "application/json",
        "User-Agent": "Barbadox-XGBoost-Observer/1.0"
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )
    except Exception as error:
        return [], f"Could not retrieve slips: {error}"

    if isinstance(payload, dict):
        for key in [
            "slips",
            "data",
            "history",
            "results",
            "items"
        ]:
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break

    if not isinstance(payload, list):
        return [], "Unexpected slip-history response format."

    selections = []

    for slip in payload:

        if not isinstance(slip, dict):
            continue

        slip_id = get_value(
            slip,
            "id",
            "slip_id",
            "reference",
            "ticket_id"
        )

        slip_status = get_value(
            slip,
            "status",
            "result",
            "settlement",
            "state"
        ).lower()

        legs = (
            slip.get("selections")
            or slip.get("legs")
            or slip.get("fixtures")
            or slip.get("matches")
            or []
        )

        if isinstance(legs, dict):
            legs = [legs]

        if not isinstance(legs, list):
            continue

        for leg in legs:

            if not isinstance(leg, dict):
                continue

            status = get_value(
                leg,
                "status",
                "result",
                "outcome",
                "settlement"
            ).lower()

            if not status:
                status = slip_status

            outcome = parse_outcome(status)

            if outcome is None:
                continue

            home, away = get_teams(leg)

            if not home or not away:
                continue

            date = parse_date(
                get_value(
                    leg,
                    "date",
                    "match_date",
                    "utc_date",
                    "kickoff",
                    "fixture_date"
                )
                or get_value(
                    slip,
                    "date",
                    "created_at",
                    "timestamp"
                )
            )

            selections.append({
                "market": get_value(
                    leg,
                    "market",
                    "selection",
                    "pick",
                    "bet_type",
                    "prediction"
                ) or "Unknown market",

                "home": home,
                "away": away,
                "hit": outcome,
                "date": date,
                "season": get_season(date),
                "slip_id": slip_id,
                "source": "current_slip_api"
            })

    return selections, (
        f"Retrieved {len(selections)} settled selection legs."
    )


def deduplicate(rows):
    """
    Deduplicate the same fixture and market for team performance rates.
    Different slips containing that fixture do not inflate the rate.
    """

    seen = set()
    output = []

    for row in rows:

        date_key = (
            row["date"].date().isoformat()
            if row["date"] else ""
        )

        key = (
            row["market"].lower(),
            row["home"].lower(),
            row["away"].lower(),
            date_key
        )

        if key not in seen:
            seen.add(key)
            output.append(row)

    return output


def analyse_teams(rows):
    stats = defaultdict(lambda: {
        "appearances": 0,
        "won": 0,
        "failed": 0,
        "fixtures": set(),
        "failed_fixtures": set(),
        "slips_affected": set()
    })

    for row in rows:

        date_key = (
            row["date"].date().isoformat()
            if row["date"] else ""
        )

        fixture_key = (
            row["market"].lower(),
            row["home"].lower(),
            row["away"].lower(),
            date_key
        )

        for team in [row["home"], row["away"]]:

            item = stats[team]

            if fixture_key not in item["fixtures"]:

                item["fixtures"].add(fixture_key)
                item["appearances"] += 1

                if row["hit"] == 1:
                    item["won"] += 1

                else:
                    item["failed"] += 1
                    item["failed_fixtures"].add(
                        fixture_key
                    )

            if row["hit"] == 0 and row.get("slip_id"):
                item["slips_affected"].add(
                    row["slip_id"]
                )

    results = []

    for team, item in stats.items():

        appearances = item["appearances"]

        failure_rate = (
            item["failed"] / appearances
            if appearances else 0
        )

        results.append({
            "team": team,
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


def train_xgboost(rows):
    """
    Secondary model.

    Uses chronological training/testing to reduce data leakage.
    Does not alter the team failure rankings.
    """

    if len(rows) < 150:
        return (
            f"XGBoost not trained: only {len(rows)} "
            "settled unique selections. At least 150 required."
        )

    if len({row["hit"] for row in rows}) < 2:
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
            f"XGBoost dependencies unavailable: {error}. "
            "Install requirements-observer.txt."
        )

    data = []

    for row in rows:

        date = row["date"]

        data.append({
            "market": row["market"],
            "home": row["home"],
            "away": row["away"],
            "season": row["season"],
            "month": date.month if date else None,
            "year": date.year if date else None,
            "date_sort": (
                date.timestamp() if date else 0
            ),
            "hit": row["hit"]
        })

    frame = pd.DataFrame(data).sort_values(
        "date_sort"
    )

    split = int(len(frame) * 0.8)

    train = frame.iloc[:split]
    test = frame.iloc[split:]

    if len(test) < 20 or train["hit"].nunique() < 2:
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
        ("preprocessing", preprocessing),
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


def format_ranking(title, ranking):
    lines = [
        f"## {title}",
        "",
        "| Team | Appearances | Failed | Failure rate | Slips affected |",
        "|---|---:|---:|---:|---:|"
    ]

    if not ranking:
        return [
            f"## {title}",
            "",
            "No settled selections available.",
            ""
        ]

    for item in ranking[:20]:

        lines.append(
            f"| {item['team']} "
            f"| {item['appearances']} "
            f"| {item['failed']} "
            f"| {item['failure_rate']:.1%} "
            f"| {item['slips_affected']} |"
        )

    lines.append("")
    return lines


def main():

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    core1 = read_backtest(
        CORE1_FILE,
        "Core 1"
    )

    core2 = read_backtest(
        CORE2_FILE,
        "Core 2"
    )

    historical = deduplicate(
        core1 + core2
    )

    current, current_note = fetch_current_slips()

    now = datetime.now(timezone.utc)

    current_season = get_season(now)

    current = [
        row for row in current
        if row["season"] == current_season
    ]

    current_ranking = analyse_teams(
        deduplicate(current)
    )

    historical_ranking = analyse_teams(
        historical
    )

    seasons = sorted({
        row["season"]
        for row in historical
        if row["season"] != "Unknown"
    })

    xgb_result = train_xgboost(
        historical
    )

    report = [
        "# BARBADOX XGBOOST OBSERVER",
        "",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Current season: {current_season}",
        "",
        "## DATA COVERAGE",
        "",
        f"- Core 1 settled selections: {len(core1)}",
        f"- Core 2 settled selections: {len(core2)}",
        f"- Historical unique selections: {len(historical)}",
        f"- Historical seasons found: {', '.join(seasons) if seasons else 'None'}",
        f"- Current slip data: {current_note}",
        "",
        (
            "Four-season coverage is only claimed if four actual "
            "backtest seasons are present in the source files."
        ),
        "",
        "## CURRENT-SEASON SLIP ANALYSIS",
        "",
        (
            "A team is associated with a failed selection when it "
            "appears in the failed fixture. This does not prove "
            "that the team caused the slip to fail."
        ),
        ""
    ]

    report += format_ranking(
        "Current-season team ranking",
        current_ranking
    )

    report += format_ranking(
        "Historical backtest team ranking",
        historical_ranking
    )

    report += [
        "## XGBOOST OBSERVATION",
        "",
        xgb_result,
        "",
        "## INTERPRETATION",
        "",
        "- Pending selections are excluded.",
        "- Repeated fixtures are deduplicated for team failure rates.",
        "- Both teams in a failed fixture are associated with the failure.",
        "- Team rankings are descriptive, not causal.",
        "- XGBoost is not trained when data is insufficient.",
        "- No Core 1 or Core 2 logic is modified.",
        ""
    ]

    content = "\n".join(report)

    timestamp = now.strftime(
        "%Y%m%d_%H%M%S"
    )

    timestamped = (
        REPORT_DIR /
        f"observer_{timestamp}.md"
    )

    latest = REPORT_DIR / "latest.md"

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
