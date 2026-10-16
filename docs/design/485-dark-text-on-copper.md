# #485 — Dark text on copper fills

Split from #451 on 2026-10-15. Decided 2026-10-16 (user): **dark text on
copper**, the same fix #451 gave the sage / amber fills.

## What was wrong

White text on the copper fill (`--copper` `#b87333`) measures **3.79:1**,
under WCAG AA's 4.5:1 for normal-size text. It is the app's primary
button (`.btn`: Save, Plan, Run, Copy to tomorrow, …) and every control
that copies it.

| Text on | Ratio |
|---|---|
| white on copper (before) | 3.79 |
| `--on-fill` (`#131110`) on copper | 4.97 |
| `--on-fill` on copper-bright (hover) | 6.85 |

## Surface (swept 2026-10-16: every style.css rule with a solid copper fill)

White text on a solid copper / `--accent` fill → `color: var(--on-fill)`:

- `.btn` (and `.btn:hover`, which inherits); `.btn-stop`
- `.update-banner`, plus its button (white with copper text, also 3.79 —
  now white with dark text)
- `.inbox-badge`, `.day-cell-today`, `.parent-picker-chip`
- `.reopen-btn:hover`, `.voice-candidate-recur-btn:hover`
- `.project-filter-btn.active`, `.goal-filter-btn.active`,
  `#projectsBulkToggle.active`, `.bulk-select-toggle.active`
- `.review-btn-freeze`, `.recurring-toolbar #recurringNew`
- `.bulk-pending-chip` (its hover was a light-theme blue `#1d4ed8` — now
  `--accent-hover` like every other copper control)
- `.voice-candidate-route.route-task`, `.reflection-op-badge.op-update`,
  `.swipe-action-move` (these three set only the fill and inherit white
  from a shared base — the base keeps white for its other fills)

Kept white: `.btn-danger` (it inherited `.btn`'s white — it now says so
itself), `.swipe-action-delete`, `.review-btn-delete`.

Not text on a fill (unchanged): progress fills, the Today stripe / ring,
the voice level bars, `.task-card.dragging` (a 0.4-opacity drag ghost).

## Out of scope — filed as #496

White on the sage fill (`.voice-candidate-route.route-goal`,
`.reflection-op-badge.op-create`, `.day-cell-hover`, ~2.8:1) and the
light-theme pink `.voice-candidate-route.route-project` (`#ec4899`, 3.5:1)
— the same class of miss as #451, different fills.

## Guard

`tests/e2e/copper_contrast.spec.js`: each control above, built with the
app's own classes, measures ≥ 4.5:1 (hover states too); `.btn-danger`
still has white text (the quiet case); and on 18 real pages every visible
element with a solid copper fill and its own text measures ≥ 4.5:1.
