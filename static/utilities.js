/**
 * /utilities page (#222 — 2026-05-24, extended #223 — 2026-05-24,
 * extended #236 — 2026-05-26, extended #229b — 2026-05-27).
 *
 * Wires each .utility-card to its API endpoint(s). Four utility
 * shapes are supported via the slug-keyed UTILITIES registry below:
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
 *   3. Inline-scan utilities (the #236 shape) — provide runUrl + the
 *      `inlineScan: true` flag. The Run button POSTs and the result
 *      JSON `{total, per_check, findings}` is rendered inline as a
 *      per-check breakdown + (when total > 0) a finding list. No
 *      email is sent for UI runs.
 *
 *   4. Async inline-scan utilities (the #229b shape) — provide runUrl
 *      + `inlineScan: true` + `asyncJob: true` + `statusUrl`. POST to
 *      `runUrl` kicks off a background subprocess and returns
 *      immediately. The page then polls `statusUrl` every 2s until
 *      the response's `status` is `"complete"` (renders result) or
 *      `"error"` (renders error message). The button text becomes
 *      "Running… (~{estimatedSeconds}s)" with a spinner during the
 *      wait. Used for the #229 coverage audit (pytest+cov ~30s).
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
        // #236 — inline-scan (runs in-process; no email; results
        // render inline as a per-check breakdown).
        "run-bug-pattern-scan": {
            runUrl: "/api/utilities/run-bug-pattern-scan",
            inlineScan: true,
            cleanResultText: "Scan CLEAN — no findings across the 6 checks.",
            postRunHint: "Same checks as the Sunday 13:00 UTC weekly cron.",
        },
        "run-security-posture-scan": {
            runUrl: "/api/utilities/run-security-posture-scan",
            inlineScan: true,
            cleanResultText: "Audit CLEAN — no findings across the 4 checks.",
            postRunHint: "Same checks as the 1st-of-month 13:00 UTC cron.",
        },
        "run-tech-debt-audit": {
            runUrl: "/api/utilities/run-tech-debt-audit",
            inlineScan: true,
            cleanResultText: "Audit CLEAN — no findings across the 4 checks.",
            postRunHint: "Same checks as the Saturday 13:00 UTC weekly cron. (Slower than the other scans — pip outdated + jscpd duplication detection take ~5-15s.)",
        },
        // #229b — async inline-scan (runs pytest --cov as a background
        // subprocess; the page polls for status every 2s and renders
        // the result when the job completes).
        // #251 (2026-05-28) — observed Railway runtime is 3-5 minutes
        // (not ~30s like on dev). The live elapsed-time counter in
        // pollAsyncJob makes the actual duration visible.
        "run-coverage-audit": {
            runUrl: "/api/utilities/run-coverage-audit",
            statusUrl: "/api/utilities/coverage-audit-status",
            inlineScan: true,
            asyncJob: true,
            pollIntervalMs: 2000,
            cleanResultText: "Audit CLEAN — no findings across the 3 checks.",
            postRunHint: "Same checks as the Friday 13:00 UTC weekly cron. (Runs the full pytest suite with --cov; takes 3-5 minutes on Railway.)",
        },
    };

    /**
     * #236 — render the inline-scan `{total, per_check, findings}`
     * payload into the .utility-result element. Returns nothing —
     * mutates `resultEl` in place. Per-check breakdown is always
     * shown; finding details are appended when total > 0.
     */
    function renderScanResult(resultEl, data, config) {
        const total = (data && typeof data.total === "number")
            ? data.total : 0;
        const perCheck = Array.isArray(data && data.per_check)
            ? data.per_check : [];
        const findings = Array.isArray(data && data.findings)
            ? data.findings : [];

        // Lead line — clean vs N findings.
        let leadText;
        if (total === 0) {
            leadText = config.cleanResultText
                || "Scan CLEAN — no findings.";
            resultEl.classList.add("utility-result-ok");
        } else {
            leadText = total + " finding"
                + (total === 1 ? "" : "s") + " across "
                + perCheck.filter((c) => c.count > 0).length
                + " check" + (perCheck.filter((c) => c.count > 0).length === 1 ? "" : "s")
                + ".";
            resultEl.classList.add("utility-result-err");
        }
        resultEl.textContent = leadText;
        if (config.postRunHint) {
            resultEl.appendChild(document.createTextNode(
                " " + config.postRunHint,
            ));
        }

        // Per-check breakdown (always shown — useful even on CLEAN
        // because it confirms each check actually ran).
        const breakdown = document.createElement("ul");
        breakdown.className = "utility-scan-breakdown";
        perCheck.forEach(function (c) {
            const li = document.createElement("li");
            const mark = c.errored ? "✗"
                : (c.count === 0 ? "✓" : "•");
            const tail = c.errored
                ? " errored (" + c.errored + ")"
                : " " + c.count + " finding" + (c.count === 1 ? "" : "s");
            li.textContent = mark + " " + c.label + ":" + tail;
            if (c.errored) li.classList.add("utility-scan-check-errored");
            else if (c.count > 0) li.classList.add("utility-scan-check-hit");
            breakdown.appendChild(li);
        });
        resultEl.appendChild(breakdown);

        // Findings detail list (collapsible, only on non-clean runs).
        if (findings.length > 0) {
            const det = document.createElement("details");
            det.className = "utility-scan-findings";
            det.open = total <= 10;  // small lists expand; big lists collapse
            const sum = document.createElement("summary");
            sum.textContent = "Findings (" + findings.length + ")";
            det.appendChild(sum);
            const ul = document.createElement("ul");
            findings.forEach(function (f) {
                const li = document.createElement("li");
                const idLabel = (f.check_id || f.checkId || "");
                const where = f.path
                    ? (f.path + (f.line_num ? ":" + f.line_num : ""))
                    : "";
                const head = idLabel + (where ? " — " + where : "");
                if (head) {
                    const strong = document.createElement("strong");
                    strong.textContent = head;
                    li.appendChild(strong);
                    li.appendChild(document.createTextNode(" "));
                }
                li.appendChild(document.createTextNode(
                    f.detail || f.message || f.line || "",
                ));
                ul.appendChild(li);
            });
            det.appendChild(ul);
            resultEl.appendChild(det);
        }
    }

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
     * #229b — poll the async-job statusUrl every `pollIntervalMs` until
     * the response's `status` field is `"complete"` (renders the
     * embedded `result` payload via renderScanResult) or `"error"`
     * (renders the error message). Resolves when the poll terminates.
     *
     * #244 (2026-05-27): also terminate on an unexpected flip back
     * to `"idle"` after we've seen `"running"`. The in-memory job
     * state on Railway lives only as long as the gunicorn worker —
     * when the container restarts (e.g. mid-deploy), state resets
     * to `"idle"` and the original job is effectively cancelled.
     * Before this fix the polling loop kept asking and never stopped.
     */
    /**
     * #251 (2026-05-28): format an elapsed duration as `Xm Ys` or
     * `Ys` depending on length. Used for the live "Running…" label.
     */
    function formatElapsed(seconds) {
        seconds = Math.max(0, Math.floor(seconds));
        if (seconds < 60) {
            return seconds + "s";
        }
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return m + "m " + s + "s";
    }

    function pollAsyncJob(resultEl, config, btn) {
        return new Promise(function (resolve) {
            // Track whether we've seen `running` at least once. The
            // FIRST poll might arrive before the kickoff has flipped
            // state to running (rare race); we only treat idle as
            // terminal AFTER we've seen running.
            let sawRunning = false;
            const interval = setInterval(async function () {
                let snap;
                try {
                    snap = await window.apiFetch(config.statusUrl);
                } catch (err) {
                    // Transient fetch error — keep polling. If the
                    // network is dead the operator can refresh; the
                    // backend keeps the job state in memory until the
                    // next run replaces it.
                    return;
                }
                if (snap && snap.status === "running") {
                    sawRunning = true;
                    // #251 — live elapsed-time label so the operator
                    // can see the job IS progressing, even when it
                    // takes longer than the rough estimate. Computes
                    // elapsed from `started_at` on every poll.
                    if (btn && snap.started_at) {
                        const startMs = new Date(snap.started_at).getTime();
                        const elapsedS = (Date.now() - startMs) / 1000;
                        btn.textContent = "Running… ("
                            + formatElapsed(elapsedS) + ")";
                    }
                    return;  // keep polling
                }
                if (snap && snap.status === "complete") {
                    clearInterval(interval);
                    renderScanResult(
                        resultEl,
                        snap.result || {},
                        config,
                    );
                    resolve();
                    return;
                }
                if (snap && snap.status === "error") {
                    clearInterval(interval);
                    resultEl.classList.add("utility-result-err");
                    resultEl.textContent = "Audit failed: "
                        + (snap.error || "unknown error");
                    resolve();
                    return;
                }
                if (snap && snap.status === "idle" && sawRunning) {
                    // #244 — running → idle = container reset. The
                    // job's in-memory state is gone. Surface a clear
                    // message so the operator knows to retry rather
                    // than the spinner spinning forever.
                    clearInterval(interval);
                    resultEl.classList.add("utility-result-err");
                    resultEl.textContent = "Audit was interrupted "
                        + "(server restarted during the run — likely "
                        + "a deploy). Click Run to try again.";
                    resolve();
                    return;
                }
                // Pre-running idle (kickoff race) — keep polling.
            }, config.pollIntervalMs || 2000);
        });
    }

    /**
     * Run a utility. Branches on response shape: backfill-style returns
     * {updated: N}; dispatch-style returns {dispatched: true, actions_url};
     * async-job (#229b) returns {status: "running", started_at} and is
     * followed by repeated polls of statusUrl until completion.
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
            // #229b — async-job branch: POST kicks off a background
            // subprocess and returns immediately ({status: "running"}).
            // We then poll statusUrl every 2s until the job completes
            // or errors. The button shows "Running… (~Ns)" while we wait.
            if (config.asyncJob) {
                // #251 (2026-05-28) — initial label shows a rough
                // estimate range; the polling loop overwrites with
                // a live elapsed-time counter as soon as the first
                // poll returns started_at.
                btn.textContent = "Running… (starting…)";
                try {
                    await window.apiFetch(config.runUrl, { method: "POST" });
                } catch (err) {
                    // 409 = another run already in flight (apiFetch
                    // throws on any non-2xx). Treat as "join the
                    // existing job" — start polling anyway. Any other
                    // error rethrows into the outer catch.
                    const msg = (err && err.message) || "";
                    if (!/already running/i.test(msg)) throw err;
                }
                await pollAsyncJob(resultEl, config, btn);
                return;
            }
            const data = await window.apiFetch(config.runUrl, { method: "POST" });
            // #236 — inline-scan branch: dedicated renderer that
            // builds a per-check breakdown + findings detail list.
            if (config.inlineScan) {
                renderScanResult(resultEl, data, config);
                return;
            }
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

    // ============================================================
    // #273 — project→goal mapping cleanup card.
    //
    // A self-loading audit card (no countUrl/runUrl registry entry —
    // it renders on page load and after each fix). The pure audit logic
    // lives in goal_filter_helpers.auditProjectGoalLinks (Jest-tested);
    // this is the DOM-glue + the inline reassign/clear wiring. Rows are
    // built with createElement/textContent (NOT innerHTML) so a project
    // name or goal title can never inject markup.
    // ============================================================

    function buildGoalSelect(goals, currentGoalId) {
        const sel = document.createElement("select");
        sel.className = "pg-goal-select";
        const none = document.createElement("option");
        none.value = "";
        none.textContent = "— None —";
        sel.appendChild(none);
        (goals || []).forEach(function (g) {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = g.title + " (" + g.category + ")";
            sel.appendChild(opt);
        });
        sel.value = currentGoalId || "";
        return sel;
    }

    function buildPgRow(card, project, goals, flag, flagClass, detail) {
        const row = document.createElement("div");
        row.className = "pg-row " + flagClass;

        const flagEl = document.createElement("span");
        flagEl.className = "pg-flag";
        flagEl.textContent = flag;
        row.appendChild(flagEl);

        const label = document.createElement("span");
        label.className = "pg-label";
        const name = document.createElement("strong");
        name.textContent = project.name;
        label.appendChild(name);
        label.appendChild(document.createTextNode(" " + detail));
        row.appendChild(label);

        const sel = buildGoalSelect(goals, project.goal_id);
        sel.addEventListener("change", function () {
            applyProjectGoal(card, project, sel.value);
        });
        row.appendChild(sel);

        // Quick "Clear" only for rows that currently HAVE a goal.
        if (project.goal_id) {
            const clear = document.createElement("button");
            clear.type = "button";
            clear.className = "btn btn-secondary pg-clear";
            clear.textContent = "Clear";
            clear.addEventListener("click", function () {
                applyProjectGoal(card, project, "");
            });
            row.appendChild(clear);
        }
        return row;
    }

    function renderProjectGoalAudit(container, audit, goals, card) {
        container.textContent = "";
        const cross = (audit && audit.crossSide) || [];
        const unlinked = (audit && audit.unlinked) || [];

        const summary = document.createElement("p");
        summary.className = "pg-summary";
        summary.textContent =
            cross.length + " cross-side · " + unlinked.length + " unlinked";
        container.appendChild(summary);

        if (cross.length === 0 && unlinked.length === 0) {
            const ok = document.createElement("p");
            ok.className = "utility-description";
            ok.textContent = "✓ Every active project links to a same-side goal.";
            container.appendChild(ok);
            return;
        }

        if (cross.length) {
            const h = document.createElement("h3");
            h.className = "pg-subhead";
            h.textContent = "Cross-side links";
            container.appendChild(h);
            cross.forEach(function (item) {
                container.appendChild(buildPgRow(
                    card, item.project, goals, "⚠", "pg-row-cross",
                    "(" + item.projectSide + ") → " + item.goal.title
                    + " [" + item.goalSide + "]",
                ));
            });
        }
        if (unlinked.length) {
            const h = document.createElement("h3");
            h.className = "pg-subhead";
            h.textContent = "Unlinked (no goal)";
            container.appendChild(h);
            unlinked.forEach(function (item) {
                container.appendChild(buildPgRow(
                    card, item.project, goals, "ℹ", "pg-row-unlinked",
                    "(" + item.project.type + ") → (no goal)",
                ));
            });
        }
    }

    async function applyProjectGoal(card, project, goalId) {
        const resultEl = card.querySelector("[data-pg-result]");
        try {
            await window.apiFetch("/api/projects/" + project.id, {
                method: "PATCH",
                body: JSON.stringify({ goal_id: goalId || null }),
            });
            if (resultEl) {
                resultEl.textContent = goalId
                    ? "Reassigned goal on “" + project.name + "”."
                    : "Cleared goal on “" + project.name + "”.";
                resultEl.classList.remove("utility-result-err");
            }
            await loadProjectGoalAudit(card);  // re-render with fresh data
        } catch (err) {
            if (resultEl) {
                resultEl.textContent = "Failed to update “" + project.name
                    + "”: " + (err.message || err);
                resultEl.classList.add("utility-result-err");
            }
        }
    }

    async function loadProjectGoalAudit(card) {
        const container = card.querySelector("[data-pg-audit]");
        if (!container) return;
        if (!window.goalFilterHelpers
            || !window.goalFilterHelpers.auditProjectGoalLinks) {
            container.textContent = "";
            const p = document.createElement("p");
            p.className = "utility-result utility-result-err";
            p.textContent = "Audit helper not loaded.";
            container.appendChild(p);
            return;
        }
        try {
            const [projects, goals] = await Promise.all([
                window.apiFetch("/api/projects"),            // active projects
                window.apiFetch("/api/goals?is_active=all"), // all goals (resolve archived links)
            ]);
            const audit = window.goalFilterHelpers.auditProjectGoalLinks(
                projects, goals,
            );
            renderProjectGoalAudit(container, audit, goals, card);
        } catch (err) {
            container.textContent = "";
            const p = document.createElement("p");
            p.className = "utility-result utility-result-err";
            p.textContent = "Failed to load project → goal map: "
                + (err.message || err);
            container.appendChild(p);
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
        // #273 — self-loading project→goal cleanup card + Refresh button.
        const pgCard = document.querySelector(
            '.utility-card[data-utility="project-goal-cleanup"]',
        );
        if (pgCard) {
            loadProjectGoalAudit(pgCard);
            const refresh = pgCard.querySelector("[data-pg-refresh]");
            if (refresh) {
                refresh.addEventListener("click", function () {
                    loadProjectGoalAudit(pgCard);
                });
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
