# Spec #402 — parallel Playwright lanes: N workers, each on its own server and DB copy

**Requested:** 2026-10-09 (user: "clean runs at enhanced speeds"); approach
approved the same day ("measure 4/6/8 lanes and pick").
**Test tooling only** — `playwright.config.js`, a new e2e fixture, the spec
files' import line, `scripts/run_all_gates.sh`. No app code → no Phase 6, no
`CACHE_VERSION`. Builds on #394 (`docs/design/394-two-worker-playwright.md`).

---

## 1. Why, in numbers (gate run 2026-10-09, 13:46–13:55, Node 24.20)

| Phase | Time |
|---|---|
| ruff + pytest (`PYTEST_WORKERS=2`) | 34 s |
| Jest | 2 s |
| two local servers up | 7 s |
| **local Playwright** | **7 m 33 s** |
| docs/arch/backlog checks, bandit, audits, semgrep, gitleaks | 11 s |
| **total** | **8 m 27 s** |

Playwright is 89 %. #394 runs two lanes — desktop + SW on :5111, mobile on
:5112 — with every project capped at one worker, so the run is as long as the
slower lane: ~7 min of `pages.spec.js` (228 tests; no test over ~6.5 s). #394
left "more than 2 workers, or splitting a project across workers" out of scope
as **RAM-bound on a 7.3 GB machine** (free RAM hit 88 MB). This machine:
32 GB, 32 cores.

Tests cannot share a DB (one reflection draft per user, milestones, weekly
focus …), which is why each lane needs its own server. No spec uses
`describe.serial`, `beforeAll` or `afterAll`, so tests can be spread across
workers freely.

## 2. Behaviour after the change

### 2a. Lanes

- `PLAYWRIGHT_WORKERS=N` (gate knob, default chosen by §4's benchmark) starts
  **N** throwaway local dev-bypass servers on **:5111 … :5111+N−1**. Lane 0 is
  the existing :5111 server on the dev DB (as today); lanes 1…N−1 each run on
  their own consistent copy (`scripts/clone_dev_db.py`,
  `instance/dev-lane-<i>.db`). All torn down by the existing EXIT trap.
- The gate exports `PW_WORKERS=N` and `PW_LANE_BASE_PORT=5111`.
- `tests/e2e/lane.js` exports `test` / `expect` with one override: the
  `baseURL` option becomes `http://127.0.0.1:<PW_LANE_BASE_PORT +
  testInfo.parallelIndex>`. Playwright guarantees a worker's `parallelIndex`
  is unique among running workers (0…N−1), so **no two concurrent workers ever
  share a server or DB**. The rule is a pure function in
  `tests/lane_base_url.js` (Jest-tested): it only rewrites a local
  `http://127.0.0.1:` base URL, only when `PW_LANE_BASE_PORT` is set — prod
  smoke and plain local runs are untouched.
- Every e2e / e2e-sw spec imports `test`/`expect` from `./lane` instead of
  `@playwright/test` (one line each, 8 files).
- `playwright.config.js`: `chromium` and `chromium-mobile` get
  `fullyParallel: true` and lose their `workers: 1` cap, so `pages.spec.js` is
  spread across lanes; `chromium-sw` keeps `workers: 1` (8 tests).
  `PW_MOBILE_BASE_URL` / server B are retired — mobile is just another lane
  user.
- `PLAYWRIGHT_WORKERS=1` = exactly today's single-server serial run (no clone,
  no `PW_LANE_BASE_PORT`). The old `=2` meaning ("mobile on :5112") becomes
  "two lanes" — same isolation, better balance.

### 2b. Safety

- A port already in use refuses to start, as #394 does for :5112, for every
  lane port.
- Each lane's server must answer `/healthz` within 60 s or the gate fails.
- Upper bound `PLAYWRIGHT_WORKERS ≤ 8` (ports 5111–5118) — a typo can't spawn
  dozens of servers.

## 3. Tests

- `tests/js/unit/lane_base_url.test.js`: lane mapping, prod URL untouched,
  no-env passthrough, lane 0 = 5111.
- `tests/js/unit/playwright_config.test.js` (#385/#394) updated: chromium and
  mobile are fully parallel with no per-project cap; SW stays capped at 1;
  `PW_WORKERS` sets the total; prod project unchanged.
- The real proof is §4: full suites at 4 / 6 / 8 lanes, then the chosen
  default repeated, all green.

## 4. Benchmark → default

Full gate runs at `PLAYWRIGHT_WORKERS` = 4, 6, 8 on this machine: Playwright
wall clock, total wall clock, failures, free-RAM minimum. Default = the fastest
count with zero failures and comfortable RAM headroom, then 3 consecutive green
runs at that default before shipping. Results recorded here.

Measured 2026-10-09, Node 24.20, one gate run at a time (TIME_WAIT = loopback
sockets sampled every 5 s with `netstat`; Windows' ephemeral pool is 16,384
ports, `netsh int ipv4 show dynamicport tcp`):

| Lanes | Gate run | Playwright | Failures | TIME_WAIT peak |
|---|---|---|---|---|
| (before, 2 servers) | 8m27s | 7m33s | 0 | — |
| 4 | 4m53s | 3.9 min | 0 | 10,229 (62%) |
| 6 | 3m58s | 2.7 min | 0 | 14,084 (86%) |
| 8 | — | 2.3 min | **14** | pool exhausted |

Free RAM (sampled every ~5 s on the first round of runs) is noisy and does not
track lane count: the 4-lane run dipped to 50 MB for one sample (pytest and
server start-up) and under 500 MB once early in Playwright, while the 8-lane
run never dropped below 5.4 GB. Typical free RAM during Playwright was 6–12 GB.

**The limit is ports, not RAM or CPU.** All 14 failures at 8 lanes were on
`/goals` tests in a 20-second window across several lanes: `page.goto:
net::ERR_ADDRESS_IN_USE`, or a chip that never rendered because the page's own
API call failed the same way. Werkzeug's dev server sends `Connection: close`
on every response (deliberately: werkzeug 3.1.6 `serving.py`, "Always close
the connection"), so every page, static file and API call takes a new loopback
port that then sits in TIME_WAIT for ~2 min. There is no switch: setting the
handler to HTTP/1.1 was tried and Werkzeug still closes (it already uses
HTTP/1.1 when threaded).

**Default: 4.** 6 passed once but used 86% of the pool, which is a flake
waiting for a busy machine. Going past 4 needs a keep-alive-capable local
server (e.g. waitress) for the lane servers: filed as #403.

**Update (#403, same day):** the lane servers now run on waitress; 8 lanes
peak at 6.7k TIME_WAIT (41%) and the default is 8 (gate run 3m08s–3m40s over 4 runs). See
`docs/design/403-keepalive-lane-servers.md` §4.

## 5. Docs

- `CLAUDE.md` "Local-dev gotchas": the #394 bullet becomes the lanes bullet
  (N servers, the knob, `=1` fallback). SOP change → called out in the commit.
- `run_all_gates.sh` header documents the knob.
- `/architecture` testing section: update if it describes the two-server run.

## 6. Out of scope

- pytest speed (34 s) — user chose Playwright only.
- Splitting `pages.spec.js` into several files.
