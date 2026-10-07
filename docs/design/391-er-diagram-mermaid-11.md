# Spec #391 — the /architecture ER diagram renders, on mermaid 11

**Filed:** 2026-10-05 (found in #386's Phase 6, confirmed on prod)
**Status:** approved to build 2026-10-06 — user picked "upgrade to mermaid 11"
over "stay on 10.9.1 and strip the generator"; no open decisions
**UI change** (one CDN pin on one page) → Phase 6 at desktop + mobile.

---

## 1. The problem

The "What the database stores" engineering diagram on `/architecture`
(`<pre class="mermaid">{{ er_diagram }}</pre>`, built by
`architecture_service.build_er_diagram()`) renders mermaid's
"Syntax error in text" SVG. The other 9 diagrams render.

Root cause, reproduced 2026-10-06 by feeding the exact generated source to
`mermaid.parse()` from the pinned CDN build:

| Source fed to mermaid | 10.9.1 | 11.17.2 |
|---|---|---|
| Generated ER, unchanged | ✗ `Expecting 'ATTRIBUTE_WORD', got 'COMMA'` (line 7) | ✓ |
| … with enum commas → `_` | ✗ `classDef core …` not expected | — |
| … with `classDef` / `class` lines removed | ✗ (commas) | — |
| … with both fixed | ✓ | — |

So the generator emits **two** things 10.9.1's `erDiagram` grammar rejects,
each of which alone is fatal:

1. Enum type tokens with commas — `enum_work,personal` (since #42).
2. `classDef` / `class` lines for the core/ops/auth colour groups (since #43).

The diagram has therefore most likely never rendered in prod. The prod smoke
test "architecture page renders Mermaid diagrams" did not notice because it
only asserts the **first** `pre.mermaid svg` is visible and ≥ 5 SVGs exist —
and mermaid's error output is itself an `svg`.

## 2. Behaviour after the fix

- `templates/architecture.html` imports mermaid **11.17.2** (exact pin, same
  jsdelivr ESM URL shape, same `initialize` config). ADR-028 §3 already
  anticipated this: "Bump in a separate ship after visual verification."
- `build_er_diagram()` is **unchanged** — 11.x accepts its output as-is,
  including the colour groups, so the ER boxes get the blue / amber outlines
  the page's legend has always promised.
- All 10 diagrams render; none shows "Syntax error".
- **The ER diagram draws at natural size and scrolls inside its own box**
  (user decision 2026-10-06, found in Phase 6). Once it rendered, fit-to-
  width shrank its ~3957px canvas into the ~754px column — 0.19×, ~3px
  labels. `er: { useMaxWidth: false }` in the mermaid config plus a scoped
  `#schema pre.mermaid svg { max-width: none; }` (the global
  `pre.mermaid svg { max-width: 100% }` otherwise clamps it back). The
  `pre` already has `overflow-x: auto`, so the page never widens.
  Flowcharts are untouched — they scale the same on 11 as on 10
  (measured against prod: e.g. the system diagram 0.42× → 0.39×).
  `static/sw.js` `CACHE_VERSION` bumped for the CSS change.

## 3. Tests (written first, red on 10.9.1)

- **Local Playwright** (`tests/e2e/architecture_mermaid.spec.js`, runs in the
  `chromium` + `chromium-mobile` projects): load `/architecture?nosw=1`, wait
  for mermaid, and assert **every** `pre.mermaid` holds an `svg` and **no**
  block's text contains "Syntax error". Red today on the ER block (#3 in
  page order). A second test asserts the ER SVG is drawn at ≥ 95% of its
  natural width, wider than its box, with no page-level horizontal
  overflow — red at fit-to-width.
- **Prod smoke** (`tests/e2e-prod/smoke.spec.js`): both existing Mermaid
  tests (no-SW and SW-active) gain the same every-block / no-"Syntax error"
  assertion, so the class of bug can't hide behind "the first one rendered".
- **pytest** `test_page_includes_mermaid_loader`: assert the exact pin
  `mermaid@11.17.2` instead of `mermaid@10`.

## 4. Docs / comments touched

- ADR-028 §3: amendment note (2026-10-06, #391) — version is now 11.17.2,
  and why.
- `app.py` CSP comment: "Mermaid v10" → v11, and drop the claim that the
  module is "hashed via SRI in the template" — it isn't (an ES `import`
  statement can't carry an `integrity` attribute); the protection is the
  exact version pin + the `script-src` host allowlist.
- `static/sw.js:146` and `docs/mockups/43-*` mention 10.9.1 as **history**
  (the #235 incident, a frozen mockup) — left as-is; editing `sw.js` would
  also force a `CACHE_VERSION` bump for a comment.

## 5. Risks checked in Phase 6

- 11.x is a major version: every one of the 10 diagrams is looked at, at
  desktop and mobile, not just the ER one.
- The ER diagram sits inside a closed `<details>`; check it lays out
  correctly once opened (mermaid measures text with `getBBox`).
- Viewport parity (`scrollWidth ≤ innerWidth`) at both sizes.

## 6. Out of scope

- The hand-written schema intro still says "Seven tables" and lists an
  "Auth (sign-in tokens)" group, but there are 14 tables and no auth table
  (#188). Separate doc-drift item, not this bug.
