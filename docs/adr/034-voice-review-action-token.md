# ADR-034: Scoped voice-review action token (hands-free mutation auth)

Date: 2026-06-22

Status: PROPOSED (draft — awaiting operator review before implementation)

## Context

Feature #297 (Voice Task Review, design doc `docs/design/297-voice-task-review.md`
§7) needs a way for an iOS Shortcut — driven by Siri/CarPlay for fully
hands-free task triage while driving — to **mutate** today's tasks:
complete them, move them between tiers, or cancel them by voice.

Neither existing auth path can carry this:

1. **OAuth session** is the app's primary auth, but an iOS Shortcut
   cannot hold a Flask-Dance OAuth session (no browser, no cookie jar,
   no token-refresh loop). The design doc §6 rules this out as not
   feasible in the Shortcuts app.
2. **The validator cookie** (`validator_cookie.py`, ADR-003 → ADR-004)
   is deliberately **read-only**: its branch in `auth.login_required`
   authenticates GET/HEAD/OPTIONS only; POST/PATCH/DELETE/PUT always
   fall through to OAuth. That read-only guarantee is exactly what
   makes it safe to hold for 90 days — so it cannot complete or move a
   task, and we do NOT want to weaken it (see Alternatives).

So #297 Option B requires a **new** credential that can mutate — the
first time the app's mutation-auth boundary extends beyond OAuth. Per
CLAUDE.md ("refactored a security-sensitive function / broadened a
scope → write an ADR"), the decision and its threat-model delta must be
recorded before any auth code is written. This is that ADR.

## Decision

Introduce a **scoped voice-review action token**: a long-lived bearer
credential, sent in the `Authorization: Bearer …` header (NEVER in a URL
query string — ADR-007), that authenticates ONLY a fixed whitelist of
review mutations on the single authorized user's own tasks, and is
rejected on everything else.

Specifics (DRAFT — exact module/function names to be wired at build time;
flagged for the operator below):

- **Mechanism.** Mirror the validator-cookie minting workflow
  (`validator_cookie.py`): an `itsdangerous` token signed with the app's
  `SECRET_KEY` under a **new distinct salt** (e.g.
  `taskmanager-voice-action-v1`, separate from the validator cookie's
  `taskmanager-validator-v1` so neither can be replayed as the other).
  Minted offline via a `flask mint-voice-action-token` CLI command (plus
  a standalone `scripts/mint_voice_action_token.py` like
  `mint_validator_cookie.py`). The token is stored ONLY inside the iOS
  Shortcut. Payload carries the authorized email + a token id, and parse
  enforces the email matches `AUTHORIZED_EMAIL` (single-user lockdown,
  same as the validator cookie).
- **Tight scope — the load-bearing security property.** The token
  authorizes ONLY:
  - `POST /api/tasks/<id>/complete`
  - `PATCH /api/tasks/<id>` restricted to a **tier-only** body whose
    value is in the whitelist `{today, tomorrow, next_week, backlog}` —
    any other field in the PATCH body, or a tier outside the whitelist,
    is rejected
  - `POST /api/tasks/<id>/cancel`

  It MUST be rejected (401/403) on **everything else**: task
  create/delete, bulk endpoints, settings, exports, goals/projects, any
  other route, and any other HTTP method on the three routes above. It
  grants no read access beyond the task titles the review queue already
  surfaces, and cannot mint or escalate any other credential.
- **Revocability.** Validity is tied to `SECRET_KEY` rotation (instant
  kill-switch for every minted token, same lever as the validator
  cookie) AND a stored token id so a single token can be revoked without
  a full key rotation. Finite lifetime (per-mint `--days`, with a
  sensible default — propose ≤ the validator cookie's 90 days; operator
  to confirm).
- **Rate-limited.** The three actions carry `@limiter.limit(...)` —
  this is a user-controllable mutation surface (CLAUDE.md cascade rule
  for user-controlled mutating routes).
- **Log hygiene.** The token format is added to the `scrub_sensitive`
  regex chain, with a `test_strips_voice_action_token` test in
  `tests/test_logging.py` (CLAUDE.md cascade rule for new tokens).

Implementation site (to be created): a `voice_action_token.py` module
mirroring `validator_cookie.py` (`mint` / `parse`), invoked from the
mutation branch of `auth.login_required` (or a dedicated decorator on the
three whitelisted routes). Regression tests: a new
`tests/test_voice_action_token.py` covering parse/expiry/email-mismatch/
revocation **plus** the scope-rejection matrix below.

## Consequences

**Easy:**
- The iOS Shortcut (Siri/CarPlay) can complete/move/cancel today's tasks
  fully hands-free — the zero-touch requirement (#297 §12 decision 1)
  is met without screen interaction while driving.
- Blast radius of a leak is tightly bounded: a stolen token can only
  complete/move/cancel the user's own tasks for its finite lifetime, and
  is killable instantly via `SECRET_KEY` rotation or by revoking its
  token id. No reads of unrelated data, no delete, no settings/exports,
  no new auth — those stay OAuth-only and are closed off to this token.
- The validator cookie's read-only guarantee is left fully intact —
  this is a *separate* credential, not a widening of an existing one, so
  ADR-004's "validator cookie cannot mutate" claim still holds verbatim.

**Hard:**
- **A new mutation-auth code path to maintain and test forever.** Every
  future change to `login_required`, the three whitelisted routes, or the
  PATCH-body shape must re-verify this token still cannot escape its
  scope. This is permanent surface area.
- **A mandatory scope-rejection regression test** is now load-bearing:
  for the token, assert 200/2xx on each whitelisted action AND assert
  401/403 on every out-of-scope route/method (create, delete, bulk,
  settings, exports, a non-whitelisted tier value, a PATCH carrying a
  non-tier field, GET/PUT on the three routes). If that matrix ever goes
  green where it should be red, the central security property is broken.
- **Threat-model delta (explicit).** This is the first credential other
  than OAuth that can mutate state. A leaked token (committed to git,
  pasted, extracted from a stolen/unlocked phone where the Shortcut
  lives) lets an attacker complete/move/cancel the user's tasks for the
  token's lifetime. That residual risk is **accepted** because it is
  bounded by, in combination: (a) the tight action whitelist — no read
  of unrelated data beyond review-queue task titles, no delete, no
  settings/exports, no ability to mint or escalate auth; (b) revocation
  via `SECRET_KEY` rotation and/or token id; (c) a finite lifetime; and
  (d) this is a single-user personal app (no other tenants, no other
  accounts to take over). Contrast with the validator cookie, whose
  residual risk is even smaller (read-only) — this token trades a strictly
  larger blast radius (it can *change* data) for the hands-free
  capability, and the four bounds above are what make that trade
  acceptable rather than reckless.
- **A new operator workflow to document**: how to mint, install into the
  Shortcut, and rotate/revoke the token (README + CLAUDE.md threat-model
  note). A token that's painful to rotate won't get rotated after a scare.

## Alternatives considered

- **Widen the validator cookie to allow these mutations.** Rejected: the
  validator cookie's entire safety story (ADR-003/ADR-004, and the
  "cannot create, modify, or delete anything" guarantee in
  `validator_cookie.py`) rests on its read-only scope, which is why it's
  acceptable to hold for 90 days. Adding mutation paths to it would erode
  that guarantee for *every* holder and use of the cookie — including the
  post-deploy validator — to serve one narrow new use case. A separate,
  separately-scoped, separately-revocable credential keeps the two blast
  radii independent.
- **Full OAuth inside the iOS Shortcut.** Rejected: not feasible in the
  Shortcuts app — it cannot run the Flask-Dance browser OAuth dance or
  maintain the refreshing session cookie (#297 §6).
- **A native iOS app with SiriKit.** Rejected: this is a deliberately
  buildless Flask + vanilla-JS web app (#297 §7); a native app is a large
  new platform/toolchain commitment far out of proportion to a single
  voice-triage feature.

## Related

- ADR-003 / ADR-004 — validator cookie (the read-only credential this one
  is deliberately *not* extending); same `SECRET_KEY`-rotation kill-switch
  pattern.
- ADR-007 — API keys / tokens go in headers, never in URL query strings.
- `docs/design/297-voice-task-review.md` §7 — the design context that
  requires this ADR; §10 — the testing plan whose token rows this ADR's
  scope-rejection matrix satisfies.
