# ADR-004: Broaden validator cookie to authenticate read-only routes

Date: 2026-04-17
Status: ACCEPTED (supersedes ADR-003)

## Context

ADR-003 chose a narrow scope: validator cookie authenticates only
`/api/auth/status`. Once the prod Playwright suite was wired up
against the live URL, we discovered that 4 of the 5 tests fail under
this scope — `auth-status` works, but page renders (/, /goals) and
/api/tasks need authentication too, and only `auth-status` accepted
the validator cookie.

Three options to fix:

1. **Broaden the cookie scope to read-only methods** (this ADR's
   choice)
2. **Split the prod Playwright suite into two tiers**: one that uses
   the validator cookie for the auth-status check only, one that
   requires a fresh real OAuth session. Tier 2 becomes manual /
   occasional.
3. **Switch the validator to a token-header auth** (similar to
   `APP_DEBUG_TOKEN`) and apply that auth to test-relevant routes.

Option 1 was chosen because:
- Option 2 means the "real browser test" tier rarely runs (manual
  step), defeating the point of building it
- Option 3 requires more code churn and ends up at the same scope
  question (which routes does the token authenticate?)

## Decision

Modify `auth.login_required` to accept the validator cookie on safe
HTTP methods (GET, HEAD, OPTIONS) before falling through to OAuth.
Mutation methods (POST, PATCH, DELETE, PUT) ALWAYS require real
OAuth — the validator cookie cannot modify data.

Implementation: `_VALIDATOR_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}`
checked at the top of the `wrapped` function inside `login_required`,
after the dev-bypass short-circuit and before the standard OAuth
check.

Read-only routes that authenticate via validator cookie also emit
an INFO-level log line ("validator_cookie served METHOD PATH as
EMAIL") for audit visibility.

## Consequences

**Easy:**
- All 5 prod Playwright tests pass with a single cookie file
- Post-deploy validation is fully automated

**Hard / accepted risks:**
- A leaked validator cookie can read all tasks, goals, projects, and
  any other GET response from any login_required-protected route for
  up to 90 days. **NOT** "auth-status only" as ADR-003 claimed.
- Mitigation: write capability is unchanged; SECRET_KEY rotation
  remains the kill-switch; default lifetime stays 90 days; the
  cookie is single-purpose (no JS access, sent only to our domain)

**Test invariant codified:**
- `tests/test_validator_cookie.py::test_validator_cookie_does_not_authenticate_mutations`
  asserts the security boundary parametrized over POST/PATCH/DELETE/PUT.
  If any future change accidentally widens that, the test catches it.

## Alternatives considered

See Context above. Notably, after this audit (2026-04-18) we recognized
option 3 (`APP_DEBUG_TOKEN`-style header auth) would have been
architecturally cleaner — one auth mechanism, narrow surface, no
cookie-refresh quirks. Not worth retrofitting now; queued as a future
"if we ever do another major auth pass" cleanup.
