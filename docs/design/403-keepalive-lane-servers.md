# Spec #403 — keep-alive local test servers, to lift the 4-lane Playwright ceiling

Status: built 2026-10-09 — default 8 lanes (§4). Follow-up to #402.

## 1. Why

#402 runs local Playwright on N "lanes", each a throwaway dev-bypass server.
It stopped at 4 because the servers are Werkzeug's dev server (`flask run`),
which sends `Connection: close` on every response (deliberate in werkzeug
3.1.6 `serving.py`; HTTP/1.1 does not change it, tried in #402). Every page,
static file and API call therefore takes a new loopback port that sits in
TIME_WAIT for ~2 min. Windows' ephemeral pool is 16,384 ports:

| Lanes | Playwright | TIME_WAIT peak | Result |
|---|---|---|---|
| 4 | 3.7–4.1 min | 10.0–11.1k | green ×5 |
| 6 | 2.7 min | 14.1k (86%) | green once, no headroom |
| 8 | 2.3 min | exhausted | 14 failures, `net::ERR_ADDRESS_IN_USE` |

## 2. Change

`scripts/run_dev_bypass.py` — the ONE launcher for the local bypass server
(gate lanes, `preview_start taskmanager-dev-bypass`, ad-hoc) — serves the app
with **waitress** instead of handing off to `flask run`. Waitress is a
pure-Python, cross-platform production WSGI server that keeps HTTP/1.1
connections open, so a browser reuses a handful of sockets per lane instead
of opening one per request.

- Everything before the hand-off is unchanged: Railway tripwire, the
  `.env.dev-bypass` file gate, `.env` + `.env.dev-bypass` loading,
  `FLASK_ENV=development`, rate limiter off (#385). The app is imported only
  after those (`from app import app`, the same module-level app gunicorn
  serves), so the bypass banner still prints at app creation.
- Arguments: `--port N` (default 5111), the only one any caller passes
  (`.claude/launch.json` passes none; `run_all_gates.sh` passes `--port`).
  Anything else is refused by argparse instead of silently ignored.
- Binds `127.0.0.1` only (same as `flask run`'s default).
- Thread pool: waitress has a fixed pool (`flask run` spawned a thread per
  request). One lane = one Playwright worker = one page at a time, which
  opens ≤ 6 connections; pool size picked so a lane never queues (see §4).
- `waitress` goes in `requirements-dev.txt` (pinned; pip-audit gate 6 already
  audits that file). Prod is unchanged: Railway runs gunicorn from
  `requirements.txt` and never runs this script.

What we lose: Werkzeug's per-request access log lines in the bypass log /
`preview_logs`. Nothing parses them (checked: no test, script or gate reads
`run_all_gates_bypass*.log` contents beyond printing them on a failed start).
App-level logging (`app_logs`, stderr) is unchanged.

## 3. Tests

- `tests/test_auth.py::TestRunDevBypassScript` — the in-process test that
  patched `flask.cli.main` now patches the serve hand-off and asserts the
  limiter is already off and the port was parsed when it is reached.
- New: a real waitress server built by the script's own helper serves a
  page, JSON and a static file over ONE TCP connection (the property the
  whole change exists for). Plus: port defaults to 5111; binds 127.0.0.1.
- New: unknown arguments are refused (exit non-zero) before the app imports.
- The real proof is §4.

## 4. Benchmark → new default

Full gate runs at `PLAYWRIGHT_WORKERS` = 4, 6, 8 with TIME_WAIT sampled every
5 s. Default = fastest count with zero failures and the TIME_WAIT peak well
under the pool (target < 50%). Then 3 consecutive green runs at that default
and one at `PLAYWRIGHT_WORKERS=1`. Results recorded here.

Measured 2026-10-09 on waitress (`SERVER_THREADS = 8`), one run at a time:

| Lanes | Gate run | Playwright | Failures | TIME_WAIT peak | (Werkzeug, #402) |
|---|---|---|---|---|---|
| 4 | 4m56s | 3.9 min | 0 | 3,896 (24%) | 10.0–11.1k |
| 6 | 3m33s | 2.5 min | 0 | 5,767 (35%) | 14.1k |
| 8 | 3m08s | 1.9 min | 0 | 6,683 (41%) | exhausted, 14 failures |

Keep-alive cut TIME_WAIT per run by ~60–65% at the same lane count. What is
left is mostly browser contexts closing their sockets at the end of each test
(every test gets a fresh context), which no server change removes.

Proof at the default: 3 consecutive full gate runs at 8 lanes — 216 / 210 /
220 s, Playwright 515 passed in 2.1 / 2.2 / 2.1 min, 0 failures, TIME_WAIT
peak 6.4–6.7k — plus one at `PLAYWRIGHT_WORKERS=1` (515 passed, 15.3 min,
peak 1.4k). All `ALL GATES GREEN`.

**Default: 8** (`LANE_MAX`). Going past 8 would need `LANE_MAX` raised and a
fresh TIME_WAIT measurement; returns are already shrinking (6 → 8 saved 0.6
min of Playwright).

Waitress detail found while testing: it keeps a connection open only when the
response has a Content-Length, and closes after a chunked one. Flask sets
Content-Length on everything this app returns (pages, JSON, static files —
the keep-alive test covers all three); nothing streams.

## 5. Docs

- `CLAUDE.md` local-dev lanes bullet: new default, why the ceiling moved.
- `run_all_gates.sh` header + default comment.
- `templates/architecture.html` gate-4 row (lane count).
- `docs/design/402-…` §4 gets a pointer here.

## 6. Out of scope

- pytest speed.
- Widening the OS port range / shortening TIME_WAIT (machine settings).
- Prod's server (gunicorn) — untouched.
