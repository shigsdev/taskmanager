/**
 * /calendar page — 2-week Mon-Sat grid with drop targets per day.
 * Bigger cells than the inline strip on the main board (#73).
 *
 * Tasks already due that day list inside each cell. Drop a draggable
 * task card here to set its due_date (auto-routes tier per #74).
 */
(function () {
    "use strict";

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
        let tasks = [];
        try {
            const resp = await fetch("/api/tasks");
            if (resp.ok) tasks = await resp.json();
        } catch (err) {
            console.error("Failed to load tasks for calendar:", err);
        }
        const byDate = {};
        const unscheduled = [];
        for (const t of tasks) {
            if (t.due_date) {
                if (!byDate[t.due_date]) byDate[t.due_date] = [];
                byDate[t.due_date].push(t);
            } else {
                unscheduled.push(t);
            }
        }
        // #94 (PR26): render an "Unscheduled" side list so the user has
        // a source to drag FROM. Tasks already in cells are also
        // draggable (between days). Without this, /calendar had nothing
        // draggable on the page at all.
        _renderUnscheduled(unscheduled);

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
                if (items.length === 0) {
                    const empty = document.createElement("div");
                    empty.className = "calendar-cell-empty";
                    empty.textContent = "Drop here";
                    cell.appendChild(empty);
                }
                cell.appendChild(list);

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
                    if (!taskId) return;
                    try {
                        const r = await fetch(`/api/tasks/${taskId}`, {
                            method: "PATCH",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ due_date: iso }),
                        });
                        if (!r.ok) throw new Error("PATCH failed");
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

        // Drop target: clear due_date.
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
            if (!taskId) return;
            try {
                const r = await fetch(`/api/tasks/${taskId}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ due_date: null }),
                });
                if (!r.ok) throw new Error("PATCH failed");
                await renderCalendar();
            } catch (err) {
                alert("Failed to clear due date: " + err.message);
            }
        });
    }

    function init() {
        renderCalendar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
