# Spec #401 — the #378 real-mouse drag test released before the target accepted the drop

**Filed:** 2026-10-09 (4 failures in a row one morning, then none in ~40 runs)
**Test-only change** (`tests/e2e/pages.spec.js`, "a real mouse drag of a card
task line never opens the task panel") → no Phase 6, no deploy.

## 1. Cause

The test used `locator.dragTo(target)`. Its default `steps: 1` sends a single
`mousemove` to the target between mouse-down and mouse-up
(`playwright-core/lib/server/frames.js` `dragAndDrop`). Measured on /projects
at 375×812: that gives the target card exactly **one** `dragover` before the
release (`steps: 10` gives only two — Chromium throttles `dragover`). A `drop`
fires only if a `dragover` that called `preventDefault()` arrived first, so the
test raced: any delay and the release came first, the task never moved, and
the `project_id` poll failed. On mobile, `dragTo` (and `hover`) also scroll the
page mid-drag to reach a target below the fold.

## 2. Fix

Drive the real mouse by hand:

1. Scroll the dragged line to the middle of the viewport **once, before the
   press**. The test creates the "from" and "to" projects back to back, so
   their cards sit together and the target is on screen too (asserted).
2. `mouse.down` on the line, move 10 px (past the drag threshold), move to the
   target in steps.
3. Poll — with a 1 px nudge each time, which yields a fresh `dragover` — until
   the card has `project-card-drop-ok`. That class is added in the same
   `onCardTaskDragOver` branch that calls `preventDefault()`
   (`static/projects.js`), so it means "this card will accept the drop".
4. `mouse.up`, then the existing assertions: panel closed, task moved.

## 3. Evidence

- New version: 40/40 (20 × desktop, 20 × mobile).
- Mutation: with `e.preventDefault()` commented out of `onCardTaskDragOver`,
  the test fails on both viewports (task not moved). Reverted.
- A first attempt that used `locator.hover()` for the moves failed 15/15 on
  mobile (the mid-drag scroll), which is why the scroll happens before the
  press.
