# #415 — Number and URL inputs render as unstyled browser defaults

Bug (filed 2026-10-11 by #414's Phase 6): the goal panel's **Priority Rank**
showed as a tiny bordered box beside full-width fields.

## 1. Surface (measured live, 2026-10-11, both viewports)

The shared `.detail-panel` field rule (`static/style.css` ~1485) and its two
mobile twins (~3592 iOS-zoom 16px font, ~3690 44px tap height) list only
`input[type="text"]`, `input[type="date"]`, `textarea` and `select`. Every
other text-like input in a panel gets browser defaults: **21px tall, no
padding, square corners, 13.3px font**. On a phone the font is under 16px, so
iOS Safari zooms the page on focus. The tap target is 21px, not 44px.

| Input | Type | Where |
|---|---|---|
| `#goalPriorityRank` | number | goal panel (`goals.html:112`) |
| `#projectPriorityOrder` | number | project panel (`projects.html:134`) |
| `#detailUrl` | url | task panel (`_task_detail_panel.html:70`) |
| `#recurEditUrl` | url | `/recurring` editor (`recurring.html:155`) |
| `#settingsWeeklyFocusSlotCount` | number | `/settings` (`settings.html:64`) — no panel; nothing styles it |

Not affected:
- `#projectColor` (`type="color"`) is a native swatch on purpose.
- The voice-memo repeat picker's day-of-month number input is styled by
  `.voice-recur-row input`.

## 2. This ship

1. Add `input[type="number"]` and `input[type="url"]` to all three
   `.detail-panel` rule lists (base, mobile 16px, mobile 44px).
2. `/settings` Weekly Focus slot input: a `.settings-row input[type="number"]`
   rule with the same field look (padding, border, radius, inherited font),
   keeping its narrow width, plus 16px + 44px in the mobile blocks.
3. **Drift guard** (pytest, `tests/test_mobile_css.py`): every text-like input
   type used inside a `.detail-panel` template must appear in each of the
   three rule lists. It fails today on `number` and `url`.
4. CACHE_VERSION bump.

## 3. Out of scope (filed)

- **#416 — the goal panel's "Add a task to this goal…" box is crushed to
  18px wide.** `.detail-panel select { width: 100% }` also catches the
  small `#linkedTaskType` picker in `.add-linked-task`, which then takes the
  whole row from the `flex: 1` text input beside it. Found while measuring
  this one. It's a different rule doing too much, not a missing type.
