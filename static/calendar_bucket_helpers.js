/**
 * /calendar page pure-logic helpers, extracted from calendar.js so they
 * can be unit-tested from Jest (#231 — closes the gap that let two bugs
 * ship together: subtasks rendered as top-level rows on the grid AND
 * Unscheduled items had no click affordance).
 *
 * Dual-export pattern, same as filter_helpers / api_helpers / etc.:
 * in the browser, the helpers are attached to `window.calendarBucketHelpers`
 * via the `<script>` load; in Node.js (Jest) they are require()-able
 * via `module.exports`.
 *
 * What lives here vs. calendar.js:
 *   - bucketTasks() — the pure function that decides which day cell
 *     a task lands in vs. the Unscheduled aside, AND filters out
 *     subtasks (#231 fix). Pure: takes args, returns a value, no DOM.
 *   - DOM mutation (rendering cells, attaching listeners) stays in
 *     calendar.js (covered by Phase 6 + local Playwright).
 *
 * Filter rule (#231, refined 2026-05-25 per user feedback):
 *
 *   Subtasks WITH a scheduled day → render on that day's cell, exactly
 *     like a top-level task. The user explicitly scheduled them; they
 *     should be visible where they put them.
 *
 *   Subtasks WITHOUT a scheduled day → HIDDEN from the calendar. They
 *     belong nested under the parent's detail card on the home board.
 *     Listing them in Unscheduled was what produced the user-reported
 *     duplicate-feeling ("I still see Subtasks listed on unscheduled
 *     and the day i put them on") — the parent sat on its day cell and
 *     the unscheduled subtask appeared as a separate Unscheduled row
 *     that visually felt like the same item in two places.
 *
 *   First-pass mistake (now reverted): the original #231 fix filtered
 *   ALL subtasks out — including ones the user had explicitly scheduled.
 *   User clarified: "i did not want the subtasks to go away from the
 *   calender - i just did not want them to show under unscheduled and
 *   the day i scheduled them. they should be on the day i scheduled
 *   them."
 *
 * Tier fallback (#100 / PR29): tasks with no `due_date` but with a
 * tier of TODAY or TOMORROW bucket to today / tomorrow's cell. Other
 * tiers (THIS_WEEK / NEXT_WEEK span multiple days; BACKLOG / FREEZER
 * are intentionally undated) leave the task without a scheduled day.
 */
"use strict";

/**
 * Bucket the API task list into `{ byDate: {iso: [task,...]}, unscheduled: [task,...] }`.
 *
 * Subtasks (rows with `parent_id` set) are included in `byDate` if they
 * have a scheduled day, and SUPPRESSED from `unscheduled` otherwise.
 * Top-level rows always go somewhere.
 *
 * @param {Array<{id, title, parent_id, due_date, tier, ...}>} tasks - raw /api/tasks rows
 * @param {string} todayIso - "YYYY-MM-DD" for "today" (caller computes from local clock)
 * @param {string} tomorrowIso - "YYYY-MM-DD" for "tomorrow"
 * @returns {{ byDate: Object<string, Array>, unscheduled: Array }}
 */
function bucketTasks(tasks, todayIso, tomorrowIso) {
    const byDate = {};
    const unscheduled = [];
    for (const t of tasks) {
        let cellDate = t.due_date;
        if (!cellDate) {
            if (t.tier === "today") cellDate = todayIso;
            else if (t.tier === "tomorrow") cellDate = tomorrowIso;
        }
        if (cellDate) {
            // Scheduled — top-level OR subtask, render on its day.
            if (!byDate[cellDate]) byDate[cellDate] = [];
            byDate[cellDate].push(t);
        } else if (!t.parent_id) {
            // Top-level with no day → Unscheduled aside.
            unscheduled.push(t);
        }
        // else: subtask with no day → suppressed. It's still visible on
        // the home board nested under its parent's detail card.
    }
    return { byDate: byDate, unscheduled: unscheduled };
}

/**
 * #267: compute the new in-cell task order after a within-day drag-reorder.
 *
 * Pure mirror of app.js getDragAfterElement: insert `draggedId` BEFORE the
 * first existing item whose vertical midpoint sits below the pointer `y`
 * (i.e. the closest item whose center is past the cursor); if none, append.
 * Keeping the math here (DOM-free) lets Jest exercise every insertion
 * position without a browser — calendar.js only supplies the measured
 * midpoints (getBoundingClientRect) and persists the result.
 *
 * @param {Array<{id: string, mid: number}>} items - the cell's current task
 *   rows in display order, each with its vertical midpoint (top + height/2).
 *   May include the dragged item itself — it's filtered out before insert.
 * @param {string} draggedId - the task id being dropped
 * @param {number} y - pointer clientY at drop
 * @returns {Array<string>} the new ordered list of task ids for the cell
 */
function calendarReorderIds(items, draggedId, y) {
    const others = items.filter((it) => it.id !== draggedId);
    let insertBefore = others.length; // default: append to the end
    let closestOffset = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < others.length; i++) {
        const offset = y - others[i].mid;
        // offset < 0 → this item's center is below the cursor; pick the
        // one closest to the cursor (largest still-negative offset).
        if (offset < 0 && offset > closestOffset) {
            closestOffset = offset;
            insertBefore = i;
        }
    }
    const ids = others.map((o) => o.id);
    ids.splice(insertBefore, 0, draggedId);
    return ids;
}

/**
 * #279: build a tier's FULL new order after a within-cell reorder, so the
 * persisted sort_order can't collide across cells.
 *
 * A calendar cell holds only a SUBSET of a tier's tasks. Reordering just the
 * cell's ids (writing sort_order 0..N for them) can collide with the same
 * tier's tasks in other cells. Instead, walk the tier's CURRENT order and,
 * wherever a cell task sits, drop in the next id from the cell's NEW order —
 * leaving every non-cell task in its existing slot. The caller then sends the
 * whole tier to /api/tasks/reorder, which renumbers it 0..N with every member
 * distinct (no collision), while non-cell tasks keep their relative position.
 *
 * @param {Array<string>} tierOrderedIds - all of the tier's task ids in their
 *   current display order (sort_order asc).
 * @param {Array<string>} cellNewOrder - the cell's task ids in the desired new
 *   order. Every id MUST also appear in tierOrderedIds.
 * @returns {Array<string>} the full tier order with the cell's tasks
 *   substituted into the positions they currently occupy.
 */
function reorderTierWithCell(tierOrderedIds, cellNewOrder) {
    const cellSet = new Set(cellNewOrder);
    let k = 0;
    return tierOrderedIds.map(function (id) {
        return cellSet.has(id) ? cellNewOrder[k++] : id;
    });
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { bucketTasks, calendarReorderIds, reorderTierWithCell };
} else if (typeof window !== "undefined") {
    window.calendarBucketHelpers = {
        bucketTasks, calendarReorderIds, reorderTierWithCell,
    };
}
