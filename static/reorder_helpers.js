/**
 * Pure reorder logic for the bulk move-up / move-down feature.
 *
 * Extracted to a dual-export module per CLAUDE.md anti-pattern #3 so
 * the boundary cases (top-edge no-op, bottom-edge no-op, contiguous
 * block, non-contiguous selection) can be Jest-tested without DOM.
 *
 * Browser: window.reorderHelpers; Node (Jest): module.exports.
 */
"use strict";

/**
 * Move every selected id up or down by one slot, preserving their
 * relative order. Contiguous block-of-selected stays a block. Non-
 * contiguous selections move independently. Selections already at
 * the boundary in the move direction stay put.
 *
 * Algorithm (move-up): walk top→bottom; whenever ids[i] is selected
 * AND ids[i-1] is NOT selected, swap them. This naturally:
 *  - swaps a single selected with its non-selected predecessor
 *  - shifts a contiguous block up by one (only the block's top
 *    swaps; the rest already have selected predecessors and skip)
 *  - moves each non-contiguous selected up over its non-selected
 *    predecessor in one pass
 *
 * Move-down is the symmetric walk bottom→top.
 *
 * @param {string[]} currentIds - Current ordered list of task ids in
 *     the tier.
 * @param {Set<string>|string[]} selectedIdsArg - Set/array of ids to
 *     move.
 * @param {"up"|"down"} direction - Direction to move.
 * @returns {string[]} The new ordering. Returns a NEW array — input
 *     is not mutated. If nothing moves, the returned array equals
 *     the input by value (same ids in same order).
 */
function reorderSelectionWithinTier(currentIds, selectedIdsArg, direction) {
    if (direction !== "up" && direction !== "down") {
        throw new Error("direction must be 'up' or 'down'");
    }
    if (!Array.isArray(currentIds)) {
        throw new Error("currentIds must be an array");
    }
    const selected = (selectedIdsArg instanceof Set)
        ? selectedIdsArg
        : new Set(selectedIdsArg || []);
    if (selected.size === 0) return currentIds.slice();

    const ids = currentIds.slice();
    if (direction === "up") {
        for (let i = 1; i < ids.length; i++) {
            if (selected.has(ids[i]) && !selected.has(ids[i - 1])) {
                const tmp = ids[i - 1];
                ids[i - 1] = ids[i];
                ids[i] = tmp;
            }
        }
    } else {
        for (let i = ids.length - 2; i >= 0; i--) {
            if (selected.has(ids[i]) && !selected.has(ids[i + 1])) {
                const tmp = ids[i + 1];
                ids[i + 1] = ids[i];
                ids[i] = tmp;
            }
        }
    }
    return ids;
}

/**
 * Decide whether the selection is reorderable as a single tier
 * operation. Returns either {ok:true, tier} or {ok:false, reason}.
 *
 * Reasons callers care about:
 *   - "empty"            no items selected
 *   - "multiple_tiers"   selection spans tiers; reorder doesn't apply
 *   - "single_tier"      OK, returns the tier
 *
 * Pure: takes a list of {id, tier} and a Set of selected ids.
 */
function classifySelectionForReorder(taskTierPairs, selectedIdsArg) {
    const selected = (selectedIdsArg instanceof Set)
        ? selectedIdsArg
        : new Set(selectedIdsArg || []);
    if (selected.size === 0) {
        return { ok: false, reason: "empty" };
    }
    const tiers = new Set();
    for (const { id, tier } of taskTierPairs) {
        if (selected.has(id)) tiers.add(tier);
    }
    if (tiers.size === 0) {
        return { ok: false, reason: "empty" };
    }
    if (tiers.size > 1) {
        return { ok: false, reason: "multiple_tiers" };
    }
    return { ok: true, tier: Array.from(tiers)[0] };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        reorderSelectionWithinTier,
        classifySelectionForReorder,
    };
} else if (typeof window !== "undefined") {
    window.reorderHelpers = {
        reorderSelectionWithinTier,
        classifySelectionForReorder,
    };
}
