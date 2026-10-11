# #418 — A closed ✨ Plan can't write into the next one

Filed 2026-10-11 by the #406 spec §5. The board's ✨ Plan pop-up
(`#weeklyFocusPlanModal`, driven by `static/weekly_focus.js`) is one shared
dialog used by both planners: ✨ Plan on a slot and ✨ Plan week. Nothing ties
an answer to the request that asked for it.

## 1. Surface

Every async completion that writes into the shared dialog:

| Completion | Writes | Race today |
|---|---|---|
| `_runPlan` — planner POST resolves | label stays; hides loading; fills `pendingChanges`, the rows and the Apply button | Open A, close it (✕ / Cancel / backdrop / Escape), open B. If A answers after B, A's rows sit under B's label and Apply applies A's changes. If A answers while the dialog is closed, it fills the hidden dialog (harmless, but pointless). |
| `_runPlan` — planner POST rejects | shows "Couldn't reach the planner" | Same: A's error can replace B's rows. |
| `applyPlan` — its PATCH/POST loop | reads `pendingChanges[i]` live on each step; at the end closes the dialog or rewrites the Apply button | Close mid-apply: `closeModal` empties `pendingChanges`, so the loop quietly stops part-way. Close and open B mid-apply: once B answers, the loop carries on through **B's** changes from index *i* (all ticked by default) without anyone clicking Apply, then closes B. |

The last row is the worst one, and it is the same root cause: a completion
that doesn't check it still owns the dialog.

## 2. This ship

1. New helper `static/request_guard_helpers.js` (dual export,
   `window.requestGuardHelpers` / `module.exports`):
   `createRequestGuard()` returns `{ begin, isCurrent, cancel }`.
   `begin()` returns a new token and makes it the only current one;
   `cancel()` makes no token current; `isCurrent(t)` says whether `t` is
   still the live one. Generic on purpose: #421 reuses it.
2. `_runPlan` takes a token on open and drops its answer (success or error)
   unless the token is still current.
3. `closeModal` cancels the token, so an answer that arrives after close is
   dropped too.
4. `_runPlan` also resets the Apply button (`disabled = false`), so a new
   plan never inherits "Applying…" from an older apply.
5. `applyPlan` works on a **snapshot** of the changes the user approved, and
   remembers the token it started under:
   - it never reads a newer plan's changes;
   - **closing mid-apply no longer stops it part-way.** Apply was clicked,
     so the approved changes all go through and the board reloads.
     Stopping silently half-way, with no report of what landed, is the
     worse outcome;
   - at the end it only closes the dialog, or rewrites the Apply button,
     if its token is still current. It always reloads the board.
6. Cascade for a new static asset: `sw.js` APP_SHELL + CACHE_VERSION,
   `health.py` EXPECTED_STATIC_FILES, a script tag in `templates/index.html`
   before `weekly_focus.js`.
7. Tests:
   - Jest (`tests/js/unit/request_guard_helpers.test.js`): begin / isCurrent
     / cancel, a newer begin supersedes, cancel invalidates every token.
   - Playwright, desktop + mobile, with the planner POST held open by a
     route: open A, close, open B, answer B, then answer A — the dialog
     shows B's label and B's rows only. Close mid-request and let it answer:
     the dialog stays hidden and empty. Apply A with its PATCH held, close,
     open B (two changes) and let it answer, release A's PATCH: no request
     goes out for B's tasks, and B stays open with "Apply (2)" enabled.
     All three fail on the old code.
8. Help (`docs.html`, "Planning against your focus"): one sentence — close
   the pop-up while the planner is still working and that answer is
   dropped.

## 3. Out of scope (filed)

- **#421** — 💡 Auto-categorize (`static/inbox_categorize.js`) has the same
  race: `openModal` awaits three requests and writes into the shared dialog
  unchecked, and `applyAll` closes the dialog at the end even if a newer
  one is open. Lower impact (one endpoint, same inbox), same fix with the
  #418 guard.
- **#422** — ✨ Plan's "Apply remaining (N failed)" re-runs the whole list,
  so a `create_new` that succeeded the first time is created again. The
  retry should skip changes that already landed (Auto-categorize already
  does: it removes each applied row).
