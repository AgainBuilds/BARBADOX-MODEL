/*
 * BARBADOX LIVE-SCORE TRACKER
 *
 * Integrates with the existing console.html slips tracker.
 *
 * Features:
 * - Displays current scores and match status.
 * - Shows whether each selection is on track.
 * - Matches fixtures by team names and date.
 * - Captures the FINAL SCORE of every finished leg and saves it
 *   on the leg itself, so the slips history archive, the CSV
 *   export and the GitHub record all keep the score forever.
 * - Automatically grades completed four-leg slips
 *   when every result can be confidently determined.
 * - Preserves the existing tracker and manual grading.
 */

(() => {
    "use strict";

    if (window.__barbadoxLiveScoresStarted) {
        return;
    }

    window.__barbadoxLiveScoresStarted = true;

    const FINISHED = new Set([
        "FT",
        "AET",
        "PEN",
        "AWD",
        "WO"
    ]);

    const PLAYING = new Set([
        "1H",
        "HT",
        "2H",
        "ET",
        "BT",
        "P",
        "LIVE",
        "INT"
    ]);

    let fixtures = [];
    let updatedAt = null;
    let message = "";

    const $ = id => document.getElementById(id);


    /*
     * Safely escape text before placing it in the tracker.
     */
    function escapeHTML(value) {
        const text = String(value ?? "");

        if (typeof esc === "function") {
            return esc(text);
        }

        return text.replace(/[&<>"']/g, character => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }


    /*
     * Add the score banner inside the existing tracker.
     */
    function addUI() {
        if ($("liveScoreBanner")) {
            return;
        }

        const trackerKPIs = $("trackerKpis");

        if (!trackerKPIs) {
            return;
        }

        const css = document.createElement("style");

        css.textContent = `
            .live-banner {
                padding: 10px 12px;
                margin: 0 0 12px;
                border: 1px solid var(--line);
                border-radius: 9px;
                color: var(--dim);
                font-size: 11px;
            }

            .live-leg {
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                align-items: center;
                gap: 6px;
                padding: 8px 0;
                border-bottom: 1px solid var(--line);
            }

            .live-leg:last-child {
                border-bottom: 0;
            }

            .live-score {
                font-weight: 900;
                color: var(--ink);
                white-space: nowrap;
            }

            .live-detail {
                font-size: 10px;
                color: var(--dim);
            }

            .live-good {
                color: var(--green);
            }

            .live-bad {
                color: var(--pink);
            }

            .live-wait {
                color: var(--amber);
            }
        `;

        document.head.appendChild(css);

        trackerKPIs.insertAdjacentHTML(
            "beforebegin",
            `
                <div
                    class="live-banner"
                    id="liveScoreBanner"
                    role="status"
                >
                    Connecting to live scores…
                </div>
            `
        );
    }


    /*
     * Normalize club names for fixture matching.
     */
    function normalizeTeam(name) {
        return String(name || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(
                /\b(football club|soccer club|fc|cf|afc|sc|ac|calcio|club|football|the)\b/g,
                " "
            )
            .replace(/[^a-z0-9]+/g, " ")
            .trim()
            .split(/\s+/)
            .filter(Boolean);
    }


    /*
     * Compare two club names.
     */
    function similarity(first, second) {
        const a = new Set(normalizeTeam(first));
        const b = new Set(normalizeTeam(second));

        if (!a.size || !b.size) {
            return 0;
        }

        let common = 0;

        for (const word of a) {
            if (b.has(word)) {
                common++;
            }
        }

        return common / Math.max(a.size, b.size);
    }


    /*
     * Compare fixture dates.
     */
    function dayDifference(first, second) {
        const a = Date.parse(
            String(first || "").slice(0, 10)
            + "T12:00:00Z"
        );

        const b = Date.parse(
            String(second || "").slice(0, 10)
            + "T12:00:00Z"
        );

        if (
            !Number.isFinite(a)
            || !Number.isFinite(b)
        ) {
            return 99;
        }

        return Math.abs(
            Math.round((a - b) / 86400000)
        );
    }


    /*
     * Match a tracker leg against the score provider.
     *
     * A fixture must have similar home/away names and
     * a date within one day. No score is invented when
     * a fixture cannot be matched.
     */
    function matchFixture(leg) {
        let bestFixture = null;
        let bestScore = 0;

        for (const fixture of fixtures) {
            if (
                dayDifference(
                    leg.date,
                    fixture.date
                ) > 1
            ) {
                continue;
            }

            const direct = (
                similarity(leg.home, fixture.home)
                +
                similarity(leg.away, fixture.away)
            ) / 2;

            const reversed = (
                similarity(leg.home, fixture.away)
                +
                similarity(leg.away, fixture.home)
            ) / 2;

            const score = Math.max(
                direct,
                reversed
            );

            if (score > bestScore) {
                bestScore = score;
                bestFixture = fixture;
            }
        }

        return bestScore >= 0.62
            ? bestFixture
            : null;
    }


    /*
     * Human-readable final score, e.g. "2 - 1".
     * Empty string when the fixture has no confirmed score.
     */
    function formatScore(fixture) {
        if (
            !fixture
            || fixture.homeScore == null
            || fixture.awayScore == null
        ) {
            return "";
        }

        return `${fixture.homeScore} - ${fixture.awayScore}`;
    }


    /*
     * Convert provider status codes into readable text.
     */
    function getMatchStatus(fixture) {
        if (FINISHED.has(fixture.status)) {
            if (fixture.status === "FT") {
                return "FULL TIME";
            }

            return (
                fixture.statusText || "FINISHED"
            ).toUpperCase();
        }

        if (PLAYING.has(fixture.status)) {
            if (fixture.status === "HT") {
                return "HALF TIME";
            }

            const minute = fixture.elapsed == null
                ? ""
                : ` · ${fixture.elapsed}′`;

            return `LIVE${minute}`;
        }

        if (
            ["PST", "CANC", "ABD", "SUSP"]
                .includes(fixture.status)
        ) {
            return (
                fixture.statusText
                || fixture.status
            ).toUpperCase();
        }

        return "SCHEDULED";
    }


    /*
     * Determine the final result for supported markets.
     *
     * Returns:
     * true  = won
     * false = lost
     * null  = cannot determine safely
     */
    function getOutcome(leg, fixture) {
        if (
            !FINISHED.has(fixture.status)
            || fixture.homeScore == null
            || fixture.awayScore == null
        ) {
            return null;
        }

        const total =
            Number(fixture.homeScore)
            +
            Number(fixture.awayScore);

        const market = String(
            leg.market || ""
        ).toUpperCase();

        if (market.includes("OVER 1.5")) {
            return total >= 2;
        }

        if (market.includes("UNDER 3.5")) {
            return total <= 3;
        }

        return null;
    }


    /*
     * Explain the current state of an individual leg.
     */
    function getLegState(leg, fixture) {
        if (!fixture) {
            return [
                "FIXTURE NOT MATCHED",
                "live-wait"
            ];
        }

        const hasScore =
            fixture.homeScore != null
            && fixture.awayScore != null;

        const total = hasScore
            ? Number(fixture.homeScore)
                + Number(fixture.awayScore)
            : null;

        if (FINISHED.has(fixture.status)) {
            const outcome = getOutcome(
                leg,
                fixture
            );

            if (outcome === true) {
                return ["WON", "live-good"];
            }

            if (outcome === false) {
                return ["LOST", "live-bad"];
            }

            return [
                "RESULT UNAVAILABLE",
                "live-wait"
            ];
        }

        if (
            ["PST", "CANC", "ABD", "SUSP"]
                .includes(fixture.status)
        ) {
            return [
                getMatchStatus(fixture),
                "live-wait"
            ];
        }

        if (total === null) {
            return [
                "NOT STARTED",
                "live-wait"
            ];
        }

        const market = String(
            leg.market || ""
        ).toUpperCase();

        if (market.includes("OVER 1.5")) {
            if (total >= 2) {
                return [
                    "TARGET REACHED · NOT FINAL",
                    "live-good"
                ];
            }

            const needed = 2 - total;

            return [
                `NEEDS ${needed} MORE GOAL`
                + (needed === 1 ? "" : "S"),
                "live-wait"
            ];
        }

        if (market.includes("UNDER 3.5")) {
            if (total >= 4) {
                return [
                    "LINE CROSSED · NOT FINAL",
                    "live-bad"
                ];
            }

            const room = 3 - total;

            return [
                `CURRENTLY UNDER · ${room} GOAL`
                + (room === 1 ? "" : "S")
                + " ROOM",
                "live-good"
            ];
        }

        return [
            "IN PLAY",
            "live-wait"
        ];
    }


    /*
     * Capture the final score of every finished leg.
     *
     * Runs on EVERY slip (pending, won, lost) so scores are
     * recorded even when the slip was graded manually before
     * the live feed confirmed the fixture. The saved scores
     * flow automatically into the slips history archive,
     * its CSV export, and the GitHub record.
     */
    function captureScores() {
        if (
            typeof readTracker !== "function"
            || typeof saveTracker !== "function"
        ) {
            return false;
        }

        const slips = readTracker();

        if (!Array.isArray(slips)) {
            return false;
        }

        let changed = false;

        for (const slip of slips) {
            if (!Array.isArray(slip.legs)) {
                continue;
            }

            for (const leg of slip.legs) {
                const fixture = matchFixture(leg);

                if (
                    !fixture
                    || !FINISHED.has(fixture.status)
                ) {
                    continue;
                }

                const score = formatScore(fixture);

                if (!score) {
                    continue;
                }

                if (leg.liveScore !== score) {
                    leg.liveScore = score;
                    changed = true;
                }

                const statusText = getMatchStatus(fixture);

                if (leg.fixtureStatus !== statusText) {
                    leg.fixtureStatus = statusText;
                    changed = true;
                }

                const outcome = getOutcome(leg, fixture);

                const result =
                    outcome === true
                        ? "WON"
                        : outcome === false
                            ? "LOST"
                            : (leg.result || "PENDING");

                if (leg.result !== result) {
                    leg.result = result;
                    changed = true;
                }
            }
        }

        if (changed) {
            saveTracker(slips);
        }

        return changed;
    }


    /*
     * Automatically grade a slip only if:
     *
     * - It is still pending.
     * - It has exactly four legs.
     * - All four fixtures are matched.
     * - All four matches are finished.
     * - Every market result can be determined.
     */
    function autoGradeSlips() {
        if (
            typeof readTracker !== "function"
            || typeof saveTracker !== "function"
        ) {
            return false;
        }

        const slips = readTracker();

        if (!Array.isArray(slips)) {
            return false;
        }

        let changed = false;

        for (const slip of slips) {
            if (
                slip.status !== "PENDING"
                || !Array.isArray(slip.legs)
                || slip.legs.length !== 4
            ) {
                continue;
            }

            const matchedLegs = slip.legs.map(
                leg => ({
                    leg,
                    fixture: matchFixture(leg)
                })
            );

            const everyFixtureFinished =
                matchedLegs.every(
                    item =>
                        item.fixture
                        && FINISHED.has(
                            item.fixture.status
                        )
                );

            if (!everyFixtureFinished) {
                continue;
            }

            const outcomes = matchedLegs.map(
                item => getOutcome(
                    item.leg,
                    item.fixture
                )
            );

            if (
                outcomes.some(
                    outcome => outcome === null
                )
            ) {
                continue;
            }

            /* Stamp every leg with its final score before
               grading, so the archive keeps the scores. */
            matchedLegs.forEach(item => {
                const score = formatScore(item.fixture);

                if (score) {
                    item.leg.liveScore = score;
                }

                item.leg.fixtureStatus = getMatchStatus(
                    item.fixture
                );

                const outcome = getOutcome(
                    item.leg,
                    item.fixture
                );

                item.leg.result =
                    outcome === true
                        ? "WON"
                        : outcome === false
                            ? "LOST"
                            : (item.leg.result || "PENDING");
            });

            slip.status = outcomes.every(
                Boolean
            )
                ? "WON"
                : "LOST";

            slip.gradedAt = new Date().toISOString();

            slip.gradingSource = "LIVE_SCORE_API";

            slip.autoGraded = true;

            changed = true;
        }

        if (changed) {
            saveTracker(slips);
        }

        return changed;
    }


    /*
     * Render scores beneath each slip's existing legs.
     */
    function renderLiveScores() {
        addUI();

        const banner = $("liveScoreBanner");

        if (banner) {
            if (message) {
                banner.textContent = message;
            } else if (updatedAt) {
                banner.textContent =
                    "LIVE SCORES · Provider updated "
                    + new Date(
                        updatedAt
                    ).toLocaleTimeString()
                    + " · Page checks every 60 seconds.";
            } else {
                banner.textContent =
                    "Waiting for score data…";
            }
        }

        if (typeof readTracker !== "function") {
            return;
        }

        const filter =
            $("trackerFilter")?.value || "ALL";

        const allSlips = readTracker();

        if (!Array.isArray(allSlips)) {
            return;
        }

        const visibleSlips = allSlips.filter(
            slip =>
                filter === "ALL"
                || slip.status === filter
        );

        const slipElements = document.querySelectorAll(
            "#trackerList .sliprow"
        );

        slipElements.forEach((element, slipIndex) => {
            const slip = visibleSlips[slipIndex];

            if (
                !slip
                || !Array.isArray(slip.legs)
            ) {
                return;
            }

            const target = element.querySelector(
                ".legs"
            );

            if (!target) {
                return;
            }

            target.innerHTML = slip.legs.map(
                (leg, legIndex) => {
                    const fixture = matchFixture(leg);

                    const legState = getLegState(
                        leg,
                        fixture
                    );

                    const score =
                        fixture
                        && fixture.homeScore != null
                        && fixture.awayScore != null
                            ? `${fixture.homeScore} – ${fixture.awayScore}`
                            : "— : —";

                    const probability =
                        typeof pct === "function"
                            ? pct(leg.probability)
                            : `${Math.round(
                                Number(
                                    leg.probability || 0
                                ) * 100
                            )}%`;

                    const fixtureStatus = fixture
                        ? getMatchStatus(fixture)
                        : "Fixture not matched";

                    const league = fixture?.league
                        ? ` · ${escapeHTML(fixture.league)}`
                        : "";

                    return `
                        <div class="live-leg">
                            <div>
                                <div>
                                    ${legIndex + 1}.
                                    ${escapeHTML(leg.home)}
                                    vs
                                    ${escapeHTML(leg.away)}

                                    <span class="live-detail">
                                        —
                                        ${escapeHTML(leg.market)}
                                        (${escapeHTML(probability)})
                                    </span>
                                </div>

                                <div class="live-detail">
                                    ${escapeHTML(fixtureStatus)}
                                    ${league}
                                </div>
                            </div>

                            <div style="text-align:right">
                                <div class="live-score">
                                    ${escapeHTML(score)}
                                </div>

                                <div class="live-detail ${legState[1]}">
                                    ${escapeHTML(legState[0])}
                                </div>
                            </div>
                        </div>
                    `;
                }
            ).join("");
        });
    }


    /*
     * Fetch the latest score snapshot from the backend.
     */
    async function refreshLiveScores() {
        addUI();

        try {
            const response = await fetch(
                "/api/live-scores",
                {
                    cache: "no-store"
                }
            );

            const payload = await response.json();

            if (!payload.configured) {
                fixtures = [];

                message =
                    "LIVE SCORES NOT CONFIGURED · "
                    + "Add API_FOOTBALL_KEY in Render → "
                    + "Environment. Manual tracking remains available.";

            } else if (
                !response.ok
                || !payload.ok
            ) {
                message =
                    "LIVE SCORE ERROR · "
                    + (
                        payload.message
                        || `HTTP ${response.status}`
                    );

            } else {
                fixtures = Array.isArray(
                    payload.fixtures
                )
                    ? payload.fixtures
                    : [];

                updatedAt = payload.updatedAt
                    || new Date().toISOString();

                message = "";

                /* Capture final scores first so every
                   archived leg keeps its score. */
                const scoresChanged = captureScores();

                if (
                    autoGradeSlips()
                    || scoresChanged
                ) {
                    if (
                        typeof renderTracker
                            === "function"
                    ) {
                        renderTracker();
                    }
                }
            }

        } catch (error) {
            message =
                "LIVE SCORES UNAVAILABLE · "
                + (
                    error.message
                    || "Network error"
                );
        }

        renderLiveScores();
    }


    /*
     * Refresh the live display when the tracker filter changes.
     */
    document.addEventListener(
        "change",
        event => {
            if (
                event.target?.id === "trackerFilter"
            ) {
                setTimeout(
                    renderLiveScores,
                    0
                );
            }
        }
    );


    /*
     * Refresh after manual grading actions.
     */
    document.addEventListener(
        "click",
        event => {
            if (
                event.target?.closest(
                    "#trackerList [data-grade]"
                )
            ) {
                setTimeout(
                    renderLiveScores,
                    0
                );
            }
        }
    );


    /*
     * Start the tracker.
     */
    addUI();

    renderLiveScores();

    refreshLiveScores();

    setInterval(
        refreshLiveScores,
        60000
    );

})();
