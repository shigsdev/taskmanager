# ADR-032: Cache verified identity in the signed session

Date: 2026-05-17
Status: ACCEPTED
Supersedes: none (refines ADR-001's identity-resolution mechanism;
the single-user lockdown decision itself is unchanged)

## Context

User report 2026-05-17: "I still seem to get logged out every 10 to
15 minutes." An earlier change (PR100) had already raised
`PERMANENT_SESSION_LIFETIME` to 30 days and `@app.before_request`
sets `session.permanent = True` on every request, so the *Flask
session cookie* was not the thing expiring.

Root cause was in `auth.get_current_user_email()`. It called
`google.get("/oauth2/v2/userinfo")` on **every** `login_required`
request to resolve the user's email. Google OAuth access tokens are
short-lived (nominally ~1h, in practice variable and sometimes much
shorter), and `make_google_blueprint` requests **no offline/refresh
token** (no `offline=True`), so Flask-Dance cannot renew the token.
The first request after the access token expired raised
`TokenExpiredError` → `session.clear()` → the user was bounced back
through the full OAuth sign-in. Under active use with variable token
TTLs this presented as "logged out every 10-15 minutes."

The app's real authentication boundary is the Flask session cookie:
signed with `SECRET_KEY`, `HttpOnly`, `Secure`, `SameSite=Lax`, 30-day
sliding lifetime. There is no security reason to re-prove identity to
Google on every single request for a single-user personal tool.

## Decision

Resolve the user's email via Google's userinfo endpoint **once**, at
first sign-in, then cache it in the signed Flask session
(`session["auth_email"]`). Every subsequent request trusts the signed
cookie instead of re-calling Google. `login_required` continues to
compare that email against `AUTHORIZED_EMAIL` on **every** request, so
the authorization decision is unchanged — only the identity *lookup*
is cached.

## Consequences

**Easy / fixed:**
- The "logged out every 10-15 min" symptom is gone. App-session
  longevity (30-day signed cookie) is now decoupled from Google's
  access-token lifetime.
- One fewer outbound HTTP call to Google per request — faster, and no
  longer rate-limitable or dependent on Google userinfo availability.
- `session.clear()` on `/logout` and on the unauthorized-email branch
  still wipes the cached email, so explicit logout and lockout work
  unchanged.

**Accepted trade-offs:**
- A rotated `AUTHORIZED_EMAIL` does not retroactively invalidate the
  *identity* cache — but it does not need to: `login_required`
  re-checks the cached email against the current `AUTHORIZED_EMAIL`
  on every request and `session.clear()`s on mismatch, so a rotation
  locks out a stale session on its very next request.
- Identity is trusted for up to the 30-day session lifetime without
  re-confirming with Google. For a single-user personal tool whose
  threat model (CLAUDE.md) explicitly accepts the signed-cookie
  boundary, this is the correct trade. A multi-user app would want
  periodic re-validation with a real refresh-token flow instead.
- Account-level revocation at Google (password change, token revoke)
  is not detected until the 30-day session expires or the user logs
  out. Acceptable for a single-user tool; the mitigation if ever
  needed is the `SECRET_KEY` rotation kill-switch, which invalidates
  every session immediately.

## Alternatives considered

- **Request `offline=True` + refresh token + Flask-Dance auto-refresh.**
  The "proper" OAuth fix, but heavier: requires an OAuth consent
  scope/prompt change (forces re-consent), a token storage backend,
  and refresh-failure handling — and still ultimately trusts the
  session between refreshes. Larger blast radius for a symptom the
  session cache fully resolves. Left as a possible future hardening
  if the app ever goes multi-user; noted, not done.
- **Re-validate with Google on a timer (every N hours).** Rejected:
  with no refresh token the Google token is guaranteed to expire
  within ~1h, so *any* periodic re-validation against Google
  reintroduces the exact forced-logout failure mode. The signed
  session must be the source of truth, not Google's token.
- **Shorten nothing, just raise the token lifetime.** Not possible —
  Google controls access-token TTL; the client cannot extend it.

## Verification

- `tests/test_auth.py::TestGetCurrentUserEmailSessionCache` (5 tests):
  - first lookup hits Google exactly once and caches the email
  - cached email short-circuits and Google is **never** called
  - **expired Google token with a cached email does NOT clear the
    session** (the literal bug — the user stays signed in)
  - expired token *without* a cache still clears the session (no
    regression to the safe-fail path)
  - not-signed-in + no cache still returns None (login redirect)
- All quality gates green; deploy-validated + prod smoke.
