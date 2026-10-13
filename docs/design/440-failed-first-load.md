# #440 — A failed first load leaves dead or misleading pages

Deep review 2026-10-11 §B6. Full surface mapped 2026-10-12 (every page's
first load traced: what it binds, what a failure shows).

## Before

| Surface | On a failed first load |
|---|---|
| /goals | Listeners bound **after** the load → blank board, dead New / filter buttons. A later app.js refresh drew cards whose panel had **no working ✕, backdrop, Escape or Save** (Save did a native page reload). |
| /projects | The same, plus the goal filter never got its options. |
| Board (/ and /tier/<name>) | `alert("Could not load tasks…")` (again on every 60 s poll), then every section drawn empty: Inbox reads **"All caught up — inbox is empty"**, counts 0. |
| /calendar | Any failed refresh (poll, tab focus, save, range switch) **replaced a populated calendar with empty days**. |
| Completed / Cancelled | "Loading..." forever; the section was already marked loaded, so re-opening never retried; counts kept the template's "0". |
| Weekly Focus panel | Blank; and if the goals list loaded while the focus didn't, **3 empty editable slots** were drawn from the default state — typing replaced saved text the user never saw. A failed tab switch left the other week's slots editable under the new tab. |
| /recurring | Blank list; bulk Project / Goal menus offered only "(none)". |
| /recycle-bin | "Loading…" forever, blank lists. |
| /settings | "--" stats, empty tables, **"Recycle Bin (0)"**. |

## Fix

One shared helper, `static/load_error_helpers.js` (global via base.html):
`showLoadError(container, what, err, onRetry)` draws
"Couldn't load <what>. <server reason>" and a **Retry** button
(`role="alert"`; the reason is text, never markup; apiFetch's own
reload prompt isn't repeated). Each surface:

- **/goals, /projects:** filters, buttons, panel and touch listeners are
  bound **before** the first load. The load is wrapped: a failure shows
  the message in the board with Retry. The projects goal filter fills
  after a successful load (or its retry).
- **Board:** no alert. Until `/api/tasks` has answered once
  (`tasksLoaded`), the board isn't drawn and a banner sits above it
  (`#boardLoadError`) with Retry; the 60 s poll also retries. After a good
  load, a failed refresh keeps what's on screen silently (as before).
- **/calendar:** a failed tasks fetch stops the render — what was drawn
  stays — and a banner says "Couldn't load the latest tasks (showing
  what loaded earlier)", or "your tasks" before anything loaded.
- **Completed / Cancelled:** the error with Retry, the "loaded" mark is
  dropped (re-opening retries), counts read "–".
- **Weekly Focus:** slots are drawn only from a loaded week
  (`focusLoaded`); a failed load replaces them with the message and
  disables Plan week.
- **/recurring:** the message with Retry in the list (first load only; a
  failed refresh keeps the list).
- **/recycle-bin:** a box under the summary row (it holds Empty Bin)
  and one in Deleted tasks, each with Retry.
- **/settings:** a box per section (overview, service status, import
  history) with Retry; the bin count reads "?" on failure and "…"
  before it loads (was a hard-coded "0").

Out of scope (noted, not filed): the calendar's recurring-preview fetch
still falls back to none on failure (the tasks are what matter; previews
reappear on the next refresh); /settings' weekly-focus slot count keeps
its default on failure.

## Tests

- Jest `load_error_helpers.test.js`: text, the reason, no repeat of a
  notified error, Retry wiring, text-not-markup, clear.
- Playwright (7, all red on the old pages): each surface with its load
  stubbed to 500 — the message, buttons/panels still working where they
  apply, no alert, no "All caught up", calendar not wiped, Completed
  retries, no editable focus slots, and Retry recovering.
