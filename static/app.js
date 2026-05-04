/* app.js — Main UI: tier board, task cards, detail panel */
"use strict";

const API = "/api/tasks";
const GOALS_API = "/api/goals";
const PROJECTS_API = "/api/projects";

// --- State -------------------------------------------------------------------

let allTasks = [];
let allGoals = [];
// #59 (2026-04-25): track load state separately from `[]` so the bulk
// dropdowns can distinguish "still loading — try again in a moment"
// from "truly no goals exist — go create one." Without this the user
// sees a misleading empty dropdown on early clicks.
let goalsLoaded = false;
let projectsLoaded = false;
let allProjects = [];
let allPreviews = [];  // recurring-template previews (#32). Each item:
// {template_id, title, type, frequency, project_id, goal_id,
//  fire_date: "YYYY-MM-DD", notes, url}
let currentView = "all"; // "all" | "work" | "personal"
// #97 (PR31, 2026-04-26): multi-select filters. Sets allow OR-within-
// dimension (multiple projects → tasks in any of them; same for goals).
// Type filter (Work/Personal) stays single-select since the data is
// mutually exclusive — picking "both" is just "All".
// localStorage persists comma-joined ids; old single-UUID values from
// PR25 parse cleanly into a Set with one element.
let projectFilter = new Set();  // Set<UUID>; empty = "All"
let goalFilter = new Set();     // Set<UUID>; empty = "All"
// #107 (PR42): free-text search across title/notes/url. Persisted to
// localStorage like the other filters. Empty string = no filter.
let searchQuery = "";
const _FILTER_LS_KEYS = {
    view: "tm.filter.view",
    project: "tm.filter.project",
    goal: "tm.filter.goal",
    search: "tm.filter.search",
};
// PR39 (C3+C7): pure helpers extracted to static/filter_helpers.js so
// they're Jest-importable. window.filterHelpers is populated by that
// script BEFORE app.js loads (via the template script-tag order).
// Backwards-compat: re-bind as module-scope identifiers so the rest of
// app.js doesn't have to change every call site at once.
const _UUID_RE = window.filterHelpers.FILTER_UUID_RE;
const _parseUuidCsv = window.filterHelpers.parseUuidCsv;
function _loadFilterPrefs() {
    try {
        const v = localStorage.getItem(_FILTER_LS_KEYS.view);
        if (v === "all" || v === "work" || v === "personal") currentView = v;
        projectFilter = _parseUuidCsv(localStorage.getItem(_FILTER_LS_KEYS.project));
        goalFilter = _parseUuidCsv(localStorage.getItem(_FILTER_LS_KEYS.goal));
        // #107 (PR42): restore search query (cap length defensively).
        const s = localStorage.getItem(_FILTER_LS_KEYS.search);
        if (typeof s === "string" && s.length <= 200) searchQuery = s;
    } catch (_) { /* private mode etc. — silently use defaults */ }
}
function _saveFilterPrefs() {
    try {
        localStorage.setItem(_FILTER_LS_KEYS.view, currentView);
        if (projectFilter.size) {
            localStorage.setItem(_FILTER_LS_KEYS.project, Array.from(projectFilter).join(","));
        } else {
            localStorage.removeItem(_FILTER_LS_KEYS.project);
        }
        if (goalFilter.size) {
            localStorage.setItem(_FILTER_LS_KEYS.goal, Array.from(goalFilter).join(","));
        } else {
            localStorage.removeItem(_FILTER_LS_KEYS.goal);
        }
        // #107 (PR42)
        if (searchQuery) {
            localStorage.setItem(_FILTER_LS_KEYS.search, searchQuery);
        } else {
            localStorage.removeItem(_FILTER_LS_KEYS.search);
        }
    } catch (_) { /* ignore */ }
}
_loadFilterPrefs();

// --- API helpers -------------------------------------------------------------

// PR52 #115: singleton recovery prompt. Multiple concurrent fetch
// failures (e.g. visibilitychange fan-out fails 5 loaders at once)
// would each fire their own confirm() — the user hits 5 OKs in a
// row. Gate via a module-level flag so only ONE prompt is shown
// per recovery cycle. Reset the flag after the user dismisses or
// the page reloads.
let _recoveryPromptShown = false;
function _maybePromptRecovery(message) {
    if (_recoveryPromptShown) return;
    _recoveryPromptShown = true;
    // eslint-disable-next-line no-alert
    const ok = confirm(message);
    if (ok) {
        _hardRecover();  // navigation kills _recoveryPromptShown anyway
    } else {
        // User dismissed — let them try again; reset after a beat.
        setTimeout(() => { _recoveryPromptShown = false; }, 5_000);
    }
}

// PR49 #113: hard-recover from a stuck SW. location.reload() can hang
// when the SW controller is in a weird state — its fetch handler may
// intercept the navigation and never resolve. Unregistering the SW
// first guarantees the next navigation goes straight to the network.
// URL builder + retry/classify logic lives in api_helpers.js (Jest-tested).
async function _hardRecover() {
    try {
        if ("serviceWorker" in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((r) => r.unregister().catch(() => {})));
        }
    } catch (_) { /* never block recovery on unregister failure */ }
    window.location.href = window.apiHelpers.buildRecoveryUrl(window.location);
}

async function apiFetch(url, opts = {}) {
    // PR47 #112 + PR49 #113: stale-tab fetch failure recovery.
    // Causes for "TypeError: Failed to fetch" on a long-idle tab:
    //  (a) Mobile browser killed the page's network connection during
    //      tab suspension; first wake-up fetch dies before reconnect.
    //  (b) Service worker controller went stale during sleep.
    //  (c) Flask OAuth session expired (24h sliding) — redirect to
    //      /login/google → cross-origin → browser blocks.
    // Recovery: auto-retry once on TypeError. If retry also fails,
    // prompt to reload via _hardRecover() (unregisters SW first so
    // the reload can't hang on a stuck SW).
    //
    // PR47 originally added redirect:"manual" + opaqueredirect detection
    // for case (c). PR49 dropped that branch — it false-positived on
    // legitimate sessions (some 3xx in normal flow gets read as opaque
    // redirect). Use the default redirect behavior; if a session 302
    // genuinely surfaces, the cross-origin block falls through to the
    // TypeError path which has the same recovery prompt.
    let resp;
    try {
        resp = await fetch(url, {
            headers: { "Content-Type": "application/json", ...opts.headers },
            ...opts,
        });
    } catch (err) {
        // Auto-retry once before bothering the user — covers the
        // "stale-tab first-wake" class, which usually succeeds on
        // retry once the connection / SW rebinds.
        if (err && err.name === "TypeError" && !opts._retried) {
            await new Promise((r) => setTimeout(r, 250));
            return apiFetch(url, { ...opts, _retried: true });
        }
        // PR52 #115: single-prompt during recovery. Without this guard,
        // the visibilitychange fan-out (loadTasks + loadGoals +
        // loadProjects + loadCompletedTasks + loadCancelledTasks) can
        // each fail concurrently and each fire its own prompt — user
        // hits OK five times. Once one prompt is showing, suppress the
        // others; once the user accepts ONE recovery, fire it once.
        _maybePromptRecovery(
            "Network request failed (this can happen on a tab that's " +
            "been idle for a while). Reload the page to recover?"
        );
        throw err;
    }
    if (resp.status === 204) return null;
    // 401/403 — actual auth failure. Surface a clean message instead of
    // dumping a JSON parse + raw statusText. Still throw so callers can
    // decide what to do; default UX is the alert in submitCapture etc.
    if (resp.status === 401 || resp.status === 403) {
        _maybePromptRecovery("Authentication failed. Reload to sign in again?");
        throw new Error("Authentication required");
    }
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || resp.statusText);
    }
    return resp.json();
}

// --- Data loading ------------------------------------------------------------

async function loadTasks() {
    // Exposed on window so non-app.js modules (e.g. inbox_categorize.js)
    // can refresh the board after a write without a hard reload.
    window.loadTasks = loadTasks;
    try {
        allTasks = await apiFetch(API);
    } catch (err) {
        console.error("Failed to load tasks:", err);
        // Don't wipe existing tasks if fetch fails (offline/cache issue)
        if (allTasks.length === 0) {
            alert("Could not load tasks. Please check your connection and reload.");
        }
        return;
    }
    renderBoard();
}

// #59 (2026-04-25): wrap goal/project loads in try/catch matching the
// loadTasks pattern. Without this, a network blip or 401 on /api/goals
// would leave allGoals = [] silently, and the bulk-edit + detail-panel
// dropdowns would render empty with no feedback to the user.
// PR36 audit BUG-2: when a project/goal is archived or deleted on the
// server, its UUID can linger forever in the localStorage filter Set
// — silently hiding all tasks because no task matches the dead id.
// After every load, sweep stale ids out of the filter Sets and persist.
function _sweepStaleFilterIds() {
    let dirty = false;
    if (allProjects && allProjects.length) {
        const live = new Set(allProjects.map((p) => p.id));
        for (const id of Array.from(projectFilter)) {
            if (!live.has(id)) { projectFilter.delete(id); dirty = true; }
        }
    }
    if (allGoals && allGoals.length) {
        const live = new Set(allGoals.map((g) => g.id));
        for (const id of Array.from(goalFilter)) {
            if (!live.has(id)) { goalFilter.delete(id); dirty = true; }
        }
    }
    if (dirty) _saveFilterPrefs();
}

async function loadGoals() {
    try {
        allGoals = await apiFetch(GOALS_API);
        goalsLoaded = true;
    } catch (err) {
        console.error("Failed to load goals:", err);
        return;
    }
    _sweepStaleFilterIds();  // PR36 BUG-2
    taskDetailPopulateGoals();
    renderGoalFilter();  // #92
}

async function loadProjects() {
    try {
        allProjects = await apiFetch(PROJECTS_API);
        projectsLoaded = true;
    } catch (err) {
        console.error("Failed to load projects:", err);
        return;
    }
    _sweepStaleFilterIds();  // PR36 BUG-2
    taskDetailPopulateProjects();
    renderProjectFilter();
}

// Backlog #32: load recurring-template previews for the 14-day window
// covering This Week + Next Week. The backend filters already-spawned
// same-day collisions and inactive templates. Failure is non-fatal —
// the board still renders real tasks.
async function loadRecurringPreviews() {
    // 14-day window from today; adjust if we later support wider preview
    // ranges (e.g. the 4-week planning view).
    const today = new Date();
    const end = new Date(today.getTime() + 13 * 24 * 60 * 60 * 1000);
    const fmt = (d) => {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
    };
    try {
        allPreviews = await apiFetch(
            `/api/recurring/previews?start=${fmt(today)}&end=${fmt(end)}`
        );
    } catch (err) {
        console.warn("Could not load recurring previews:", err);
        allPreviews = [];
    }
}

async function init() {
    // Only run task-board setup on the tasks page (index.html).
    // Other pages (goals, review, etc.) load app.js for shared utilities
    // like apiFetch() but don't have the task detail panel DOM elements.
    const isTasksPage = !!document.getElementById("detailOverlay");
    if (!isTasksPage) return;

    await Promise.all([
        loadTasks(), loadGoals(), loadProjects(), loadRecurringPreviews(),
    ]);
    // loadTasks already called renderBoard before previews loaded; re-render
    // to pick up the previews now that they're available.
    renderBoard();
    setupNavTabs();
    setupCollapse();
    setupDetailPanel();
    // Populate the Completed + Cancelled sections immediately so their
    // header counts are correct even before the user expands either.
    loadCompletedTasks();
    loadCancelledTasks();
}

// --- Rendering ---------------------------------------------------------------

const TIER_ORDER = ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"];
const TIER_EMPTY = {
    inbox: "All caught up — inbox is empty",
    today: "No tasks for today",
    tomorrow: "Nothing planned for tomorrow",
    this_week: "No tasks this week",
    next_week: "Nothing planned for next week",
    backlog: "Backlog is empty",
    freezer: "Nothing in the freezer",
};

// Tiers where tasks get visually sub-grouped by their due_date's
// day-of-week. See ADR-010. Today is already a single-day surface
// and Inbox/Backlog/Freezer don't carry a meaningful weekday
// semantics, so only This Week + Next Week get grouped.
// The pure grouping logic lives in static/day_group.js so Jest can
// unit-test it without a DOM.
const DAY_GROUPED_TIERS = new Set(["this_week", "next_week"]);

// Day-of-week labels. Mirrors the list in static/day_group.js but used
// here to bucket preview fire_dates into the Mon/Tue/... groups produced
// by groupTasksByWeekday so previews merge naturally with real tasks.
const _DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"];

// Backlog #32: given a tier name, return the [start, end] inclusive
// date range that tier covers, for filtering previews. Returns null if
// the tier isn't a preview-eligible one.
//
// #72 (2026-04-26): "this week" = Mon-Sat (Sunday excluded — used as
// rest/planning day). "Next week" = next Mon-Sat. If today is Sunday,
// "this week" is the week JUST ENDING (Mon-Sat ending yesterday) so
// you still see the Saturday/Sunday-prep view; "next week" is the
// upcoming Mon-Sat.
function _tierDateRange(tier) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    // JS weekday: Sun=0, Mon=1, ..., Sat=6. Our day_group is Mon-first.
    const jsDay = today.getDay();
    const daysSinceMonday = (jsDay + 6) % 7;  // Mon=0, Sun=6
    const thisMonday = new Date(today.getTime() - daysSinceMonday * 86400000);
    const thisSaturday = new Date(thisMonday.getTime() + 5 * 86400000);  // Mon+5 = Sat
    const nextMonday = new Date(thisMonday.getTime() + 7 * 86400000);
    const nextSaturday = new Date(thisMonday.getTime() + 12 * 86400000);  // next Mon+5
    if (tier === "this_week") return [thisMonday, thisSaturday];
    if (tier === "next_week") return [nextMonday, nextSaturday];
    return null;
}

function _previewsForTier(tier) {
    const range = _tierDateRange(tier);
    if (!range) return [];
    const [start, end] = range;
    const toMs = (iso) => {
        const parts = iso.split("-");
        return new Date(+parts[0], +parts[1] - 1, +parts[2]).getTime();
    };
    const startMs = start.getTime();
    const endMs = end.getTime();
    // View / project filters: apply the same ones the real tasks obey.
    return allPreviews.filter((p) => {
        const ms = toMs(p.fire_date);
        if (ms < startMs || ms > endMs) return false;
        if (currentView === "work" && p.type !== "work") return false;
        if (currentView === "personal" && p.type !== "personal") return false;
        if (projectFilter.size && !projectFilter.has(p.project_id)) return false;  // #97
        // PR36 audit TD-1: also filter previews by goalFilter so the
        // dashed preview cards stay consistent with the real-task
        // filter. Otherwise filtering to "Goal X" hides spawned tasks
        // but leaves their template previews visible — confusing.
        if (goalFilter.size && !goalFilter.has(p.goal_id)) return false;
        return true;
    });
}

function renderTierGroupedByDay(list, tasks, tier) {
    // Bucket real tasks by day (existing logic).
    const groups = window.groupTasksByWeekday(tasks);

    // Merge preview instances (#32). Build a lookup so we can append to
    // existing day buckets in place rather than appending extra groups
    // at the bottom that would visually split Tuesday's real tasks from
    // Tuesday's previews.
    const previews = _previewsForTier(tier);
    if (previews.length > 0) {
        const groupByLabel = new Map();
        for (const g of groups) groupByLabel.set(g.label, g);
        for (const p of previews) {
            // fire_date → Python-safe weekday label
            const parts = p.fire_date.split("-");
            const d = new Date(+parts[0], +parts[1] - 1, +parts[2]);
            const label = _DAY_LABELS[(d.getDay() + 6) % 7];
            let g = groupByLabel.get(label);
            if (!g) {
                g = { label, tasks: [], previews: [] };
                groupByLabel.set(label, g);
                groups.push(g);
            }
            if (!g.previews) g.previews = [];
            g.previews.push(p);
        }
        // Re-sort groups so new preview-only groups slot into
        // Monday-first order + "No date" last.
        const order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                       "Friday", "Saturday", "Sunday", "No date"];
        groups.sort(
            (a, b) => order.indexOf(a.label) - order.indexOf(b.label),
        );
    }

    for (const group of groups) {
        const realCount = group.tasks.length;
        // Count shown in the heading reflects REAL tasks only — the
        // preview cards are "coming up, not on your plate." Matches the
        // Option-1 decision from 2026-04-20 on the mockup.
        const heading = document.createElement("h3");
        heading.className = "day-group-heading";
        heading.textContent = `${group.label} (${realCount})`;
        list.appendChild(heading);

        const groupWrap = document.createElement("div");
        groupWrap.className = "day-group";
        for (const task of group.tasks) {
            groupWrap.appendChild(taskCardEl(task));
        }
        if (group.previews) {
            for (const preview of group.previews) {
                groupWrap.appendChild(_previewCardEl(preview));
            }
        }
        list.appendChild(groupWrap);
    }
}

// Build a preview card for a recurring template. Backlog #32 treatment
// A (dashed border). Click opens the most-recent spawned Task detail
// panel so the user can edit the Repeat settings there; if no spawn
// exists yet we show a friendly first-preview alert.
function _previewCardEl(preview) {
    const card = document.createElement("div");
    card.className = "task-card preview-card";
    card.dataset.preview = "true";
    card.dataset.templateId = preview.template_id;
    card.title = (
        `Preview of recurring template.\n` +
        `Fires: ${preview.fire_date} (${_frequencyLabel(preview.frequency)})\n` +
        `Click to edit template via its most-recent spawn.`
    );
    // Explicit draggable=false so browsers don't treat .task-card's
    // default draggable behaviour as applying here.
    card.draggable = false;

    const body = document.createElement("div");
    body.className = "task-body";
    const title = document.createElement("div");
    title.className = "task-title";
    title.textContent = preview.title;
    title.title = preview.title;  // #85: full text on hover when truncated
    body.appendChild(title);
    const meta = document.createElement("div");
    meta.className = "task-meta";
    meta.textContent = `🔁 ${_frequencyLabel(preview.frequency)} · ${preview.type}`;
    body.appendChild(meta);
    card.appendChild(body);

    card.addEventListener("click", async (e) => {
        // Previews must not interact with task-click behaviours (tier
        // buttons, checkbox, bulk-select) even if those bubble here.
        e.stopPropagation();
        await _openPreviewTemplate(preview);
    });

    return card;
}

function _frequencyLabel(freq) {
    switch (freq) {
        case "daily": return "daily";
        case "weekdays": return "weekdays";
        case "weekly": return "weekly";
        case "day_of_week": return "weekly";
        case "monthly_date": return "monthly (date)";
        case "monthly_nth_weekday": return "monthly (nth weekday)";
        default: return freq;
    }
}

// Clicking a preview opens the detail panel of the most-recent Task
// spawned from this template. That's where the Repeat dropdown can be
// used to edit the template itself. If no spawn exists yet (brand new
// template), we show an informational alert explaining it'll first
// spawn on fire_date.
async function _openPreviewTemplate(preview) {
    let recentTask = null;
    try {
        // Ask the API for any task tied to this template, newest first.
        // We reuse the existing list endpoint + filter client-side
        // because adding a ?recurring_task_id= filter is a separate
        // small backend change not worth coupling to #32.
        const allStatuses = await apiFetch(API + "?status=all");
        const matches = allStatuses.filter(
            (t) => t.repeat && t.repeat.template_id === preview.template_id,
        );
        // Fallback: match by title if repeat wasn't serialized with id.
        if (matches.length === 0) {
            recentTask = allStatuses.find((t) => t.title === preview.title) || null;
        } else {
            matches.sort(
                (a, b) => new Date(b.updated_at) - new Date(a.updated_at),
            );
            recentTask = matches[0];
        }
    } catch (err) {
        console.warn("Could not look up recent spawn:", err);
    }
    if (recentTask) {
        taskDetailOpen(recentTask);
    } else {
        alert(
            `"${preview.title}" hasn't spawned a task yet.\n\n` +
            `It will first appear on ${preview.fire_date}. ` +
            `Create a task manually and set Repeat on it if you want ` +
            `to edit this template before then.`
        );
    }
}

// #79 (2026-04-26): date / date-range string for a tier header.
// "Mon Apr 25" for today/tomorrow; "Apr 21 — Apr 26" for this/next week
// (Mon-Sat per #72). Year only when crossing a year boundary.
const _DATE_FMT_DOW_MONTH_DAY = { weekday: "short", month: "short", day: "numeric" };
const _DATE_FMT_MONTH_DAY = { month: "short", day: "numeric" };
function _tierHeaderDate(tier) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (tier === "today") {
        return today.toLocaleDateString(undefined, _DATE_FMT_DOW_MONTH_DAY);
    }
    if (tier === "tomorrow") {
        const t = new Date(today.getTime() + 86400000);
        return t.toLocaleDateString(undefined, _DATE_FMT_DOW_MONTH_DAY);
    }
    const range = _tierDateRange(tier);
    if (!range) return "";
    const [start, end] = range;
    const crossYear = start.getFullYear() !== end.getFullYear();
    const fmt = crossYear
        ? { ..._DATE_FMT_MONTH_DAY, year: "numeric" }
        : _DATE_FMT_MONTH_DAY;
    return `${start.toLocaleDateString(undefined, fmt)} — ${end.toLocaleDateString(undefined, fmt)}`;
}

function _updateTierHeaderDate(tier) {
    const section = document.querySelector(`.tier[data-tier="${tier}"]`);
    if (!section) return;
    const header = section.querySelector(".tier-header");
    if (!header) return;
    const label = _tierHeaderDate(tier);
    let dateEl = header.querySelector(".tier-date");
    if (!label) {
        if (dateEl) dateEl.remove();
        return;
    }
    if (!dateEl) {
        dateEl = document.createElement("div");
        dateEl.className = "tier-date";
        header.appendChild(dateEl);
    }
    dateEl.textContent = label;
}

// #73 (2026-04-26): inline day strip above Today. 12 cells covering
// this Mon-Sat + next Mon-Sat (per #72 week boundaries). Each cell is
// a drop target; dropping a task patches due_date — which then auto-
// routes the tier per #74.
function _formatDayCellLabel(d) {
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
}

function _isoDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
}

function renderDayStrip() {
    const strip = document.getElementById("dayStrip");
    if (!strip) return;
    strip.innerHTML = "";

    // Compute Mon-Sat for this week + next week.
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const daysSinceMonday = (today.getDay() + 6) % 7;
    const thisMonday = new Date(today.getTime() - daysSinceMonday * 86400000);

    const todayIso = _isoDate(today);
    for (let i = 0; i < 12; i++) {
        // Skip Sundays — week is Mon-Sat per #72. We have 6 days × 2 = 12 cells.
        const offset = Math.floor(i / 6) * 7 + (i % 6);
        const d = new Date(thisMonday.getTime() + offset * 86400000);
        const cell = document.createElement("div");
        cell.className = "day-cell";
        const iso = _isoDate(d);
        if (iso === todayIso) cell.classList.add("day-cell-today");
        if (iso < todayIso) cell.classList.add("day-cell-past");
        cell.dataset.date = iso;
        cell.title = `Drop a task to set due date to ${d.toLocaleDateString()}`;
        cell.textContent = _formatDayCellLabel(d);
        cell.addEventListener("dragover", (e) => {
            e.preventDefault();
            cell.classList.add("day-cell-hover");
        });
        cell.addEventListener("dragleave", () => cell.classList.remove("day-cell-hover"));
        cell.addEventListener("drop", async (e) => {
            e.preventDefault();
            cell.classList.remove("day-cell-hover");
            const taskId = e.dataTransfer && e.dataTransfer.getData("text/plain");
            // PR36 audit BUG-1: match calendar.js's UUID guard. Without
            // this, an external-app or cross-tab drag injects garbage
            // into text/plain and we send PATCH /api/tasks/<garbage>
            // (server 422s, but the alert dialog fires anyway).
            if (!taskId || !_UUID_RE.test(taskId)) return;
            try {
                await apiFetch(`${API}/${taskId}`, {
                    method: "PATCH",
                    body: JSON.stringify({ due_date: iso }),
                });
                await loadTasks();
            } catch (err) {
                alert("Failed to set due date: " + err.message);
            }
        });
        strip.appendChild(cell);
    }
}

function renderBoard() {
    renderDayStrip();
    // PR70 perf #4: was running filteredTasks() once per tier (7 tiers ×
    // search/project/goal/view filters over allTasks every iteration).
    // With 500 tasks that was 3500 string comparisons per render. Compute
    // ONCE here, bucket by tier, look up O(1) inside the loop.
    const filtered = filteredTasks();
    const byTier = new Map();
    for (const t of filtered) {
        const bucket = byTier.get(t.tier);
        if (bucket) bucket.push(t);
        else byTier.set(t.tier, [t]);
    }
    for (const tier of TIER_ORDER) {
        // #79: refresh the date / date-range below each header on every
        // board render. Cheap, idempotent.
        _updateTierHeaderDate(tier);

        const list = document.querySelector(`.task-list[data-tier="${tier}"]`);
        if (!list) continue;
        const tasks = byTier.get(tier) || [];
        // For day-grouped tiers (#32), check whether we have previews to
        // render even if there are zero real tasks — otherwise a week
        // with only recurring previews falls through to the empty-state
        // and the previews never render.
        const previewsForThisTier = DAY_GROUPED_TIERS.has(tier)
            ? _previewsForTier(tier) : [];
        list.innerHTML = "";
        if (tasks.length === 0 && previewsForThisTier.length === 0) {
            list.classList.add("empty-state");
            list.setAttribute("data-empty-msg", TIER_EMPTY[tier]);
        } else {
            list.classList.remove("empty-state");
            list.removeAttribute("data-empty-msg");

            // In work/personal view with no project filter, group by project.
            // This applies on BOTH the multi-tier board and the single-tier
            // detail page — the function only needs a list element + tasks.
            if ((currentView === "work" || currentView === "personal") && projectFilter.size === 0) {  // #97
                renderTierGroupedByProject(list, tasks);
            } else if (DAY_GROUPED_TIERS.has(tier)) {
                // This Week + Next Week: group by day-of-week of due_date.
                // See ADR-010. Pass tier so previews can be filtered to
                // this tier's date range (#32).
                renderTierGroupedByDay(list, tasks, tier);
            } else {
                for (const task of tasks) {
                    list.appendChild(taskCardEl(task));
                }
            }
        }
        // Update count — board-layout lookup first, tier-detail fallback.
        const section = list.closest(".tier");
        if (section) {
            const count = section.querySelector(".tier-count");
            if (count) count.textContent = tasks.length;
        } else {
            // Tier detail page: count lives in .tier-detail-header, empty
            // state lives in #tierDetailEmpty (shown when no tasks).
            const detailCount = document.getElementById("tierDetailCount");
            if (detailCount) detailCount.textContent = tasks.length;
            const detailEmpty = document.getElementById("tierDetailEmpty");
            if (detailEmpty) {
                detailEmpty.style.display = tasks.length === 0 ? "" : "none";
            }
        }
    }
    updateInboxBadge();
    updateTodayWarning();
    updateBulkTriageBtn();
    // Post-#12 brainstorm Option A — toggle the auto-categorize
    // button's visibility with the inbox cohort. Defined in
    // static/inbox_categorize.js; null-guarded for pages that don't
    // load that script (tier-detail / completed / projects / etc.).
    if (typeof window.updateAutoCategorizeBtn === "function") {
        window.updateAutoCategorizeBtn();
    }
    setupDragAndDrop();
}

function renderTierGroupedByProject(list, tasks) {
    // Collect tasks by project
    const byProject = new Map();
    const noProject = [];
    for (const task of tasks) {
        if (task.project_id) {
            if (!byProject.has(task.project_id)) byProject.set(task.project_id, []);
            byProject.get(task.project_id).push(task);
        } else {
            noProject.push(task);
        }
    }

    // Render each project group
    for (const project of allProjects) {
        const projectTasks = byProject.get(project.id);
        if (!projectTasks) continue;
        const groupHeader = document.createElement("div");
        groupHeader.className = "project-group-header";
        groupHeader.innerHTML = `<span class="project-dot" style="background:${project.color || '#999'}"></span> ${escapeHtml(project.name)}`;
        list.appendChild(groupHeader);
        for (const task of projectTasks) {
            list.appendChild(taskCardEl(task));
        }
    }

    // Tasks without project
    if (noProject.length > 0) {
        const groupHeader = document.createElement("div");
        groupHeader.className = "project-group-header";
        groupHeader.textContent = "No project";
        list.appendChild(groupHeader);
        for (const task of noProject) {
            list.appendChild(taskCardEl(task));
        }
    }
}

// --- Drag and drop reordering ------------------------------------------------
// Supports both desktop (HTML5 drag) and mobile (touch events).

let draggedCard = null;
let dragDropInitialized = false;
let touchDragState = null; // { card, placeholder, startY, scrollInterval }

function setupDragAndDrop() {
    if (dragDropInitialized) return;
    dragDropInitialized = true;

    for (const tier of TIER_ORDER) {
        const list = document.querySelector(`.task-list[data-tier="${tier}"]`);
        if (!list) continue;

        // --- Desktop: HTML5 drag events ---
        list.addEventListener("dragover", function (e) {
            e.preventDefault();
            if (!draggedCard) return;
            e.dataTransfer.dropEffect = "move";
            const afterEl = getDragAfterElement(list, e.clientY);
            if (afterEl) {
                list.insertBefore(draggedCard, afterEl);
            } else {
                list.appendChild(draggedCard);
            }
        });

        list.addEventListener("drop", function (e) {
            e.preventDefault();
            if (!draggedCard) return;
            finishDrop(list);
        });
    }

    // --- Completed section: drop-to-archive target ---
    // The Completed section isn't a tier — it's a status filter — so it
    // needs its own drop handler that PATCHes {status: "archived"} instead
    // of the normal tier move. We attach to the whole <section> (not just
    // the inner list) so the drop zone works even when the list is
    // collapsed, which is the default state.
    const completedSection = document.getElementById("tierCompleted");
    if (completedSection) {
        completedSection.addEventListener("dragenter", function (e) {
            if (!draggedCard) return;
            // Don't offer to "complete" a card that's already completed.
            if (draggedCard.dataset.sourceTier === "completed") return;
            e.preventDefault();
            completedSection.classList.add("drag-over");
        });
        completedSection.addEventListener("dragover", function (e) {
            if (!draggedCard) return;
            if (draggedCard.dataset.sourceTier === "completed") return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            completedSection.classList.add("drag-over");
        });
        completedSection.addEventListener("dragleave", function (e) {
            // Only clear when the pointer actually leaves the section,
            // not when it moves between child elements inside it.
            if (!completedSection.contains(e.relatedTarget)) {
                completedSection.classList.remove("drag-over");
            }
        });
        completedSection.addEventListener("drop", function (e) {
            e.preventDefault();
            e.stopPropagation();
            completedSection.classList.remove("drag-over");
            if (!draggedCard) return;
            const taskId = draggedCard.dataset.id;
            draggedCard.classList.remove("dragging");
            draggedCard = null;
            taskComplete(taskId);
        });
    }

    // --- Mobile: touch events (document-level for cross-tier dragging) ---
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    document.addEventListener("touchend", onTouchEnd);
}

function onTouchMove(e) {
    if (!touchDragState) return;
    e.preventDefault(); // stop page scrolling while dragging

    var touch = e.touches[0];
    var card = touchDragState.card;

    // Move the card visually
    var dy = touch.clientY - touchDragState.startY;
    card.style.transform = "translateY(" + dy + "px)";
    card.style.zIndex = "9999";

    // Is the finger over the Completed drop-zone?
    // Checked BEFORE the tier-list scan so an inbox card dropped on the
    // completed section archives instead of landing in a tier underneath.
    // Skip this when the card being dragged ALREADY lives in completed —
    // dropping it back on itself would be a no-op.
    var completedSection = document.getElementById("tierCompleted");
    var draggingFromCompleted = card.dataset.sourceTier === "completed";
    if (!draggingFromCompleted && completedSection &&
            isPointOverEl(completedSection, touch.clientX, touch.clientY)) {
        completedSection.classList.add("drag-over");
        touchDragState.overCompleted = true;
        return;
    }
    if (completedSection) {
        completedSection.classList.remove("drag-over");
    }
    touchDragState.overCompleted = false;

    // Find which tier list we're over and reposition
    var targetList = getListUnderPoint(touch.clientX, touch.clientY);
    if (targetList) {
        var afterEl = getDragAfterElement(targetList, touch.clientY);
        if (afterEl) {
            targetList.insertBefore(card, afterEl);
        } else {
            targetList.appendChild(card);
        }
    }
}

function onTouchEnd() {
    if (!touchDragState) return;
    var card = touchDragState.card;
    var overCompleted = touchDragState.overCompleted;

    // Reset visual state
    card.style.transform = "";
    card.style.zIndex = "";
    card.classList.remove("dragging");
    var completedSection = document.getElementById("tierCompleted");
    if (completedSection) completedSection.classList.remove("drag-over");

    if (overCompleted) {
        // Dropped on Completed → archive instead of tier-move
        var taskId = card.dataset.id;
        touchDragState = null;
        draggedCard = null;
        taskComplete(taskId);
        return;
    }

    // Find the list it ended up in
    var parentList = card.closest(".task-list");
    if (parentList && parentList.dataset.tier) {
        finishDrop(parentList);
    }

    touchDragState = null;
    draggedCard = null;
}

function isPointOverEl(el, x, y) {
    var rect = el.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function getListUnderPoint(x, y) {
    for (var i = 0; i < TIER_ORDER.length; i++) {
        var list = document.querySelector('.task-list[data-tier="' + TIER_ORDER[i] + '"]');
        if (!list) continue;
        var rect = list.getBoundingClientRect();
        // Use generous vertical bounds for easier targeting
        if (y >= rect.top - 20 && y <= rect.bottom + 20 && x >= rect.left && x <= rect.right) {
            return list;
        }
    }
    return null;
}

function finishDrop(list) {
    if (!draggedCard) return;
    var targetTier = list.dataset.tier;
    var taskId = draggedCard.dataset.id;
    var sourceTier = draggedCard.dataset.sourceTier;

    var cardIds = Array.from(list.querySelectorAll(".task-card"))
        .map(function (c) { return c.dataset.id; });

    if (sourceTier === "completed") {
        // Completed → tier: restore status=active AND set new tier
        apiFetch(API + "/" + taskId, {
            method: "PATCH",
            body: JSON.stringify({ status: "active", tier: targetTier }),
        }).then(function () {
            return saveReorder(targetTier, cardIds);
        }).then(function () {
            loadTasks();
            loadCompletedTasks();
        });
    } else if (sourceTier !== targetTier) {
        apiFetch(API + "/" + taskId, {
            method: "PATCH",
            body: JSON.stringify({ tier: targetTier }),
        }).then(function () {
            return saveReorder(targetTier, cardIds);
        }).then(function () {
            loadTasks();
        });
    } else {
        saveReorder(targetTier, cardIds);
    }
}

function getDragAfterElement(list, y) {
    var cards = Array.from(list.querySelectorAll(".task-card:not(.dragging)"));
    var closest = null;
    var closestOffset = Number.NEGATIVE_INFINITY;

    for (var i = 0; i < cards.length; i++) {
        var box = cards[i].getBoundingClientRect();
        var offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closestOffset) {
            closestOffset = offset;
            closest = cards[i];
        }
    }
    return closest;
}

async function saveReorder(tier, taskIds) {
    await apiFetch(API + "/reorder", {
        method: "POST",
        body: JSON.stringify({ tier: tier, task_ids: taskIds }),
    });
}

function filteredTasks() {
    // PR42 (#107): delegate to filter_helpers.js applyFilters so the
    // logic (incl. search) is unit-testable and shared with the
    // filteredCompleted / filteredCancelled clones below.
    return window.filterHelpers.applyFilters(
        allTasks, currentView, projectFilter, goalFilter, searchQuery,
    );
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function taskCardEl(task) {
    const card = document.createElement("div");
    card.className = "task-card";
    card.dataset.id = task.id;
    card.dataset.sourceTier = task.tier;
    card.draggable = true;

    // Desktop drag events
    card.addEventListener("dragstart", function (e) {
        draggedCard = card;
        card.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", task.id);
    });
    card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
        draggedCard = null;
    });

    // Mobile touch: long-press to start drag (500ms hold)
    var longPressTimer = null;
    var touchStartX = 0;
    var touchStartY = 0;
    card.addEventListener("touchstart", function (e) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        longPressTimer = setTimeout(function () {
            longPressTimer = null;
            draggedCard = card;
            touchDragState = {
                card: card,
                startY: e.touches[0].clientY,
            };
            card.classList.add("dragging");
            // Haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(50);
        }, 500);
    }, { passive: true });
    card.addEventListener("touchmove", function (e) {
        // Only cancel long-press if finger moves more than 10px (natural jitter tolerance)
        if (longPressTimer) {
            var dx = e.touches[0].clientX - touchStartX;
            var dy = e.touches[0].clientY - touchStartY;
            if (Math.sqrt(dx * dx + dy * dy) > 10) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        }
    }, { passive: true });
    card.addEventListener("touchend", function () {
        if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
        }
    });

    const today = new Date().toISOString().slice(0, 10);

    // Triage checkbox (inbox only) — kept for the existing inbox-triage flow.
    const triageCheck = document.createElement("input");
    triageCheck.type = "checkbox";
    triageCheck.className = "triage-check";
    triageCheck.addEventListener("click", (e) => e.stopPropagation());
    triageCheck.addEventListener("change", updateBulkTriageBtn);
    card.appendChild(triageCheck);

    // Bulk-select checkbox — appears on EVERY task card when bulk-select
    // mode is on (body has class .bulk-select-mode). Independent of the
    // triage-check above. See backlog #21.
    const bulkCheck = document.createElement("input");
    bulkCheck.type = "checkbox";
    bulkCheck.className = "bulk-select-check";
    bulkCheck.title = "Select for bulk action";
    bulkCheck.addEventListener("click", (e) => e.stopPropagation());
    bulkCheck.addEventListener("change", () => {
        card.classList.toggle("bulk-selected", bulkCheck.checked);
        updateBulkToolbar();
    });
    card.appendChild(bulkCheck);

    // Complete checkbox
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "task-checkbox";
    cb.title = "Complete task";
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", () => taskComplete(task.id));
    card.appendChild(cb);

    // Body
    const body = document.createElement("div");
    body.className = "task-body";

    const title = document.createElement("div");
    title.className = "task-title";
    title.textContent = task.title;
    title.title = task.title;  // #85: full text on hover when truncated
    body.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "task-meta";

    // Type badge
    const typeBadge = document.createElement("span");
    typeBadge.className = `badge badge-${task.type}`;
    typeBadge.textContent = task.type;
    meta.appendChild(typeBadge);

    // Project badge (work tasks)
    if (task.project_id) {
        const project = allProjects.find((p) => p.id === task.project_id);
        if (project) {
            const projBadge = document.createElement("span");
            projBadge.className = "badge badge-project";
            if (project.color) projBadge.style.borderColor = project.color;
            projBadge.textContent = project.name;
            meta.appendChild(projBadge);
        }
    }

    // Due date
    if (task.due_date) {
        const dueBadge = document.createElement("span");
        dueBadge.className = "badge badge-due";
        if (task.due_date < today) {
            dueBadge.classList.add("overdue");
            dueBadge.textContent = `overdue: ${task.due_date}`;
        } else if (task.due_date === today) {
            dueBadge.classList.add("due-today");
            dueBadge.textContent = "due today";
        } else {
            dueBadge.textContent = `due ${task.due_date}`;
        }
        meta.appendChild(dueBadge);
    }

    // Goal badge
    if (task.goal_id) {
        const goal = allGoals.find((g) => g.id === task.goal_id);
        if (goal) {
            const goalBadge = document.createElement("span");
            goalBadge.className = "badge badge-goal";
            goalBadge.textContent = goal.title;
            meta.appendChild(goalBadge);
        }
    }

    // Repeat badge
    if (task.repeat) {
        const repeatBadge = document.createElement("span");
        repeatBadge.className = "badge badge-repeat";
        const freqLabels = {
            daily: "Daily",
            weekdays: "Weekdays",
            weekly: "Weekly",
            monthly_date: "Monthly",
            monthly_nth_weekday: "Monthly",
        };
        repeatBadge.textContent = "\u21BB " + (freqLabels[task.repeat.frequency] || "Repeat");
        meta.appendChild(repeatBadge);
    }

    // URL / article badge
    if (task.url) {
        const urlBadge = document.createElement("a");
        urlBadge.className = "badge badge-url";
        urlBadge.textContent = "Read ↗";
        urlBadge.href = task.url;
        urlBadge.target = "_blank";
        urlBadge.rel = "noopener noreferrer";
        urlBadge.title = task.url;
        urlBadge.addEventListener("click", (e) => e.stopPropagation());
        meta.appendChild(urlBadge);
    }

    // Checklist progress
    if (task.checklist && task.checklist.length > 0) {
        const done = task.checklist.filter((c) => c.checked).length;
        const clBadge = document.createElement("span");
        clBadge.className = "badge badge-checklist";
        if (done === task.checklist.length) clBadge.classList.add("all-done");
        clBadge.textContent = `${done}/${task.checklist.length}`;
        meta.appendChild(clBadge);
    }

    // Subtask progress badge (parent tasks only)
    if (task.subtask_count > 0) {
        const stBadge = document.createElement("span");
        stBadge.className = "badge badge-subtask";
        if (task.subtask_done === task.subtask_count) stBadge.classList.add("all-done");
        stBadge.textContent = `${task.subtask_done}/${task.subtask_count} subtasks`;
        meta.appendChild(stBadge);
    }

    // Parent indicator (subtasks only)
    if (task.parent_id) {
        const parent = allTasks.find((t) => t.id === task.parent_id);
        if (parent) {
            const parentBadge = document.createElement("span");
            parentBadge.className = "badge badge-parent";
            parentBadge.textContent = `↳ ${parent.title}`;
            parentBadge.title = `Subtask of: ${parent.title}`;
            meta.appendChild(parentBadge);
        }
    }

    body.appendChild(meta);
    card.appendChild(body);

    // Quick actions
    const actions = document.createElement("div");
    actions.className = "task-quick-actions";

    // Complete button — shown on every tier, including inbox, so users
    // can archive a task straight from triage without a two-step move.
    const completeBtn = document.createElement("button");
    completeBtn.textContent = "✓ Done";
    completeBtn.title = "Mark complete";
    completeBtn.className = "quick-complete-btn";
    completeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        taskComplete(task.id);
    });
    actions.appendChild(completeBtn);

    const tierBtns = TIER_ORDER.filter((t) => t !== task.tier && t !== "inbox");
    for (const t of tierBtns) {
        const btn = document.createElement("button");
        btn.textContent = tierLabel(t);
        btn.title = `Move to ${tierLabel(t)}`;
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            taskMoveTier(task.id, t);
        });
        actions.appendChild(btn);
    }

    // #78 followup (2026-04-26): + Subtask button on parent-eligible cards.
    // Subtasks can't have subtasks (1-level-deep model rule), so hide on
    // tasks that already have a parent.
    if (!task.parent_id) {
        const subBtn = document.createElement("button");
        subBtn.textContent = "+ Subtask";
        subBtn.title = "Add a subtask under this task";
        subBtn.className = "quick-subtask-btn";
        subBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const title = prompt("Subtask title:");
            if (!title || !title.trim()) return;
            try {
                await apiFetch(API, {
                    method: "POST",
                    body: JSON.stringify({
                        title: title.trim(),
                        type: task.type,
                        parent_id: task.id,
                    }),
                });
                await loadTasks();
            } catch (err) {
                alert("Failed to add subtask: " + err.message);
            }
        });
        actions.appendChild(subBtn);
    }

    card.appendChild(actions);

    // Click to open detail
    card.addEventListener("click", () => taskDetailOpen(task));

    return card;
}

function tierLabel(tier) {
    // #81 (2026-04-25): map missed `tomorrow` + `next_week` so badges,
    // hover titles, and tier-button labels render the proper Title-Case
    // form instead of the raw enum value (`next_week` → "Next Week").
    const labels = {
        today: "Today",
        tomorrow: "Tomorrow",
        this_week: "This Week",
        next_week: "Next Week",
        backlog: "Backlog",
        freezer: "Freezer",
        inbox: "Inbox",
    };
    return labels[tier] || tier;
}

// --- Inbox badge & Today warning -------------------------------------------

function updateInboxBadge() {
    // PR28 audit fix #2: null-guard to match updateTodayWarning's pattern.
    // CLAUDE.md cascade-check rule: subpages load app.js + can call render
    // helpers transitively; unguarded getElementById on a board-only element
    // throws TypeError and stops downstream init. Two prior incidents
    // already (#87/#78 in CLAUDE.md) — don't let it be three.
    const badge = document.getElementById("inboxBadge");
    if (!badge) return;
    const count = allTasks.filter((t) => t.tier === "inbox").length;
    badge.textContent = count;
    badge.classList.toggle("empty", count === 0);
}

function updateTodayWarning() {
    const warn = document.getElementById("todayWarning");
    if (!warn) return;  // not on this page (e.g. /completed, /tier/<name>)
    const count = filteredTasks().filter((t) => t.tier === "today").length;
    warn.style.display = count > 7 ? "" : "none";
}

// --- Project filter (Work view) ----------------------------------------------

function renderProjectFilter() {
    const container = document.getElementById("projectFilterBar");
    if (!container) return;
    container.innerHTML = "";

    // #92 (PR25): always show projects (was: only when work/personal active).
    // When a view filter is set, scope to that type; otherwise show all.
    const viewProjects = (currentView === "all")
        ? allProjects.slice()
        : allProjects.filter((p) => p.type === currentView);

    const label = document.createElement("span");
    label.className = "goal-filter-label";  // reuse the label style
    label.textContent = "Project:";
    container.appendChild(label);

    // #97 (PR31): "All" clears the set; individual chips toggle membership.
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "btn-sm project-filter-btn" + (projectFilter.size === 0 ? " active" : "");
    allBtn.textContent = "All";
    allBtn.addEventListener("click", () => {
        projectFilter.clear(); _saveFilterPrefs();
        renderBoard(); renderCompletedList(); renderProjectFilter();
    });
    container.appendChild(allBtn);

    for (const p of viewProjects) {
        const btn = document.createElement("button");
        btn.type = "button";
        const active = projectFilter.has(p.id);
        btn.className = "btn-sm project-filter-btn" + (active ? " active" : "");
        btn.innerHTML = `<span class="project-dot" style="background:${p.color || '#999'}"></span> ${escapeHtml(p.name)}`;
        btn.addEventListener("click", () => {
            // #97: toggle in/out of the multi-select Set.
            if (projectFilter.has(p.id)) projectFilter.delete(p.id);
            else projectFilter.add(p.id);
            _saveFilterPrefs();
            renderBoard(); renderCompletedList(); renderProjectFilter();
        });
        container.appendChild(btn);
    }
}

// #92 (PR25): goal/objective filter — chip-style tabs matching the
// existing All/Work/Personal pattern so all three filter dimensions
// look consistent. Long lists wrap onto multiple rows.
function renderGoalFilter() {
    const container = document.getElementById("goalFilterBar");
    if (!container) return;
    container.innerHTML = "";

    const label = document.createElement("span");
    label.className = "goal-filter-label";
    label.textContent = "Objective:";
    container.appendChild(label);

    // #97 (PR31): "All" clears the set; individual chips toggle membership.
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "btn-sm goal-filter-btn" + (goalFilter.size === 0 ? " active" : "");
    allBtn.textContent = "All";
    allBtn.addEventListener("click", () => {
        goalFilter.clear(); _saveFilterPrefs();
        renderBoard(); renderCompletedList(); renderCancelledList();
        renderGoalFilter();
    });
    container.appendChild(allBtn);

    // Sort goals by category then title for stable scanning.
    const sorted = (allGoals || []).slice().sort((a, b) => {
        const ac = a.category || ""; const bc = b.category || "";
        if (ac !== bc) return ac.localeCompare(bc);
        return (a.title || "").localeCompare(b.title || "");
    });
    for (const g of sorted) {
        const btn = document.createElement("button");
        btn.type = "button";
        const active = goalFilter.has(g.id);
        btn.className = "btn-sm goal-filter-btn" + (active ? " active" : "");
        btn.textContent = g.title;
        btn.title = g.title + (g.category ? ` — ${g.category}` : "");
        btn.addEventListener("click", () => {
            if (goalFilter.has(g.id)) goalFilter.delete(g.id);
            else goalFilter.add(g.id);
            _saveFilterPrefs();
            renderBoard(); renderCompletedList(); renderCancelledList();
            renderGoalFilter();
        });
        container.appendChild(btn);
    }
}

// #107 (PR42): task search bar. Free-text input above the filter chips
// that case-insensitively matches title/notes/url. Persisted via
// localStorage like the other filter dimensions. Wired into the same
// re-render trifecta (board / completed / cancelled).
function renderSearchBar() {
    const input = document.getElementById("taskSearchInput");
    if (!input) return;
    // One-time wiring guard so we don't re-attach the listener on
    // every render (PR28 BUG-1 listener-accumulation class).
    if (input.dataset.searchWired) {
        // Just reflect persisted value if it's stale.
        if (input.value !== searchQuery) input.value = searchQuery;
        renderSearchMeta();
        return;
    }
    input.dataset.searchWired = "1";
    input.value = searchQuery;
    let debounceId = null;
    input.addEventListener("input", () => {
        const next = window.filterHelpers.searchTerm(input.value);
        clearTimeout(debounceId);
        debounceId = setTimeout(() => {
            searchQuery = next;
            _saveFilterPrefs();
            renderBoard();
            renderCompletedList();
            renderCancelledList();
            renderSearchMeta();
        }, 120);
    });
    const clearBtn = document.getElementById("taskSearchClear");
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            searchQuery = "";
            input.value = "";
            _saveFilterPrefs();
            renderBoard();
            renderCompletedList();
            renderCancelledList();
            renderSearchMeta();
            input.focus();
        });
    }
    renderSearchMeta();
}

function renderSearchMeta() {
    const meta = document.getElementById("taskSearchMeta");
    if (!meta) return;
    if (!searchQuery) { meta.textContent = ""; return; }
    // Show "<n> of <total> match" against allTasks size (active board only).
    const matched = window.filterHelpers.applyFilters(
        allTasks, currentView, projectFilter, goalFilter, searchQuery,
    ).length;
    const total = (allTasks || []).length;
    meta.textContent = `${matched} of ${total} match`;
}

// --- Bulk triage -------------------------------------------------------------

function updateBulkTriageBtn() {
    const btn = document.getElementById("bulkTriageBtn");
    if (!btn) return;
    const checked = document.querySelectorAll(
        '.tier[data-tier="inbox"] .triage-check:checked'
    );
    btn.style.display = checked.length > 0 ? "" : "none";
}

const _bulkTriageBtn = document.getElementById("bulkTriageBtn");
if (_bulkTriageBtn) _bulkTriageBtn.addEventListener("click", (e) => {
    const existing = document.querySelector(".triage-dropdown");
    if (existing) { existing.remove(); return; }

    const dd = document.createElement("div");
    dd.className = "triage-dropdown";
    dd.style.top = e.target.offsetTop + e.target.offsetHeight + "px";
    dd.style.right = "14px";

    // PR45 #110 sweep: was missing tomorrow + next_week. Triage from
    // Inbox should support every destination tier (inbox excluded —
    // you're triaging AWAY from it).
    for (const tier of ["today", "tomorrow", "this_week", "next_week", "backlog", "freezer"]) {
        const btn = document.createElement("button");
        btn.textContent = tierLabel(tier);
        btn.addEventListener("click", () => {
            bulkMoveTier(tier);
            dd.remove();
        });
        dd.appendChild(btn);
    }
    e.target.parentElement.appendChild(dd);
    document.addEventListener("click", function close(ev) {
        if (!dd.contains(ev.target) && ev.target !== e.target) {
            dd.remove();
            document.removeEventListener("click", close);
        }
    });
});

async function bulkMoveTier(tier) {
    const checks = document.querySelectorAll(
        '.tier[data-tier="inbox"] .triage-check:checked'
    );
    const ids = Array.from(checks).map((c) => c.closest(".task-card").dataset.id);
    await Promise.all(
        ids.map((id) => apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ tier }),
        }))
    );
    await loadTasks();
}

// --- Task mutations ----------------------------------------------------------

async function taskMoveTier(id, tier) {
    await apiFetch(`${API}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ tier }),
    });
    await loadTasks();
}

async function taskComplete(id) {
    const task = allTasks.find((t) => t.id === id);

    // Parent tasks with open subtasks: use the /complete endpoint which
    // returns a 422 warning. Prompt user to auto-close or cancel.
    if (task && task.subtask_count > task.subtask_done) {
        const open = task.subtask_count - task.subtask_done;
        const ok = confirm(
            `This task has ${open} open subtask(s).\n\nComplete all subtasks too?`
        );
        if (!ok) return;
        await apiFetch(`${API}/${id}/complete`, {
            method: "POST",
            body: JSON.stringify({ complete_subtasks: true }),
        });
    } else {
        await apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify({ status: "archived" }),
        });
    }

    await loadTasks();
    loadCompletedTasks();
}

async function taskDelete(id) {
    await apiFetch(`${API}/${id}`, { method: "DELETE" });
    await loadTasks();
    taskDetailClose();
}

// Backlog #25: mark a task cancelled with an optional reason.
async function taskCancel(id, reason) {
    await apiFetch(`${API}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
            status: "cancelled",
            cancellation_reason: reason || null,
        }),
    });
    await loadTasks();
    loadCancelledTasks();
}

// --- Nav tabs ----------------------------------------------------------------

function setupNavTabs() {
    document.querySelectorAll(".nav-tab[data-view]").forEach((tab) => {
        tab.addEventListener("click", (e) => {
            e.preventDefault();
            // Only clear active state on the view-filter sub-nav, not on
            // the main page tabs in the header (which now include a
            // permanent .active marker for the current page).
            document.querySelectorAll(".view-filter-btn").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            currentView = tab.dataset.view;
            projectFilter.clear();  // #97 (PR31): resetting type clears all project chips to avoid empty results
            _saveFilterPrefs();  // #92: persist view + clear stale project filter
            renderBoard();
            renderCompletedList();
            renderCancelledList();
            // #92: project filter bar is now always visible — just re-render
            // so the project list reflects the new view's type filter.
            renderProjectFilter();
        });
    });
}

// --- Collapse / expand -------------------------------------------------------

function setupCollapse() {
    document.querySelectorAll(".collapse-toggle").forEach((btn) => {
        btn.addEventListener("click", () => {
            const section = btn.closest(".tier");
            const body = section.querySelector(".tier-body");
            const expanded = btn.getAttribute("aria-expanded") === "true";
            btn.setAttribute("aria-expanded", !expanded);
            btn.textContent = expanded ? "▸" : "▾";
            if (expanded) {
                body.style.display = "none";
            } else {
                body.style.display = "";
                // Load completed tasks on first expand
                if (section.id === "tierCompleted" && !section.dataset.loaded) {
                    loadCompletedTasks();
                }
                if (section.id === "tierCancelled" && !section.dataset.loaded) {
                    loadCancelledTasks();
                }
            }
        });
    });
}

// --- Completed tasks ---------------------------------------------------------

let completedLoaded = false;
let allCompleted = [];  // raw cache so view/project filter changes don't re-hit the API

async function loadCompletedTasks() {
    const section = document.getElementById("tierCompleted");
    const list = document.getElementById("completedList");
    // Also supports the dedicated /completed page (#29) which has a
    // different DOM shape (#tierDetailList instead of #completedList).
    const dedicatedList = document.querySelector(
        '#tierDetailList[data-archived-list="true"]'
    );

    if (list) {
        list.innerHTML = "<div class='loading-msg'>Loading...</div>";
        if (section) section.dataset.loaded = "true";
    }
    if (dedicatedList) {
        dedicatedList.innerHTML = "<div class='loading-msg'>Loading...</div>";
    }
    if (!list && !dedicatedList) return;  // no completed container on this page

    allCompleted = await apiFetch(API + "?status=archived");
    if (list) renderCompletedList();
    if (dedicatedList) renderCompletedPage();
}

// Backlog #29: renders archived tasks onto the dedicated /completed
// full-page view using the standard taskCardEl (full interaction
// affordances — tier buttons work, bulk-select works, click opens
// the detail panel). The board's inline Completed section keeps its
// compact completed-card treatment via renderCompletedList.
function renderCompletedPage() {
    const list = document.querySelector(
        '#tierDetailList[data-archived-list="true"]'
    );
    const count = document.getElementById("tierDetailCount");
    const empty = document.getElementById("tierDetailEmpty");
    if (!list) return;
    const tasks = filteredCompleted();
    list.innerHTML = "";
    if (count) count.textContent = tasks.length;
    if (empty) empty.style.display = tasks.length === 0 ? "" : "none";
    if (tasks.length === 0) return;
    for (const task of tasks) {
        list.appendChild(taskCardEl(task));
    }
}

function filteredCompleted() {
    return window.filterHelpers.applyFilters(  // PR42 #107
        allCompleted, currentView, projectFilter, goalFilter, searchQuery,
    );
}

function renderCompletedList() {
    // Also refresh the dedicated /completed page (#29) if we're on it.
    // querySelector returns null on the board, so this is a no-op there.
    renderCompletedPage();

    const list = document.getElementById("completedList");
    const count = document.getElementById("completedCount");
    if (!list) return;  // on the dedicated page there's no inline section
    const tasks = filteredCompleted();
    list.innerHTML = "";
    if (count) count.textContent = tasks.length;

    if (tasks.length === 0) {
        list.classList.add("empty-state");
        list.setAttribute("data-empty-msg", "No completed tasks yet");
        return;
    }

    list.classList.remove("empty-state");
    // Show most recently completed first
    for (const task of tasks) {
        const card = document.createElement("div");
        card.className = "task-card completed-card";
        card.dataset.id = task.id;
        // Marker used by finishDrop() + touch handlers to route drops
        // from the Completed list into taskRestore instead of a tier move.
        card.dataset.sourceTier = "completed";
        card.draggable = true;

        // Desktop drag
        card.addEventListener("dragstart", function (e) {
            draggedCard = card;
            card.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", task.id);
        });
        card.addEventListener("dragend", function () {
            card.classList.remove("dragging");
            draggedCard = null;
        });

        // Mobile long-press to drag
        var cLongPress = null;
        var cStartX = 0;
        var cStartY = 0;
        card.addEventListener("touchstart", function (e) {
            cStartX = e.touches[0].clientX;
            cStartY = e.touches[0].clientY;
            cLongPress = setTimeout(function () {
                cLongPress = null;
                draggedCard = card;
                touchDragState = {
                    card: card,
                    startY: e.touches[0].clientY,
                };
                card.classList.add("dragging");
                if (navigator.vibrate) navigator.vibrate(50);
            }, 500);
        }, { passive: true });
        card.addEventListener("touchmove", function (e) {
            if (cLongPress) {
                var dx = e.touches[0].clientX - cStartX;
                var dy = e.touches[0].clientY - cStartY;
                if (Math.sqrt(dx * dx + dy * dy) > 10) {
                    clearTimeout(cLongPress);
                    cLongPress = null;
                }
            }
        }, { passive: true });
        card.addEventListener("touchend", function () {
            if (cLongPress) { clearTimeout(cLongPress); cLongPress = null; }
        });

        const title = document.createElement("div");
        title.className = "task-title completed-title";
        title.textContent = task.title;
        title.title = task.title;  // #85
        card.appendChild(title);

        const meta = document.createElement("div");
        meta.className = "task-meta";

        const typeBadge = document.createElement("span");
        typeBadge.className = "badge badge-" + task.type;
        typeBadge.textContent = task.type;
        meta.appendChild(typeBadge);

        const dateBadge = document.createElement("span");
        dateBadge.className = "badge";
        dateBadge.textContent = task.updated_at.slice(0, 10);
        meta.appendChild(dateBadge);

        card.appendChild(meta);

        // Re-open dropdown
        const reopenWrap = document.createElement("div");
        reopenWrap.className = "reopen-wrap";
        const reopenBtn = document.createElement("button");
        reopenBtn.className = "btn-sm reopen-btn";
        reopenBtn.textContent = "Re-open ▾";
        reopenBtn.title = "Move back to active tasks";
        reopenBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            // Toggle dropdown
            const existing = reopenWrap.querySelector(".reopen-dropdown");
            if (existing) { existing.remove(); return; }
            const dd = document.createElement("div");
            dd.className = "reopen-dropdown";
            // PR45 #110: was missing 'tomorrow' + 'next_week'. Both are
            // valid Tier enum values and present in the detail-panel
            // dropdown — the reopen-dropdown was a stale subset that
            // pre-dated the Tomorrow tier (#27) and Next Week tier (#82).
            ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"].forEach(function (t) {
                const opt = document.createElement("button");
                opt.textContent = tierLabel(t);
                opt.addEventListener("click", function (ev) {
                    ev.stopPropagation();
                    taskRestore(task.id, t);
                    dd.remove();
                });
                dd.appendChild(opt);
            });
            reopenWrap.appendChild(dd);
            // Close on outside click
            document.addEventListener("click", function close() {
                dd.remove();
                document.removeEventListener("click", close);
            }, { once: true });
        });
        reopenWrap.appendChild(reopenBtn);
        card.appendChild(reopenWrap);

        // Click to view detail
        card.addEventListener("click", function () {
            taskDetailOpen(task);
        });

        list.appendChild(card);
    }
}

async function taskRestore(id, tier) {
    tier = tier || "inbox";
    await apiFetch(API + "/" + id, {
        method: "PATCH",
        body: JSON.stringify({ status: "active", tier: tier }),
    });
    await loadTasks();
    // Always reload — keeps #completedCount in sync even if the
    // Completed section hasn't been expanded yet.
    loadCompletedTasks();
    loadCancelledTasks();
}

// --- Cancelled tasks (#25) ---------------------------------------------------
// Stripped-down twin of the Completed section: load on demand, render
// title + reason, click-to-open in the detail panel for un-cancellation.
// No drag/drop here — cancellation is a deliberate end-state, not a
// throw-away gesture, so requiring a panel-open to restore is the right
// friction.

let allCancelled = [];

async function loadCancelledTasks() {
    const section = document.getElementById("tierCancelled");
    if (!section) return;  // not on the board page
    const list = document.getElementById("cancelledList");
    if (!list) return;  // PR28 audit fix #4: section exists but list doesn't (template variation)
    list.innerHTML = "<div class='loading-msg'>Loading...</div>";
    section.dataset.loaded = "true";
    allCancelled = await apiFetch(API + "?status=cancelled");
    renderCancelledList();
}

function filteredCancelled() {
    return window.filterHelpers.applyFilters(  // PR42 #107
        allCancelled, currentView, projectFilter, goalFilter, searchQuery,
    );
}

function renderCancelledList() {
    const list = document.getElementById("cancelledList");
    const count = document.getElementById("cancelledCount");
    if (!list || !count) return;
    const tasks = filteredCancelled();
    list.innerHTML = "";
    count.textContent = tasks.length;

    if (tasks.length === 0) {
        list.classList.add("empty-state");
        list.setAttribute("data-empty-msg", "No cancelled tasks");
        return;
    }
    list.classList.remove("empty-state");
    for (const task of tasks) {
        const card = document.createElement("div");
        card.className = "task-card cancelled-card";
        card.dataset.id = task.id;
        card.dataset.sourceTier = "cancelled";

        const title = document.createElement("div");
        title.className = "task-title";
        title.textContent = task.title;
        title.title = task.title;  // #85
        card.appendChild(title);

        if (task.cancellation_reason) {
            const reason = document.createElement("div");
            reason.className = "task-cancellation-reason";
            reason.textContent = "Reason: " + task.cancellation_reason;
            card.appendChild(reason);
        }

        card.addEventListener("click", () => taskDetailOpen(task));
        list.appendChild(card);
    }
}

// --- Detail panel ------------------------------------------------------------

function setupDetailPanel() {
    document.getElementById("detailClose").addEventListener("click", taskDetailClose);
    document.getElementById("detailOverlay").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) taskDetailClose();
    });
    document.getElementById("detailForm").addEventListener("submit", taskDetailSave);
    document.getElementById("detailDelete").addEventListener("click", () => {
        const id = document.getElementById("detailId").value;
        if (id) taskDelete(id);
    });
    document.getElementById("detailComplete").addEventListener("click", () => {
        const id = document.getElementById("detailId").value;
        if (id) {
            taskDetailClose();
            taskComplete(id);
        }
    });
    // #143 (2026-05-04): "Copy to tomorrow". Original stays put;
    // POST /api/tasks/<id>/duplicate creates a clone in TOMORROW
    // tier with due_date=tomorrow. Close the panel + reload the
    // board so the new card renders.
    const dupBtn = document.getElementById("detailDuplicate");
    if (dupBtn) {
        dupBtn.addEventListener("click", async () => {
            const id = document.getElementById("detailId").value;
            if (!id) return;
            dupBtn.disabled = true;
            dupBtn.textContent = "…";
            try {
                await apiFetch(`/api/tasks/${id}/duplicate`, { method: "POST" });
                taskDetailClose();
                await loadTasks();
            } catch (err) {
                alert("Couldn't duplicate task: " + (err && err.message ? err.message : err));
                dupBtn.disabled = false;
                dupBtn.textContent = "⧉ Copy to tomorrow";
            }
        });
    }
    // Backlog #25: Cancel button — sets status=cancelled and saves the
    // optional reason from the inline input. Different from Complete.
    document.getElementById("detailCancel").addEventListener("click", () => {
        const id = document.getElementById("detailId").value;
        if (id) {
            const reason = document.getElementById("detailCancellationReason").value.trim();
            taskDetailClose();
            taskCancel(id, reason);
        }
    });
    document.getElementById("addChecklistItem").addEventListener("click", () => {
        taskDetailAddChecklistRow("", false);
    });
    setupAddSubtask();
}

function taskDetailOpen(task) {
    document.getElementById("detailId").value = task.id;
    document.getElementById("detailTitle").value = task.title;
    document.getElementById("detailTier").value = task.tier;
    document.getElementById("detailType").value = task.type;
    // #98 (PR32): scope the project dropdown to projects matching this
    // task's type. Repopulating BEFORE setting detailProject's value
    // ensures the value persists if it's a valid match (and gets
    // dropped to "" if the task somehow has a cross-type project_id —
    // which would be a data anomaly, but at least we surface it).
    taskDetailPopulateProjects(task.type);
    document.getElementById("detailProject").value = task.project_id || "";
    document.getElementById("detailDueDate").value = task.due_date || "";
    document.getElementById("detailGoal").value = task.goal_id || "";
    const urlInput = document.getElementById("detailUrl");
    const urlOpen = document.getElementById("detailUrlOpen");
    urlInput.value = task.url || "";
    if (task.url) {
        urlOpen.href = task.url;
        urlOpen.style.display = "";
    } else {
        urlOpen.style.display = "none";
    }
    // PR36 audit TD-2: assignment overwrites, addEventListener accumulates.
    // Was leaking a fresh handler on every panel open — same listener-
    // accumulation class as the PR28 calendar fix. .oninput = ...
    // pattern is also used in _setupParentPicker (line ~1962).
    urlInput.oninput = () => {
        const v = urlInput.value.trim();
        if (v.startsWith("http://") || v.startsWith("https://")) {
            urlOpen.href = v;
            urlOpen.style.display = "";
        } else {
            urlOpen.style.display = "none";
        }
    };

    document.getElementById("detailNotes").value = task.notes || "";

    // Cancellation reason field — visible only when this task is cancelled
    // OR when the user clicks the Cancel button below. Both modes write
    // into the same input, so we always sync its value here.
    const cancelBlock = document.getElementById("detailCancellation");
    const reasonInput = document.getElementById("detailCancellationReason");
    if (cancelBlock && reasonInput) {
        reasonInput.value = task.cancellation_reason || "";
        cancelBlock.style.display = task.status === "cancelled" ? "" : "none";
    }

    // Show/hide project selector based on type
    taskDetailToggleProject(task.type);

    // Repeat
    taskDetailPopulateRepeat(task);

    // Checklist
    const container = document.getElementById("checklistItems");
    container.innerHTML = "";
    if (task.checklist) {
        for (const item of task.checklist) {
            taskDetailAddChecklistRow(item.text, item.checked);
        }
    }

    // Subtasks section — only for non-subtask tasks (one level deep)
    const subtaskSection = document.getElementById("subtaskSection");
    const subtaskList = document.getElementById("subtaskItems");
    subtaskList.innerHTML = "";
    // Backlog #30: parent-link section — inverse toggle of subtasks
    const parentLinkSection = document.getElementById("parentLinkSection");
    if (task.parent_id) {
        subtaskSection.style.display = "none";
        if (parentLinkSection) {
            parentLinkSection.style.display = "";
            taskDetailPopulateParentLink(task.parent_id);
        }
    } else {
        subtaskSection.style.display = "";
        if (parentLinkSection) parentLinkSection.style.display = "none";
        taskDetailLoadSubtasks(task.id);
    }

    // #78 (2026-04-26): parent picker — visible unless this task has its
    // own subtasks (one-level-deep model rule).
    _setupParentPicker(task);

    // Meta
    document.getElementById("detailMeta").innerHTML =
        `Created: ${new Date(task.created_at).toLocaleDateString()}<br>` +
        `Updated: ${new Date(task.updated_at).toLocaleDateString()}`;

    document.getElementById("detailOverlay").style.display = "";
}

function taskDetailToggleProject(type) {
    taskDetailPopulateProjects(type);
}

// #117 (PR53/PR56): UI mirror of the server-side #77 cascade. When
// user picks a project, look up its goal_id and pre-set the Goal
// dropdown. Pure logic in filter_helpers.projectCascadeGoalId
// (Jest-tested per anti-pattern #3); this is the DOM-glue layer.
function taskDetailProjectChanged(projectId) {
    const goalSel = document.getElementById("detailGoal");
    if (!goalSel) return;
    const allowed = new Set(Array.from(goalSel.options).map((o) => o.value));
    const newGoalId = window.filterHelpers.projectCascadeGoalId(
        projectId, allProjects, allowed,
    );
    if (newGoalId) goalSel.value = newGoalId;
}

function taskDetailClose() {
    document.getElementById("detailOverlay").style.display = "none";
}

function taskDetailAddChecklistRow(text, checked) {
    const container = document.getElementById("checklistItems");
    const row = document.createElement("div");
    row.className = "checklist-item";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    row.appendChild(cb);

    const input = document.createElement("input");
    input.type = "text";
    input.value = text;
    input.placeholder = "Checklist item…";
    row.appendChild(input);

    // #120 (PR57): per-row voice input. attachVoiceButton wires the
    // SpeechRecognition lifecycle and falls back to hiding the button
    // when the API is unavailable. New rows attach immediately;
    // existing rows on panel re-render are re-created so they get
    // the same treatment.
    const voiceBtn = document.createElement("button");
    voiceBtn.type = "button";
    voiceBtn.className = "icon-btn voice-btn";
    voiceBtn.textContent = "🎤";
    voiceBtn.title = "Voice input";
    if (window.voiceInput) {
        window.voiceInput.attachVoiceButton(voiceBtn, input);
    }
    row.appendChild(voiceBtn);

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "remove-item";
    rm.textContent = "✕";
    rm.addEventListener("click", () => row.remove());
    row.appendChild(rm);

    container.appendChild(row);
}

// #78 (2026-04-26): parent task typeahead picker. Populates from
// allTasks (already loaded). Excludes: this task itself, this task's
// existing subtasks, and tasks that already have a parent (the model
// is one-level-deep — subtasks can't be parents).
function _setupParentPicker(task) {
    const section = document.getElementById("parentPickerSection");
    const input = document.getElementById("parentPickerInput");
    const hidden = document.getElementById("parentPickerId");
    const results = document.getElementById("parentPickerResults");
    const current = document.getElementById("parentPickerCurrent");
    if (!section || !input) return;

    // Hide if this task has subtasks (can't be a child of anything).
    // taskDetailLoadSubtasks renders into #subtaskItems async, so check
    // the cheaper proxy: this task has no parent_id but might have
    // children. Treat "has children" as "this is itself a parent" and
    // hide the picker — preserves the one-level-deep model rule.
    const hasChildren = (typeof allTasks !== "undefined") && allTasks.some(
        (t) => t.parent_id === task.id,
    );
    if (hasChildren) {
        section.style.display = "none";
        return;
    }
    section.style.display = "";

    // Reset state.
    input.value = "";
    hidden.value = task.parent_id || "";
    results.style.display = "none";
    results.innerHTML = "";

    // Show current parent (if any) as a chip with a Clear button.
    function renderCurrent() {
        if (!hidden.value) {
            current.style.display = "none";
            current.innerHTML = "";
            return;
        }
        const parent = (typeof allTasks !== "undefined")
            && allTasks.find((t) => t.id === hidden.value);
        const label = parent ? parent.title : "(unknown)";
        current.innerHTML = "";
        const chip = document.createElement("span");
        chip.className = "parent-picker-chip";
        chip.textContent = "Parent: " + label;
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "parent-picker-clear";
        clear.textContent = "✕";
        clear.title = "Remove parent";
        clear.addEventListener("click", () => {
            hidden.value = "";
            renderCurrent();
        });
        current.appendChild(chip);
        current.appendChild(clear);
        current.style.display = "";
    }
    renderCurrent();

    // Typeahead: as user types, filter allTasks by title contains.
    function searchAndShow() {
        const q = input.value.trim().toLowerCase();
        results.innerHTML = "";
        if (q.length < 2) {
            results.style.display = "none";
            return;
        }
        const matches = (typeof allTasks !== "undefined" ? allTasks : [])
            .filter((t) => t.id !== task.id
                && !t.parent_id
                && t.title.toLowerCase().includes(q))
            .slice(0, 10);
        if (matches.length === 0) {
            results.style.display = "none";
            return;
        }
        for (const m of matches) {
            const item = document.createElement("div");
            item.className = "parent-picker-result";
            item.textContent = m.title;
            item.title = m.title;
            item.addEventListener("click", () => {
                hidden.value = m.id;
                input.value = "";
                results.style.display = "none";
                renderCurrent();
            });
            results.appendChild(item);
        }
        results.style.display = "";
    }
    input.oninput = searchAndShow;
    input.onfocus = searchAndShow;
    input.onblur = () => setTimeout(() => { results.style.display = "none"; }, 200);
}

function taskDetailPopulateGoals() {
    const sel = document.getElementById("detailGoal");
    while (sel.options.length > 1) sel.remove(1);
    for (const goal of allGoals) {
        const opt = document.createElement("option");
        opt.value = goal.id;
        opt.textContent = `${goal.title} (${goal.category})`;
        sel.appendChild(opt);
    }
}

function taskDetailPopulateProjects(filterType) {
    const sel = document.getElementById("detailProject");
    if (!sel) return;
    const currentValue = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    const filtered = filterType
        ? allProjects.filter((p) => p.type === filterType)
        : allProjects;
    for (const p of filtered) {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        sel.appendChild(opt);
    }
    // Restore selection if it's still in the filtered list
    if (currentValue && filtered.some((p) => p.id === currentValue)) {
        sel.value = currentValue;
    }
}

function taskDetailInitRepeat() {
    // Populate day-of-month dropdown (1-31)
    const domSel = document.getElementById("detailRepeatDayOfMonth");
    if (domSel && domSel.options.length === 0) {
        for (let i = 1; i <= 31; i++) {
            const opt = document.createElement("option");
            opt.value = String(i);
            opt.textContent = String(i);
            domSel.appendChild(opt);
        }
    }
}

function taskDetailRepeatChanged() {
    const freq = document.getElementById("detailRepeat").value;
    document.getElementById("repeatWeeklyField").style.display =
        freq === "weekly" ? "" : "none";
    document.getElementById("repeatMonthlyDateField").style.display =
        freq === "monthly_date" ? "" : "none";
    document.getElementById("repeatMonthlyNthField").style.display =
        freq === "monthly_nth_weekday" ? "" : "none";
    // #101 (PR30): end_date applies to ANY repeat frequency.
    const endField = document.getElementById("repeatEndDateField");
    if (endField) endField.style.display = freq ? "" : "none";
}

function taskDetailPopulateRepeat(task) {
    taskDetailInitRepeat();
    const repeat = task.repeat;
    const sel = document.getElementById("detailRepeat");
    const endInput = document.getElementById("detailRepeatEndDate");
    if (endInput) endInput.value = "";
    if (!repeat) {
        sel.value = "";
    } else {
        sel.value = repeat.frequency || "";
        if (repeat.day_of_week != null) {
            document.getElementById("detailRepeatDay").value = String(repeat.day_of_week);
            document.getElementById("detailRepeatNthDay").value = String(repeat.day_of_week);
        }
        if (repeat.day_of_month != null) {
            document.getElementById("detailRepeatDayOfMonth").value = String(repeat.day_of_month);
        }
        if (repeat.week_of_month != null) {
            document.getElementById("detailRepeatWeekOfMonth").value = String(repeat.week_of_month);
        }
        // #101 (PR30): existing template's sunset date.
        if (endInput && repeat.end_date) endInput.value = repeat.end_date;
    }
    taskDetailRepeatChanged();
}

function taskDetailCollectRepeat() {
    const freq = document.getElementById("detailRepeat").value;
    if (!freq) return null;
    const repeat = { frequency: freq };
    if (freq === "weekly") {
        repeat.day_of_week = parseInt(document.getElementById("detailRepeatDay").value);
    } else if (freq === "monthly_date") {
        repeat.day_of_month = parseInt(document.getElementById("detailRepeatDayOfMonth").value);
    } else if (freq === "monthly_nth_weekday") {
        repeat.week_of_month = parseInt(document.getElementById("detailRepeatWeekOfMonth").value);
        repeat.day_of_week = parseInt(document.getElementById("detailRepeatNthDay").value);
    }
    // #101 (PR30): include the optional sunset date. Empty string → null
    // (clear an existing end_date).
    const endInput = document.getElementById("detailRepeatEndDate");
    if (endInput) {
        repeat.end_date = endInput.value || null;
    }
    return repeat;
}

async function taskDetailSave(e) {
    e.preventDefault();
    const id = document.getElementById("detailId").value;
    if (!id) return;

    // Collect checklist
    const clItems = [];
    document.querySelectorAll("#checklistItems .checklist-item").forEach((row, i) => {
        const text = row.querySelector('input[type="text"]').value.trim();
        const checked = row.querySelector('input[type="checkbox"]').checked;
        if (text) {
            clItems.push({ id: String(i), text, checked });
        }
    });

    const rawUrl = document.getElementById("detailUrl").value.trim();
    const data = buildTaskDetailPayload({
        title: document.getElementById("detailTitle").value.trim(),
        tier: document.getElementById("detailTier").value,
        type: document.getElementById("detailType").value,
        project_id: document.getElementById("detailProject").value,
        due_date: document.getElementById("detailDueDate").value,
        goal_id: document.getElementById("detailGoal").value,
        url: rawUrl,
        notes: document.getElementById("detailNotes").value,
        checklist: clItems,
        repeat: taskDetailCollectRepeat(),
    });
    // #78: parent_id from the typeahead picker (separate field — payload
    // builder doesn't know about parent yet, so wire it in directly).
    const parentPickerEl = document.getElementById("parentPickerId");
    if (parentPickerEl) {
        const pid = parentPickerEl.value || null;
        // Only send when present or when explicitly cleared on a task that
        // had a parent before; the API treats absence as no-change.
        data.parent_id = pid;
    }

    try {
        await apiFetch(`${API}/${id}`, {
            method: "PATCH",
            body: JSON.stringify(data),
        });
        await loadTasks();
        taskDetailClose();
    } catch (err) {
        alert("Save failed: " + err.message);
    }
}

// --- Subtasks in detail panel ------------------------------------------------

// Backlog #30: render a clickable link to the parent task inside the
// detail panel of a subtask. Looks up the parent in the client-side
// ``allTasks`` cache first (covers 99% of cases — parent is usually
// active), falls back to a single-task API fetch so archived /
// cancelled / deleted parents still render.
async function taskDetailPopulateParentLink(parentId) {
    const body = document.getElementById("parentLinkBody");
    if (!body) return;
    body.innerHTML = "";  // clear before populate

    let parent = allTasks.find((t) => t.id === parentId);
    if (!parent) {
        // Fallback for non-active parents not in the board cache.
        try {
            parent = await apiFetch(`${API}/${parentId}`);
        } catch {
            body.textContent = "Parent task not found.";
            return;
        }
    }

    const link = document.createElement("a");
    link.href = "#";
    link.className = "parent-link";
    link.textContent = parent.title;
    link.addEventListener("click", (e) => {
        e.preventDefault();
        taskDetailOpen(parent);
    });
    body.appendChild(link);

    // Status badge if the parent is NOT active — visual signal that
    // clicking opens something the user has since marked done /
    // dropped / recycled. Avoids surprise when the detail panel
    // shows a "dead" task.
    if (parent.status && parent.status !== "active") {
        const badge = document.createElement("span");
        badge.className = "badge parent-link-status parent-link-status-" + parent.status;
        const labels = {
            archived: "completed",
            cancelled: "cancelled",
            deleted: "deleted",
        };
        badge.textContent = labels[parent.status] || parent.status;
        body.appendChild(document.createTextNode(" "));
        body.appendChild(badge);
    }
}


async function taskDetailLoadSubtasks(parentId) {
    const list = document.getElementById("subtaskItems");
    list.innerHTML = "";
    let subtasks;
    try {
        subtasks = await apiFetch(`${API}/${parentId}/subtasks`);
    } catch {
        return;
    }
    for (const sub of subtasks) {
        const row = document.createElement("div");
        row.className = "subtask-row";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.title = "Complete subtask";
        cb.addEventListener("change", async () => {
            await apiFetch(`${API}/${sub.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "archived" }),
            });
            await loadTasks();
            taskDetailLoadSubtasks(parentId);
        });
        row.appendChild(cb);

        const titleEl = document.createElement("span");
        titleEl.className = "subtask-title";
        titleEl.textContent = sub.title;
        titleEl.addEventListener("click", () => {
            const full = allTasks.find((t) => t.id === sub.id) || sub;
            taskDetailOpen(full);
        });
        row.appendChild(titleEl);

        const tierBadge = document.createElement("span");
        tierBadge.className = "badge badge-subtask-tier";
        tierBadge.textContent = tierLabel(sub.tier);
        row.appendChild(tierBadge);

        list.appendChild(row);
    }
}

function setupAddSubtask() {
    const btn = document.getElementById("addSubtaskBtn");
    const input = document.getElementById("subtaskInput");
    if (!btn || !input) return;

    btn.addEventListener("click", addSubtask);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            addSubtask();
        }
    });
}

async function addSubtask() {
    const input = document.getElementById("subtaskInput");
    const title = input.value.trim();
    if (!title) return;

    const parentId = document.getElementById("detailId").value;
    if (!parentId) return;

    const parentTask = allTasks.find((t) => t.id === parentId);
    const type = parentTask ? parentTask.type : "work";
    const goalId = parentTask ? parentTask.goal_id : null;
    const projectId = parentTask ? parentTask.project_id : null;

    try {
        const body = {
            title,
            type,
            tier: "inbox",
            parent_id: parentId,
        };
        if (goalId) body.goal_id = goalId;
        if (projectId) body.project_id = projectId;
        await apiFetch(API, {
            method: "POST",
            body: JSON.stringify(body),
        });
        input.value = "";
        await loadTasks();
        taskDetailLoadSubtasks(parentId);
    } catch (err) {
        alert("Failed to add subtask: " + err.message);
    }
}

// --- Bulk select & batch operations (backlog #21) ----------------------------
//
// State machine:
//   - Off (default): no body class, no checkboxes visible, no toolbar
//   - On + 0 selected: body has .bulk-select-mode, checkboxes visible
//                       on every card, toolbar HIDDEN (nothing to act on)
//   - On + ≥1 selected: same as above + toolbar visible at bottom
//
// Selection lives in the DOM (one checkbox per card). We don't keep a
// JS array of ids — a simple querySelectorAll is the source of truth.
// Re-renders (loadTasks) clear selection naturally.

function getBulkSelectedIds() {
    return Array.from(
        document.querySelectorAll(".bulk-select-check:checked")
    ).map((cb) => cb.closest(".task-card").dataset.id);
}

function updateBulkToolbar() {
    const tb = document.getElementById("bulkToolbar");
    if (!tb) return;
    const ids = getBulkSelectedIds();
    const countEl = document.getElementById("bulkSelectedCount");
    if (countEl) countEl.textContent = String(ids.length);
    tb.style.display = ids.length > 0 ? "" : "none";
}

function setBulkSelectMode(on) {
    document.body.classList.toggle("bulk-select-mode", on);
    const toggle = document.getElementById("bulkSelectToggle");
    if (toggle) toggle.classList.toggle("active", on);
    if (!on) {
        // Turning off — clear selection, hide toolbar
        document.querySelectorAll(".bulk-select-check:checked").forEach((cb) => {
            cb.checked = false;
            cb.closest(".task-card").classList.remove("bulk-selected");
        });
    }
    updateBulkToolbar();
}

function clearBulkSelection() {
    document.querySelectorAll(".bulk-select-check:checked").forEach((cb) => {
        cb.checked = false;
        cb.closest(".task-card").classList.remove("bulk-selected");
    });
    updateBulkToolbar();
    // #71: clearing selection also drops any staged-but-unapplied changes.
    if (typeof clearBulkPending === "function") clearBulkPending();
}

// Helper: build an absolutely-positioned dropdown anchored under a button.
// Clamps the horizontal position so the dropdown never overflows the
// viewport — important on mobile where buttons can be close to the
// right edge of the screen.
function showBulkDropdown(anchor, items) {
    document.querySelectorAll(".bulk-dropdown").forEach((d) => d.remove());
    const dd = document.createElement("div");
    dd.className = "bulk-dropdown";
    const rect = anchor.getBoundingClientRect();
    dd.style.position = "fixed";
    dd.style.bottom = (window.innerHeight - rect.top + 4) + "px";
    // Append first so we can measure dd.offsetWidth, then clamp.
    document.body.appendChild(dd);
    items.forEach(({ label, onClick }) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        b.addEventListener("click", () => {
            dd.remove();
            onClick();
        });
        dd.appendChild(b);
    });
    // Clamp horizontal position. Default is to anchor under the click
    // target; if that overflows the viewport on the right, slide left.
    const ddWidth = dd.offsetWidth;
    let left = rect.left;
    const margin = 8;
    if (left + ddWidth > window.innerWidth - margin) {
        left = window.innerWidth - ddWidth - margin;
    }
    if (left < margin) left = margin;
    dd.style.left = left + "px";
    // Close on outside click
    setTimeout(() => {
        document.addEventListener("click", function close(ev) {
            if (!dd.contains(ev.target) && ev.target !== anchor) {
                dd.remove();
                document.removeEventListener("click", close);
            }
        });
    }, 0);
}

async function bulkPatch(updates, successMessage) {
    const ids = getBulkSelectedIds();
    if (ids.length === 0) return;
    try {
        const resp = await apiFetch("/api/tasks/bulk", {
            method: "PATCH",
            body: JSON.stringify({ task_ids: ids, updates }),
        });
        const errCount = (resp.errors || []).length;
        const notFound = (resp.not_found || []).length;
        if (errCount || notFound) {
            const parts = [`${resp.updated} updated`];
            if (notFound) parts.push(`${notFound} not found`);
            if (errCount) parts.push(`${errCount} validation error(s)`);
            alert(parts.join(" — "));
        } else if (successMessage) {
            // Quiet success — no popup
        }
    } catch (err) {
        alert("Bulk update failed: " + (err.message || err));
        return;
    }
    clearBulkSelection();
    await loadTasks();
}

async function bulkDelete() {
    const ids = getBulkSelectedIds();
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} task(s)? They will land in the recycle bin.`)) return;
    // Delete iterates per-task — keeps recycle-bin batch_id semantics
    // identical to single deletes (no special bulk-delete endpoint).
    let failed = 0;
    await Promise.all(
        ids.map((id) =>
            apiFetch(`${API}/${id}`, { method: "DELETE" }).catch(() => { failed += 1; })
        )
    );
    if (failed) alert(`${failed} delete(s) failed`);
    clearBulkSelection();
    await loadTasks();
}

// #71 (2026-04-26): staged bulk-edit. Type/Tier/Due/Goal/Project
// dropdown picks STAGE the change in `bulkPending` instead of firing
// a PATCH immediately. The user can stage multiple fields, then click
// Apply to send a single multi-field PATCH. Selection persists between
// stage operations. Status (archive/cancel/active) + Delete remain
// immediate (commit-style; no clear value in staging them).

const _BULK_PENDING_LABELS = {
    type:                 "Type",
    tier:                 "Tier",
    due_date:             "Due",
    goal_id:              "Goal",
    project_id:           "Project",
};

let bulkPending = {};

function _displayValueForBulk(field, value) {
    if (value === null || value === "") return "(none)";
    if (field === "tier" && typeof tierLabel === "function") return tierLabel(value);
    if (field === "type") return value === "work" ? "Work" : "Personal";
    if (field === "goal_id") {
        const g = (typeof allGoals !== "undefined" ? allGoals : []).find((x) => x.id === value);
        return g ? g.title : "(unknown)";
    }
    if (field === "project_id") {
        const p = (typeof allProjects !== "undefined" ? allProjects : []).find((x) => x.id === value);
        return p ? p.name : "(unknown)";
    }
    return String(value);
}

function stageBulkChange(field, value) {
    bulkPending[field] = value;
    renderBulkPending();
}

function clearBulkPending() {
    bulkPending = {};
    renderBulkPending();
}

function renderBulkPending() {
    const wrap = document.getElementById("bulkPending");
    const list = document.getElementById("bulkPendingList");
    if (!wrap || !list) return;
    const keys = Object.keys(bulkPending);
    if (keys.length === 0) {
        wrap.style.display = "none";
        list.innerHTML = "";
        return;
    }
    wrap.style.display = "";
    list.innerHTML = "";
    for (const k of keys) {
        const chip = document.createElement("span");
        chip.className = "bulk-pending-chip";
        const label = _BULK_PENDING_LABELS[k] || k;
        chip.textContent = `${label}: ${_displayValueForBulk(k, bulkPending[k])}`;
        // Click chip to remove that staged change.
        chip.title = "Click to remove";
        chip.addEventListener("click", () => {
            delete bulkPending[k];
            renderBulkPending();
        });
        list.appendChild(chip);
    }
}

async function applyStagedChanges() {
    if (Object.keys(bulkPending).length === 0) return;
    const updates = { ...bulkPending };
    bulkPending = {};
    renderBulkPending();
    await bulkPatch(updates);
}

// Wire up the toggle + toolbar buttons (deferred to DOMContentLoaded
// because the static HTML elements need to exist when listeners attach)
function initBulkSelect() {
    const toggle = document.getElementById("bulkSelectToggle");
    if (!toggle) return;  // not on this page
    toggle.addEventListener("click", () => {
        const on = !document.body.classList.contains("bulk-select-mode");
        setBulkSelectMode(on);
    });

    const clearBtn = document.getElementById("bulkClearSelection");
    if (clearBtn) clearBtn.addEventListener("click", clearBulkSelection);

    const typeBtn = document.getElementById("bulkActionType");
    if (typeBtn) typeBtn.addEventListener("click", () => {
        showBulkDropdown(typeBtn, [
            { label: "Work", onClick: () => stageBulkChange("type", "work") },
            { label: "Personal", onClick: () => stageBulkChange("type", "personal") },
        ]);
    });

    const tierBtn = document.getElementById("bulkActionTier");
    if (tierBtn) tierBtn.addEventListener("click", () => {
        showBulkDropdown(tierBtn, [
            { label: "Today", onClick: () => stageBulkChange("tier", "today") },
            { label: "Tomorrow", onClick: () => stageBulkChange("tier", "tomorrow") },
            { label: "This Week", onClick: () => stageBulkChange("tier", "this_week") },
            { label: "Next Week", onClick: () => stageBulkChange("tier", "next_week") },
            { label: "Backlog", onClick: () => stageBulkChange("tier", "backlog") },
            { label: "Freezer", onClick: () => stageBulkChange("tier", "freezer") },
            { label: "Inbox", onClick: () => stageBulkChange("tier", "inbox") },
        ]);
    });

    const goalBtn = document.getElementById("bulkActionGoal");
    if (goalBtn) goalBtn.addEventListener("click", () => {
        const items = [{ label: "(no goal)", onClick: () => stageBulkChange("goal_id", null) }];
        for (const g of allGoals) {
            items.push({ label: g.title, onClick: () => stageBulkChange("goal_id", g.id) });
        }
        // #59 (2026-04-25): if there are no goals, distinguish "still
        // loading" from "truly empty." User reported a delay where the
        // dropdown was misleadingly empty for a few seconds before goals
        // loaded — happens on a slow network or cold container.
        if (allGoals.length === 0) {
            const msg = goalsLoaded
                ? "(no goals available — create one on Goals page)"
                : "(loading goals… try again in a moment)";
            items.push({ label: msg, onClick: () => {} });
        }
        showBulkDropdown(goalBtn, items);
    });

    const projBtn = document.getElementById("bulkActionProject");
    if (projBtn) projBtn.addEventListener("click", () => {
        // #98 (PR32): scope to projects matching the active type tab.
        // In "all" view, show every project so the user isn't blocked
        // when picking across types.
        const scoped = (currentView === "all")
            ? allProjects
            : allProjects.filter((p) => p.type === currentView);
        const items = [{ label: "(no project)", onClick: () => stageBulkChange("project_id", null) }];
        for (const p of scoped) {
            items.push({ label: p.name, onClick: () => stageBulkChange("project_id", p.id) });
        }
        if (scoped.length === 0) {
            const msg = projectsLoaded
                ? `(no ${currentView === "all" ? "" : currentView + " "}projects available — create one on Projects page)`
                : "(loading projects… try again in a moment)";
            items.push({ label: msg, onClick: () => {} });
        }
        showBulkDropdown(projBtn, items);
    });

    const statusBtn = document.getElementById("bulkActionStatus");
    if (statusBtn) statusBtn.addEventListener("click", () => {
        showBulkDropdown(statusBtn, [
            {
                label: "Mark complete",
                onClick: () => {
                    const n = getBulkSelectedIds().length;
                    if (n && confirm(`Mark ${n} task(s) complete?`)) {
                        bulkPatch({ status: "archived" });
                    }
                },
            },
            {
                label: "Mark cancelled",
                onClick: () => {
                    const n = getBulkSelectedIds().length;
                    if (!n) return;
                    // Single shared reason for the whole batch — keeps the
                    // bulk flow simple. Per-task reasons can still be set
                    // by opening individual cards in the detail panel.
                    const reason = prompt(
                        `Mark ${n} task(s) cancelled. Optional reason (Cancel to abort):`,
                        "",
                    );
                    if (reason === null) return;
                    bulkPatch({
                        status: "cancelled",
                        cancellation_reason: reason.trim() || null,
                    });
                },
            },
            {
                label: "Mark active",
                onClick: () => bulkPatch({ status: "active" }),
            },
        ]);
    });

    const dueDateBtn = document.getElementById("bulkActionDueDate");
    if (dueDateBtn) dueDateBtn.addEventListener("click", () => {
        // Local-time YYYY-MM-DD so "Today" matches the user's calendar
        // day, not UTC's. Avoids the off-by-one bug where a 9pm PT user
        // gets "tomorrow" because UTC has rolled over.
        const fmt = (d) => {
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${y}-${m}-${day}`;
        };
        const today = new Date();
        const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
        const inAWeek = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
        showBulkDropdown(dueDateBtn, [
            { label: "Today", onClick: () => stageBulkChange("due_date", fmt(today)) },
            { label: "Tomorrow", onClick: () => stageBulkChange("due_date", fmt(tomorrow)) },
            { label: "In 1 week", onClick: () => stageBulkChange("due_date", fmt(inAWeek)) },
            { label: "Pick a date…", onClick: () => promptCustomDate(dueDateBtn) },
            { label: "Clear (no due date)", onClick: () => stageBulkChange("due_date", null) },
        ]);
    });

    const deleteBtn = document.getElementById("bulkActionDelete");
    if (deleteBtn) deleteBtn.addEventListener("click", bulkDelete);

    // #71: Apply / Clear-pending wiring
    const applyBtn = document.getElementById("bulkApplyChanges");
    if (applyBtn) applyBtn.addEventListener("click", applyStagedChanges);
    const clearPendingBtn = document.getElementById("bulkClearPending");
    if (clearPendingBtn) clearPendingBtn.addEventListener("click", clearBulkPending);
}

// "Pick a date…" — show an inline native date input near the Due-date
// button. Native pickers are platform-correct (calendar on touch
// devices, keyboard input on desktop). Confirms via Enter / blur,
// dismisses on Escape.
function promptCustomDate(anchor) {
    document.querySelectorAll(".bulk-date-pick").forEach((d) => d.remove());
    const wrap = document.createElement("div");
    wrap.className = "bulk-dropdown bulk-date-pick";
    const rect = anchor.getBoundingClientRect();
    wrap.style.position = "fixed";
    wrap.style.bottom = (window.innerHeight - rect.top + 4) + "px";

    const input = document.createElement("input");
    input.type = "date";
    input.className = "bulk-date-input";
    wrap.appendChild(input);

    const ok = document.createElement("button");
    ok.type = "button";
    ok.textContent = "Apply";
    ok.addEventListener("click", () => {
        if (!input.value) return;
        wrap.remove();
        stageBulkChange("due_date", input.value);  // #71: stage instead of fire
    });
    wrap.appendChild(ok);

    document.body.appendChild(wrap);
    // Clamp horizontal position (same logic as showBulkDropdown)
    const w = wrap.offsetWidth;
    let left = rect.left;
    const margin = 8;
    if (left + w > window.innerWidth - margin) {
        left = window.innerWidth - w - margin;
    }
    if (left < margin) left = margin;
    wrap.style.left = left + "px";
    input.focus();
    setTimeout(() => {
        document.addEventListener("click", function close(ev) {
            if (!wrap.contains(ev.target) && ev.target !== anchor) {
                wrap.remove();
                document.removeEventListener("click", close);
            }
        });
    }, 0);
}

// --- Drag auto-scroll (#87) -------------------------------------------------
//
// When the user drags a card past the top or bottom edge of the
// viewport, scroll the page so the drop target reachable. Standard
// pattern: a single document-level dragover listener checks pointer Y
// vs window edges; if within EDGE_PX of either edge, schedule a
// requestAnimationFrame loop that scrolls until the pointer leaves the
// edge zone or the drag ends. Speed scales with proximity (closer to
// edge = faster scroll).

function _setupDragAutoScroll() {
    var EDGE_PX = 60;       // start scrolling when within this many px of edge
    var MAX_SPEED = 20;     // px per frame at the very edge
    var scrollDir = 0;      // -1 up, 0 idle, +1 down
    var scrollSpeed = 0;    // px per frame
    var rafId = null;

    function frame() {
        if (scrollDir === 0) {
            rafId = null;
            return;
        }
        window.scrollBy(0, scrollDir * scrollSpeed);
        rafId = requestAnimationFrame(frame);
    }

    function start() {
        if (rafId === null) rafId = requestAnimationFrame(frame);
    }

    function stop() {
        scrollDir = 0;
        scrollSpeed = 0;
        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
    }

    document.addEventListener("dragover", function (e) {
        // Only act on actual drags (dataTransfer present).
        if (!e.dataTransfer) return;
        var y = e.clientY;
        var h = window.innerHeight;
        if (y < EDGE_PX) {
            scrollDir = -1;
            // Closer to top = faster (1.0 at edge, 0 at EDGE_PX away).
            scrollSpeed = Math.max(2, Math.round(MAX_SPEED * (1 - y / EDGE_PX)));
            start();
        } else if (y > h - EDGE_PX) {
            scrollDir = 1;
            scrollSpeed = Math.max(2, Math.round(MAX_SPEED * (1 - (h - y) / EDGE_PX)));
            start();
        } else {
            stop();
        }
    }, { passive: true });

    document.addEventListener("dragend", stop);
    document.addEventListener("drop", stop);
}

// --- Boot --------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
    init();
    initBulkSelect();
    _setupDragAutoScroll();
    // #92 (PR25): filter bars are page-agnostic. The main board pulls
    // allGoals + allProjects via init(); other pages that host the
    // filter bars (#completed, /tier/<name>) need their own load.
    const goalBar = document.getElementById("goalFilterBar");
    const projBar = document.getElementById("projectFilterBar");
    const isTasksPage = !!document.getElementById("detailOverlay");
    if ((goalBar || projBar) && !isTasksPage) {
        // init() already loaded these on the tasks page; avoid a double-fetch.
        if (goalBar) loadGoals();
        if (projBar) loadProjects();
    } else {
        if (goalBar) renderGoalFilter();
        if (projBar) renderProjectFilter();
    }
    // Also reflect the persisted view tab as active on whichever page hosts it.
    document.querySelectorAll(".view-filter-btn").forEach((tab) => {
        if (tab.dataset.view === currentView) tab.classList.add("active");
        else tab.classList.remove("active");
    });
    // #107 (PR42): wire the search bar wherever it appears.
    renderSearchBar();

    // #116 (PR54): voice-to-text on any field with a sibling
    // .voice-btn[data-voice-target]. attachVoiceButton handles the
    // Speech API wiring + falls back to hiding the button when the
    // API isn't available (Firefox, older browsers).
    if (window.voiceInput) {
        document.querySelectorAll(".voice-btn[data-voice-target]").forEach((btn) => {
            const target = document.getElementById(btn.dataset.voiceTarget);
            if (target) window.voiceInput.attachVoiceButton(btn, target);
        });
    }

    // #109 (PR44): multi-device stale state. allTasks is loaded ONCE on
    // page boot — if the user changes a task on mobile, desktop has no
    // idea until they manually reload. Refresh whenever the tab becomes
    // visible again (visibilitychange fires when switching tabs/apps).
    // Throttled to once every 10s so the cron / autosave path doesn't
    // hammer /api/tasks if the user wiggles between tabs.
    let _lastVisibleRefresh = 0;
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        const now = Date.now();
        if (now - _lastVisibleRefresh < 10_000) return;
        _lastVisibleRefresh = now;
        // loadTasks is the entry point on the main board / tier-detail
        // pages. loadCompletedTasks + loadCancelledTasks pages have their
        // own boot path; they call loadX directly. Defensive: only call
        // these if they're defined on this page (subpages don't all
        // export them via the global scope).
        if (typeof loadTasks === "function") loadTasks();
        if (typeof loadCompletedTasks === "function") loadCompletedTasks();
        if (typeof loadCancelledTasks === "function") loadCancelledTasks();
        // Also re-pull goals + projects so a goal/project added on
        // another device shows up in the dropdowns.
        if (typeof loadGoals === "function") loadGoals();
        if (typeof loadProjects === "function") loadProjects();
        // PR46 #111: ALSO ask the SW to check for a newer sw.js. The
        // browser's auto-update poll runs at most once per ~24h, so a
        // long-lived tab opened yesterday never sees today's deploy
        // until the user hard-refreshes. Calling reg.update() forces
        // a fetch of /sw.js — if the bytes changed (CACHE_VERSION
        // bumped), it installs the new SW. base.html's existing
        // updatefound + statechange + skipWaiting + reload handshake
        // then auto-applies it (gated on userIsBusy so the user isn't
        // yanked mid-edit).
        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.getRegistration().then((reg) => {
                if (reg && typeof reg.update === "function") {
                    reg.update().catch(() => { /* offline / network blip — silent */ });
                }
            }).catch(() => { /* private mode etc. */ });
        }
    });

    // PR52 #115: proactive polling for freshness. User-flagged: "is
    // there no way to simply keep the page fresh?" — visibilitychange
    // only fires on tab switch, doesn't help when the user is actively
    // looking at the page while another device makes changes. Poll
    // every 60s while the tab is visible. Skipped while document is
    // hidden (no point fetching when the user can't see results).
    // Skipped if the user is mid-input (active typing) so a re-render
    // doesn't yank focus from the capture bar / detail panel.
    function _isUserBusy() {
        const el = document.activeElement;
        if (!el) return false;
        const tag = (el.tagName || "").toUpperCase();
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
        if (el.isContentEditable) return true;
        return false;
    }
    let _pollLast = Date.now();
    setInterval(() => {
        if (document.visibilityState !== "visible") return;
        if (_isUserBusy()) return;
        const now = Date.now();
        if (now - _pollLast < 55_000) return;  // ~60s with margin for setInterval drift
        _pollLast = now;
        if (typeof loadTasks === "function") loadTasks();
        if (typeof loadCompletedTasks === "function") loadCompletedTasks();
        if (typeof loadCancelledTasks === "function") loadCancelledTasks();
        if (typeof loadGoals === "function") loadGoals();
        if (typeof loadProjects === "function") loadProjects();
    }, 30_000);  // tick every 30s, gated by 55s throttle inside
});
