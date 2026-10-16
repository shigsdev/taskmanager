# #459 — Gates so the next sibling bug can't be written

Deep review "Structural fixes" (2026-10-11). Checked 2026-10-15.

#459 is an umbrella: "land pieces alongside the rows they serve". Where each
piece stands:

| Piece | State |
|---|---|
| Calendar-day `addDays` + ms-per-day gate | done in #424 |
| `withInflight` / `inflightSubmit` | done in #429 |
| One failure reporter `actionFailureMessage` | done in #430 |
| `createRequestGuard` on reused containers | ✨ Plan (#418), import (#432), Focus / panels / previews (#441); 💡 Auto-categorize is #421 |
| Server length / width validator | done in #447 |
| Payload round-trip tests per review → confirm flow | voice (#425), import, plan, auto-categorize, reflection have them; **/scan builds its confirm payload inline with no test → #490** |
| Phase 6 seed: long / URL titles, archived project with tasks, >200-card tier | not done → **#491** |
| Gate: no `toISOString().slice(0, 10)` dates | **this ship** |
| Gate: no `apiFetch(…).then(…)` statement without `.catch` | **this ship** |
| Jest under `TZ=America/New_York` | only `dst_date_math.test.js` pins it → **this ship** pins the whole run |

## This ship (tests and gates only — no app change)

1. **UTC-date gate** (`tests/test_repo_hygiene.py`): fail when a page script
   (`static/*.js`, or a template's inline script) takes a calendar date with
   `toISOString().slice(0, 10)` / `.substring(0, 10)` / `.substr(0, 10)` /
   `.split("T")[0]`. That is the UTC date: after 8 pm Eastern it is
   tomorrow. Use `dateHelpers.localIsoDate`. Comments are ignored. No
   current offenders (#424 removed them).
2. **Unhandled-`apiFetch` gate** (same file): fail when a statement starts
   with `apiFetch(…)` (or `window.apiFetch(…)`) chained with `.then(…)` and
   no `.catch(…)` in the chain. A rejected fetch there is an unhandled
   promise rejection, and the page silently does nothing. Returned /
   awaited / assigned chains are the caller's business and aren't flagged.
   No current offenders (all five such chains have a `.catch`).
3. **Jest timezone pin**: `jest.config.js` `globalSetup` sets
   `TZ=America/New_York` before any worker starts, so every date test runs
   in the user's zone (with its DST changes) on any machine, CI included.
   `tests/js/unit/timezone_pin.test.js` asserts the offset on each side of
   2026-11-01.

## Tests

- Each gate has a detector test fed known-bad and known-good snippets
  (the #424 pattern), plus the real-tree test.
- The pin is proven by running Jest with `TZ=UTC` in the shell: the pin
  test fails without `globalSetup` and passes with it.

## Found on the way

- **#492** — /architecture's gate tables (including the drift table this ship
  adds to) are wider than a phone screen and their right-hand columns are
  clipped. Present before this ship; filed.
