/**
 * Pure helper for dropdowns that RESTORE a stored project/goal id (#355).
 *
 * The bug this exists to stop: every select that restores a stored
 * `project_id` / `goal_id` is populated from an ACTIVE-ONLY list. When the
 * stored row is archived, no <option> matches it, `selectedIndex` goes to
 * -1, and the select reads back "". The save path then treats "not in my
 * option list" as "the user cleared this field" and writes the clearing to
 * the database — on a save where the user edited nothing. On the task
 * detail panel that also trips the #148 revival branch, so absent-mindedly
 * opening and saving a COMPLETED task on an archived project resurrects it
 * onto the active board (270 such tasks existed on prod when this was
 * filed).
 *
 * The fix: when the stored id is absent from the active list, keep a row
 * for it so the value round-trips. Generalises #272's `keep` set from
 * "don't let the TYPE filter hide the current value" to "don't let
 * ANYTHING hide the current value" — #272 couldn't solve this because it
 * filters `allGoals`, and an archived goal is not in `allGoals` at all.
 *
 * This helper decides WHICH rows and in WHAT STATE — never how they are
 * labelled. The five call sites don't share a label format (projects
 * render `p.name`, goals render `${g.title} (${g.category})`), so owning
 * labels here would mean a format parameter per caller and would stop this
 * being pure logic. Callers render their own text and append the suffix:
 *
 *   state "live"     → caller's existing format, enabled
 *   state "archived" → caller's format + " (archived)", disabled
 *   state "missing"  → "(unavailable)", disabled
 *
 * Dual-export per CLAUDE.md anti-pattern #3:
 *   Browser: window.archivedOptionHelpers
 *   Node (Jest): module.exports
 */
"use strict";

const OPTION_STATE_LIVE = "live";
const OPTION_STATE_ARCHIVED = "archived";
const OPTION_STATE_MISSING = "missing";

/** Suffix appended to an archived row's own label by the caller. */
const ARCHIVED_SUFFIX = " (archived)";

/** Full label for an id that is in neither list (a dangling reference). */
const MISSING_LABEL = "(unavailable)";

/**
 * The rows a value-restoring dropdown should render.
 *
 * Returns every `live` row first, in the order given, each tagged
 * `state: "live"`. Then — ONLY when `currentId` is truthy and absent from
 * `live` — appends exactly one entry representing the stored value:
 *
 *   - found in `archived` → that row, `state: "archived"`
 *   - in neither list     → `{ id: currentId }`, `state: "missing"`
 *
 * When `currentId` is falsy or already live, nothing is appended, so the
 * common path produces exactly the list the caller rendered before #355.
 *
 * The appended entry deliberately BYPASSES whatever type filter the caller
 * applied to `live`: the point is to represent what is stored, and a
 * stored cross-type archived value is still stored. Callers filter `live`
 * themselves before calling; this helper knows nothing about types, names
 * or categories.
 *
 * @param {object} opts
 * @param {Array<{id: string}>} opts.live  Rows the user may choose from —
 *     already type-filtered by the caller.
 * @param {Array<{id: string}>} opts.archived  Archived rows to look the
 *     stored id up in. Not rendered unless it IS the stored id.
 * @param {string|null|undefined} opts.currentId  The stored value. On the
 *     panel-open path this must be passed explicitly (the select is still
 *     empty); elsewhere callers pass `sel.value`.
 * @returns {Array<{row: object, state: string}>}
 */
function optionRowsPreservingValue(opts) {
    const o = opts || {};
    const live = Array.isArray(o.live) ? o.live.filter((r) => r && r.id) : [];
    const rows = live.map((row) => ({ row, state: OPTION_STATE_LIVE }));

    const currentId = o.currentId;
    if (!currentId) return rows;
    if (live.some((r) => r.id === currentId)) return rows;

    const archived = Array.isArray(o.archived) ? o.archived : [];
    const found = archived.find((r) => r && r.id === currentId);
    rows.push(
        found
            ? { row: found, state: OPTION_STATE_ARCHIVED }
            : { row: { id: currentId }, state: OPTION_STATE_MISSING },
    );
    return rows;
}

/**
 * The text an <option> should carry, given its state and the caller's own
 * label for the row. Keeps the three label rules in one place so all five
 * selects read identically to the user.
 *
 * @param {string} state  From optionRowsPreservingValue.
 * @param {string} baseLabel  The caller's existing format for the row.
 */
function optionLabelForState(state, baseLabel) {
    if (state === OPTION_STATE_MISSING) return MISSING_LABEL;
    const base = typeof baseLabel === "string" ? baseLabel : "";
    if (state === OPTION_STATE_ARCHIVED) return base + ARCHIVED_SUFFIX;
    return base;
}

/** True when an option in this state must not be newly selectable. */
function optionIsDisabled(state) {
    return state === OPTION_STATE_ARCHIVED || state === OPTION_STATE_MISSING;
}

/**
 * Split one `?is_active=all` response into the active-only list the
 * existing readers expect and the archived list this helper needs.
 *
 * Exists so the three call sites share one definition of the split rather
 * than each re-deriving `.filter((x) => x.is_active)`. The active half
 * MUST keep its active-only meaning — in app.js `allProjects` has nine
 * readers, three of which are the independent halves of the PR63 #129 fix
 * (_sweepStaleFilterIds, the task badge, the filter bar), so widening it
 * would reintroduce #129's phantom badges and ghost filters.
 *
 * @param {Array<{is_active: boolean}>} rows  An is_active=all response.
 * @returns {{active: Array, archived: Array}}
 */
function splitByActive(rows) {
    const out = { active: [], archived: [] };
    if (!Array.isArray(rows)) return out;
    for (const row of rows) {
        if (!row) continue;
        if (row.is_active === false) out.archived.push(row);
        else out.active.push(row);
    }
    return out;
}

/**
 * Apply `optionRowsPreservingValue` output to a real <select>, then
 * restore the stored value.
 *
 * All five #355 call sites share this so there is ONE implementation of
 * the option loop rather than five copies that can drift apart — and so
 * the Jest round-trip test exercises the shipped renderer instead of a
 * duplicate of it (anti-pattern #3: a paraphrased handler in a test
 * proves nothing about the handler that ships).
 *
 * Every one of the five selects declares its own placeholder <option> in
 * the template (`— None —`, or `(no goal)` on /projects), so index 0 is
 * preserved and only the generated options are replaced. That matches
 * what app.js and recurring.js already did, and removes the redundant
 * placeholder re-creation projects.js was doing via innerHTML.
 *
 * The value is assigned here when the stored id is among the rendered
 * rows, which is what makes an archived value stick: the disabled option
 * exists, so `select.value = id` finds it instead of falling through to
 * selectedIndex -1.
 *
 * @param {HTMLSelectElement} select  Target select. No-op when falsy.
 * @param {Array<{row: object, state: string}>} rows  From
 *     optionRowsPreservingValue.
 * @param {function(object): string} labelOf  Caller's label format for a
 *     row. Not called for `missing` rows (there is no row to label).
 * @param {string|null|undefined} currentId  The stored value to restore.
 * @returns {boolean} true when `currentId` was found and assigned.
 */
function renderValuePreservingOptions(select, rows, labelOf, currentId) {
    if (!select) return false;
    while (select.options.length > 1) select.remove(1);
    const list = Array.isArray(rows) ? rows : [];
    for (const entry of list) {
        if (!entry || !entry.row || !entry.row.id) continue;
        const opt = select.ownerDocument.createElement("option");
        opt.value = entry.row.id;
        opt.textContent = optionLabelForState(
            entry.state,
            typeof labelOf === "function" ? labelOf(entry.row) : "",
        );
        if (optionIsDisabled(entry.state)) opt.disabled = true;
        select.appendChild(opt);
    }
    if (currentId && list.some((e) => e && e.row && e.row.id === currentId)) {
        select.value = currentId;
        return true;
    }
    return false;
}

// No intermediate top-level binding here, deliberately. Every static
// helper is a CLASSIC script sharing one global scope, so a top-level
// `const _api` collides with inbox_categorize_helpers.js's `var _api`
// and throws "Identifier '_api' has already been declared" — which kills
// the whole file, not just the line. That took out loadCompletedTasks on
// /completed. Jest cannot see it (each module is required in isolation);
// only a real page load can. Follow goal_archive_helpers.js and build
// the object inline on both branches.
if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        optionRowsPreservingValue, optionLabelForState, optionIsDisabled,
        renderValuePreservingOptions, splitByActive,
        OPTION_STATE_LIVE, OPTION_STATE_ARCHIVED, OPTION_STATE_MISSING,
        ARCHIVED_SUFFIX, MISSING_LABEL,
    };
} else if (typeof window !== "undefined") {
    window.archivedOptionHelpers = {
        optionRowsPreservingValue: optionRowsPreservingValue,
        optionLabelForState: optionLabelForState,
        optionIsDisabled: optionIsDisabled,
        renderValuePreservingOptions: renderValuePreservingOptions,
        splitByActive: splitByActive,
        OPTION_STATE_LIVE: OPTION_STATE_LIVE,
        OPTION_STATE_ARCHIVED: OPTION_STATE_ARCHIVED,
        OPTION_STATE_MISSING: OPTION_STATE_MISSING,
        ARCHIVED_SUFFIX: ARCHIVED_SUFFIX,
        MISSING_LABEL: MISSING_LABEL,
    };
}
