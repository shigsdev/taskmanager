# ADR-039: The dev bypass audits once per process, not once per request

Date: 2026-10-09

Status: ACCEPTED (backlog #384; spec `docs/design/384-bypass-log-once.md`)

Supersedes: ADR-002's "every served request emits a WARNING log row to
`app_logs`" and its consequence "audit trail of every bypass-served request
via `/api/debug/logs`". The rest of ADR-002 — the four gates, the triple
Railway tripwire, the launcher's pre-import refusal, the startup banner —
stands unchanged.

## Context

ADR-002 made the local auth bypass write a WARNING row per served request
so "any accidental activation is noisy and traceable" and the developer can
see which routes were touched. Since then the bypass became the server
behind every local Playwright run: 8 parallel lanes (#402, #403), ~515
tests per gate run. Measured 2026-10-09 on one full gate run, lane 0's
database received 1,041 `app_logs` rows, 976 of them this line (94%); 8
lanes means ~7,800 SQLite inserts per run, each one written inside the
request it describes, competing with that request's own writes (#383 traced
`DBLogHandler insert failed` lines to this). With `MAX_ROWS = 10_000` the
line also evicts every other row: the dev DB's log was ~2 hours deep and
97% bypass noise.

## Decision

Per server process, the bypass persists two WARNING rows:

1. the startup banner (unchanged — also printed loudly to stderr), and
2. the FIRST bypass-served request, with method, path and email, and a
   note that later requests log at DEBUG.

Every later bypass-served request logs `served <METHOD> <path>` at DEBUG —
below `DBLogHandler`'s default `APP_LOG_LEVEL=WARNING`, so it reaches the
console but not the table. The "first" flag is a module global behind a
lock (the bypass server is a waitress thread pool, #403).

## Consequences

**Still true:**
- Accidental activation is noisy and traceable: a banner on stderr at
  boot, plus two WARNING rows in `app_logs` (boot time, first request).
  The post-deploy check in ARCHITECTURE.md — query WARNING rows for bypass
  entries on prod, expect zero — still detects it.
- The bypass can only run locally (four gates + the launcher's tripwire);
  nothing about who can activate it changed.

**Given up:**
- The persisted per-route list. It is still available on demand:
  `APP_LOG_LEVEL=DEBUG` persists every request's line again.

**Not changed:** the validator-cookie and voice-action-token per-request
log lines. Those are credentials that work on prod, so their per-request
trail stays.

## Alternatives considered

- **Per path at DEBUG, no WARNING at all** — loses the "this process served
  traffic" row; the banner alone only proves the process booted.
- **Keep per-request WARNING, batch the inserts** — keeps the eviction
  problem (the cap still fills with bypass rows) and adds a buffer to the
  logging path.
- **Exclude the bypass logger from `DBLogHandler` entirely** — loses the
  first-request audit row too, for no further gain.
