# #491 — Phase 6 seed data as rough as real use

Split from #459 on 2026-10-15 (deep review cause 4, "the test environment
is gentler than prod").

## What was wrong

`scripts/seed_dev_data.py` seeded short titles only; #138 (calendar
overflow) and #447 (long import lines) needed long text the seed never had.

## This ship

- The seed adds, idempotently (it wipes and re-seeds): a ~300-character
  title (Today), a bare-URL title with nothing to wrap on (This Week) and
  an OPEN task on the archived "Community of Practice" project (Backlog —
  #434's case; the project already had a completed one).
- `--many-backlog` adds 210 Backlog tasks for a >200-card section. Off by
  default: the gate copies the dev DB to 7 lanes, and no test needs it.
- Re-ran Phase 6 on the board, /tier/<name>, /calendar, /projects and
  /print at 1280 and 375 against it:
  - board / section / calendar cards cut the long titles to one line with
    "…" (the full title is the card's tooltip) — fine;
  - Work view lists the archived project's task under "Community of
    Practice (archived)" — fine;
  - **/print at 375 scrolled sideways**: the URL title ran to 634px. A
    flex item won't shrink below an unbroken string (`min-width: auto`).
    Fixed: `.print-task-title { min-width: 0; overflow-wrap: anywhere; }`
    (`templates/print.html`) — it also kept running off a printed page.
  - With `--many-backlog`: 217 Backlog cards draw in ~0.3s at 1280, no
    sideways scroll at either width, no console errors.
- The gate run on the fresh seed turned up one more hidden gap:
  /recycle-bin's `#recycleDeletedMore` button is empty until the bin has
  more deleted tasks than fit, so #458's name check failed on a small bin.
  The old dev DB always had hundreds of E2E leftovers in it, so the button
  always had text. It now reads "Show all" from the markup
  (`templates/recycle_bin.html`).
- The re-run then failed #452's "Re-open menu can be tapped in full" once,
  under the gate's 8 lanes only (16/16 alone): the first option tappable,
  the other six not — the Completed card sat at the screen's bottom edge
  and the downward menu ran off it, so `elementFromPoint` found nothing.
  Nothing was clipped. The test now centres the open menu before it
  hit-tests (`tests/e2e/phone_clipping.spec.js`); mutation-checked — with
  the card clipping put back it still fails. No retries added.
- CLAUDE.md Phase 6 setup says what the rough rows are and when to use the
  flag.

## Tests

`tests/e2e/rough_text.spec.js` makes its own rough tasks over the API (so
it doesn't depend on the seed) and checks /print, the board,
/tier/this_week and /calendar: no sideways scroll, every rough title inside
the screen — red before on /print at 375.
