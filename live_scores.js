/*
 * BARBADOX LIVE-SCORE TRACKER
 *
 * Integrates with the existing console.html slips tracker.
 *
 * Features:
 * - Displays current scores and match status.
 * - Shows whether selections are on track.
 * - Matches fixtures by club names and date.
 * - Rejects ambiguous fixture matches.
 * - Never grades a slip using a repeated fixture.
 * - Persists final scores on tracker and archive legs.
 * - Automatically grades completed slips.
 * - Requests historical match dates for pending slips.
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
     * Score similarity between two club names.
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
     * Match a tracker leg to exactly one plausible fixture.
     *
     * The home/away order must match.
     * The fixture date must be within one day.
     * Ambiguous matches are rejected rather than guessed.
     */
    function matchFixture(leg) {
        if (!leg || !leg.home || !leg.away || !leg.date) {
            return null;
        }

        const candidates = [];

        for (const fixture of fixtures) {
            if (!fixture || !fixture.home || !fixture.away) {
                continue;
            }

            if (
                dayDifference(
                    leg.date,
                    fixture.date
                ) > 1
            ) {
                continue;
            }

            const homeScore = similarity(
                leg.home,
                fixture.home
            );

            const awayScore = similarity(
                leg.away,
                fixture.away
            );

            if (
                homeScore < 0.68
                || awayScore < 0.68
            ) {
                continue;
            }

            const score = (homeScore + awayScore) / 2;

            if (score >= 0.80) {
                candidates.push({
                    fixture,
                    score
                });
            }
        }

        candidates.sort(
            (a, b) => b.score - a.score
        );

        if (!candidates.length) {
            return null;
        }

        if (
            candidates.length > 1
            && candidates[0].score - candidates[1].score < 0.08
        ) {
            return null;
        }

        return candidates[0].fixture;
    }


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
     * Determine a leg outcome from confirmed final scores.
     */
    function getOutcome(leg, fixture) {
        if (
            !fixture
            || !FINISHED.has(fixture.status)
            || fixture.homeScore == null
            || fixture.awayScore == null
        ) {
            return null;
        }

        const homeScore = Number(fixture.homeScore);
        const awayScore = Number(fixture.awayScore);

        if (
            !Number.isFinite(homeScore)
            || !Number.isFinite(awayScore)
            || homeScore < 0
            || awayScore < 0
        ) {
            return null;
        }

        const total = homeScore + awayScore;

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
            ? Number(fixture.homeScore) + Number(fixture.awayScore)
            : null;

        if (FINISHED.has(fixture.status)) {
            const outcome = getOutcome(leg, fixture);

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
     * Capture final scores in either the active tracker or archive.
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
                    || !formatScore(fixture)
                ) {
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
     * Grade only when all four legs map to four distinct finished fixtures.
     */
    function gradeCollection(slips) {
        if (!Array.isArray(slips)) {
            return false;
        }

        let changed = false;

        for (const slip of slips) {
            if (
                String(slip.status || "PENDING").toUpperCase() !== "PENDING"
                || !Array.isArray(slip.legs)
                || slip.legs.length !== 4
            ) {
                continue;
            }

            const matchedLegs = slip.legs.map(leg => ({
                leg,
                fixture: matchFixture(leg)
            }));

            const identity = fixture => {
                if (fixture && fixture.id != null) {
                    return "id:" + String(fixture.id);
                }

                if (!fixture) {
                    return "";
                }

                return [
                    String(fixture.date || ""),
                    String(fixture.home || "").toLowerCase(),
                    String(fixture.away || "").toLowerCase()
                ].join("|");
            };

            const identities = matchedLegs.map(
                item => identity(item.fixture)
            );

            if (
                identities.some(value => !value)
                || new Set(identities).size !== 4
            ) {
                continue;
            }

            const everyFixtureFinished = matchedLegs.every(
                item =>
                    item.fixture
                    && FINISHED.has(item.fixture.status)
            );

            if (!everyFixtureFinished) {
                continue;
            }

            const outcomes = matchedLegs.map(
                item => getOutcome(item.leg, item.fixture)
            );

            if (outcomes.some(outcome => outcome === null)) {
                continue;
            }

            matchedLegs.forEach(item => {
                stampLeg(item.leg, item.fixture);
            });

            slip.status = outcomes.every(Boolean)
                ? "WON"
                : "LOST";

            slip.gradedAt = new Date().toISOString();
            slip.gradingSource = "FOOTBALL_DATA_ORG";
            slip.autoGraded = true;

            changed = true;
        }

        return changed;
    }


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


    function captureArchiveScores() {
        const archive = readArchive();
        const changed = captureCollectionScores(archive);

        if (changed) {
            writeArchive(archive);
        }

        return changed;
    }


    function autoGradeArchive() {
        const archive = readArchive();

        if (!archive.length) {
            return false;
        }

        const changed = gradeCollection(archive);

        if (changed) {
            writeArchive(archive);
        }

        return changed;
    }


    /*
     * Ask the backend for dates represented by pending slips.
     * Includes archived slips that are no longer visible in the tracker.
     */
    function pendingMatchDates() {
        const dates = new Set();
        const collections = [];

        if (typeof readTracker === "function") {
            const tracker = readTracker();

            if (Array.isArray(tracker)) {
                collections.push(tracker);
            }
        }

        const archive = readArchive();

        if (Array.isArray(archive)) {
            collections.push(archive);
        }

        for (const collection of collections) {
            for (const slip of collection) {
                if (
                    String(slip.status || "PENDING").toUpperCase()
                    !== "PENDING"
                ) {
                    continue;
                }

                for (const leg of (
                    Array.isArray(slip.legs) ? slip.legs : []
                )) {
                    const date = String(leg.date || "").slice(0, 10);

                    if (/^\d{4}-\d{2}-\d{2}$/.test(date)) {
                        dates.add(date);
                    }
                }
            }
        }

        return [...dates].sort();
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
                    + new Date(updatedAt).toLocaleTimeString()
                    + " · Page checks every 60 seconds.";
            } else {
                banner.textContent = "Waiting for score data…";
            }
        }

        if (typeof readTracker !== "function") {
            return;
        }

        const filter = $("trackerFilter")?.value || "ALL";
        const allSlips = readTracker();

        if (!Array.isArray(allSlips)) {
            return;
        }

        const visibleSlips = allSlips.filter(
            slip => filter === "ALL" || slip.status === filter
        );

        const slipElements = document.querySelectorAll(
            "#trackerList .sliprow"
        );

        slipElements.forEach((element, slipIndex) => {
            const slip = visibleSlips[slipIndex];

            if (!slip || !Array.isArray(slip.legs)) {
                return;
            }

            const target = element.querySelector(".legs");

            if (!target) {
                return;
            }

            target.innerHTML = slip.legs.map((leg, legIndex) => {
                const fixture = matchFixture(leg);
                const legState = getLegState(leg, fixture);

                const score =
                    fixture
                    && fixture.homeScore != null
                    && fixture.awayScore != null
                        ? `${fixture.homeScore} – ${fixture.awayScore}`
                        : "— : —";

                const probability =
                    typeof pct === "function"
                        ? pct(leg.probability)
                        : `${Math.round(Number(leg.probability || 0) * 100)}%`;

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
            }).join("");
        });
    }


    /*
     * Request score data from the backend and grade safely matched slips.
     */
    async function refreshLiveScores() {
        addUI();

        try {
            const response = await fetch(
                "/api/live-scores",
                {
                    method: "POST",
                    cache: "no-store",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        dates: pendingMatchDates()
                    })
                }
            );

            const payload = await response.json();

            if (!payload.configured) {
                fixtures = [];

                message =
                    "LIVE SCORES NOT CONFIGURED · "
                    + "Add FOOTBALL_DATA_KEY in Render → "
                    + "Environment. Scores come from football-data.org.";

            } else if (!response.ok || !payload.ok) {
                message =
                    "LIVE SCORE ERROR · "
                    + (
                        payload.message
                        || payload.error
                        || `HTTP ${response.status}`
                    );

            } else {
                fixtures = Array.isArray(payload.fixtures)
                    ? payload.fixtures
                    : [];

                updatedAt = payload.updatedAt
                    || new Date().toISOString();

                message = (
                    Array.isArray(payload.historyWarnings)
                    && payload.historyWarnings.length
                )
                    ? "SCORE DATA PARTIAL · " + payload.historyWarnings[0]
                    : "";

                /* Capture confirmed final scores on the active tracker. */
                const scoresChanged = captureScores();

                /* Grade active slips only when all four fixtures are confirmed. */
                const trackerGraded = autoGradeSlips();

                /* Capture and persist confirmed scores for archived slips. */
                const archiveScoresChanged = captureArchiveScores();

                /* Grade archived slips, even after they leave the active tracker. */
                const archiveGraded = autoGradeArchive();

                if (archiveScoresChanged || archiveGraded) {
                    syncArchiveToServer(readArchive());

                    document.dispatchEvent(
                        new CustomEvent("barbadox:history-updated")
                    );
                }

                if (
                    trackerGraded
                    || scoresChanged
                ) {
                    if (typeof renderTracker === "function") {
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
     * Repaint score rows when the tracker filter changes.
     */
    document.addEventListener("change", event => {
        if (event.target?.id === "trackerFilter") {
            setTimeout(renderLiveScores, 0);
        }
    });


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
