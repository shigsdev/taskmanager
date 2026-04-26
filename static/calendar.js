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
        for (const t of tasks) {
            if (t.due_date) {
                if (!byDate[t.due_date]) byDate[t.due_date] = [];
                byDate[t.due_date].push(t);
            }
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

    function init() {
        renderCalendar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
