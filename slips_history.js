
/* BARBADOX homepage: archive-aware slip generation + tracker navigation.
 * The detailed archive and score tracker lives at /slips-tracker.
 */
(() => {
  "use strict";
  const TRACK_KEY = "barbadox.slips.tracker.v1";
  const $ = id => document.getElementById(id);

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  async function getArchive() {
    const response = await fetch("/api/slip-history", { cache: "no-store" });
    if (!response.ok) throw new Error(`Permanent archive returned HTTP ${response.status}`);
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.slips)) throw new Error("Permanent archive response is invalid.");
    localStorage.setItem(TRACK_KEY, JSON.stringify(data.slips));
    return data;
  }

  function addTrackerLink() {
    const actions = document.querySelector("#btnSlip")?.parentElement;
    if (!actions || $("btnOpenTracker")) return;
    const link = document.createElement("a");
    link.id = "btnOpenTracker";
    link.className = "btn secondary";
    link.href = "/slips-tracker";
    link.textContent = "OPEN SLIPS TRACKER ↗";
    link.style.textDecoration = "none";
    actions.appendChild(link);
  }

  function hideHomepageTracker() {
    for (const panel of document.querySelectorAll("#dash > .panel")) {
      const heading = panel.querySelector(".panelhead h2");
      if (heading && heading.textContent.toUpperCase().includes("SLIPS TRACKER")) {
        if (typeof window.renderTracker === "function") window.renderTracker = () => {};
        panel.remove();
      }
    }
  }

  function renderFreshSlips(slips) {
    const cards = $("slipCards");
    if (!cards) return;
    cards.innerHTML = slips.map(slip => {
      const legs = Array.isArray(slip.legs) ? slip.legs : [];
      return `<article class="card">
        <div class="league"><span>SLIP #${escapeHTML(slip.number)} · 4 MATCHES</span><span class="reason q">NEW · SAVED</span></div>
        ${legs.map(leg => `<div class="teams" style="font-size:13.5px;margin-top:9px">
          ${escapeHTML(leg.home)} <span class="vs">VS</span> ${escapeHTML(leg.away)}
        </div><div class="meta"><span class="market-chip ${String(leg.market).toUpperCase().includes("UNDER") ? "u" : ""}">${escapeHTML(leg.market)}</span>
        <span>${Number.isFinite(Number(leg.probability)) ? (Number(leg.probability) * 100).toFixed(1) + "%" : "—"}</span></div>`).join("")}
      </article>`;
    }).join("");
  }

  async function generateFromServer() {
    const modal = $("slipModal");
    if (!modal) return;
    modal.style.display = "block";
    $("slipStatus").textContent = "Checking the permanent archive and reserving fixtures…";
    $("slipDiag").innerHTML = "";
    $("slipCards").innerHTML = '<div class="empty skeleton" style="height:110px">Building new slips…</div>';

    try {
      const history = await getArchive();
      if (typeof snap === "undefined" || !snap) {
        throw new Error("Core 1 snapshot is not loaded. Run the model or load the last snapshot first.");
      }
      if (typeof underSnap === "undefined" || !underSnap) {
        try { underSnap = await api("/api/under35"); } catch {}
      }
      if (typeof buildSlips !== "function") throw new Error("The existing slip builder is unavailable.");
      if (typeof slipDiagnostics === "function" && typeof renderDiag === "function") {
        $("slipDiag").innerHTML = renderDiag(slipDiagnostics());
      }

      const result = buildSlips();
      const built = Array.isArray(result.list) ? result.list : [];
      if (!built.length) {
        $("slipCards").innerHTML = '<div class="empty">No complete new slip can be built from the currently qualified upcoming picks.</div>';
        $("slipStatus").textContent = `0 new slips generated · ${result.overFree || 0} free Over picks · ${result.underFree || 0} free Under picks. Existing unsettled fixtures remain reserved in the permanent archive.`;
        return;
      }

      const createdAt = new Date().toISOString();
      const candidates = built.map(item => ({
        createdAt,
        status: "PENDING",
        autoGraded: false,
        legs: [
          ...item.over.map(f => ({
            home: f.home, away: f.away, date: f.date, league: f.league,
            market: "OVER 1.5", probability: Number(f.point ?? f.core),
            kickoff: typeof kickoffIso === "function" ? kickoffIso(f) : null,
            footballDataId: f.id ?? f.fixture_id ?? f.match_id ?? null
          })),
          {
            home: item.under.home, away: item.under.away,
            date: item.under.date, league: item.under.league,
            market: "UNDER 3.5", probability: Number(item.under.p_final),
            kickoff: typeof kickoffIso === "function" ? kickoffIso(item.under) : null,
            footballDataId: item.under.id ?? item.under.fixture_id ?? item.under.match_id ?? null
          }
        ]
      }));

      const response = await fetch("/api/slip-history/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slips: candidates })
      });
      if (!response.ok) throw new Error(`Server rejected the generation request (HTTP ${response.status}).`);
      const saved = await response.json();
      if (!saved.ok) throw new Error(saved.error || "The server could not reserve these slips.");

      renderFreshSlips(saved.accepted || []);
      const accepted = (saved.accepted || []).length;
      const rejected = (saved.rejected || []).length;
      $("slipStatus").textContent = accepted
        ? `${accepted} new slip(s) saved with server-assigned numbers. ${rejected} duplicate or conflicting candidate(s) were skipped. Visit OPEN SLIPS TRACKER to view playable, ongoing, won and lost slips with live scores.`
        : `No new slip was accepted. ${rejected} candidate(s) were blocked because their fixtures are reserved or the exact combination already exists. Visit the tracker to follow your existing slips.`;

      await getArchive();
      if (typeof renderTracker === "function") renderTracker();
      if (saved.backupStatus && !/backed up to github/i.test(saved.backupStatus)) {
        $("slipStatus").textContent += " Archive backup: " + saved.backupStatus;
      }
    } catch (error) {
      $("slipCards").innerHTML = '<div class="empty">No new slips were created. The archive was not bypassed.</div>';
      $("slipStatus").textContent = error.message || "Slip generation failed.";
      $("slipStatus").className = "status err";
    }
  }

  function attachGeneratorOverride() {
    const button = $("btnSlip");
    if (!button || button.dataset.serverArchiveHandler === "1") return;
    button.dataset.serverArchiveHandler = "1";
    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      generateFromServer();
    }, true);
  }

  addTrackerLink();
  hideHomepageTracker();
  attachGeneratorOverride();
  getArchive().then(() => {
    if (typeof renderTracker === "function") renderTracker();
  }).catch(error => {
    const status = $("runStatus");
    if (status) {
      status.textContent = "Tracker archive could not be reached yet: " + error.message;
      status.className = "status warn";
    }
  });
})();
