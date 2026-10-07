# Spec #362 — pytest never writes audit results into the real BACKLOG.md

**Filed:** 2026-10-01 (during #355's ship)
**Status:** approved to build 2026-10-07 (user picked #362); no open decisions
**Test-only change.** No app code, no UI; nothing deployed changes behaviour.

---

## 1. The problem (root cause confirmed 2026-10-07)

Every audit runner in `utilities_api.py` ends by calling
`scripts.backlog_autofile.run_for_audit(...)`, which reads and rewrites
`backlog_autofile.BACKLOG_PATH` — hard-wired to the repo's real
`BACKLOG.md`. Tests reach that call without mocking it:

| Path | Tests that leak | Row it rewrites |
|---|---|---|
| `_run_audit_script_checks` via `/api/utilities/run-bug-pattern-scan` (also security-posture, tech-debt) | `test_inline_scan_aggregates_findings_from_mocked_checks` injects a fake `bare-1fr-grids` finding at `static/style.css` line 42 "bare 1fr"; the real-CHECKS smoke tests then report 0 findings and mark it resolved | `bug-pattern/bare-1fr-grids/static-style.css` |
| `_run_coverage_audit_subprocess` | the direct calls in `TestCoverageAuditAsync` with fabricated payloads (one carries an `overall-coverage-drift` finding) | `coverage/overall-coverage-drift/` |

Result: every full gate run rewrites those two rows' "last seen" / status
cells to today, and the operator has to revert them by hand before every
commit (done on every ship this week). A real drift could be marked
resolved by a test, or a resolved one re-opened, and the row's state tracks
test ordering rather than the codebase.

**Sibling hole on the same call path.** After autofiling, the inline-scan
routes call `_dispatch_audit_workflow_for_autofile`, which POSTs a
`workflow_dispatch` to GitHub when `GITHUB_DISPATCH_TOKEN` is set. It is
not set on this machine, so today it fails closed — but a test run in any
environment that has the token would fire real GitHub Actions runs.

## 2. Behaviour after the fix

One autouse fixture in `tests/conftest.py` — so no future test can forget
it — applied to every test:

- `backlog_autofile.BACKLOG_PATH` → a per-worker temp path that **does not
  exist**. An unrelated test that reaches the autofile step now hits the
  existing `FileNotFoundError` handling (logged and swallowed, exactly as
  in prod when the file is missing) instead of writing anywhere. Tests that
  *want* an upsert (`tests/test_backlog_autofile.py`'s `temp_backlog`)
  set their own path after the autouse fixture runs, so they are
  unaffected. Not a per-test copy of the 1 MB file: nothing outside
  `test_backlog_autofile.py` needs the content.
- `GITHUB_DISPATCH_TOKEN` is removed from the environment. Tests that
  exercise dispatch already `setenv` it themselves (after the autouse
  fixture) and mock the HTTP call.

## 3. Tests (written first, red today)

In `tests/test_backlog_autofile.py`, a new `TestRealBacklogIsolation`:

1. `test_autofile_never_points_at_the_real_backlog` — inside an ordinary
   test, `backlog_autofile.BACKLOG_PATH` is not
   `<repo>/BACKLOG.md`. Red today (it is).
2. `test_audit_runners_leave_real_backlog_untouched` — hash the real
   `BACKLOG.md`, POST a bug-pattern scan with a synthetic finding carrying
   a unique sentinel path, run `_run_coverage_audit_subprocess` with a
   fabricated drift payload, re-hash: bytes identical, and the sentinel
   never appears in the file. Red today (the sentinel row is written).
3. `test_tests_never_hold_a_github_dispatch_token` — the env var is absent.

## 4. After it ships

- The two audit rows already match the last bot-authored state
  (`3abd937` / `6c74aa5`, 2026-10-02/03), so nothing to restore.
- Gate runs stop dirtying `BACKLOG.md`; the per-ship manual revert step
  goes away.

## 5. Out of scope

- Whether the `bare-1fr-grids/static-style.css` row was itself first
  created by this test (first seen 2026-05-27, the day #243 landed, with
  the test's exact "line 42: bare 1fr" text). It is marked resolved; the
  bot owns that section. Note it on the ship-mark, don't hand-edit it.
- #385 (gate speed) — separate item.
