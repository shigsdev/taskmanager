/**
 * /calendar page — 2-week Mon-Sat grid with drop targets per day.
 * Bigger cells than the inline strip on the main board (#73).
 *
 * Tasks already due that day list inside each cell. Drop a draggable
 * task card here to set its due_date (auto-routes tier per #74).
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

    async function renderCalendar() {
        const grid = document.getElementById("calendarGrid");
        if (!grid) return;
        grid.innerHTML = "";

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
        const tomorrowIso = _isoDate(new Date(today.getTime() + 86400000));
        const byDate = {};
        const unscheduled = [];
        for (const t of tasks) {
            let cellDate = t.due_date;
            if (!cellDate) {
                if (t.tier === "today") cellDate = todayIso;
                else if (t.tier === "tomorrow") cellDate = tomorrowIso;
            }
            if (cellDate) {
                if (!byDate[cellDate]) byDate[cellDate] = [];
                byDate[cellDate].push(t);
            } else {
                unscheduled.push(t);
            }
        }
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

        // 2 weeks × 6 days (Mon-Sat per #72) = 12 cells. Render as 2 rows.
        for (let week = 0; week < 2; week++) {
            const row = document.createElement("div");
            row.className = "calendar-row";
            for (let dow = 0; dow < 6; dow++) {
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
                    empty.textContent = "Drop here";
                    cell.appendChild(empty);
                }

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
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
