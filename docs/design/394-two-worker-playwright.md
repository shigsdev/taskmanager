# Spec #394 — local Playwright runs desktop and mobile side by side, each on its own local server

**Filed:** 2026-10-07 (split out of #385)
**Status:** probe done 2026-10-07; user decision "fix #395 first, then build" (done —
#395 shipped 2026-10-08); design approved in chat 2026-10-08. Awaiting written-spec review.
**Test-infrastructure change.** No app code, no UI, nothing on Railway changes. The
"servers" here are throwaway local processes on the developer's PC that exist only
while `run_all_gates.sh` runs.

---

## 1. Why, in numbers (probe, 2026-10-07, same machine and session)

| | Wall clock | Result | Free RAM min / avg |
|---|---|---|---|
| Today: 1 worker, 1 local server | 17.1 min | 498 passed | 327 / 669 MB |
| 2 workers, mobile on its own local server + DB copy | 8.8 / 9.5 / 9.6 min | 497+1 / 498 / 498 | 88 / 462 MB |

The one failure was #395 — a test race on mermaid's `data-processed`, since fixed. So
the expected win is local Playwright ≈ 17 → ≈ 9.5 min, whole gate run ≈ 20 → ≈ 12 min.
The cost is RAM: one more Python process and one more headless Chromium while the
gates run. Hence a one-line way back to today's behaviour (§2a).

## 2. Behaviour after the change

### 2a. `scripts/run_all_gates.sh`

- New knob `PLAYWRIGHT_WORKERS`, default **2**. `PLAYWRIGHT_WORKERS=1` = exactly
  today's run (one local server, one worker). Same idea as the existing
  `PYTEST_WORKERS`; not a skip flag — every test still runs.
- When it is 2, after server A (`:5111`) is up or reused, as today:
  1. `python scripts/clone_dev_db.py <dest>` makes server B's database: a consistent
     copy of the SQLite file server A uses (§2b). Destination
     `instance/dev-mobile.db` (`instance/` is gitignored), overwritten every run.
  2. If something already listens on `:5112`, **fail loudly** — never reuse an
     unknown process as a test server.
  3. Start server B: `DATABASE_URL=sqlite:///<abs path to dev-mobile.db> python
     scripts/run_dev_bypass.py --port 5112`, log to `/tmp/run_all_gates_bypass_mobile.log`;
     same 60 s readiness probe as A (`127.0.0.1:5112/healthz`).
  4. Export `PW_WORKERS=2` and `PW_MOBILE_BASE_URL=http://127.0.0.1:5112` for the
     Playwright run.
- The existing EXIT/INT/TERM cleanup trap also stops server B (by PID, plus whatever
  still holds `:5112`) and deletes `instance/dev-mobile.db`. Server A's handling is
  unchanged (still reused if already running, still only stopped if we started it).
- The per-gate timing table (#385) records the result; no other gate changes.

### 2b. `scripts/clone_dev_db.py` (new)

- Resolves the database the app would use: `DATABASE_URL` from the environment, else
  from `.env`, else `sqlite:///dev.db`; a relative SQLite path resolves against
  `<repo>/instance/` (Flask-SQLAlchemy 3.1's rule), an absolute one is used as is.
- **Refuses anything that is not SQLite** (exit 2, clear message) — it can never read
  from or write to Postgres.
- Copies with `sqlite3.Connection.backup()`, so the copy is consistent even when
  server A is a dev server that is mid-write.
- Prints the absolute destination path (forward slashes) for the gate script to use.

### 2c. `playwright.config.js`

- `workers: Number(process.env.PW_WORKERS || 1)` — a manual `npx playwright test`
  stays serial on one server, exactly as today; only the gate script, which provides
  server B, turns parallelism on.
- Each local project (`chromium`, `chromium-sw`, `chromium-mobile`) gets
  `workers: 1` (Playwright ≥ 1.52 per-project cap): within a project tests stay
  serial, as today; only *different* projects run side by side.
- `chromium-mobile` uses `PW_MOBILE_BASE_URL`, falling back to `LOCAL_BASE_URL`.
- `chromium-sw` stays on server A and may overlap desktop there (6 short service-worker
  tests in their own browser contexts; overlapped in all 3 probe runs without issue).
  Making it depend on `chromium` instead would skip it whenever a desktop test fails,
  hiding results.
- `chromium-prod` untouched.

### 2d. What does not change

The tests themselves, which projects run, `retries: 0`, the prod smoke suite, and
Railway. Mobile now starts from a copy of the DB as it was at gate start, rather than
after desktop's tests — the probe showed no test depends on desktop's leftovers.

## 3. Tests

- **Jest** `tests/js/unit/playwright_config.test.js` (extended): with no env, global
  `workers` is 1 and mobile targets `127.0.0.1:5111`; with `PW_WORKERS=2` +
  `PW_MOBILE_BASE_URL`, global `workers` is 2 and mobile targets `:5112`; every local
  project has `workers: 1`. Loaded via `jest.isolateModules` so the env is read fresh.
- **pytest** `tests/test_clone_dev_db.py` (new): relative URL → `instance/…`; absolute
  URL kept; a `postgresql://` URL is refused with exit 2 and no file written; the copy
  has the same rows as the source; source untouched.
- **Proof:** two full gate runs at the default (expect Playwright ≈ 9–10 min, all
  pass), and one with `PLAYWRIGHT_WORKERS=1` (expect today's ≈ 16–17 min, one server)
  to show the fallback works. Each log must contain exactly one `EXIT=` line.

## 4. Docs

- `CLAUDE.md` "Local-dev gotchas": one bullet — the gates run desktop and mobile
  Playwright side by side on two local servers; if RAM is tight (free memory reached
  88 MB in the probe on a 7.3 GB machine) run with `PLAYWRIGHT_WORKERS=1`. SOP change
  → called out in the commit message (cascade row "new SOP rule").
- Header comment of `run_all_gates.sh` documents `PLAYWRIGHT_WORKERS`.

## 5. Out of scope

- More than 2 workers, or splitting a project across workers — RAM-bound here.
- Automatic RAM detection to pick the worker count — YAGNI; the knob is enough.
- Speeding up pytest (157 s at `PYTEST_WORKERS=2`) — separate if wanted.
