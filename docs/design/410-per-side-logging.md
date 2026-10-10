# #410 — Log Left and Right reps on per-side Strength Forge exercises

User ask (2026-10-10): "if some exercises require each side or leg, we need
to log per instead of one." Decided: **L + R reps per set, ONE shared
resistance** (same band both sides).

## 1. Surface

- Log form — `static/strength_forge.js` `exerciseBlock()` / `addSet()` /
  `collectExercises()`: one `.sf-logform-reps` input per set row.
- Draft autosave — `loadDraft` / `scheduleDraftSave` (localStorage): rows
  stored as `{reps, resistance}`.
- Payload — `strength_forge_helpers.js` `buildSetsPayload()` →
  `{exercise_id, name, set_number, reps, resistance}`.
- Server — `strength_forge_service.py` `_clean_set_entry()` /
  `serialize_set()`; model `WorkoutSet` (`workout_sets`): no side column.
- History strip — `toggleDetail()` renders "10 reps @ Medium, …".
- Print sheet — `S1 reps ___ resistance ___` blanks.
- Docs — `templates/docs.html` "Tracking your workouts" + print section;
  `ARCHITECTURE.md`; `architecture_schemas.py` column descriptions.

## 2. Which exercises are per-side

An explicit `perSide: true` on the catalog entry (not parsed from "each" —
"10 each direction" on arm circles is NOT per side):

| id | prescription |
|---|---|
| `pallof-press` | 3 × 10 each side |
| `dead-bug` | 3 × 8/10 each side |
| `lateral-walk` | 3 × 10–12 each way |
| `band-leg-curl` | 3 × 12 each |
| `band-glute-kickback` | 3 × 12 each |
| `band-concentration-curl` | 3 × 10 each |
| `band-tricep-kickback` | 3 × 12 each |
| `reverse-lunge` | 3 × 10 each leg |
| `glute-bridge-single` | 3 × 10 each leg |
| `leg-swings` | 10 each direction/leg (warm-up) |

Not per-side: timed "× 2 sides" stretches (a hold, not reps), arm circles
(directions, not sides), everything bilateral.

## 3. This ship

1. **Schema:** nullable `workout_sets.side` (`'L'` / `'R'`, NULL = both /
   not per-side). Alembic revision on top of `t9b0c1d2e3f4`. Existing rows
   stay NULL — they were logged as one combined number and stay that way.
2. **Server:** `_clean_set_entry` accepts `side` ∈ {L, R} (anything else →
   NULL); `serialize_set` returns it. Each side is its own `WorkoutSet` row
   sharing the `set_number` — reps stay a plain integer per row, so totals
   and the last-resistance reference keep working unchanged.
3. **Helpers (Jest):** `isPerSide(item, catalog)`; `buildSetsPayload` takes
   `{repsL, repsR, resistance}` rows for per-side exercises → one entry per
   filled side (resistance on each), a resistance-only row → one side-less
   entry; `summarizeSets(rows)` for history → "L 10 · R 9 @ Medium, …".
4. **Form:** per-side rows show **L** and **R** reps boxes + one resistance
   box; mobile row stays within 375px. Draft rows carry `repsL`/`repsR`; an
   older draft's single `reps` restores into L.
5. **History + print:** summary via the helper; print blanks
   `S1 L ___ R ___ resistance ___`.
6. **Docs:** Help (fact-checked), `ARCHITECTURE.md` (+ fix its stale
   "Google-Images photo link" line from #409), schema description.

## 4. Tests

- pytest: side stored per row; invalid side → NULL; serialized; legacy
  side-less entries unchanged.
- Jest: `isPerSide`, payload per side (both, one side, resistance-only,
  blank), `summarizeSets` (mixed, legacy, resistance-only); data: every
  `perSide` id exists and its plan items say "each".
- Playwright: Split Day 1 log form → Pallof Press has L/R boxes; save →
  session detail returns an L and an R row with the same set number; the
  history strip shows "L … · R …".

## 5. Out of scope

- Backfilling old combined logs into sides (no way to split them).
- Per-side resistance (user chose one band).
