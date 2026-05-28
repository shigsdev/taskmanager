# #224 — Dark theme refresh: "Soft Concrete" direction

**Status:** Working visual mockup at `docs/design/224-dark-theme-soft-concrete-mockup.html` —
open directly in a browser (no build step). Use to evaluate the
aesthetic before the actual rollout into `static/style.css`.

**Date:** 2026-05-28

## The brief

User-requested 2026-05-24: "I prefer a dark background that is more
sleek. Want to do an updated UI." (BACKLOG #224.)

Looked at 5 aesthetic directions before committing: Editorial
Brutalism, Console/Terminal, Sumi-e Minimalist, **Soft Concrete**,
Bento Modular. Soft Concrete best fits "sleek" without going monastic
(Sumi-e) or geek-flavored (Console).

## Why Soft Concrete

A task manager is a *daily-driver tool* used multiple times per day for
hours. The aesthetic has to be:

- **Calm** — not loud, won't tire the eyes after a 10-hour stretch
- **Material** — not floaty / glassy; gives a sense of weight + place
- **Hierarchical** — Today should *feel* heaviest, Inbox should *feel*
  lightest, without needing borders or strong color
- **Self-respecting** — single-user app, can be opinionated without
  defaulting to portfolio-piece flourishes

Soft Concrete delivers all four via material metaphor: each tier card
is a different "weight" of slate. Today sits with the deepest shadow
and a copper-tinted gradient. Inbox is barely there — a dashed-border
outline against the page. The information architecture is communicated
*through material*, not through ornament.

## Decisions

### Palette

```
--slate-0       #131110   viewport canvas (deepest)
--slate-100     #1a1816   tier card surface
--slate-200     #221f1c   raised cards (Today, detail panel)
--slate-300     #2c2825   hover / focus

--cream         #ece4d5   primary text
--cream-bright  #fbf6ec   emphasis (display headlines)
--cream-dim     #a89e8e   secondary text
--cream-faint   #6a6358   tertiary / metadata

--copper        #b87333   ONE accent — Today + primary actions
--copper-bright #d68b46   hover state
--sage          #94a48b   completed states
--rust          #c64a2a   overdue (rare, used sparingly)
```

**Crucially:** the accents (copper, sage, rust) cover *roughly 5% of
the rendered UI*. The other 95% is the slate-and-cream continuum. This
is what makes the design feel calm — most generic "dark mode" attempts
fail because they evenly distribute color, which fatigues the eye.

### Typography

```
Display:  Fraunces           variable serif, optical-size aware
Body:     IBM Plex Sans      neutral but characterful
Mono:     JetBrains Mono     due dates, IDs, technical metadata
```

All three are **free Google Fonts**. No proprietary licenses needed.

Fraunces is the standout choice — it's a high-contrast serif with a
"SOFT" variation axis that lets us pick a slightly rounded, warmer
character set for headlines without losing precision. The display
headlines use `opsz: 144` (the optical size variant intended for
40pt+) so they have proper hairline thins.

Body type stays in IBM Plex Sans at 15px — slightly less common than
the obvious Inter/Roboto but still extremely readable. Plex has a
lower x-height which pairs well with Fraunces's tall serif headlines.

Monospace is JetBrains Mono — for due dates ("2026-05-26 · 2 days
overdue"), tier counts ("04 / 06"), task projects, and any place
where alignment matters. Avoids visual noise from variable-width
in tabular metadata.

### Motion

- Page-load stagger: tiers fade-up in with 60ms delays between rows
  (160ms range total). One coordinated moment, not scattered.
- Hover lift on icon buttons: `translateY(-1px)` + shadow grow.
- Voice memo recording: amber breathing glow on the card background +
  pulse on the indicator dot + animated waveform bars.
- Task check on click: spring ease for the tick animation
  (`cubic-bezier(0.34, 1.56, 0.64, 1)`).
- Detail panel reveal: 500ms slide-in from right with spring ease.

**`prefers-reduced-motion: reduce` honored** — all animations turn off
in that branch (`@media (prefers-reduced-motion: no-preference)` wraps
all keyframes).

### Spatial composition

- Tier board is **single-column, asymmetric heights** — Today is
  visually heaviest, Inbox is faintest dashed outline. Each tier has
  the same horizontal width but feels like a different weight.
- Detail panel is **always-visible on desktop ≥1024px** as a right
  sidebar (480px wide). On mobile it stacks below the board.
- Capture bar is **centered, max 880px wide** — same width as the
  board column. Voice / scan / submit are icon-only at 44×44 (mobile
  touch target).
- Background has a **subtle SVG noise texture** (1.8% opacity) baked
  into the body via `data:` URL. Gives the slate surfaces a tactile
  concrete feel without an actual image asset.

### Signature element

The **Today tier has a 2px vertical copper rule** down its left edge,
with a soft 18px copper glow around it. This is the one piece of
chrome that immediately signals "this is the now slab" — the rest of
the design uses only material weight to communicate hierarchy.

## What's NOT in the mockup

- Real interactivity (the dropdowns are static, no JS handlers wired)
- The other 17 routes — only the home board + detail panel + voice
  memo card. Goals / Projects / Calendar / Recurring / Reflection
  would each get their own treatment in the same aesthetic, but the
  mockup focuses on the canonical task surface first.
- System-prefs detection (`prefers-color-scheme: dark` auto-applies)
  + manual toggle on `/settings`. Phase 2 of the rollout.
- Brand colors for goal categories (Work / Personal / Health / etc.) —
  the mockup uses generic project pills; the real rollout would map
  each category to a muted variant of the cream-slate palette.

## Rollout plan (if approved)

1. **Sweep current `static/style.css`** — find every hardcoded color
   (`#[0-9a-f]{3,6}`, `rgb(...)`, `rgba(...)`) that isn't already a
   CSS variable. Move to vars in the `:root` block.
2. **Add the Soft Concrete palette** — replace the existing light
   palette values, keep variable names stable so component code
   doesn't change.
3. **Update component CSS surface by surface** — capture bar, tier
   cards, task rows, detail panel, voice card, goals page, projects
   page, calendar grid, reflection page. Each becomes a Phase-6
   verifiable change.
4. **Add the noise texture** + serif font import + variable font
   settings.
5. **System prefs + manual toggle** — `[data-theme="dark"]` on the
   `<html>` element, persisted in localStorage. Default to system
   preference.
6. **Phase 6 sweep across all 18 routes at desktop + mobile**.

Total estimated effort: M-L (~6-10 hours of careful work, spread
across multiple sessions). The mockup IS the design contract — once
the aesthetic is approved, the rollout is mechanical.

## Open questions before kickoff

- **Keep light theme at all?** Single-user app, single operator
  preference — could just commit to dark. Saves Phase 6 time.
- **Time-of-day-aware accent shift?** Could rotate the copper
  accent through copper-bright (morning) → copper (mid-day) →
  copper-dim (evening). Small touch; might feel gimmicky.
- **Goal category color mapping?** Today the goal categories
  (Health / Personal Growth / Relationships / Work / BAU) get
  badges via `category` field. The mockup doesn't render them —
  the real rollout needs a muted-color treatment that doesn't
  break the 95/5 accent rule.

Discuss before kickoff.
