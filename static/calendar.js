/**
 * /calendar page — 2-week Mon-Sun grid with drop targets per day.
 * Bigger cells than the inline strip on the main board (#73).
 *
 * Tasks already due that day list inside each cell. Drop a draggable
 * task card here to set its due_date (auto-routes tier per #74).
 *
 * #218 (2026-05-24): Sunday was originally excluded per the #72 Mon-Sat
 * design (Sunday was the planning/rest pivot day with no panel home).
 * User-reported: "missing sunday and then has taks that i moved to next
 * week listed as yesterday" — the Mon-Sat layout left Sunday-dated tasks
 * with no visible cell AND the off-by-one made it hard to drag onto next
 * week from a Sunday viewpoint. Switched to Mon-Sun ISO week — 14 cells.
 */
(function () {
    "use strict";

    // PR28 audit fix #6: drop handlers read e.dataTransfer.getData(
    // "text/plain") which can be ANY string (cross-tab drag, external
    // app drag, etc.). Validate it's a UUID before building the PATCH
    // URL so we never send `/api/tasks/<garbage>` to the server (the
    // server would 422, but client-side validation cuts the noise +
    // closes any future URL-injection footgun).
    function _isValidUuid(s) {
        return typeof s === "string"
            && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
    }

    function _isoDate(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
    }

    function _formatHeader(d) {
        return d.toLocaleDateString(undefined, {
            weekday: "long", month: "short", day: "numeric",
        });
    }

    // #219 (2026-05-24): stale-render guard. renderCalendar is async
    // and awaits two apiFetch calls (tasks + recurring previews). If
    // a second renderCalendar fires WHILE the first is mid-await —
    // e.g. the visibilitychange handler (#114) on tab focus + the
    // cross-tab BroadcastChannel subscriber (#214) for a sibling-tab
    // mutation — both calls clear the grid AT THE TOP, then both
    // proceed to append rows AFTER their awaits resolve. Net effect:
    // double-rendered weeks (the user's screenshot showed the current
    // week repeated under the next-week row). The fix: bump a
    // monotonic counter on entry, snapshot it, and bail the DOM-mutate
    // step if a newer call superseded us. The latest call wins —
    // intermediate stale calls drop silently.
    let _renderGeneration = 0;

    async function renderCalendar() {
        const myGen = ++_renderGeneration;
        const grid = document.getElementById("calendarGrid");
        if (!grid) return;

        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const daysSinceMonday = (today.getDay() + 6) % 7;
        const thisMonday = new Date(today.getTime() - daysSinceMonday * 86400000);
        const todayIso = _isoDate(today);

        // Pre-fetch all active tasks so we can list them per day.
        // PR67 #132: use window.apiFetch (stale-tab retry + recovery
        // prompt). On failure, the caller saw an empty calendar with
        // no error feedback — apiFetch surfaces a recovery prompt.
        let tasks = [];
        try {
            tasks = await window.apiFetch("/api/tasks");
        } catch (err) {
            console.error("Failed to load tasks for calendar:", err);
        }
        // #99 (PR34): also pull recurring-template previews for the
        // 12-day window. Each preview = {template_id, title, type,
        // frequency, fire_date, ...}. Render as dashed-border items
        // matching the main board's preview treatment (#32).
        let previews = [];
        const startIso = _isoDate(thisMonday);
        const endIso = _isoDate(new Date(thisMonday.getTime() + 12 * 86400000));
        try {
            previews = await window.apiFetch(
                `/api/recurring/previews?start=${startIso}&end=${endIso}`
            );
        } catch (err) {
            console.error("Failed to load recurring previews:", err);
        }
        // PR29 (#100): tasks in tier=TODAY/TOMORROW without an explicit
        // due_date used to fall through to "Unscheduled" even though
        // they obviously belong on today/tomorrow's cell. Caused the
        // user-reported mismatch ("Update position paper" was on the
        // main board's Tomorrow tier but invisible on /calendar 4/27).
        // Use the tier as a fallback date assignment for the unambiguous
        // tiers; THIS_WEEK / NEXT_WEEK span 6 days so we can't pin them
        // to a single cell — those still go to Unscheduled.
        //
        // #231 (2026-05-25): the bucketing AND the subtask-exclusion are
        // pure logic and live in static/calendar_bucket_helpers.js so
        // Jest can exercise them directly (per CLAUDE.md anti-pattern
        // #3 — don't string-match source; exercise the path).
        const tomorrowIso = _isoDate(new Date(today.getTime() + 86400000));
        const { byDate, unscheduled } = window.calendarBucketHelpers.bucketTasks(
            tasks, todayIso, tomorrowIso,
        );
        // #219: bail if a newer renderCalendar() call started while we
        // were awaiting the apiFetch calls above — its DOM mutation
        // will be more current than ours.
        if (myGen !== _renderGeneration) return;
        // Clear grid HERE (post-await) so the concurrent-call race
        // can't double-append. The grid and unscheduled aside are
        // both populated in the synchronous tail of this function.
        grid.innerHTML = "";
        // #94 (PR26): render an "Unscheduled" side list so the user has
        // a source to drag FROM. Tasks already in cells are also
        // draggable (between days). Without this, /calendar had nothing
        // draggable on the page at all.
        _renderUnscheduled(unscheduled);
        // #99 (PR34): bucket previews by fire_date for the per-cell render.
        const previewsByDate = {};
        for (const p of previews) {
            if (!previewsByDate[p.fire_date]) previewsByDate[p.fire_date] = [];
            previewsByDate[p.fire_date].push(p);
        }

        // #218: 2 weeks × 7 days (Mon-Sun) = 14 cells. Render as 2 rows.
        // Was 12 cells (Mon-Sat per #72) — see header comment.
        for (let week = 0; week < 2; week++) {
            const row = document.createElement("div");
            row.className = "calendar-row";
            for (let dow = 0; dow < 7; dow++) {
                const offset = week * 7 + dow;
                const d = new Date(thisMonday.getTime() + offset * 86400000);
                const iso = _isoDate(d);
                const cell = document.createElement("div");
                cell.className = "calendar-cell";
                if (iso === todayIso) cell.classList.add("calendar-cell-today");
                if (iso < todayIso) cell.classList.add("calendar-cell-past");
                cell.dataset.date = iso;

                const header = document.createElement("div");
                header.className = "calendar-cell-header";
                header.textContent = _formatHeader(d);
                cell.appendChild(header);

                const list = document.createElement("ul");
                list.className = "calendar-cell-tasks";
                const items = byDate[iso] || [];
                for (const t of items) {
                    const li = document.createElement("li");
                    li.textContent = t.title;
                    li.title = t.title;
                    // #94 (PR26): make in-cell tasks draggable so you can
                    // move them between days. Without this the only thing
                    // the user can drag is... nothing — the page has no
                    // tier panels to drag from.
                    li.draggable = true;
                    li.dataset.taskId = t.id;
                    // #153 (2026-05-09): click on a task line opens the
                    // task detail panel. Without this, long titles
                    // truncated with ellipsis had no full-text affordance
                    // and the user couldn't edit a task from /calendar
                    // without leaving the page. Click and drag are
                    // distinguished by the browser natively — a
                    // mousedown→mousemove→mouseup sequence fires
                    // dragstart/dragend, while a fast mousedown→mouseup
                    // (no movement) fires click. Both wired here.
                    li.classList.add("calendar-task-link");
                    li.addEventListener("click", function () {
                        // Detail panel lives on the home page (index.html);
                        // navigate there with ?task=<id> and let app.js'
                        // open-from-url hook do the rest.
                        window.location.href = "/?task=" + encodeURIComponent(t.id);
                    });
                    li.addEventListener("dragstart", function (e) {
                        li.classList.add("dragging");
                        if (e.dataTransfer) {
                            e.dataTransfer.effectAllowed = "move";
                            e.dataTransfer.setData("text/plain", t.id);
                        }
                    });
                    li.addEventListener("dragend", function () {
                        li.classList.remove("dragging");
                    });
                    list.appendChild(li);
                }
                cell.appendChild(list);
                // #99 (PR34): recurring-template previews for this cell —
                // dashed-border items, not draggable, not real tasks
                // (they materialize when the spawn cron runs at 00:05).
                const dayPreviews = previewsByDate[iso] || [];
                if (dayPreviews.length > 0) {
                    const pList = document.createElement("ul");
                    pList.className = "calendar-cell-tasks calendar-cell-previews";
                    for (const p of dayPreviews) {
                        const li = document.createElement("li");
                        li.className = "calendar-preview-item";
                        li.textContent = p.title;
                        li.title = p.title + " (recurring — not yet spawned)";
                        pList.appendChild(li);
                    }
                    cell.appendChild(pList);
                }
                if (items.length === 0 && dayPreviews.length === 0) {
                    const empty = document.createElement("div");
                    empty.className = "calendar-cell-empty";
                    empty.textContent = "Drop here · click to add";
                    cell.appendChild(empty);
                }
                // #156 (2026-05-09): click empty space on a cell →
                // navigate to / with ?new_task_due=<iso>; app.js init
                // hook opens the detail panel in "create new" mode
                // pre-filled with that date. Click handler attached
                // to the cell itself; drop handler stays separate
                // (drop is on .calendar-cell too — distinguish by
                // whether dataTransfer carries a task UUID).
                cell.addEventListener("click", function (e) {
                    // If the click landed on a task line (li), the li's
                    // own click handler navigates to ?task=<id>; this
                    // cell-level handler fires AFTER but we don't want
                    // to re-navigate. Bail when the target is inside
                    // an existing list item.
                    if (e.target.closest("li")) return;
                    window.location.href =
                        "/?new_task_due=" + encodeURIComponent(iso);
                });

                cell.addEventListener("dragover", function (e) {
                    e.preventDefault();
                    cell.classList.add("calendar-cell-hover");
                });
                cell.addEventListener("dragleave", function () {
                    cell.classList.remove("calendar-cell-hover");
                });
                cell.addEventListener("drop", async function (e) {
                    e.preventDefault();
                    cell.classList.remove("calendar-cell-hover");
                    const taskId = e.dataTransfer && e.dataTransfer.getData("text/plain");
                    if (!_isValidUuid(taskId)) return;  // PR28 audit fix #6
                    try {
                        // PR67 #132: window.apiFetch (auto-retry + recovery)
                        await window.apiFetch(`/api/tasks/${taskId}`, {
                            method: "PATCH",
                            body: JSON.stringify({ due_date: iso }),
                        });
                        await renderCalendar();  // refresh after drop
                    } catch (err) {
                        alert("Failed to set due date: " + err.message);
                    }
                });

                row.appendChild(cell);
            }
            grid.appendChild(row);
        }
    }

    // #94 (PR26): render the unscheduled-tasks side panel. Tasks here
    // are draggable onto any calendar day; dropping a calendar task on
    // this panel clears its due_date.
    function _renderUnscheduled(tasks) {
        const panel = document.getElementById("calendarUnscheduled");
        if (!panel) return;
        panel.innerHTML = "";
        const h = document.createElement("h3");
        h.textContent = `Unscheduled (${tasks.length})`;
        panel.appendChild(h);

        const list = document.createElement("ul");
        list.className = "calendar-unscheduled-list";
        if (tasks.length === 0) {
            const empty = document.createElement("li");
            empty.className = "calendar-cell-empty";
            empty.textContent = "Drop a task here to clear its due date";
            list.appendChild(empty);
        }
        for (const t of tasks) {
            const li = document.createElement("li");
            li.textContent = t.title;
            li.title = t.title;
            li.draggable = true;
            li.dataset.taskId = t.id;
            // #231 (2026-05-25): click an unscheduled item to open the
            // task detail panel — mirrors the day-cell item handler
            // (#153). Without this, the user could only drag tasks
            // out of the unscheduled list but never SEE what one was
            // (a long title is ellipsis-truncated in the narrow side
            // panel) or edit it without leaving the page. Click and
            // drag are distinguished by the browser natively: a fast
            // mousedown→mouseup with no movement fires click; movement
            // fires dragstart/dragend instead.
            li.classList.add("calendar-task-link");
            li.addEventListener("click", function () {
                window.location.href = "/?task=" + encodeURIComponent(t.id);
            });
            li.addEventListener("dragstart", function (e) {
                li.classList.add("dragging");
                if (e.dataTransfer) {
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", t.id);
                }
            });
            li.addEventListener("dragend", function () {
                li.classList.remove("dragging");
            });
            list.appendChild(li);
        }
        panel.appendChild(list);

        // PR28 audit fix (high-confidence #1): the panel is a persistent
        // DOM element — _renderUnscheduled used to attach dragover/
        // dragleave/drop listeners on EVERY render, doubling the listener
        // count after every drop. After N drops, a single drop fired
        // N+1 PATCH requests in parallel. Guard with a one-shot flag
        // so we attach exactly once. innerHTML clears can't drop the
        // listeners since they're on the panel itself, not its children.
        if (!panel.dataset.dropAttached) {
            panel.dataset.dropAttached = "1";
            panel.addEventListener("dragover", function (e) {
                e.preventDefault();
                panel.classList.add("calendar-unscheduled-hover");
            });
            panel.addEventListener("dragleave", function () {
                panel.classList.remove("calendar-unscheduled-hover");
            });
            panel.addEventListener("drop", async function (e) {
                e.preventDefault();
                panel.classList.remove("calendar-unscheduled-hover");
                const taskId = e.dataTransfer && e.dataTransfer.getData("text/plain");
                if (!_isValidUuid(taskId)) return;  // PR28 audit fix #6
                try {
                    // PR67 #132: window.apiFetch (auto-retry + recovery)
                    await window.apiFetch(`/api/tasks/${taskId}`, {
                        method: "PATCH",
                        body: JSON.stringify({ due_date: null }),
                    });
                    await renderCalendar();
                } catch (err) {
                    alert("Failed to clear due date: " + err.message);
                }
            });
        }
    }

    function init() {
        renderCalendar();
        // PR51 #114: multi-device + multi-window staleness. PR44 added a
        // visibilitychange refresh in app.js that calls loadTasks() — but
        // that's the main board's loader. /calendar has its own
        // renderCalendar() that re-fetches /api/tasks + /api/recurring/
        // previews; we need a sibling listener here so the calendar
        // pulls fresh state when the user switches back from another
        // tab (e.g. the main board where they just moved a task).
        // Throttled to 10s like the app.js handler.
        let _lastRefresh = 0;
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState !== "visible") return;
            const now = Date.now();
            if (now - _lastRefresh < 10_000) return;
            _lastRefresh = now;
            renderCalendar();
        });
        // #160 (2026-05-09): polling backstop for the case where the
        // user keeps the page foregrounded but state changes happen
        // elsewhere (a phone PWA + a desktop browser editing the
        // same data, or a recurring-spawn cron firing). Every 60s we
        // re-fetch — same throttle as the app.js poll. Cheap, idempotent.
        setInterval(() => {
            if (document.visibilityState === "visible") renderCalendar();
        }, 60_000);
        // Expose renderCalendar so other modules (or DevTools) can
        // force a refresh — useful for the cross-tab consistency
        // story (#214) and for ad-hoc debugging.
        window.renderCalendar = renderCalendar;

        // #214 (2026-05-23): cross-tab sync. Subscribe through the
        // SHARED api_client channel (NOT a new BroadcastChannel
        // instance) — BroadcastChannel's "don't deliver to self"
        // semantics then guarantees a same-tab mutation here does not
        // trigger a re-render that would clobber in-DOM state like
        // bulk-select checkboxes. Other-tab mutations still deliver.
        // 150ms debounce so a burst of PATCHes (bulk apply,
        // auto-categorize Apply-all) collapses to one re-render.
        if (window.apiClient && window.apiClient.subscribeTasksChanged) {
            let _resyncTimer = null;
            window.apiClient.subscribeTasksChanged(() => {
                if (_resyncTimer) clearTimeout(_resyncTimer);
                _resyncTimer = setTimeout(() => {
                    _resyncTimer = null;
                    if (document.visibilityState === "visible") renderCalendar();
                }, 150);
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
