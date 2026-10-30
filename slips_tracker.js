/* BARBADOX dedicated slips tracker. The server CSV is the source of truth.
 *
 * October 2026 fix: tolerant fixture matching. Near-exact club names
 * (both team similarities >= 0.9) tolerate +/- 2 days of kickoff drift,
 * all other accepted matches require +/- 1 day. Ambiguous matches are
 * rejected and never graded.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const FINISHED = new Set(["FT", "AWD"]);
  const LIVE = new Set(["LIVE", "HT", "ET", "P"]);
  const VOID_OR_DELAYED = new Set(["PST", "CANC", "SUSP", "ABD"]);
  const POLL_MS = 25000;
  const MATCH_THRESHOLD = 0.62;
  const NEAR_EXACT = 0.9;
  const AMBIGUITY_MARGIN = 0.02;
  let archive = [];
  let activeView = "ALL";
  let pollBusy = false;
  let lastWarning = "";
  let unsynced = new Map();

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const pct = (value) => {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? (n * 100).toFixed(1) + "%" : "—";
  };

  function teamKey(value) {
    return String(value || "")
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/&/g, " and ")
      .replace(/\b(football club|soccer club|football|calcio|fc|sc|afc|cf|ac|ssc|club)\b/g, " ")
      .replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
  }

  /* Word-prefix equivalence: two tokens count as the same word when
     one is at least 4 characters and the other starts with it (or
     vice versa), so "manchester" ~ "manchester utd" style variants
     survive provider naming drift. */
  function tokenMatches(a, b) {
    if (a === b) return true;
    if (a.length >= 4 && b.startsWith(a)) return true;
    if (b.length >= 4 && a.startsWith(b)) return true;
    return false;
  }

  function similarity(a, b) {
    if (!a || !b) return 0;
    if (a === b) return 1;

    const at = a.split(" ");
    const bt = b.split(" ");

    let matched = 0;
    for (const token of at) {
      if (bt.some(other => tokenMatches(token, other))) matched++;
    }

    const shorter = Math.min(at.length, bt.length);
    const longer = Math.max(at.length, bt.length);
    if (matched === shorter && shorter > 0) return 0.9;
    if (matched === 0) return 0;

    return matched / longer;
  }

  function dayDiff(a, b) {
    const da = Date.parse(String(a || "").slice(0, 10) + "T12:00:00Z");
    const db = Date.parse(String(b || "").slice(0, 10) + "T12:00:00Z");
    if (!Number.isFinite(da) || !Number.isFinite(db)) return 99;
    return Math.abs(Math.round((da - db) / 86400000));
  }

  function kickoffMs(leg) {
    const value = leg && (leg.kickoff || leg.kickoff_utc || leg.utcDate);
    if (!value) return NaN;
    const stamp = Date.parse(value);
    return Number.isFinite(stamp) ? stamp : NaN;
  }

  function formatKickoff(value) {
    if (!value) return "Kickoff unavailable";
    const stamp = Date.parse(value);
    if (!Number.isFinite(stamp)) return esc(value);
    return new Intl.DateTimeFormat("en-NG", {
      timeZone: "Africa/Lagos", weekday: "short", day: "2-digit", month: "short",
      year: "numeric", hour: "2-digit", minute: "2-digit", hour12: true
    }).format(new Date(stamp)) + " WAT";
  }

  function formatRefresh(value) {
    if (!value) return "Not refreshed yet";
    const stamp = Date.parse(value);
    if (!Number.isFinite(stamp)) return esc(value);
    return new Intl.DateTimeFormat("en-NG", {
      timeZone: "Africa/Lagos", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true
    }).format(new Date(stamp)) + " WAT";
  }

  /* Tolerant matcher (October 2026):
     - provider fixture ID wins when unique;
     - near-exact names (both >= 0.9) tolerate +/- 2 days drift;
     - other accepted matches (both >= 0.62) require +/- 1 day;
     - ambiguous candidates are rejected — never graded. */
  function matchFixture(leg, fixtures) {
    const savedId = leg.footballDataId ?? leg.fixtureId ?? leg.providerId;
    if (savedId != null && savedId !== "") {
      const byId = fixtures.filter(f => String(f.id ?? f.providerId) === String(savedId));
      return byId.length === 1 ? byId[0] : null;
    }

    const home = teamKey(leg.home);
    const away = teamKey(leg.away);
    if (!home || !away || !leg.date) return null;

    const candidates = [];
    for (const fixture of fixtures) {
      const homeScore = similarity(home, teamKey(fixture.home));
      const awayScore = similarity(away, teamKey(fixture.away));
      if (homeScore < MATCH_THRESHOLD || awayScore < MATCH_THRESHOLD) continue;

      const nearExact = homeScore >= NEAR_EXACT && awayScore >= NEAR_EXACT;
      const maxDrift = nearExact ? 2 : 1;
      const drift = dayDiff(leg.date, fixture.date);
      if (drift > maxDrift) continue;

      const legKickoff = kickoffMs(leg);
      if (Number.isFinite(legKickoff) && Number.isFinite(fixture.timestamp)) {
        if (Math.abs(legKickoff - Number(fixture.timestamp) * 1000) > (maxDrift + 0.5) * 86400000) continue;
      }

      candidates.push({
        fixture,
        score: Math.min(homeScore, awayScore)
      });
    }

    if (!candidates.length) return null;
    candidates.sort((a, b) => b.score - a.score);
    if (candidates.length > 1 &&
        candidates[0].score - candidates[1].score < AMBIGUITY_MARGIN) {
      return null;
    }
    return candidates[0].fixture;
  }

  function displayStatus(fixture) {
    const code = String(fixture.statusCode || fixture.status || "").toUpperCase();
    if (code === "NS") return "SCHEDULED";
    if (code === "HT") return "HALF TIME";
    if (code === "LIVE" || code === "ET" || code === "P") {
      const minute = fixture.minute == null ? "" : ` · ${fixture.minute}${fixture.injuryTime ? "+" + fixture.injuryTime : ""}′`;
      return (code === "ET" ? "EXTRA TIME" : code === "P" ? "PENALTIES" : "LIVE") + minute;
    }
    if (FINISHED.has(code)) return code === "AWD" ? "AWARDED" : "FULL TIME";
    return String(fixture.statusText || code || "STATUS UNAVAILABLE").toUpperCase();
  }

  function fixtureState(fixture) {
    return String(fixture.state || "").toUpperCase() || (
      FINISHED.has(String(fixture.status).toUpperCase()) ? "FINISHED" :
      LIVE.has(String(fixture.status).toUpperCase()) ? "LIVE" :
      String(fixture.status).toUpperCase() === "NS" ? "SCHEDULED" : "UNKNOWN"
    );
  }

  function marketOutcome(leg, fixture) {
    const state = fixtureState(fixture);
    if (state !== "FINISHED" || fixture.scoreFinalConfirmed !== true || fixture.homeScore == null || fixture.awayScore == null) return null;
    const home = Number(fixture.homeScore), away = Number(fixture.awayScore);
    if (!Number.isInteger(home) || !Number.isInteger(away) || home < 0 || away < 0) return null;
    const total = home + away;
    const market = String(leg.market || "").toUpperCase();
    if (market.includes("OVER") && market.includes("1.5")) return total >= 2;
    if (market.includes("UNDER") && market.includes("3.5")) return total <= 3;
    return null;
  }

  function stampLeg(leg, fixture) {
    const priorResult = String(leg.result || "PENDING").toUpperCase();
    if (priorResult === "WON" || priorResult === "LOST") {
      const refreshedOutcome = marketOutcome(leg, fixture);
      const priorOutcome = priorResult === "WON";
      if (refreshedOutcome === null || refreshedOutcome !== priorOutcome) return false;
    }

    let changed = false;
    const assign = (key, value) => {
      if (value !== undefined && value !== null && value !== "" && leg[key] !== value) {
        leg[key] = value;
        changed = true;
      }
    };

    assign("footballDataId", fixture.id ?? fixture.providerId);
    assign("fixtureId", fixture.id ?? fixture.providerId);
    assign("fixtureStatusCode", fixture.statusCode || fixture.status);
    assign("fixtureState", fixtureState(fixture));
    assign("fixtureStatus", displayStatus(fixture));
    assign("lastRefresh", fixture.refreshedAt || new Date().toISOString());
    if (fixture.kickoff) assign("providerKickoff", fixture.kickoff);
    if (fixture.minute != null) assign("matchMinute", Number(fixture.minute));
    if (fixture.injuryTime != null) assign("injuryTime", Number(fixture.injuryTime));

    const started = LIVE.has(String(fixture.statusCode || fixture.status).toUpperCase()) ||
      FINISHED.has(String(fixture.statusCode || fixture.status).toUpperCase());
    if (started) {
      assign("scoreProvisional", fixture.scoreProvisional === true);
      assign("scoreFinalConfirmed", fixture.scoreFinalConfirmed === true);
      assign("scoreUnconfirmed", fixture.scoreUnconfirmed === true);
      if (fixture.homeScore != null && fixture.awayScore != null) {
        assign("homeScore", Number(fixture.homeScore));
        assign("awayScore", Number(fixture.awayScore));
        assign("liveScore", `${Number(fixture.homeScore)} - ${Number(fixture.awayScore)}`);
      }
    } else if (fixtureState(fixture) === "SCHEDULED") {
      assign("liveScore", "");
      assign("scoreProvisional", false);
    }

    const outcome = marketOutcome(leg, fixture);
    const oldResult = String(leg.result || "PENDING").toUpperCase();
    if (outcome !== null && !["WON", "LOST"].includes(oldResult)) {
      assign("result", outcome ? "WON" : "LOST");
    }
    return changed;
  }

  function slipSignature(slip) {
    const legs = Array.isArray(slip.legs) ? slip.legs : [];
    const parts = legs.map(l => [
      String(l.date || "").slice(0, 10), teamKey(l.home), teamKey(l.away),
      String(l.market || "").toUpperCase().replace(/\s+/g, " ").trim()
    ].join("|"));
    return parts.length === 4 ? parts.sort().join("::") : String(slip.id || "");
  }

  function applyFeed(slips, fixtures) {
    let changed = false;
    for (const slip of slips) {
      if (!Array.isArray(slip.legs)) continue;
      const matches = slip.legs.map(leg => ({ leg, fixture: matchFixture(leg, fixtures) }));
      const ids = new Map();
      for (const item of matches) {
        if (!item.fixture) continue;
        const id = String(item.fixture.id ?? item.fixture.providerId ?? "");
        ids.set(id, (ids.get(id) || 0) + 1);
      }

      for (const item of matches) {
        if (!item.fixture) continue;
        const id = String(item.fixture.id ?? item.fixture.providerId ?? "");
        if ((ids.get(id) || 0) !== 1) continue;
        if (stampLeg(item.leg, item.fixture)) changed = true;
      }

      const status = String(slip.status || "PENDING").toUpperCase();
      if (status !== "PENDING" || slip.legs.length !== 4) continue;

      const outcomes = matches.map(item => {
        if (!item.fixture) return null;
        const id = String(item.fixture.id ?? item.fixture.providerId ?? "");
        if ((ids.get(id) || 0) !== 1) return null;
        return marketOutcome(item.leg, item.fixture);
      });

      const legResults = slip.legs.map(leg => String(leg.result || "PENDING").toUpperCase());
      if (legResults.some(value => value === "LOST") || outcomes.some(value => value === false)) {
        slip.status = "LOST";
        slip.gradedAt = slip.gradedAt || new Date().toISOString();
        slip.autoGraded = true;
        slip.gradingSource = "FOOTBALL_DATA_ORG";
        changed = true;
      } else if (legResults.length === 4 && legResults.every(value => value === "WON")) {
        slip.status = "WON";
        slip.gradedAt = slip.gradedAt || new Date().toISOString();
        slip.autoGraded = true;
        slip.gradingSource = "FOOTBALL_DATA_ORG";
        changed = true;
      }
    }
    return changed;
  }

  function mergeUnsynced(serverSlips) {
    const byId = new Map(serverSlips.map(s => [String(s.id), s]));
    for (const [id, local] of unsynced.entries()) byId.set(id, local);
    return [...byId.values()];
  }

  async function syncArchive(slips) {
    const response = await fetch("/api/slip-history", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slips })
    });
    if (!response.ok) throw new Error(`Archive save returned HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Archive save failed");
    unsynced.clear();
    return data;
  }

  function uniqueSlips(rows) {
    const bySignature = new Map();
    for (const slip of rows) {
      const key = slipSignature(slip);
      const old = bySignature.get(key);
      if (!old) { bySignature.set(key, slip); continue; }
      const a = String(old.status || "PENDING").toUpperCase();
      const b = String(slip.status || "PENDING").toUpperCase();
      if (a === "LOST" || b === "LOST") bySignature.set(key, a === "LOST" ? old : slip);
      else if (a === "WON" || b === "WON") bySignature.set(key, a === "WON" ? old : slip);
      else if (Number(slip.number) > Number(old.number)) bySignature.set(key, slip);
    }
    return [...bySignature.values()];
  }

  function category(slip) {
    const status = String(slip.status || "PENDING").toUpperCase();
    const legs = Array.isArray(slip.legs) ? slip.legs : [];
    if (status === "LOST" || legs.some(l => String(l.result).toUpperCase() === "LOST")) return "LOST";
    if (status === "WON" || legs.length === 4 && legs.every(l => String(l.result).toUpperCase() === "WON")) return "WON";

    const now = Date.now();
    const allScheduledFuture = legs.length === 4 && legs.every(leg => {
      const state = String(leg.fixtureState || "").toUpperCase();
      const kick = kickoffMs({ kickoff: leg.providerKickoff || leg.kickoff });
      return state === "SCHEDULED" && Number.isFinite(kick) && kick > now;
    });
    if (allScheduledFuture) return "PLAYABLE";

    return "ONGOING";
  }

  function statusForLeg(leg) {
    const code = String(leg.fixtureStatusCode || "").toUpperCase();
    const state = String(leg.fixtureState || "").toUpperCase();
    if (leg.fixtureStatus) return leg.fixtureStatus;
    if (state === "SCHEDULED" || code === "NS") return "SCHEDULED";
    const kick = kickoffMs(leg);
    if (Number.isFinite(kick) && kick <= Date.now()) return "AWAITING PROVIDER CONFIRMATION";
    return "FIXTURE STATUS NOT MATCHED";
  }

  function scoreForLeg(leg) {
    const state = String(leg.fixtureState || "").toUpperCase();
    if (state === "SCHEDULED" || String(leg.fixtureStatusCode || "").toUpperCase() === "NS") return "— : —";
    if (leg.homeScore != null && leg.awayScore != null) return `${leg.homeScore} : ${leg.awayScore}${leg.scoreProvisional || leg.scoreUnconfirmed ? "*" : ""}`;
    return "— : —";
  }

  function legMarkup(leg, index) {
    const market = String(leg.market || "").toUpperCase();
    const outcome = String(leg.result || "PENDING").toUpperCase();
    const scoreClass = outcome === "WON" ? "won" : outcome === "LOST" ? "lost" :
      LIVE.has(String(leg.fixtureStatusCode || "").toUpperCase()) ? "live" : "";
    const status = statusForLeg(leg);
    const lastRefresh = leg.lastRefresh ? formatRefresh(leg.lastRefresh) : "Awaiting score refresh";
    const kickoff = leg.providerKickoff || leg.kickoff;
    const scoreNote = outcome === "WON" ? "LEG WON" : outcome === "LOST" ? "LEG LOST" :
      leg.scoreProvisional ? "LIVE SCORE AWAITING PROVIDER UPDATE" :
      leg.scoreUnconfirmed ? "FINAL SCORE AWAITING PROVIDER CONFIRMATION" :
      "MATCH STATUS: " + status;
    return `<div class="leg">
      <div><div class="teams">${index + 1}. ${esc(leg.home)} vs ${esc(leg.away)}</div>
        <div class="meta"><span class="market ${market.includes("UNDER") ? "under" : ""}">${esc(market)}</span> · ${esc(pct(leg.probability))}</div></div>
      <div class="meta">${esc(formatKickoff(kickoff))}<br>${esc(status)}</div>
      <div class="score ${scoreClass}">${esc(scoreForLeg(leg))}</div>
      <div class="leg-status"><span>${esc(scoreNote)}</span><span class="refresh">LAST REFRESH: ${esc(lastRefresh)}</span></div>
    </div>`;
  }

  function render() {
    const items = uniqueSlips(archive).map(slip => ({ slip, category: category(slip) }));
    const totals = { PLAYABLE: 0, ONGOING: 0, WON: 0, LOST: 0 };
    items.forEach(item => totals[item.category]++);
    const total = items.length;
    const graded = totals.WON + totals.LOST;
    const winRate = graded ? (totals.WON / graded * 100).toFixed(1) + "%" : "—";
    const lossRate = graded ? (totals.LOST / graded * 100).toFixed(1) + "%" : "—";

    $("stats").innerHTML = [
      [total, "UNIQUE SLIPS"], [totals.WON, "WON"], [totals.LOST, "LOST"],
      [totals.PLAYABLE, "PLAYABLE"], [totals.ONGOING, "ONGOING"],
      [winRate, "WIN RATE · GRADED"], [lossRate, "LOSS RATE · GRADED"]
    ].map(([value, label]) => `<div class="kpi"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`).join("");

    document.querySelectorAll(".tab").forEach(button => {
      button.classList.toggle("active", button.dataset.view === activeView);
      const view = button.dataset.view;
      button.textContent = view === "ALL" ? `ALL (${total})` : `${view} (${totals[view]})`;
    });

    const visible = items.filter(item => activeView === "ALL" || item.category === activeView)
      .sort((a, b) => Number(b.slip.number || 0) - Number(a.slip.number || 0));

    $("slips").innerHTML = visible.length ? visible.map(({ slip, category: group }) => {
      const title = `SLIP #${esc(slip.number)} · ${esc(slip.createdAt || "Date unavailable")}`;
      const gradedAt = slip.gradedAt ? `<div class="meta" style="margin-top:10px">Settled ${esc(formatRefresh(slip.gradedAt))} · AUTOMATIC</div>` : "";
      const legs = Array.isArray(slip.legs) ? slip.legs : [];
      return `<article class="slip ${group.toLowerCase()}">
        <div class="slip-head"><div class="slip-title">${title}</div><span class="chip ${group.toLowerCase()}">${group}</span></div>
        ${legs.map(legMarkup).join("")}${gradedAt}
      </article>`;
    }).join("") : `<div class="empty">No slips in this category yet.</div>`;
  }

  async function loadArchive() {
    const response = await fetch("/api/slip-history", { cache: "no-store" });
    if (!response.ok) throw new Error(`Archive returned HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.slips)) throw new Error("The permanent archive returned an invalid response.");
    archive = mergeUnsynced(data.slips);
    return data;
  }

  async function refreshOnce() {
    if (pollBusy) return;
    pollBusy = true;
    try {
      const archiveData = await loadArchive();
      const dates = [...new Set(archive.flatMap(s => (s.legs || []).filter(l => {
        const r = String(l.result || "PENDING").toUpperCase();
        return r !== "WON" && r !== "LOST";
      }).map(l => String(l.date || l.kickoff || "").slice(0, 10)).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d))))];

      let feed = { fixtures: [], historyWarnings: [], configured: true, updatedAt: new Date().toISOString() };
      if (dates.length) {
        try {
          const liveResponse = await fetch("/api/live-scores", {
            method: "POST", cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dates })
          });
          feed = await liveResponse.json();
          if (!liveResponse.ok && !feed.message) feed.message = `Live-score endpoint returned HTTP ${liveResponse.status}`;
        } catch (error) {
          feed.message = error.message || "Live-score connection failed.";
        }
      }

      const before = new Map(archive.map(slip => [String(slip.id), JSON.stringify(slip)]));
      let changed = false;
      if (Array.isArray(feed.fixtures)) {
        changed = applyFeed(archive, feed.fixtures) || changed;
      }

      if (changed) {
        for (const slip of archive) {
          const id = String(slip.id || "");
          if (id && before.get(id) !== JSON.stringify(slip)) unsynced.set(id, slip);
        }
      }
      if (unsynced.size) {
        try {
          const result = await syncArchive([...unsynced.values()]);
          if (result.backupStatus) lastWarning = result.backupStatus;
          await loadArchive();
        } catch (error) {
          lastWarning = "Archive update could not be saved: " + error.message;
        }
      } else if (archiveData.backupStatus) {
        lastWarning = archiveData.backupStatus;
      }

      const notes = [];
      if (feed.configured === false) notes.push(feed.message || "FOOTBALL_DATA_KEY is not configured; score refresh is unavailable.");
      if (feed.message) notes.push(feed.message);
      if (Array.isArray(feed.historyWarnings) && feed.historyWarnings.length) notes.push(...feed.historyWarnings.slice(0, 2));
      if (lastWarning && !/backed up to github/i.test(lastWarning)) notes.push(lastWarning);
      $("connection").textContent = feed.configured === false ? "ARCHIVE ONLINE · SCORES NOT CONFIGURED" : "ARCHIVE + SCORE FEED CONNECTED";
      $("connection").className = "pill " + (notes.length ? "warn" : "ok");
      $("trackerNotice").textContent = notes.length
        ? notes.join(" · ")
        : dates.length
          ? `Updated ${formatRefresh(feed.updatedAt || new Date().toISOString())}. Scores are matched by provider fixture ID or tolerant club-name matching; ambiguous matches are never graded.`
          : "All archived legs are settled. Live-score requests are paused to conserve the provider quota.";
      $("trackerNotice").classList.toggle("error", feed.configured === false);
      render();
    } catch (error) {
      $("connection").textContent = "ARCHIVE CONNECTION ISSUE";
      $("connection").className = "pill warn";
      $("trackerNotice").textContent = "Could not refresh the permanent archive: " + error.message;
      $("trackerNotice").classList.add("error");
      render();
    } finally {
      pollBusy = false;
    }
  }

  document.querySelectorAll(".tab").forEach(button => {
    button.addEventListener("click", () => {
      activeView = button.dataset.view;
      render();
    });
  });

  refreshOnce();
  window.setInterval(refreshOnce, POLL_MS);
})();
