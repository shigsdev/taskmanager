# Spec #395 — Mermaid checks wait for the finished diagram, not `data-processed`

**Filed:** 2026-10-07 (from the #394 parallel-Playwright probe)
**Status:** approved to build 2026-10-08 (bounded, test-only; design approved in chat)
**Test-only change.** No app code, no UI; nothing deployed changes behaviour.

---

## 1. What the probe saw, and what it actually was

One of three parallel runs failed #391's "the ER diagram draws at full size"
test: the svg was drawn 754 px wide and its viewBox read as ≤ ~793 px. #395
was filed as "the ER diagram can render collapsed inside its closed
`<details>`" — a user-facing layout bug. **That diagnosis was wrong.**

Investigation 2026-10-08:

- Not reproducible as a layout bug: 18/18 page loads at 1× / 4× / 8× CPU
  throttling and 60/60 repeated runs on 2 workers all drew 3957 px.
- mermaid 11.17.2 `runThrowsErrors` sets `data-processed="true"` on a block
  **before** `await render(id, text, element)`; `render` clears the block and
  builds the diagram **inside it** as `div#dmermaid-N > svg`
  (`appendDivSvgG`), and only the final `element.innerHTML = svg` puts the
  finished svg in as a direct child.
- A MutationObserver on the ER `<pre>` records exactly that sequence:
  `processed + DIV#dmermaid-N > svg (viewBox null, width "100%")` →
  `… viewBox 0 0 3957 4515` → emptied → `PRE > svg (viewBox 3957, width 3957)`.

So the test waited on `data-processed`, then measured the temporary svg:
`width="100%"` → 754 px drawn, no viewBox → natural 0, so `754 ≥ 0 × 0.95`
passed and `754 > 786` failed. The finished diagram is always right; **users
are not affected.** The same wait sat in the prod smoke helper
`expectEveryMermaidDiagramRendered`, where it could also miss a "Syntax
error" diagram that only appears at the final swap — the very bug #391
hardened that check against.

## 2. Behaviour after the fix

- `tests/e2e/architecture_mermaid.spec.js`: a shared
  `waitForFinishedDiagrams(page)` waits until every `pre.mermaid` has a
  **direct-child** svg (`pre.mermaid > svg`); the ER size check measures
  `#schema pre.mermaid > svg`.
- `tests/e2e-prod/smoke.spec.js`: `expectEveryMermaidDiagramRendered` waits
  on the same `pre.mermaid > svg` condition.

## 3. Tests

New `#395: the checks wait for the finished diagram, not data-processed`:
`page.route` holds the ER chunk (`/erDiagram-*.mjs`) for 4 s — mermaid loads
it **after** creating the temporary svg — which freezes the page in the
failing state deterministically. It pins the trap (`data-processed` set, a
`div#dmermaid > svg` present, no direct-child svg), then runs the real checks.

- With the old `data-processed` wait the size check failed **3/3**
  (natural width 0).
- With the fix: 18/18 (3 tests × 3 repeats × desktop + mobile).
- Prod smoke's two Mermaid tests pass against live prod with the new wait.

## 4. After it ships

#394 (two-worker Playwright) can proceed: the only failure its probe saw
was this test race.
