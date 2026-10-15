# #477 — /utilities audits outlive the request, and nothing caps runs

Split from #447 (deep review §B10).

## What happens

- `POST /api/utilities/run-tech-debt-audit` runs `check_tech_debt.CHECKS`
  inside the request. Its dependency-drift check shells out to
  `pip list --outdated` (timeout 120 s) and `npm outdated` (120 s), and
  code-duplication to `npx jscpd` (180 s) — up to 420 s against gunicorn's
  120 s worker timeout (`gunicorn.conf.py`). Past 120 s gunicorn kills the
  worker mid-request: the page shows a failure and the audit's autofile never
  runs.
- None of the /utilities POST routes has a `@limiter.limit` — only the
  200/minute global default. Each run costs container CPU (audits) or GitHub
  Actions minutes (backup, restore drill, autofile dispatch).

The bug-pattern and security scans finish in seconds (their only network call
has a 30 s timeout); the coverage audit is already a background job (#229b).

## Change

- **Tech-debt audit becomes a background job**, the coverage audit's pattern:
  POST writes `running` to a shared `/tmp` state file
  (`taskmanager_tech_debt_audit_state.json`, visible to every gunicorn
  worker), starts a daemon thread and returns `{status, started_at}` at once;
  409 while one runs. New `GET /api/utilities/tech-debt-audit-status`
  returns `{status, started_at, finished_at, duration_seconds, result, error}`.
  The thread records `complete` with the same `{total, per_check, findings}`
  result (autofile + dispatch unchanged), or `error`. The state-file read /
  write is shared with the coverage job (`_read_job_state` /
  `_write_job_state`; the coverage wrappers keep their names).
- **Page**: the tech-debt card uses the existing `asyncJob` path
  (`pollAsyncJob`): live elapsed time on the button, result when done. Card
  copy updated. `CACHE_VERSION` bump.
- **Rate limit**: `UTILITY_RUN = "5 per minute"` (`rate_limit.py`) on every
  /utilities POST that runs work or dispatches a workflow — clear stale
  next-week dates, trigger backup, trigger restore drill, bug-pattern,
  security, coverage, tech-debt — with the message
  "Too many runs — wait a minute and try again." (the card shows
  "Failed: <message>"). The GET count preview and status polls stay on the
  default.

## Tests

pytest `tests/test_utilities_jobs_477.py`: POST returns without running the
checks and starts the job; a second POST while running is 409; the job
records complete (result shape) and error; status is idle before any run and
needs login. With the limiter switched on for the test app: the 6th run in a
minute of each of the seven routes is 429 with the message; the count preview
is not limited.
