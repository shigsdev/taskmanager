# #499 — Make and revoke the Siri voice-review token on /settings

Filed 2026-10-17 (user report: the Siri setup in Help doesn't work for them).
Amends ADR-034 via ADR-042.

## 1. The problem

The iOS Shortcut "voice review" (#297) authenticates with the scoped
voice-action token (`voice_action_token.py`, ADR-034). Today the only way to
make one is a laptop command:

```
railway run python -m flask mint-voice-action-token
```

The user works on a Windows PC and an iPhone with no shared clipboard. A
token printed in a PowerShell window can't reach the Shortcut without
retyping ~90 random characters. Revoking is worse: `flask
revoke-voice-action-token <jti>` needs the database, and under `railway run`
on a laptop the host `postgres.railway.internal` only resolves inside
Railway, so it fails outright.

The user is already signed in to the app on the iPhone through Google OAuth.
So the phone is the right place to make the token: make it there, tap Copy,
paste it into the Shortcut.

## 2. Full surface (mapped)

| Piece | Today | Where |
|---|---|---|
| Token format, mint, parse, revocation check | done, pure, no DB | `voice_action_token.py` |
| Denylist of revoked token ids | AppSetting `voice_action_revoked_jtis`, JSON list | `auth._voice_action_revoked_jtis` reads it |
| CLI mint | prints token + jti; no DB write | `app.py` `mint-voice-action-token` |
| CLI revoke | appends to the denylist; **truncates the JSON to 500 chars** (`json.dumps(current)[:500]`), which corrupts the list once it is full and silently un-revokes every token | `app.py` `revoke-voice-action-token` |
| The routes the token can reach | queue + complete / move / cancel | `voice_review_api.py` |
| Help | Step 1 = the laptop command | `templates/docs.html#voice-review-shortcut` |
| README | CLI-only section | README "Voice-review action token" |
| Settings page | no token card | `templates/settings.html`, `static/settings.js` |

`AppSetting.value` is `String(500)`. Postgres refuses a longer value
(conftest's #447 width check does the same in tests). So no single JSON blob
may hold an unbounded list.

## 3. This ship's scope

### 3.1 Storage: one small AppSetting row per token made on the web

- Key `voice_action_minted:<jti>` (36 chars ≤ 100).
- Value JSON `{"minted": <ISO UTC>, "expires": <ISO UTC>, "revoked": <ISO UTC or null>}`,
  ~110 chars.
- **The token itself is never stored.** It can't be rebuilt from the row,
  because the row has no signature.
- The listing prunes rows whose `expires` is more than a day past. Pruning
  also drops that jti from the denylist: an expired token already fails
  `parse` on age, so the denylist entry has stopped doing anything. That
  keeps the 500-char denylist bounded by *live* revoked tokens.

### 3.2 New service module `voice_token_service.py`

- `list_tokens()`: prunes expired rows, then returns
  `[{jti, minted, expires, revoked}]`, newest first.
- `mint_token(days)`: validates `1 ≤ days ≤ 365`, mints via
  `voice_action_token.mint` with a fresh jti, writes the row, and returns
  `{token, jti, expires}`. The caller gets the token exactly once.
- `revoke_token(jti)`: validates the jti shape (16 lowercase hex, which is
  what `new_jti()` makes), appends it to the denylist through
  `add_revoked_jti`, and stamps `revoked` on its row if there is one. A jti
  with no row (a token made with the CLI) is still revoked, so the card's
  "Revoke by id" box covers tokens made before this ship.
- `add_revoked_jti(jti)`: the single denylist writer. Idempotent. If the
  new JSON would pass 500 chars it raises `ValidationError` ("too many
  revoked tokens still live — rotate SECRET_KEY") instead of truncating.
  **The CLI revoke command switches to it**, which fixes the truncation bug
  in §2.

### 3.3 Routes (`settings_api.py`, all `@login_required`)

| Method + path | Limit | Answer |
|---|---|---|
| `GET /api/settings/voice-tokens` | default | `{tokens: [...]}`, never a token |
| `POST /api/settings/voice-tokens` body `{days?}` | `5 per hour` ("Too many new tokens — wait a while and try again.") | 201 `{token, jti, expires}`, `Cache-Control: no-store`; 422 on bad days |
| `POST /api/settings/voice-tokens/<jti>/revoke` | `20 per minute` | `{ok, jti, listed}`; 422 on a bad jti |

Auth boundary (the load-bearing part):

- `login_required`'s validator-cookie branch is GET/HEAD/OPTIONS only, so
  the cookie **cannot mint or revoke** (POST → 401). It *can* read the GET
  list, which holds ids and dates only: no token, no secret.
- `login_required` never inspects a bearer header, so **a voice-action
  token cannot mint a new token** (no self-renewal, no escalation) or
  revoke one.
- So minting needs a real Google OAuth session. That is the same bar as
  every other mutation in the app.

Log hygiene: the routes log nothing about the token. A test makes a token
through the route with `caplog` at DEBUG and asserts the token string is in
no record. The existing scrub chain already strips a `Bearer …` value (#497).

### 3.4 The /settings card "Siri voice review"

- A short line on what the token can do (read today / overdue / tomorrow;
  complete, move, cancel) and a link to Help.
- **Lasts** select (30 / 90 / 180 / 365 days, default 90) and a
  **Make a new token** button (`withInflight`, so a double tap makes one).
- On success, a "new token" box shows:
  - the token in a read-only `<textarea>`;
  - **Copy token** and **Copy header value** (`Bearer <token>`);
  - the plain-words instruction: *In the Shortcut's Get Contents of URL
    action, add a header named `Authorization` whose value is `Bearer `, a
    space, then the token. Or paste the whole header value.*;
  - "This is the only time it's shown."
- Copy uses `navigator.clipboard.writeText`. When that is missing or
  refused (older iOS, a non-secure context), the text is selected
  (`select()` + `setSelectionRange(0, len)`) and `execCommand("copy")` is
  tried. If that fails too, the status says "Selected — tap Copy".
- While the new-token box is showing, `reloadGuard` reports busy, so a
  deploy's auto-reload can't wipe a token the user hasn't copied yet. **Done**
  hides the box and clears the field.
- **Your tokens** list: each row reads made / expires and Active or
  Revoked, plus a Revoke button (with a `confirm`). If the list is empty it
  says "No tokens made here yet."
- **Revoke by id**: a text box plus Revoke button, for a token made with the
  laptop command (its `jti=` line).
- A failed load uses the #440 `sectionLoadError` with Retry. A failed make
  or revoke says why under the button.

Pure logic goes in `static/voice_token_helpers.js` (dual export), with Jest
tests: `headerValue(token)`, `isValidJti(s)`, `tokenRowLabel(row, now)`,
`clampDays(v)`.

### 3.5 Docs

- Help `#voice-review-shortcut`: Step 1 becomes "On your iPhone: Settings →
  Siri voice review → Make a new token → Copy token". The laptop command
  stays as a fallback. Revoking becomes the card's Revoke (or Revoke by id),
  and rotating `SECRET_KEY` stays the emergency lever. Steps 2–3 (get the
  queue, complete / move / cancel) are re-checked against
  `voice_review_api.py` and stay. Fact-check table in the review.
- README section: the phone path first, the CLI second.
- ADR-042 amends ADR-034: a second way to mint a mutation credential (the
  OAuth web session), with its threat-model delta.
- The CLAUDE.md threat model's voice-action bullet adds the web mint/revoke.
- ARCHITECTURE: the three routes in the catalog, plus Components / Data Flows.
- New static asset: `sw.js` APP_SHELL, `health.py` EXPECTED_STATIC_FILES,
  CACHE_VERSION bump.

### 3.6 Tests

- pytest (`tests/test_voice_token_settings.py`):
  - OAuth mint → 201 with a token that `/api/voice-review/queue` accepts;
  - no auth → 401;
  - the validator cookie can't mint or revoke (401) but can GET the list;
  - a voice bearer can't mint, revoke or list (401);
  - days default 90, `0` / `366` / `"x"` → 422;
  - the 6th mint in an hour → 429 with the message;
  - the list never contains the token;
  - revoke → the jti is in the denylist, and that token now gets 401 on
    `/api/voice-review/queue`;
  - revoke by id for an unlisted jti; bad jti → 422;
  - idempotent revoke;
  - expired rows pruned, and their denylist entry dropped;
  - a full denylist → 422, never truncated;
  - the CLI revoke goes through the same writer;
  - the token string is in no log record.
- Jest: `tests/js/unit/voice_token_helpers.test.js`.
- Playwright `tests/e2e/settings_voice_token.spec.js` at 1280 and 375: make
  a token (real API) → it shows with Copy; Copy writes the clipboard; the
  list gains the row; Revoke flips it to Revoked; `/api/voice-review/queue`
  with that token answers 401; Revoke by id; no sideways scroll; at 375 the
  buttons are ≥ 44px tall.

## 4. Not in this ship (filed)

- **#500**: Siri add a task + edit a task's title / due date (user request
  2026-10-17, filed for a separate session).
- The token value is shown once and only in the browser. No QR code (a
  laptop-to-phone path is moot once the phone can make the token itself).

## 5. Decisions

1. The token is never stored. Shown once; lose it and you make another.
2. Max lifetime from the web is 365 days (the CLI keeps 3650). Default 90,
   as in ADR-034.
3. The validator cookie may read the id list (ids and dates only). It can't
   mint or revoke.
4. The voice token can't mint or revoke. No self-renewal.
5. The denylist never truncates. Full → refuse, and say to rotate
   `SECRET_KEY`.
