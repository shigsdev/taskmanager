# Spec #400 — an anchor jump on /docs or /architecture hid the section heading under the sticky header

**Filed:** 2026-10-08 (found in #398's Phase 6)
**UI change** (`static/style.css`) → Phase 6 at both viewports,
`CACHE_VERSION` bump (v274 → v275), deploy.

## 1. The problem (measured 2026-10-09)

In-page `#anchor` links exist only on /docs and /architecture (their TOCs plus
a few prose links). Each target is a `<section id="…">` whose first child is
its `<h2>`. A jump scrolled the section to `top: 0`, but the `.nav` header is
`position: sticky; top: 0` — **91 px tall from 601 px wide up, 165 px at
≤ 600 px** (measured at 13 widths, 320–1600; the step is the nav's own
`max-width: 600px` rule). So the heading and intro sat under the header and the
first visible line was the next sub-heading.

## 2. Fix

```css
.docs-page [id] { scroll-margin-top: 107px; }          /* 91 + 16 */
@media (max-width: 600px) {
    .docs-page [id] { scroll-margin-top: 181px; }      /* 165 + 16 */
}
```

`scroll-margin-top` applies to every way of reaching a target — TOC click,
prose link, a `/docs#section` URL on load. Scoped to `.docs-page` (the only
pages with in-page anchors) rather than `html { scroll-padding-top }`, so no
`scrollIntoView` elsewhere in the app moves.

## 3. Test (`tests/e2e/docs_toc.spec.js`, both viewports)

For /docs and /architecture, click the middle and the last TOC link; poll until
the target's heading is below the header's bottom edge AND is the element under
its own midpoint (`elementFromPoint`). Red before on both pages × both
viewports; green after (18/18 over 3 repeats).

## 4. Phase 6

1280×800 and 375×812: "Review mode" click, a `/docs#capture-hints` load, and an
/architecture flow link all land with the heading at header + 16 px (107 / 181)
and visible; no horizontal overflow; 0 console errors.
