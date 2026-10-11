# #416 — The goal panel's "Add a task to this goal…" box is an 18px sliver

Bug (filed 2026-10-11 by the #415 spec §3; confirmed by screenshot at 1280px
and 375px): in the goal panel's Linked Tasks section, the
`.add-linked-task` row is

- the `#linkedTaskInput` text box (`flex: 1`)
- the `#linkedTaskType` Work/Personal select
- the Add button

The shared `.detail-panel select { width: 100% }` field rule also matches that
small select, so the select claims the whole row (304px at desktop) and the
text box shrinks to **18px**: you can't see what you type.

## 1. Surface (live sweep, both viewports, all four side panels)

Every flex row inside an open `.detail-panel` holding a select or a
text-like input was measured. The template survey also checked every
`<select>` in the four panel templates, and found no selects created by
script in their JS.

**Only `.add-linked-task` is affected.** Every other panel select sits
alone in its own `.form-field`, where full width is correct.

## 2. This ship

1. `.detail-panel .add-linked-task select { width: auto; flex: 0 0 auto; }`.
   It's more specific than the panel rule, so it doesn't depend on source
   order. The text box takes the rest of the row.
2. **Playwright (desktop + mobile):** open a goal, assert the text box is
   wider than the select and at least 150px, then type a title, press Add,
   and read the created task back through the API with that goal (a
   behaviour check, not just a size check).
3. CACHE_VERSION bump.

## 3. Out of scope

Nothing new found.
