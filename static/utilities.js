/**
 * /utilities page (#222 — 2026-05-24).
 *
 * Wires each .utility-card to its API endpoint pair:
 *   GET  /api/utilities/<name>/count → preview count display
 *   POST /api/utilities/<name>       → run + display {updated: N}
 *
 * One handler covers ALL utility cards via `data-utility` /
 * `data-run` attributes — new utilities just need a new <section>
 * in utilities.html with the matching slug. No JS changes needed
 * to register a new card.
 */
(function () {
    "use strict";

    // Slug-keyed registry — single source of truth for endpoint
    // URLs. Adding a new utility = adding a row here AND a matching
    // <section> in utilities.html.
    const UTILITIES = {
        "clear-stale-next-week-due-dates": {
            countUrl: "/api/utilities/clear-stale-next-week-due-dates/count",
            runUrl: "/api/utilities/clear-stale-next-week-due-dates",
            // After a successful run, this prose tells the user what
            // to check next. Concrete next-step trumps "Success!".
            postRunHint: "Open /calendar to verify the stuck tasks have moved off today's cell and into Unscheduled.",
        },
    };

    async function loadCount(card) {
        const slug = card.dataset.utility;
        const config = UTILITIES[slug];
        if (!config) return;
        const countEl = card.querySelector("[data-count]");
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

    async function runUtility(card) {
        const slug = card.dataset.utility;
        const config = UTILITIES[slug];
        if (!config) return;
        const btn = card.querySelector("[data-run]");
        const resultEl = card.querySelector("[data-result]");
        btn.disabled = true;
        btn.textContent = "Running…";
        resultEl.textContent = "";
        resultEl.classList.remove("utility-result-ok", "utility-result-err");
        try {
            const data = await window.apiFetch(config.runUrl, { method: "POST" });
            const n = (data && typeof data.updated === "number") ? data.updated : 0;
            resultEl.classList.add("utility-result-ok");
            const lead = n === 0
                ? "Nothing to update — the data is already clean."
                : "Updated " + n + " task" + (n === 1 ? "" : "s") + ".";
            const hint = config.postRunHint
                ? " " + config.postRunHint
                : "";
            resultEl.textContent = lead + hint;
            // Re-load count so the user sees the post-run state.
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
        // Load counts for every utility card on page load.
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
