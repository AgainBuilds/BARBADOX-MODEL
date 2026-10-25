/*
 * BARBADOX SLIPS HISTORY
 *
 * Permanent, historical record of every generated slip.
 *
 * Storage layers:
 *   1. Browser localStorage archive (instant, offline).
 *   2. Server CSV (slips_browser.csv) -> survives browser wipes.
 *   3. GitHub commit via the server  -> survives Render redeploys.
 *
 * This script is self-contained: it adds the SLIPS HISTORY button,
 * its modal, weekly grouping, stats, CSV export, and the server
 * sync. It never deletes anything.
 *
 * NEW: graded slips (WON/LOST) can never regress to PENDING,
 * even when the live tracker still holds an ungraded copy of
 * the same slip. Final scores captured by live_scores.js are
 * displayed and exported automatically.
 */

(() => {
    "use strict";

    if (window.__barbadoxSlipsHistoryStarted) {
        return;
    }

    window.__barbadoxSlipsHistoryStarted = true;

    const TRACK_KEY = "barbadox.slips.tracker.v1";
    const HISTORY_KEY = "barbadox.slips.history.v2";
    const API = "/api/slip-history";

    const $ = id => document.getElementById(id);

    const esc = value =>
        String(value ?? "").replace(
            /[&<>"']/g,
            character => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;"
            })[character]
        );

    const pct = value => {
        const n = Number(value);

        return Number.isFinite(n)
            ? Math.round(n * 100) + "%"
            : "—";
    };


    /* -------------------------------------------------------
       STATUS PRECEDENCE
    ------------------------------------------------------- */

    /* A graded status (WON/LOST) is never downgraded back to
       PENDING by an ungraded copy of the same slip. When both
       copies are graded, the newer grading wins. */
    function protectGraded(previous, incoming) {
        const merged = incoming;

        const prevStatus = String(
            previous.status || "PENDING"
        ).toUpperCase();

        const incStatus = String(
            merged.status || "PENDING"
        ).toUpperCase();

        const prevGraded =
            prevStatus === "WON" || prevStatus === "LOST";
        const incGraded =
            incStatus === "WON" || incStatus === "LOST";

        let keepPrevious = false;

        if (prevGraded && !incGraded) {
            keepPrevious = true;
        } else if (prevGraded && incGraded) {
            const prevAt =
                Date.parse(previous.gradedAt || "") || 0;
            const incAt =
                Date.parse(merged.gradedAt || "") || 0;

            keepPrevious = prevAt > incAt;
        }

        if (keepPrevious) {
            merged.status = previous.status;
            merged.gradedAt = previous.gradedAt;
            merged.autoGraded = previous.autoGraded;
        }

        return merged;
    }


    /* -------------------------------------------------------
       LOCAL ARCHIVE
    ------------------------------------------------------- */

    function readStored(key) {
        try {
            const value = JSON.parse(
                localStorage.getItem(key) || "[]"
            );

            return Array.isArray(value) ? value : [];
        } catch {
            return [];
        }
    }

    function readTracker() {
        return readStored(TRACK_KEY);
    }

    function readHistory() {
        return readStored(HISTORY_KEY);
    }

    /* Merge current tracker rows into the permanent archive.
       Nothing is ever removed, and a graded slip in the archive
       is never reset to PENDING by the tracker. */
    function localArchive() {
        const byId = new Map(
            readHistory().map(s => [String(s.id), s])
        );

        for (const slip of readTracker()) {
            const id = String(slip.id || "");

            if (!id) {
                continue;
            }

            const previous = byId.get(id) || {};

            byId.set(
                id,
                protectGraded(
                    previous,
                    Object.assign(
                        {},
                        previous,
                        slip,
                        {
                            archivedAt:
                                previous.archivedAt ||
                                new Date().toISOString()
                        }
                    )
                )
            );
        }

        const merged = [...byId.values()];

        try {
            localStorage.setItem(
                HISTORY_KEY,
                JSON.stringify(merged)
            );
        } catch {}

        return merged;
    }


    /* -------------------------------------------------------
       SERVER SYNC (slips_browser.csv on the server + GitHub)
    ------------------------------------------------------- */

    let syncTimer = null;

    function queueServerSync() {
        clearTimeout(syncTimer);

        syncTimer = setTimeout(pushToServer, 1500);
    }

    async function pushToServer() {
        try {
            await fetch(
                API,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        slips: localArchive()
                    })
                }
            );
        } catch {}

        renderHistory();
    }

    /* Convert a server CSV row into the browser slip shape. */
    function normalizeServer(slip) {
        return {
            id: slip.id,
            number: slip.number,
            createdAt: slip.created_at || slip.createdAt || "",
            status: (slip.status || "PENDING").toUpperCase(),
            gradedAt: slip.graded_at || slip.gradedAt || null,
            autoGraded:
                slip.auto_graded === "YES" ||
                slip.autoGraded === true,
            archivedAt: slip.archived_at || slip.archivedAt || null,
            legs: Array.isArray(slip.legs) ? slip.legs : []
        };
    }

    async function pullFromServer() {
        try {
            const response = await fetch(
                API,
                { cache: "no-store" }
            );

            const data = await response.json();

            if (data && data.ok && Array.isArray(data.slips)) {
                const byId = new Map(
                    readHistory().map(s => [String(s.id), s])
                );

                for (const slip of data.slips) {
                    const id = String(slip.id || "");

                    if (!id) {
                        continue;
                    }

                    const normalized = normalizeServer(slip);

                    const previous = byId.get(id) || {};

                    byId.set(
                        id,
                        protectGraded(
                            previous,
                            Object.assign(
                                {},
                                previous,
                                normalized
                            )
                        )
                    );
                }

                const merged = [...byId.values()];

                try {
                    localStorage.setItem(
                        HISTORY_KEY,
                        JSON.stringify(merged)
                    );
                } catch {}
            }
        } catch {}

        renderHistory();
    }


    /* -------------------------------------------------------
       CHANGE HOOKS
    ------------------------------------------------------- */

    /* Watch every write to the tracker — this catches
       generation, manual grading, auto grading, and clears. */
    const setItem = localStorage.setItem.bind(localStorage);

    localStorage.setItem = (key, value) => {
        setItem(key, value);

        if (key === TRACK_KEY) {
            setTimeout(() => {
                localArchive();
                renderHistory();
                queueServerSync();
            }, 0);
        }
    };


    /* -------------------------------------------------------
       WEEK GROUPING (Monday-based, UTC)
    ------------------------------------------------------- */

    function slipWeekDate(slip) {
        const dates = (Array.isArray(slip.legs) ? slip.legs : [])
            .map(leg => String(leg.date || "").slice(0, 10))
            .filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))
            .sort();

        if (dates.length) {
            return dates[0];
        }

        const created = String(slip.createdAt || "").slice(0, 10);

        return /^\d{4}-\d{2}-\d{2}$/.test(created)
            ? created
            : "";
    }

    function mondayOf(dateStr) {
        if (!dateStr) {
            return null;
        }

        const date = new Date(dateStr + "T12:00:00Z");

        if (isNaN(date)) {
            return null;
        }

        const day = (date.getUTCDay() + 6) % 7;

        date.setUTCDate(date.getUTCDate() - day);

        return date;
    }

    function weekLabel(monday) {
        const now = new Date();

        const thisMonday = mondayOf(
            now.toISOString().slice(0, 10)
        );

        const diff = thisMonday && monday
            ? Math.round((thisMonday - monday) / 86400000)
            : 99;

        const end = new Date(monday);

        end.setUTCDate(end.getUTCDate() + 6);

        const fmt = date =>
            date.toLocaleDateString("en-GB", {
                day: "numeric",
                month: "short",
                timeZone: "UTC"
            });

        const range =
            fmt(monday) + " – " + fmt(end) +
            " " + monday.getUTCFullYear();

        if (diff <= 0) {
            return "THIS WEEK (" + range + ")";
        }

        if (diff <= 7) {
            return "LAST WEEK (" + range + ")";
        }

        return "WEEK OF " + range;
    }

    function historyStats(slips) {
        const won = slips.filter(s => s.status === "WON").length;
        const lost = slips.filter(s => s.status === "LOST").length;
        const pend = slips.filter(s => s.status === "PENDING").length;
        const graded = won + lost;

        return {
            total: slips.length,
            won,
            lost,
            pend,
            graded,
            hitRate: graded ? won / graded : null
        };
    }


    /* -------------------------------------------------------
       UI
    ------------------------------------------------------- */

    function addUI() {
        if ($("btnSlipsHistory")) {
            return;
        }

        const anchor = $("btnSlip");

        if (anchor) {
            const button = document.createElement("button");

            button.id = "btnSlipsHistory";
            button.type = "button";
            button.className = "btn secondary";
            button.textContent = "SLIPS HISTORY";

            anchor.insertAdjacentElement("afterend", button);

            button.addEventListener("click", openHistory);
        }

        const modal = document.createElement("div");

        modal.id = "slipsHistoryModal";

        modal.style.cssText =
            "display:none;position:fixed;inset:0;" +
            "background:var(--bg,#0b1020);z-index:20;" +
            "overflow:auto;padding:20px";

        modal.innerHTML = `
            <div style="max-width:900px;margin:auto">
                <div class="panelhead">
                    <h2>SLIPS HISTORY · PERMANENT RECORD</h2>
                    <div class="actions">
                        <button
                            id="exportSlipsHistory"
                            class="btn secondary"
                            type="button">
                            EXPORT CSV
                        </button>

                        <button
                            id="closeSlipsHistory"
                            class="btn secondary"
                            type="button">
                            CLOSE
                        </button>
                    </div>
                </div>

                <div id="slipsHistoryStats" class="kpis"></div>

                <div class="status">
                    Every slip is archived forever — in this browser,
                    on the server (slips_browser.csv), and committed to
                    GitHub. Grouped by match week.
                    CLEAR TRACKER never deletes this history.
                </div>

                <div id="slipsHistoryList" class="tracker-list"></div>
            </div>
        `;

        document.body.appendChild(modal);

        $("closeSlipsHistory").addEventListener(
            "click",
            () => {
                modal.style.display = "none";
            }
        );

        $("exportSlipsHistory").addEventListener(
            "click",
            exportHistory
        );
    }

    function openHistory() {
        addUI();

        $("slipsHistoryModal").style.display = "block";

        localArchive();

        renderHistory();

        pullFromServer();
    }

    function renderHistorySlip(slip) {
        const legs = Array.isArray(slip.legs)
            ? slip.legs
            : [];

        return `
            <article class="sliprow">
                <div class="sliprowhead">
                    <strong>
                        SLIP #${esc(slip.number || "?")}
                        · ${esc(slip.createdAt || "")}
                    </strong>

                    <span class="chip ${
                        slip.status === "WON"
                            ? "hit"
                            : slip.status === "LOST"
                                ? "miss"
                                : "pending"
                    }">
                        ${
                            slip.status === "WON"
                                ? "HIT / WON"
                                : slip.status === "LOST"
                                    ? "FAILED / LOST"
                                    : "PENDING"
                        }
                    </span>
                </div>

                <div class="legs">
                    ${legs.map((leg, index) => `
                        <div>
                            ${index + 1}.
                            ${esc(leg.home)} vs ${esc(leg.away)}
                            — ${esc(leg.market)}
                            (${pct(leg.probability)})
                            ${
                                leg.liveScore
                                    ? " · " + esc(leg.liveScore)
                                    : ""
                            }
                            ${
                                leg.result === "WON"
                                    ? " · LEG WON"
                                    : leg.result === "LOST"
                                        ? " · LEG LOST"
                                        : ""
                            }
                        </div>
                    `).join("")}
                </div>

                ${
                    slip.gradedAt
                        ? `<div class="status">
                               Graded ${esc(slip.gradedAt)} ${
                                   slip.autoGraded
                                       ? "· AUTOMATIC"
                                       : "· MANUAL"
                               }
                           </div>`
                        : ""
                }
            </article>
        `;
    }

    function renderHistory() {
        if (!$("slipsHistoryModal")) {
            return;
        }

        const history = localArchive();

        const all = historyStats(history);

        $("slipsHistoryStats").innerHTML = `
            <div class="kpi">
                <strong>${all.total}</strong>
                <span>SLIPS ARCHIVED</span>
            </div>

            <div class="kpi">
                <strong>${all.won}</strong>
                <span>HIT / WON</span>
            </div>

            <div class="kpi">
                <strong>${all.lost}</strong>
                <span>FAILED / LOST</span>
            </div>

            <div class="kpi">
                <strong>${all.pend}</strong>
                <span>PENDING</span>
            </div>

            <div class="kpi">
                <strong>${all.graded ? pct(all.hitRate) : "—"}</strong>
                <span>ALL-TIME HIT RATE</span>
            </div>
        `;

        if (!history.length) {
            $("slipsHistoryList").innerHTML =
                '<div class="empty">' +
                'No slips archived yet. Slips are added here ' +
                'automatically every time you tap GENERATE SLIPS.' +
                '</div>';

            return;
        }

        const groups = new Map();

        for (const slip of history) {
            const monday = mondayOf(slipWeekDate(slip));

            const key = monday ? monday.getTime() : 0;

            if (!groups.has(key)) {
                groups.set(key, {
                    monday,
                    slips: []
                });
            }

            groups.get(key).slips.push(slip);
        }

        const ordered = [...groups.values()].sort(
            (a, b) =>
                (b.monday ? b.monday.getTime() : 0) -
                (a.monday ? a.monday.getTime() : 0)
        );

        $("slipsHistoryList").innerHTML = ordered.map(group => {
            const stats = historyStats(group.slips);

            return `
                <div style="margin:18px 0 6px">
                    <strong>${
                        esc(
                            group.monday
                                ? weekLabel(group.monday)
                                : "OLDER / UNDATED"
                        )
                    }</strong>

                    <span class="muted">
                        · ${stats.total} slips
                        · ${stats.won} won
                        · ${stats.lost} lost
                        · ${stats.pend} pending
                        · hit rate ${
                            stats.graded ? pct(stats.hitRate) : "—"
                        }
                    </span>
                </div>

                ${group.slips
                    .slice()
                    .sort((a, b) =>
                        String(b.createdAt || "")
                            .localeCompare(
                                String(a.createdAt || "")
                            )
                    )
                    .map(renderHistorySlip)
                    .join("")}
            `;
        }).join("");
    }

    function exportHistory() {
        const history = localArchive();

        const head = [
            "number",
            "week_of",
            "createdAt",
            "status",
            "gradedAt",
            "autoGraded",
            "legs"
        ];

        const csv = [
            head.join(","),

            ...history.map(slip => {
                const monday = mondayOf(slipWeekDate(slip));

                const week = monday
                    ? monday.toISOString().slice(0, 10)
                    : "";

                const legs = Array.isArray(slip.legs)
                    ? slip.legs.map(leg =>
                        leg.home + " vs " + leg.away +
                        " (" + leg.market + ")" +
                        (
                            leg.liveScore
                                ? " [" + leg.liveScore + "]"
                                : ""
                        )
                    ).join(" | ")
                    : "";

                return [
                    slip.number,
                    week,
                    slip.createdAt,
                    slip.status,
                    slip.gradedAt || "",
                    slip.autoGraded ? "YES" : "NO",
                    legs
                ].map(value =>
                    '"' +
                    String(value ?? "").replace(/"/g, '""') +
                    '"'
                ).join(",");
            })
        ].join("\r\n");

        const blob = new Blob(
            [csv],
            { type: "text/csv;charset=utf-8" }
        );

        const url = URL.createObjectURL(blob);

        const link = document.createElement("a");

        link.href = url;
        link.download = "barbadox-slips-history.csv";

        document.body.appendChild(link);

        link.click();

        link.remove();

        setTimeout(() => {
            URL.revokeObjectURL(url);
        }, 1000);
    }


    /* -------------------------------------------------------
       START
    ------------------------------------------------------- */

    addUI();

    /* Archive whatever already sits in the tracker,
       then hydrate from the server and mirror everything back. */
    localArchive();

    pullFromServer();

    pushToServer();

})();
