# Spec #384 — the dev bypass logs once per process, not once per request

Status: building (2026-10-09). Supersedes the per-request audit line in
ADR-002 (see ADR-039).

## 1. Why, in numbers

Under `LOCAL_DEV_BYPASS_AUTH`, `login_required` logs
`LOCAL_DEV_BYPASS_AUTH served <METHOD> <path> as <email>` at WARNING on every
request, and `DBLogHandler` (level WARNING) persists each one to `app_logs`.
Measured on one full gate run, 2026-10-09 (`bash scripts/run_all_gates.sh`,
8 lanes):

- lane 0's database (`instance/dev.db`) received **1,041** `app_logs` rows,
  **976 (94%)** of them this line. 8 lanes ⇒ ~7,800 SQLite inserts per run,
  each one inside the request, competing with the request's own writes
  (lock waits; #383 traced its `DBLogHandler insert failed` lines here).
- The table is capped at `MAX_ROWS = 10_000`, so the bypass line also evicts
  the rows anyone actually looks for: the dev DB's whole log is ~2 hours deep
  and 97% bypass noise.

## 2. Change

`auth.login_required`, bypass branch:

- The **first** bypass-served request in a process logs at **WARNING**
  (persisted, same audit fields as today: method, path, email — redacted
  by the existing scrubber), with "further requests log at DEBUG" in the
  message so nobody hunts for the missing rows.
- **Every** bypass-served request logs at **DEBUG**: method + path. Below
  the handler's default WARNING level, so not persisted; visible on stderr
  / `APP_LOG_LEVEL=DEBUG` when someone wants the full trail.
- "First" is tracked by a module-level flag behind a lock — the bypass
  server runs a waitress thread pool (#403), so two first requests can
  race.

Unchanged: the four gates and their order; the startup banner (stderr +
one WARNING row to `app_logs` per boot, `log_bypass_startup_banner`); the
validator-cookie and voice-action per-request lines (those are prod
credentials and stay per request).

What the audit trail still shows for any bypass session: the boot (banner
row) and the first request served (WARNING row), both in `app_logs` — i.e.
"the bypass was active, from when, and it served traffic". What it no
longer persists: the per-route list. That list was the ADR-002 rationale
"audit exactly which routes were touched"; in practice it is a test
fixture's traffic (the gate's Playwright lanes), the bypass can only run
locally (four gates + the launcher's tripwire), and the per-route detail
is still one env var away (`APP_LOG_LEVEL=DEBUG`).

## 3. Tests (`tests/test_auth.py`)

- first bypass request → exactly one WARNING with method, path, email;
- second and third → no further WARNING; each produces a DEBUG record
  with its method + path;
- the flag is per process: resetting it (as a new process would) logs a
  WARNING again;
- end to end through a real `DBLogHandler` on the test DB: three
  bypass-served requests persist exactly ONE "served" row;
- the existing "bypass inactive → OAuth redirect" and "no leak between
  requests" tests stay as they are.
- Proof: one full gate run, same measurement as §1 — lane 0's bypass rows
  per run should drop from 976 to ~1, and the total from 1,041 to ~65.

## 4. Docs

- `auth.py` module docstring + `log_bypass_startup_banner` docstring;
  `app.py:270` comment.
- ARCHITECTURE.md "Every bypass-served request logs a WARNING row" (two
  places).
- README bypass section step 4 ("Every protected route accessed … writes a
  `WARNING` row").
- ADR-039 supersedes ADR-002's per-request audit claim only (ADR-002 stays
  ACCEPTED for the four gates; gets a "partly superseded by ADR-039" note).
