# ADR-003: Validator cookie — initial narrow scope

Date: 2026-04-17
Status: SUPERSEDED by ADR-004

## Context

The post-deploy validator (`scripts/validate_deploy.py --auth-check`)
needs to authenticate to the deployed app to verify the auth pipeline
works end-to-end. Two paths considered:

1. Have the validator copy a real Flask session cookie from a logged-in
   browser and send that. Problem: Flask-Dance auto-refreshes the
   OAuth token during normal browser use, which silently re-signs the
   session cookie and invalidates the captured copy. Validator returns
   401 the next time it runs; user gets a confusing failure.
2. Mint a separate signed cookie that doesn't get refreshed.

We chose path 2.

## Decision

Add a dedicated cookie name `validator_token`, signed with the same
`SECRET_KEY` as Flask sessions but using a different `itsdangerous`
salt (`taskmanager-validator-v1`). 90-day default lifetime,
configurable per-mint via `--days`. Carries only the authorized
email as its payload.

**Initial scope: authenticate ONLY `/api/auth/status`.** Other
protected routes continue to require real OAuth via `login_required`.
This ensures a leaked validator cookie grants access to nothing
except the auth-state reporter endpoint — no task or goal data.

Mint via `flask mint-validator-cookie` (Flask CLI command in app.py)
or `scripts/mint_validator_cookie.py` (standalone, doesn't require
the full Flask app to import — useful when local Python is missing
psycopg).

`SECRET_KEY` rotation instantly invalidates every minted validator
cookie — emergency revocation lever.

## Consequences

**Easy:**
- Long-lived (90 day) credential survives Flask-Dance token refreshes
- Narrow blast radius if leaked

**Hard:**
- Prod Playwright tests can ONLY verify `/api/auth/status` and
  unauthenticated endpoints. Cannot verify page renders, /api/tasks
  shape, or anything else that requires `login_required`.
- See ADR-004 for the resolution.

## Alternatives considered

- **Reuse Flask session cookie**: addressed in Context — token
  refresh problem
- **No special cookie, use Google service account OAuth**: multi-day
  effort, expanded auth surface
- **Use the existing `APP_DEBUG_TOKEN` mechanism**: in retrospect, this
  would have worked too (and arguably better — see notes in ADR-004),
  but at decision time the validator-cookie design felt cleaner
  because it reused the SECRET_KEY signing path that was already trusted
