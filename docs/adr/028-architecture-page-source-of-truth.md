# ADR-028: In-app `/architecture` page — source-of-truth strategy

Date: 2026-04-23
Status: ACCEPTED

## Context

Backlog #42. The owner asked for an in-app system documentation page
(architecture diagrams, DB schema, process flows) accessible as a
top-level nav tab. Two prior data points shaped the design:

1. **`ARCHITECTURE.md` drifted three times** in early 2026-04 (catchup
   commits 31ad952, c74c586, 781b248) before `arch_sync_check.py` was
   added as a mechanical gate. The file is hand-edited, and every
   commit that adds a route / scheduler job / table is supposed to
   touch it. Writing rules said so; reality showed people forget.
2. **`templates/docs.html`** (the Help page from #33/#40) is also
   hand-edited and ALSO drifted between feature ships — most recently
   the doc fact-check SOP (commit e47a976) was added specifically
   because the OneNote import section made claims that didn't match
   the parser code.

Both surfaces fail the same way: hand-written documentation that
references code which moves faster than the docs.

The /architecture page would be a fourth such surface — except the
content is amenable to a different design: a substantial chunk of it
can be **generated from the running app** (route catalog from
`app.url_map`, ER diagram from `db.Model.registry`, ARCHITECTURE.md
content via inline markdown render). The remaining hand-written
parts (process-flow sequence diagrams, the prose in ARCHITECTURE.md)
get covered by an explicit cascade-check addition shipped in the
same change.

## Decisions

### 1. Three-layer source of truth

| Layer | Source | Drift risk |
|---|---|---|
| ARCHITECTURE.md prose + ASCII diagrams | The on-disk file, rendered via Python `markdown` lib at request time | Low — single source, used by both `arch_sync_check.py` AND the live page |
| Route catalog | `app.url_map` introspection at request time | Zero — IS the running app's routes |
| ER diagram | `db.Model.registry` introspection at request time, emitted as Mermaid `erDiagram` syntax | Zero — IS the actual schema, including FK arrows + nullable + enum values |
| Process-flow sequence diagrams | Hand-written Mermaid in `templates/architecture.html` | Real — covered by NEW cascade-check rule |

The first three layers are drift-proof by construction. The fourth is
the only remaining drift surface, and it's small (3 diagrams in v1,
each ~20 lines of Mermaid + a paragraph of prose).

### 2. Render ARCHITECTURE.md inline at request time, not at boot

A boot-time render + cache would be marginally faster but introduces
a "did the cache update?" failure mode. Single-user app, no
performance pressure, request-time render is fine — and it means
ARCHITECTURE.md edits flow to the live page on the next request, not
the next deploy.

The render uses two `markdown` extensions:

- `fenced_code` — for triple-backtick blocks (the ASCII components
  diagram + the ASCII sequence flows already present in
  ARCHITECTURE.md continue to render in `<pre>` blocks)
- `tables` — for the threat-model table

No other extensions. Bare invocation, easy to audit.

### 3. Mermaid via CDN, page-scoped, version-pinned

Mermaid v10.9.1 from `cdn.jsdelivr.net`, loaded only on
`/architecture` (the `<script>` tag is in the page's content block,
not `base.html`, so the rest of the app stays fast). CSP allows
`script-src` from `cdn.jsdelivr.net`.

Version pinning matters because Mermaid 11.x changed sequence-
diagram rendering defaults; pinning a known-good version means our
hand-written diagrams won't randomly re-arrange between deploys.
Bump in a separate ship after visual verification.

Rejected alternatives:

- **Self-host Mermaid** — adds a 70 KB file to the repo + an
  APP_SHELL entry. CDN is simpler for a single-user app and the
  CSP narrowing keeps the security gain real.
- **mermaid-cli at build time → static SVG** — adds a Node-side
  build step. Single-user app, request-time client render is fine.
- **No diagrams (ASCII only)** — sequence diagrams in ASCII are
  unreadable past 5-6 steps; the auth flow has 12+ steps.

### 4. Auth detection via marker attribute on the wrapper

`build_route_catalog` needs to know which routes are
`@login_required` vs public to populate the auth column. Walking the
`__wrapped__` chain looking for our wrapper's name is brittle.
Cleaner: `auth.login_required` sets `wrapped._login_required = True`
as a marker; `_detect_auth` walks the chain for that boolean.

One-line addition to `auth.py`. No behavior impact. Falls back to
`"public"` if not found, so a future custom auth wrapper that forgets
the marker shows up as `public` — a visible reminder in the catalog
to mark it.

### 5. Hidden routes for the catalog

`/static/*` (Flask's static asset endpoint) and `/login/*` (Flask-
Dance OAuth callbacks) are excluded — they're infrastructure, not
user-facing surface. Hardcoded list in `_HIDDEN_ROUTE_PREFIXES` +
`_HIDDEN_ENDPOINTS` so future contributors can see + amend.

### 6. New CLAUDE.md cascade rules in the same ship

Two NEW rows + amendments to two EXISTING rows in the cascade-check
table:

- NEW: "User-visible behavior" → update `templates/docs.html` (Help)
- NEW: "A process flow that has a sequence diagram on /architecture"
  → update the Mermaid in `templates/architecture.html`
- AMENDMENT to "A new HTML template / route renderer" — note that
  `/architecture` auto-renders ARCHITECTURE.md and auto-generates
  the route catalog, so updating ARCHITECTURE.md flows to the live
  page automatically
- AMENDMENT to "A new database column / enum member" — note that
  the ER diagram is auto-generated, AND that user-visible columns
  trigger the User-visible behavior row above

These land in the same commit as the page itself so the rules and
the surfaces they reference are simultaneously in place.

## Consequences

**Easy:**
- The page content matches the running app for the auto-generated
  bits — guaranteed by introspection, not by discipline.
- Updating `ARCHITECTURE.md` updates the live page on the next
  request — single source of truth, no cache.
- Future routes / models / columns appear in the page immediately
  on next deploy without any code change to architecture_service or
  architecture.html.

**Accepted trade-offs:**
- Page render does work on every request: read+parse ARCHITECTURE.md
  (~10 KB), introspect ~40 routes, introspect 7 models. Single-user
  app, negligible.
- New CSP entry for `cdn.jsdelivr.net`. Narrowed to script-src only;
  not a major attack surface expansion.
- The 3 hand-written sequence diagrams CAN drift. Mitigated by the
  cascade-check rule + the doc fact-check SOP. Future drift is a
  process failure, not a tooling failure — same posture as
  ARCHITECTURE.md prose itself.
- Mermaid's client-side render means the page has a brief
  unrendered moment before the JS finishes; users see the raw
  Mermaid text in `<pre>` tags first. Accepted — it's still
  readable, and it confirms the source content is there.

## Alternatives considered

- **Generate everything**: rejected for sequence diagrams. Auto-
  generated sequence diagrams from code (e.g. tracing decorator
  calls) are hopelessly noisy for a 12-step OAuth flow.
- **Render ARCHITECTURE.md as a static SVG diagram (Graphviz dot)**:
  rejected. The diagram is already in ASCII art that humans read in
  PRs; converting + losing diff-friendliness is a regression.
- **Embed the page in `/docs` as a TOC group instead of a new tab**:
  rejected per Q1 — owner explicitly asked for a separate tab.
- **Build the page server-side at boot, cache the rendered HTML**:
  rejected. Adds a "did the cache update?" failure mode for marginal
  perf. Single-user app doesn't need it.
- **Skip the cascade-check additions, add later**: rejected per Q12 —
  the rules and the page land together so neither references vapor.

## Verification

- New tests in `tests/test_architecture.py` covering:
  - Route 200 + login_required behavior
  - Validator cookie can read the page (GET, ADR-004)
  - `build_route_catalog` returns at least the known top-level routes
    (`/`, `/architecture`, `/docs`)
  - `build_route_catalog` correctly tags `/architecture` as `login`
    and finds no public routes that aren't intentional (sanity check)
  - `build_er_diagram` includes every known table (`tasks`, `goals`,
    `projects`, `recurring_tasks`, `app_logs`, `import_log`)
  - `build_er_diagram` emits Mermaid `erDiagram` header
  - `render_architecture_md` raises `FileNotFoundError` for missing
    file (caller handles with friendly message)
  - `render_architecture_md` round-trip on a known fixture renders
    `# heading` to `<h1>heading</h1>`
- Phase 6 manual regression at desktop 1280×800 + mobile 375×812 via
  Claude Preview: nav rename visible, Architecture tab clickable,
  TOC anchors scroll, Mermaid renders the 3 sequence diagrams + the
  ER diagram, route catalog table is readable on mobile.
- All 11 gates pass.
- `arch_sync_check.py` should pass — `/architecture` is now in
  ARCHITECTURE.md's Route catalog section.
