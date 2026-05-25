/**
 * /utilities page (#222 — 2026-05-24, extended #223 — 2026-05-24).
 *
 * Wires each .utility-card to its API endpoint(s). Two utility shapes
 * are supported via the slug-keyed UTILITIES registry below:
 *
 *   1. Query-driven utilities (the #222 shape) — provide countUrl +
 *      runUrl. The page loads countUrl on init to show a preview count
 *      ("Tasks that will be cleaned: N"), the Run button POSTs to
 *      runUrl, the result message reads {updated: N}, and the count is
 *      re-loaded post-run.
 *
 *   2. Action-only utilities (the #223 shape) — provide runUrl ONLY,
 *      with countUrl undefined. The page hides the .utility-status row
 *      entirely on init (no count to preview); the Run button POSTs to
 *      runUrl and the result message displays config.actionResultText
 *      (utility-specific wording) plus config.postRunHint (where to
 *      check status — typically the GitHub Actions URL the endpoint
 *      returns).
 *
 * Adding a new utility = adding an entry here + a matching <section>
 * in utilities.html. No other JS changes.
 */
(function () {
    "use strict";

    const UTILITIES = {
        // #222 — query-driven backfill
        "clear-stale-next-week-due-dates": {
            countUrl: "/api/utilities/clear-stale-next-week-due-dates/count",
            runUrl: "/api/utilities/clear-stale-next-week-due-dates",
            postRunHint: "Open /calendar to verify the stuck tasks have moved off today's cell and into Unscheduled.",
        },
        // #223 — action-only (no count preview); both dispatch a
        // GitHub Actions workflow_dispatch and return {dispatched, actions_url}
        "trigger-backup": {
            runUrl: "/api/utilities/trigger-backup",
            // Wording for the success result text; uses {actions_url}
            // placeholder which is filled in from the API response.
            actionResultText: "Backup workflow dispatched. The run takes ~3 minutes; PASS/FAIL email arrives when it finishes.",
            postRunHint: "Watch progress at the GitHub Actions tab — link below.",
        },
        "trigger-restore-drill": {
            runUrl: "/api/utilities/trigger-restore-drill",
            actionResultText: "Restore-drill workflow dispatched. The run takes ~5-8 minutes; PASS/FAIL email arrives when it finishes.",
            postRunHint: "Watch progress at the GitHub Actions tab — link below.",
        },
    };

    /**
     * Load count preview for a utility card. Skipped (and the status
     * row hidden) for action-only utilities that don't declare countUrl.
     */
    async function loadCount(card) {
        const slug = card.dataset.utility;
        const config = UTILITIES[slug];
        if (!config) return;
        const statusRow = card.querySelector("[data-status]");
        const countEl = card.querySelector("[data-count]");
        if (!config.countUrl) {
            // Action-only utility — hide the count row entirely so
            // the user sees: explanation + Run button + (eventually)
            // result message. No "Tasks that will be cleaned: …".
            if (statusRow) statusRow.hidden = true;
            return;
        }
        if (!countEl) return;
        try {
            const data = await window.apiFetch(config.countUrl);
            const n = (data && typeof data.count === "number") ? data.count : 0;
            countEl.textContent = String(n);
            if (n === 0) {
                countEl.classList.add("utility-count-zero");
            } else {
                countEl.classList.remove("utility-count-zero");
            }
        } catch (err) {
            countEl.textContent = "(failed to load — " + (err.message || err) + ")";
        }
    }

    /**
     * Run a utility. Branches on response shape: backfill-style returns
     * {updated: N}; dispatch-style returns {dispatched: true, actions_url}.
     */
    async function runUtility(card) {
        const slug = card.dataset.utility;
        const config = UTILITIES[slug];
        if (!config) return;
        const btn = card.querySelector("[data-run]");
        const resultEl = card.querySelector("[data-result]");
        btn.disabled = true;
        btn.textContent = "Running…";
        resultEl.textContent = "";
        // Clear any prior result-link children too — runs can repeat.
        while (resultEl.firstChild) resultEl.removeChild(resultEl.firstChild);
        resultEl.classList.remove("utility-result-ok", "utility-result-err");
        try {
            const data = await window.apiFetch(config.runUrl, { method: "POST" });
            resultEl.classList.add("utility-result-ok");
            let leadText;
            if (typeof data.updated === "number") {
                // Query-driven shape (#222 backfill).
                leadText = data.updated === 0
                    ? "Nothing to update — the data is already clean."
                    : "Updated " + data.updated + " task" + (data.updated === 1 ? "" : "s") + ".";
            } else if (data.dispatched) {
                // Action-only dispatch shape (#223).
                leadText = config.actionResultText
                    || "Workflow dispatched.";
            } else {
                leadText = "Done.";
            }
            const hint = config.postRunHint ? " " + config.postRunHint : "";
            resultEl.textContent = leadText + hint;
            // If the API returned an actions_url, append a clickable
            // link so the user can jump straight to watching the run.
            if (data && data.actions_url) {
                resultEl.appendChild(document.createTextNode(" "));
                const link = document.createElement("a");
                link.href = data.actions_url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = "View Actions →";
                resultEl.appendChild(link);
            }
            // Re-load count so query-driven utilities show post-run
            // state (action-only utilities have no count to refresh).
            await loadCount(card);
        } catch (err) {
            resultEl.classList.add("utility-result-err");
            resultEl.textContent = "Failed: " + (err.message || err);
        } finally {
            btn.disabled = false;
            btn.textContent = "Run";
        }
    }

    function init() {
        // Load counts for every utility card on page load (skipped
        // for action-only cards via the countUrl-absent branch).
        document.querySelectorAll(".utility-card").forEach(loadCount);
        // Wire the Run buttons.
        document.querySelectorAll(".utility-run-btn").forEach((btn) => {
            btn.addEventListener("click", function () {
                const card = btn.closest(".utility-card");
                if (card) runUtility(card);
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
