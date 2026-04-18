# ADR-002: Four-gate dev bypass for local browser testing

Date: 2026-04-10
Status: ACCEPTED

## Context

The Phase 6 manual browser regression (see CLAUDE.md) requires Claude
Preview / a real browser to navigate auth-gated pages. Doing real
Google OAuth from a headless browser is fragile (Google detects
automation, requires CAPTCHA, etc.) and slow.

We need a way to skip Google OAuth on local dev, but with safeguards
robust enough to guarantee it cannot accidentally activate in
production. A leak would mean any attacker can hit any route as the
authorized user.

## Decision

`auth._dev_bypass_active()` returns True ONLY if all four independent
gates are satisfied:

1. `LOCAL_DEV_BYPASS_AUTH=1` — explicit opt-in env var
2. `FLASK_ENV=development` — must be in dev mode
3. NONE of `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_NAME`, or
   `RAILWAY_SERVICE_ID` are set — three independent Railway-injected
   variables as a tripwire
4. `AUTHORIZED_EMAIL` is set — so we know who the bypass should
   pretend to be

Each gate is independent. A single misconfiguration disarms the
bypass. The triple Railway tripwire means a Railway env-var rename
of any one variable cannot silently disarm the gate — they would
have to rename all three at once.

When the bypass IS active, every served request emits a WARNING log
row to `app_logs`, and a loud banner is printed to stderr at startup.
A `scripts/run_dev_bypass.py` launcher applies the same Railway
tripwire BEFORE Flask imports, so even shell-injecting the env var
in a Railway shell wouldn't help.

## Consequences

**Easy:**
- Local browser regression of auth-gated pages "just works"
- Audit trail of every bypass-served request via `/api/debug/logs`

**Hard:**
- More moving parts to remember
- The tripwire would also fire if someone runs the app outside Railway
  in a way that mimics Railway's env layout (very unlikely)

**Defense-in-depth value:**
- A leaked env var alone can't activate the bypass on Railway
  (tripwire blocks)
- A code bug that ignores one gate still leaves three others
- Audit log makes any accidental activation noisy and traceable

## Alternatives considered

- **Run real Google OAuth in Playwright**: technically possible but
  fragile (Google's detection, CAPTCHA, account lockouts on repeated
  failed logins)
- **Mock the OAuth library**: requires test-only code paths in
  production code, easy to leave on accidentally
- **No bypass — manually click through OAuth before each test**:
  unworkable for fast iteration
