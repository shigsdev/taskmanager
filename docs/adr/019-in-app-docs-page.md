# ADR-019: In-app `/docs` page as the documentation hub

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #33 asked for "OneNote bulk-upload format documentation so
the user can clean data before pasting." The original scope was either
(a) an inline collapsible help panel on the /import page, or (b) a
linked `docs/IMPORT_FORMAT.md` file. During implementation the user
expanded scope: **"we should post the documentation in the app by
making a section for documentation."**

Rationale for that call (captured here so future additions have a
clear home): the app already accumulates non-obvious behaviour —
capture-bar shortcuts (`#today`, `#tomorrow`, `#work`), tier
semantics, the Tomorrow auto-roll cron, the recurring-template
preview cards, the Cancelled-vs-Completed distinction. Each has
surfaced in conversation as "wait, what does that mean?" at some
point. A dedicated in-app docs section gives all of them a landing
spot, searchable by the user in the tool they're already using,
without a second tab or a README dig.

## Decisions

### 1. URL: `/docs`, one page with anchored sections

Single flat template with a sticky sidebar TOC on desktop, stacked
on mobile. Each topic is a `<section>` with an `id` that the TOC
links to. Rationale: one page means one render + one scroll;
anchor links are shareable ("here's the format guide → /docs#import-onenote");
and a flat structure is easier to iterate on than a multi-page hub
until the content grows past ~5 sections (it currently has 2, so
flat wins).

Trade-off accepted: long content on a long page. Revisit if the page
crosses ~2000 lines of rendered HTML — at that point split into
sub-pages with deep links preserved.

### 2. Two inaugural sections: OneNote text + Excel goals

Both cover the `/import` page's two primary flows. Structure for each:

- **Rules** — exactly what the parser accepts and rejects, in plain
  English.
- **What it does NOT do** — explicitly call out missing features
  (inline metadata shortcuts, project linkage, URL extraction) so
  users don't expect them.
- **Practical clean-up checklist** — actionable pre-paste steps.
- **Worked example** — a realistic input + labeled outputs so the
  reader can predict behaviour before testing.
- **Size + undo** — hard limits and the recycle-bin undo path.

### 3. Sidebar TOC + two-column layout on desktop

Sticky TOC at ~220px, main content in the remaining width.
Responsive breakpoint at 768px collapses to single-column with the
TOC becoming a styled block at the top. Chosen over a hamburger
TOC drawer because the current content fits comfortably in the
linear-scroll model, and any complexity there is cost we don't
need yet.

### 4. Prose typography rather than the app's dense board treatment

Line-height 1.6, generous heading margins, `code` pills styled
against a light-grey pill. Different from the rest of the app
(dense task rows) because docs are read linearly, not scanned in
glances. Only applies inside `.docs-content`, so the rest of the
app chrome is unaffected.

### 5. Anchor link from `/import` → `/docs#import-onenote`

Small "Format guide →" link on the /import page mode-selector so
users who show up with raw pasted text have a one-click path to the
rules. Avoids the "I didn't know docs existed" problem common in
tools where the docs nav tab gets ignored.

### 6. `/docs` added to the top nav, after `Print`

Consistent with every other top-level page. Keeps the "user-facing
pages" section of the nav in one unbroken row. `Log out` stays the
trailing link.

### 7. Scope guard: NO parser changes

The backlog scoped this as pure documentation. If writing the docs
surfaced a parser bug, that would have been a separate backlog item.
In practice, no bug was found in the parser during the write-up.

A *different* pre-existing bug was exposed during the Phase-6 +
full-suite run: `recurring_service.compute_previews_in_range` (#32)
bucketed `Task.created_at` by UTC date instead of DIGEST_TZ date,
which made its same-day-collision filter wrong when the user is in
ET after 7–8pm local (UTC has crossed midnight). That's the same TZ-
awareness pattern #28 established for `_local_today_date()`. Fixed
opportunistically in the same commit — one helper block in
`recurring_service`, documented in that commit's message, no test
changes needed (the existing test started passing again).

## Consequences

**Easy:**
- No schema change, no API change.
- Nav expands by one entry.
- Future sections are additive — drop a new `<section id="X">` in
  the template, add one TOC `<li>`, done.

**Hard / accepted trade-offs:**
- Maintenance burden: the docs now have to be kept in sync when
  parser rules or tier semantics change. Mitigated by pinning a
  few verbatim sentences in route tests (e.g. `"One non-empty
  line = one task"`) so a regression that desynced the docs from
  reality would at least break a test — not perfect, but a smoke
  signal.
- In-app docs duplicate some information that also lives in
  docstrings / ADRs / commit messages. Acceptable: the docs are
  user-facing; the others are developer-facing.

## Alternatives considered

- **Inline collapsible help panel only** (original backlog
  recommendation): rejected after the user's direction. Discoverable
  only from /import; would need to be duplicated elsewhere for
  other topics.
- **A `docs/IMPORT_FORMAT.md` linked externally**: rejected.
  Markdown files hosted on GitHub are fine for developers; users
  in the PWA don't go to GitHub.
- **Multi-page hub with `/docs/import`, `/docs/shortcuts`, etc.**:
  premature. One flat page with anchors is simpler; split later if
  content grows past the flat-page sweet spot.
- **Modal documentation popovers** (hover-triggered tooltips on
  specific features): rejected. Good for one-off hints, bad for
  anything you need to read linearly.

## Verification

- **Unit**: 6 new `TestDocsPage` tests — route 200/302/403,
  TOC present with both section anchors, OneNote section contains
  the "one non-empty line = one task" rule verbatim (regression
  guard on docs-vs-reality), nav includes `/docs` on every
  authenticated page, import page has the `/docs#import-onenote`
  link.
- **Phase 6** desktop + mobile:
  - `/docs` renders with correct title, H1, 2 sections, 2 TOC entries
  - TOC link click → URL hash updates + section scrolls near top
  - `/import` has `Format guide →` linking to `/docs#import-onenote`
  - Mobile (375x812): TOC collapses to `position: static`, no overflow,
    content fits, 0 console errors
- **Full suite**: 999 passed, 3 skipped (including the flaky-at-night
  `#32` test now behaving because of the DIGEST_TZ fix).
