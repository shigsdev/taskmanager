# Spec #385 — faster gate runs: local Playwright talks to 127.0.0.1, and every gate is timed

**Filed:** 2026-10-04 (user request: "speed up the tests while not sacrificing quality")
**Status:** scope approved 2026-10-07 — "fix + timing now, parallel later";
design approved in chat 2026-10-07. Awaiting written-spec review.
**Test-infrastructure change.** No app code, no UI, nothing deployed changes.

---

## 1. What we measured (2026-10-07, this machine: Ryzen 3 4300G, 4C/8T, 7.3 GB)

Over the last full gate run (`498 passed (39.3m)`, whole run ≈ 45 min):

| Slice | Time | Tests | Per test |
|---|---|---|---|
| `chromium` `pages.spec.js` | 1100 s | 234 | 4.7 s |
| `chromium-mobile` `pages.spec.js` | 971 s | 202 | 4.8 s |
| SW specs (both projects) | 133 s | 11 | 12 s |
| `ui_audit` (both) | 84 s | 40 | 2.1 s |
| everything else in Playwright | 43 s | 11 | — |
| pytest + Jest + ruff + scanners (parallel) + sync | ≈ 6 min | — | — |

No outlier tests (median 4.4 s): the cost is a fixed overhead paid by
every test. Hard-coded `waitForTimeout`s total ≈ 30 s per viewport — not it.
Flakes are not it either right now: 6 of 6 complete runs this session were
green first time.

**Root cause of the overhead.** The dev-bypass server listens on IPv4 only
(`127.0.0.1:5111`). The local Playwright projects use
`baseURL: "http://localhost:5111"`. Chromium on Windows tries `::1` first
for `localhost` and only falls back to IPv4 after ≈ 300 ms — on **every
new connection**, and a page load opens ~28 of them (HTML, CSS, ~18 JS
files, ~8 API calls). Node's `fetch` to the same URL answers in 16–24 ms,
so the server is not slow.

| Same page `/?nosw=1`, same server | via `localhost` (today) | via `127.0.0.1` |
|---|---|---|
| HTML TTFB | 322 ms | 14 ms |
| `load` | 1552 ms | 294 ms |
| `load` + `networkidle` | 2886 ms | 1065 ms |
| 29 real `pages.spec.js` tests (`chromium`) | **2.2 min** | **1.0 min**, all pass |

Google Fonts (one external request) made no measurable difference.

## 2. Behaviour after the change

### 2a. Local Playwright uses 127.0.0.1 — `playwright.config.js`

- One constant, `LOCAL_BASE_URL = "http://127.0.0.1:5111"`, used by the
  three local projects: `chromium`, `chromium-sw`, `chromium-mobile`.
  A comment records the IPv6-fallback cause and the numbers above, so
  nobody "tidies" it back to `localhost`.
- `chromium-prod` is untouched (it targets the Railway URL).
- Nothing else in `tests/e2e*` names the host (checked: the three
  `baseURL` lines are the only references), and the app has no host
  checks, so tests are unchanged. `127.0.0.1` is a secure context for
  service workers exactly as `localhost` is.

### 2b. The gate script uses the same address — `scripts/run_all_gates.sh`

The two bypass readiness probes (`curl …localhost:5111/healthz`, "already
running?" and "wait for ready") move to `127.0.0.1` so the script and the
tests reach the server the same way. Behaviour is otherwise identical
(still reuses a running server, still trap-cleans one it started).

### 2c. Every gate is timed — `scripts/run_all_gates.sh`

- `banner()` closes the previous section by printing
  `⏱ <section>: <N>s` before opening the next one (bash `$SECONDS`).
- On the green path, just before `ALL GATES GREEN`, a summary table lists
  every section's duration and the total.
- The security scanners 5–10 already run in parallel and are joined in
  one phase; they are reported as that phase, not per scanner.
- No change to which gates run, their order, or any pass/fail logic. The
  script's "no skip flags" rule stands.

### 2d. The local test server runs without rate limiting — `scripts/run_dev_bypass.py`

Found in the first full run on the branch: Playwright **39.3 → 17.0 min**,
but 2 tests failed (one per viewport, both in "Reflection - continuing a
past reflection (#334)"). The page said "Couldn't load history." and the
bypass log showed `GET /api/reflection` → **429** ×11 in two bursts. That
route has no limit of its own, so it gets the app default of **200 per
minute per route, keyed by client IP** — and every Playwright test shares
one IP. The reflection tests reload that page constantly (2,549 requests in
the run); at the old pace they stayed just under 200/min, at ~2× they
didn't. The speed-up was right; the shared prod limit on a test fixture was
the latent problem (and parallel workers would hit it harder).

User decision 2026-10-07: turn the limiter **off in the local bypass server
only**. `run_dev_bypass.py` gains `_disable_rate_limiting()`, called after
all its safety gates pass and before `flask run` imports the app: it sets
the shared `rate_limit.limiter.enabled = False`, which Flask-Limiter 4.1's
`init_app` keeps when the app config has no `RATELIMIT_ENABLED`. It first
puts the repo root on `sys.path` — a real `python scripts/run_dev_bypass.py`
has `scripts/` there instead, and the import failed on the first try.

- Same stance `tests/conftest.py` already takes for unit tests ("rate
  limiting is a prod concern, exercised in prod").
- No app code changes; nothing deployed; prod limits stand (Railway never
  runs this script, and it refuses on any `RAILWAY_*` var).
- No local test relies on the server limiter (the one "rate limits" e2e
  test checks the browser-side error-report throttle and stubs the route).
- Trade-off accepted: during local dev the paid-API routes are unthrottled
  on your own machine.

Verified: a real launch answers 250 rapid `GET /api/reflection` with 250×200.

## 3. Tests

- **Jest** — new `tests/js/unit/playwright_config.test.js`: `require`s
  `playwright.config.js` and asserts each local project's `baseURL`
  hostname is `127.0.0.1` and `chromium-prod`'s is not. Red today
  (they are `localhost`). Guards against drifting back.
- **pytest** (`tests/test_auth.py::TestRunDevBypassScript`):
  `test_script_turns_rate_limiting_off_before_flask_starts` — `main()`
  with every gate passing and a stubbed `flask run` sees the limiter
  already off (red before). `test_rate_limit_switch_works_from_a_real_launch`
  — runs the helper in a fresh interpreter from an unrelated cwd (red
  without the `sys.path` fix: `ModuleNotFoundError: rate_limit`).
- The timing lines are output only; they are exercised by the real gate
  run in §4 rather than a unit test.
- Existing guards still apply: `tests/test_architecture.py` spot-checks
  gate names in the script (unchanged), `test_repo_hygiene.py` scans it
  for NUL bytes.

## 4. Proof of the win

One full `run_all_gates.sh` on the branch, compared with today's
`498 passed (39.3m)`: same 498 tests, all passing, Playwright expected
≈ 18 min (29-test sample was 2.2 → 1.0 min). The new per-gate table is
the record. The commit trailer and the ship-mark cite both numbers.

## 5. Out of scope (recorded so they aren't lost)

- **Parallel isolated Playwright workers** (row option 3) — filed as a new
  BACKLOG item at ship time, to be decided with the post-change numbers.
  On a 4-core / 7 GB machine its RAM and complexity cost may no longer pay
  for itself once each test is ~2× faster.
- **Make the bypass server answer on IPv6 too**, so `http://localhost:5111`
  is also fast for Phase 6 browsing and Claude Preview. Werkzeug dual-stack
  on Windows is fiddlier than a `baseURL`; noted, not done.
- **Flake work** (row option 1) — not the cost today (6/6 green); #348 /
  #384 stay open on their own merits.
- Running fewer tests, skipping mobile, or adding retries — explicitly
  not on the table (unchanged from the row).
