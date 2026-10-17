# ADR-042: Mint and revoke the voice-action token from /settings (amends ADR-034)

Date: 2026-10-17

Status: ACCEPTED (#499, user-reported 2026-10-17)

Amends: ADR-034 (scoped voice-review action token). ADR-034's scope, token
format, lifetime default, salt, denylist and kill-switches are unchanged.
This ADR adds a second way to **mint** the token and a web way to **revoke**
one.

## Context

ADR-034 has the token minted offline only, with `flask
mint-voice-action-token` (or `scripts/mint_voice_action_token.py`) under
`railway run` on a computer. On 2026-10-17 the user reported that the Siri
setup therefore doesn't work for them:

- They work on Windows and an iPhone with no shared clipboard. A ~90-character
  random token printed in PowerShell can't reach the iOS Shortcut short of
  retyping it.
- Revoking fails outright from a laptop. `flask revoke-voice-action-token`
  writes the database, and under `railway run` the database host
  `postgres.railway.internal` only resolves inside Railway.

The phone that runs the Shortcut is already signed in to the app with Google
OAuth. Making the token there and tapping Copy removes the transfer problem.

## Decision

Add three routes under `/api/settings/voice-tokens`, all `@login_required`
(`settings_api.py`, logic in `voice_token_service.py`):

- `POST /api/settings/voice-tokens` mints a token for `AUTHORIZED_EMAIL`.
  `days` is optional (default 90, 1–365). Rate-limited to 5 per hour. It
  answers `201 {token, jti, expires}` with `Cache-Control: no-store`. **This
  answer is the only time the token exists outside the Shortcut.** The
  server stores only `{minted, expires, revoked}` under the AppSetting key
  `voice_action_minted:<jti>`. That row has no signature, so the token can't
  be rebuilt from it. The token is never logged.
- `GET /api/settings/voice-tokens` lists those rows (ids and dates; never a
  token). Rows whose token expired more than a day ago are pruned, along with
  their now-pointless denylist entries.
- `POST /api/settings/voice-tokens/<jti>/revoke` appends to the existing
  `voice_action_revoked_jtis` denylist that `auth.voice_action_or_login`
  already reads. This works for any 16-hex jti, so a token made with the CLI
  can be revoked from the phone too.

The /settings "Siri voice review" card drives these: Make a new token, Copy
token / Copy header value, the list with Revoke, and Revoke by id.

**Who can mint (the load-bearing property).** Only a real Google OAuth
session:

- The validator cookie authenticates `login_required` on GET / HEAD /
  OPTIONS only (ADR-003/004), so it is refused on both POSTs. It may read the
  list, which holds no secret.
- `login_required` never inspects a bearer header, so a voice-action token
  **cannot mint a new token** (no self-renewal past its lifetime) or revoke
  one.
- `tests/test_voice_token_settings.py` pins all of the above.

**Denylist writes never truncate.** `voice_token_service.add_revoked_jti` is
now the only writer, and the CLI revoke uses it. The CLI used to do
`json.dumps(list)[:500]`, which on a full list left broken JSON. Broken JSON
reads as an *empty* denylist, which un-revokes every token. A list that
would pass the column's 500 characters is now refused, with "rotate
SECRET_KEY".

## Consequences

**Easy:**

- The whole Siri setup (make, copy, paste, revoke) happens on the iPhone. No
  laptop, no Railway CLI.
- Revocation works again from anywhere the user is signed in, so a scare
  gets an actual rotation.
- The CLI paths remain as fallbacks.

**Hard / threat-model delta:**

- **A web session can now create a mutation credential.** Before, minting
  needed shell access to the Railway environment (`SECRET_KEY` in hand).
  Now anyone holding the user's OAuth session cookie can mint a 365-day
  voice-action token. That token *outlives* the session: signing out, or
  the 30-day session expiry, doesn't kill it. Accepted because:
  - (a) A stolen OAuth session is already the bigger compromise. It can do
    everything the voice token can and much more (delete, export, settings).
    The token adds persistence, not reach.
  - (b) Its scope is still ADR-034's whitelist.
  - (c) The list shows every token made here, with when it was made, so an
    unexpected one is visible and revocable.
  - (d) Minting is rate-limited to 5 per hour.
  - (e) Rotating `SECRET_KEY` still kills every token at once.
- **The token crosses the browser once.** It sits in a page field until Done
  or a reload. `no-store` keeps it out of the HTTP cache, and the service
  worker never handles `/api/`. It can reach the iOS clipboard. That's the
  point, and it's the same exposure as copying it from a terminal.
- Revocation is still per-jti. The denylist is bounded by revoked-and-live
  tokens. A user who somehow fills it gets told to rotate `SECRET_KEY`
  instead of the list silently breaking.

## Alternatives considered

- **A QR code on a laptop page for the phone to scan.** Rejected: it still
  needs the laptop and the Railway CLI, and it doesn't fix revoke. (A
  stopgap script outside the repo did this.)
- **Store the token so the page can show it again.** Rejected: a stored
  bearer is a database leak waiting to happen. Shown once, make another if
  lost.
- **Let the voice token mint its successor.** Rejected: it would turn a
  bounded-lifetime credential into an unbounded one.

## Related

- ADR-034: the token this amends.
- ADR-003 / ADR-004: the validator cookie, GET-only, so it can't mint.
- `docs/design/499-voice-token-settings.md`: the spec.
- #500: Siri add a task / edit title or due date (a further scope change;
  its own ADR).
