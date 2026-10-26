/*
 * BARBADOX LIVE-SCORE TRACKER
 *
 * Integrates with the existing console.html slips tracker.
 *
 * Features:
 * - Displays current scores and match status.
 * - Shows whether each selection is on track.
 * - Matches fixtures by team names and date, with tolerant
 *   name matching ("TSG 1899 Hoffenheim" matches "Hoffenheim",
 *   "Stade Rennais FC 1901" matches "Rennes", etc.).
 * - Captures the FINAL SCORE of every finished leg and saves it
 *   on the leg itself, so the slips history archive, the CSV
 *   export and the GitHub record all keep the score forever.
 * - Automatically grades completed four-leg slips — BOTH the
 *   live tracker AND the permanent history archive. Slips that
 *   were cleared from the tracker are still graded, so archived
 *   slips never sit at PENDING forever.
 * - Preserves the existing tracker and manual grading.
 */

(() => {
    "use strict";

    if (window.__barbadoxLiveScoresStarted) {
        return;
    }

    window.__barbadoxLiveScoresStarted = true;

    const TRACK_KEY = "barbadox.slips.tracker.v1";
    const HISTORY_KEY = "barbadox.slips.history.v2";

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
     * Direct access to the permanent history archive.
     * The live tracker holds only the current slips; every
     * generated slip also lives here forever.
     */
    function readArchive() {
        try {
            const value = JSON.parse(
                localStorage.getItem(HISTORY_KEY) || "[]"
            );

            return Array.isArray(value) ? value : [];
        } catch {
            return [];
        }
    }

    function writeArchive(slips) {
        try {
            localStorage.setItem(
                HISTORY_KEY,
                JSON.stringify(slips)
            );
        } catch {}
    }

    async function syncArchiveToServer(slips) {
        try {
            await fetch(
                "/api/slip-history",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ slips })
                }
            );
        } catch {}
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
     * Legal-form prefixes and founding years are kept only
     * when they do not hide the club's core identity.
     */
    function normalizeTeam(name) {
        return String(name || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(
                /\b(football club|soccer club|football|calcio|club)\b/g,
                " "
            )
            .replace(/[^a-z0-9]+/g, " ")
            .trim()
            .split(/\s+/)
            .filter(Boolean);
    }


    /*
     * Two words count as the same club word when they are
     * identical or share a 4+ character prefix:
     *   "rennais" ~ "rennes", "internazionale" ~ "inter",
     *   "milano" ~ "milan", "hoffenheim" ~ "hoffenheim".
     */
    function wordsEquivalent(a, b) {
        if (a === b) {
            return true;
        }

        const limit = Math.min(a.length, b.length);

        if (limit < 4) {
            return false;
        }

        let same = 0;

        while (
            same < limit
            && a[same] === b[same]
        ) {
            same++;
        }

        return same >= 4;
    }


    /*
     * Compare two club names.
     *
     * - Numeric-only tokens (1899, 1901, 07, 05…) are ignored.
     * - A short official name that is fully contained in the
     *   long one ("Hoffenheim" in "TSG 1899 Hoffenheim") is a
     *   strong match.
     * - Otherwise the share of matching words decides.
     */
    function similarity(first, second) {
        const a = normalizeTeam(first)
            .filter(word => /[a-z]/.test(word));

        const b = normalizeTeam(second)
            .filter(word => /[a-z]/.test(word));

        if (!a.length || !b.length) {
            return 0;
        }

        let common = 0;

        for (const word of a) {
            if (b.some(other => wordsEquivalent(word, other))) {
                common++;
            }
        }

        if (!common) {
            return 0;
        }

        const score = common / Math.max(a.length, b.length);

        const subset =
            a.every(word =>
                b.some(other => wordsEquivalent(word, other))
            )
            || b.every(word =>
                a.some(other => wordsEquivalent(word, other))
            );

        return subset
            ? Math.max(score, 0.9)
            : score;
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
     * Stamp one leg with its final score and result.
     * Returns true when the leg changed.
     */
    function stampLeg(leg, fixture) {
        let changed = false;

        const score = formatScore(fixture);

        if (score && leg.liveScore !== score) {
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

        return changed;
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
     * Capture the final score of every finished leg in a
     * slip collection (tracker or archive). Operates in
     * place; returns true when anything changed.
     */
    function captureCollectionScores(slips) {
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

                if (!formatScore(fixture)) {
                    continue;
                }

                if (stampLeg(leg, fixture)) {
                    changed = true;
                }
            }
        }

        return changed;
    }


    /*
     * Grade every slip in a collection that can be safely
     * graded. Operates in place; returns true when any slip
     * was graded.
     *
     * A slip grades only if:
     * - It is still pending.
     * - It has exactly four legs.
     * - All four fixtures are matched.
     * - All four matches are finished.
     * - Every market result can be determined.
     */
    function gradeCollection(slips) {
        if (!Array.isArray(slips)) {
            return false;
        }

        let changed = false;

        for (const slip of slips) {
            if (
                String(slip.status || "PENDING").toUpperCase()
                    !== "PENDING"
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
                stampLeg(item.leg, item.fixture);
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

        return changed;
    }


    /*
     * TRACKER: capture scores + auto-grade live slips.
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

        const changed = captureCollectionScores(slips);

        if (changed) {
            saveTracker(slips);
        }

        return changed;
    }

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

        const changed = gradeCollection(slips);

        if (changed) {
            saveTracker(slips);
        }

        return changed;
    }


    /*
     * ARCHIVE: capture scores + auto-grade archived slips.
     *
     * Slips cleared from the live tracker still live in the
     * permanent history archive. Without this pass they would
     * sit at PENDING forever even after all their matches
     * finished.
     */
    function captureArchiveScores() {
        return captureCollectionScores(readArchive());
    }

    function autoGradeArchive() {
        const archive = readArchive();

        if (!archive.length) {
            return false;
        }

        const graded = gradeCollection(archive);

        if (graded) {
            writeArchive(archive);
        }

        return graded;
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

                /* 1. Capture final scores on live tracker legs. */
                const scoresChanged = captureScores();

                /* 2. Auto-grade live tracker slips. */
                const trackerGraded = autoGradeSlips();

                /* 3. Capture final scores on ARCHIVED legs —
                   including slips that were cleared from the
                   tracker. */
                const archiveScoresChanged =
                    captureArchiveScores();

                const archive = readArchive();

                if (archiveScoresChanged) {
                    writeArchive(archive);
                }

                /* 4. Auto-grade archived slips whose four legs
                   have all finished. */
                const archiveGraded = autoGradeArchive();

                if (archiveGraded) {
                    syncArchiveToServer(readArchive());
                }

                if (
                    archiveScoresChanged
                    || archiveGraded
                ) {
                    /* Tell the slips-history module that the
                       permanent record changed. */
                    document.dispatchEvent(
                        new CustomEvent(
                            "barbadox:history-updated"
                        )
                    );
                }

                if (
                    trackerGraded
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
