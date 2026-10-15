# #486 — Phone header: pin only the nav tabs

Split from #452 on 2026-10-15. User decision: **pin only the nav-tabs strip;
the app name and the capture box scroll away.**

## What is wrong today (measured at 375×812 on `/`)

- `.nav` is `position: sticky; top: 0` at every width. At ≤600px it stacks
  into three rows: brand + 📷 (0–52), nav tabs (58–102), capture box
  (108–206). All 215px stay pinned, about a quarter of an 812px screen.
- `.reflection-combine-bar` (#335) is `sticky; top: 0; z-index: 2`. Once it
  sticks it sits under the nav (z 100) at every width, so the "Analyze
  together" bar is hidden at exactly the moment it is meant to help.
- The /docs and /architecture anchor offset (#400) is hard-coded to the nav
  height: 107px on desktop, 231px at ≤600px. The TOC `top: 107px` (#397) is
  also hard-coded.

## This ship

1. **≤600px order:** brand + 📷 first, then the capture box, then the nav tabs
   last (`.nav-links { order: 20; flex-basis: 100% }`; the capture bar is
   already `order: 10`).
2. **Pin only the tabs:** an inline script in `templates/base.html`, right
   after `</header>`, sets `.nav`'s `top` to minus the distance from the nav's
   top to the tab strip (minus a 6px navy margin), so the nav scrolls until
   only the tabs are left, then sticks. Above 600px `top` stays 0 (the
   desktop nav is one row, so nothing changes). It re-measures with a
   ResizeObserver on `.nav` (capture-bar wrapping, font load, rotation) and
   on the media-query change. Without JS the whole nav stays pinned, as
   today.
3. **`--nav-pinned-h`:** the same script sets this on `:root`: the height of
   what stays on screen (the tab strip on a phone, the whole nav on desktop).
4. **Consumers of the pinned height:**
   - `.reflection-combine-bar { top: var(--nav-pinned-h, 0px) }`, so it sticks
     under the nav instead of behind it, at every width.
   - `.docs-page [id] { scroll-margin-top: calc(var(--nav-pinned-h, 91px) + 16px) }`
     replaces the 107px / 231px pair.
   - `.docs-toc { top: calc(var(--nav-pinned-h, 91px) + 16px) }` (desktop only,
     same value as today when the nav is 91px).

## Tests (Playwright, `tests/e2e/nav_pin.spec.js`)

- 375: at scrollY 0 the capture box is visible. After a scroll, the tab strip
  sits at the top (top within 0–8px) and the capture box is off screen; a
  tab is still the element under its own midpoint.
- 375 on a page without a capture box (/settings): the same tab pinning.
- 1280: after a scroll the whole nav is still at top 0, capture box visible
  (the quiet case: desktop unchanged).
- /reflection with 30 stubbed rows: tick two, scroll to the bottom; the
  combine bar is the element under its own midpoint (not the nav), at both
  widths.
- `docs_toc.spec.js` #400 already checks that a TOC jump lands below the nav
  bottom at both widths. It keeps guarding the new offset.

## Out of scope

- A global `html { scroll-padding-top }` for every other anchor jump. Nothing
  else in the app jumps to anchors under the nav today.
