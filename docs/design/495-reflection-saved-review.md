# #495 — Re-open a reflection's saved proposals without paying again

Found 2026-10-16 by the #473 spec.

## What was wrong

`proposed_actions` is saved on the reflection, but once the review screen
was gone (Start Over, Go to Tasks, a reload, closing the tab) History only
offered "↻ Re-analyze" — a second Claude call for proposals already saved.

## This ship

- History (`static/reflection.js`): a row that has proposals and isn't
  fully applied (`reflectionHelpers.canReviewSaved`) shows
  **📋 Review proposals**. It renders the review from the saved row — no
  request at all — with `current` set to it, so Apply posts to that
  reflection's `/confirm`.
- Rows an earlier Apply landed (`applied_actions.actions`, #437) are marked
  with #437's own `markAppliedRows`: "✓ applied", unticked, disabled, not
  counted by Apply. `reflectionHelpers.landedRowKeys` maps them to
  `bucket:idx` by a key-order-independent `actionKey`. The server's dedup
  (`reflection_service._action_key`) still guarantees nothing is applied
  twice.
- The cost line reads "Saved proposals — no new Claude call." instead of
  the original analysis cost, which would read like a new charge.
- A fully applied reflection gets no button (its Apply would 409).
- Help → Weekly reflection. CACHE_VERSION v349.

## Tests

`tests/js/unit/reflection_saved_review.test.js` (red before);
`tests/e2e/reflection_review_saved.spec.js` — History stubbed: the button
opens the review, the landed row is marked, Apply sends only the other,
no analyze call; no button on a fully applied or empty row (rows opened
first, so "no button" isn't vacuous). Red before.
