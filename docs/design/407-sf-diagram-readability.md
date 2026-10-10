# #407 — Strength Forge diagram readability

User ask (2026-10-10): "we need to look to see how we can make the diagrams
clearer". Decided option: **readability pass on every diagram + a start→end
pose pair where one frozen pose is ambiguous**. #408 (18 missing diagrams)
is drawn in the style this ship defines, so it is blocked on this one.

## 1. Surface (full sweep)

- `strength_forge_diagrams.py` — the ONLY producer. `DIAGRAMS: dict[id, svg]`,
  30 entries, hand-transcribed from the prototype's `diagrams.jsx`.
- `app.py:502` renders them into `templates/strength_forge.html` as hidden
  `#sf-diagrams .sf-diagram[data-diagram=id]` nodes.
- `static/strength_forge.js` `openModal()` clones the matching node into the
  exercise ℹ️ modal (`.sf-modal-diagram`, modal max-width 440px; on a 375px
  phone the SVG renders ~343px wide, i.e. 1 viewBox unit ≈ 1.07px).
- Diagrams are NOT used on the print sheet or anywhere else.
- `tests/test_strength_forge.py` pins: count == 30, well-formed `<svg>`,
  flare ids present.

## 2. What is wrong (measured on a render of all 30)

| Problem | Cause | Where |
|---|---|---|
| Captions effectively invisible | caption text uses `DIM` #374151 on `BG` #131110 ≈ 1.9:1 contrast (WCAG text needs 4.5:1) | every diagram's footer lines, "ELBOWS PINNED", "BODY STRAIGHT", "HIPS STAY ON FLOOR", "50% only" |
| Text too small | 9–10 unit monospace ≈ 9.6–10.7px on a phone | every caption |
| Labels drawn over the figure | positions copied by eye; nothing checks | band-curl, band-tricep, band-pull-apart, band-squat, face-pull, pallof-press, bw-squat, knee-hug, mckenzie, pike-pushup, … |
| Motion not shown | one frozen pose; curls / pushdowns / presses / rows look identical to standing | band-curl, band-tricep, band-ohp, band-row, band-chest-press, face-pull, glute-bridge… |
| Anatomy unreadable | thin 2px strokes, no shoulders/elbows; cat-cow has no torso; dead-bug arms sprout mid-torso | cat-cow, dead-bug, dead-bug-arms |
| Green means two things | the band AND cue text ("SIT TALL", "HIPS HIGH") are both green | most |

## 3. This ship's scope

1. **Figure kit** in `strength_forge_diagrams.py`: one `_body()` that draws a
   person from joint coordinates (head, neck, hip, arms as shoulder→elbow→hand,
   legs as hip→knee→foot), 3.5-unit round-capped strokes, the far-side limbs
   in a dimmer tone so side views read as 3-D. A `ghost=True` style (dashed,
   ~40% opacity) draws the START position under the solid FINISH position.
2. **Colour key, applied everywhere:** band = green only; motion arrows = gold;
   form cues = blue; cautions = bright red; captions = readable warm grey.
   Every text colour ≥ 4.5:1 on the diagram background.
3. **Layout rule:** title band at the top, figure in the middle, captions in a
   reserved band at the bottom; callouts sit in clear space. Min text size 11
   units (title 13). Long captions wrap to two lines instead of shrinking.
4. **Redraw all 30** with the kit, preserving every existing instructional cue
   (70% depth line, 30–40° MAX, BACK FLAT, STOP if hips sag, sets×reps, etc.).
   Start→finish ghosts (22): leg-swings, band-squat, band-row,
   band-chest-press, glute-bridge, pallof-press, dead-bug, face-pull, band-rdl,
   band-ohp, band-curl, band-tricep, incline-pushup, pike-pushup,
   diamond-pushup, australian-pullup, bw-squat, reverse-lunge,
   glute-bridge-single, mckenzie, pelvic-tilt, dead-bug-arms. Single pose (8):
   cat-cow (two side-by-side panels instead), band-pull-apart, arm-swings,
   box-breathing, lateral-walk, plank, knee-hug, walking — holds, circles and
   side-steps where one pose plus arrows already reads. pallof-press is drawn
   from ABOVE (the press is toward the viewer in any side/front view).
5. **Mechanical guards** (pytest, pure stdlib XML parse — text is monospace so
   a label's box is exactly `len × 0.6 × size` wide):
   - every `<text>` fill ≥ 4.5:1 contrast on `BG`;
   - every font-size ≥ 11;
   - every label box inside the viewBox (4-unit margin);
   - no two label boxes overlap;
   - no label box is crossed by a figure / band / prop stroke (sampled along
     every line, polyline, circle, and quadratic path).
   These go red on today's diagrams (proves they test something) and green
   after the redraw.

## 4. Out of scope (filed / owned elsewhere)

- The 18 diagram-less exercises → **#408** (drawn in this style next).
- Search link wording / YouTube link → **#409**.
- Per-side logging → **#410**.
- Any change to exercise descriptions, sets, or the clinical avoid-list — the
  diagrams illustrate the existing text; they do not change it.

## 5. Verification

- pytest guards above; existing count/flare-id tests unchanged (still 30).
- Visual: a Playwright-rendered gallery of all 30 reviewed by eye before and
  after (attached to the ship notes).
- Phase 6: open ℹ️ modals on /strength-forge at 1280×800 and 375×812 — diagram
  visible, legible, no overflow, viewport parity.
- No new static asset; `CACHE_VERSION` unchanged (diagrams are server-rendered
  HTML, network-first SW).
