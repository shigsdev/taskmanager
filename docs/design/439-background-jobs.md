# #439 — Background jobs can stop silently

Deep review 2026-10-11 §B5. One row, one ship.

## 1. The scheduler lives only in gunicorn worker #1

`gunicorn.conf.py` `post_worker_init` starts the scheduler only when
`worker.age == 1`. `age` is a spawn counter, so when worker 1 is killed
(e.g. by the 120 s `timeout`) its replacement has age 3 and never starts
one. The 07:00 digest and the four nightly jobs stop until the next
deploy. `/healthz` turns `warn` once the heartbeat file goes stale,
but nothing restarts the scheduler.

**Fix:** whichever worker holds an exclusive lock on a file in the temp
directory runs the scheduler. A worker tries the lock once, at
`post_worker_init`. The OS releases the lock when the holding process
exits, so a replacement worker gets it as it boots. A second live worker
never gets it, so there is still exactly one scheduler per container (no
duplicate emails, the reason for the original `age == 1` rule).

The lock helper is `scheduler_lock.try_acquire(path)` (`fcntl.flock` on
Linux, `msvcrt.locking` on Windows so it is testable here). The handle
is kept open for the worker's lifetime.

Not covered: two containers overlapping during a Railway rolling deploy
each run a scheduler for a few seconds. That was already true and
isn't changed here.

## 2. The 07:00 digest has a 1-second grace and no catch-up

APScheduler 3's default `misfire_grace_time` is 1 s, so a fire that is
late by more than a second (busy executor, sleeping container) is
dropped. And a deploy or restart at 07:00 means no scheduler at 07:00:
the digest is simply skipped. The nightly jobs have a boot-time replay
(`cron_audit_service.replay_missed`, #167); the digest doesn't.

**Fix:**
- `BackgroundScheduler(job_defaults={"misfire_grace_time": 3600,
  "coalesce": True})` for every job: a late fire still runs (once).
- At scheduler start, `digest_service.should_catch_up(now, hour, minute,
  last)` decides whether to send now: today's digest time has passed,
  by **no more than 3 hours**, and the last recorded send attempt
  (`digest_last_send`, any status) is from before today's digest time.
  If so, the digest is sent through the same function the cron uses.
  Past the 3-hour window it is skipped: an afternoon "daily digest" is
  stale, and `/healthz` `digest_last_send` already reports a missed day.

## 3. tzdata isn't pinned; the UTC fallback is silent

`zoneinfo` needs the IANA database. `tzdata` is installed today only
because `psycopg` and `tzlocal` depend on it. `utils.local_today_date`
(and its siblings) fall back to the server's date (UTC on Railway)
without a word if `ZoneInfo(DIGEST_TZ)` fails.

**Fix:** pin `tzdata` in `requirements.txt`. The fallback logs an ERROR
the first time it happens in a process; the log scan and `/api/debug/logs`
surface it. The fallback itself stays: crashing every date computation
would be worse.

## Tests

- pytest `scheduler_lock`: a second handle can't take a held lock; once
  the first is released it can; a lock held by another process that then
  exits becomes free (real subprocess).
- pytest `gunicorn.conf.post_worker_init` (loaded from file, scheduler
  start stubbed): starts the scheduler when the lock is free, and not
  when another worker holds it, whatever the worker's `age`.
- pytest `should_catch_up`: inside the window with no send today → yes;
  before the digest time → no; past 3 hours → no; already attempted
  today (ok / fail / skip) → no; never sent → yes inside the window.
- pytest: the scheduler is built with the misfire grace and coalesce
  defaults; the catch-up sends once when due.
- pytest: the tz fallback logs an ERROR.

No page changes, so no Jest, Playwright or Phase 6.
