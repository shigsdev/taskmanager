# #408 — Draw the 18 missing Strength Forge diagrams

User report (2026-10-10): "on the new exercises we added for split, some are
missing diagrams". Decided: draw **all 18** catalog exercises without one
(13 used by the Split, 5 Isolation-only), in the #407 style.

## 1. Surface

- `static/strength_forge_data.js` `exercises` — 48 catalog ids. `DIAGRAMS`
  (`strength_forge_diagrams.py`) covers 30; flare protocol `diagramId`s
  (`mckenzie`, `knee-hug`, `walking`, `pelvic-tilt`, `dead-bug-arms`) are
  diagram-only ids, not catalog entries.
- `static/strength_forge.js` `openModal()` silently skips the diagram when
  `#sf-diagrams [data-diagram=id]` is absent — that silence is why nobody
  noticed: the modal looks complete, just with no picture.
- Missing (18): Split Day 1 `band-chest-fly`, `band-front-raise`,
  `band-overhead-tricep`, `chest-stretch`; Day 2 `band-lat-pulldown`,
  `band-rear-delt-fly`, `band-hammer-curl`; Day 3 `band-leg-curl`,
  `band-glute-bridge`, `band-glute-kickback`, `band-calf-raise`,
  `quad-stretch`, `hip-90-90`; Isolation-only `band-low-fly`,
  `band-straight-arm-pulldown`, `band-lateral-raise`,
  `band-concentration-curl`, `band-tricep-kickback`.

## 2. This ship

1. Draw the 18 with the #407 kit. Each diagram's cues come from that
   exercise's own catalog `desc` (no new instructions invented). Start→finish
   ghosts wherever the move has a start and an end; the three stretches are
   single holds.
2. A top-down view helper for moves whose motion is in the horizontal plane
   (chest fly, rear delt fly, 90/90 hip) — same reason #407 drew the Pallof
   press from above.
3. Safety emphasis carried into the picture where the description makes it a
   rule: rear delt fly "do NOT bend forward", overhead extension / glute
   kickback "do NOT arch your lower back", kickback "only 20–30°".
4. **Drift guard:** a pytest that parses every catalog id out of
   `strength_forge_data.js` and requires a diagram for each — so the next
   exercise added without one fails the gate instead of shipping silently.
   `test_diagram_count` becomes 48.
5. The #407 geometry guards cover the new 18 automatically (parametrised over
   `DIAGRAMS`).

## 3. Out of scope

- Search links → #409. Per-side logging → #410.
- No change to `openModal()`'s graceful skip — with the drift guard, a missing
  diagram can no longer reach prod, and the skip stays as defence in depth.

## 4. Verification

- pytest (drift guard red before the drawings, green after), geometry guards.
- Rendered gallery of the 18 reviewed by eye.
- Phase 6: open the Split Day 1/2/3 ℹ️ modals at 1280×800 and 375×812 —
  every exercise shows a diagram; viewport parity.
