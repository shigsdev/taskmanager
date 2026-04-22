# ADR-025: Central upload validation helper

Date: 2026-04-21
Status: ACCEPTED

## Context

Backlog #19. Two file-upload routes exist today:

- `voice_api.py` — accepts `multipart/form-data` audio (Whisper input)
- `scan_api.py` — accepts `multipart/form-data` images (Vision OCR input)

Each one needs the same five-step validation:

1. The named file field is present in `request.files`
2. Filename is non-empty
3. `Content-Type` matches an allowed MIME type (after stripping codec
   parameters that browsers append unevenly)
4. Body fits inside an endpoint-specific size cap
5. Body is non-empty (the "user pressed record but never spoke" case
   that would otherwise burn a Whisper call on silence)

Plus a sixth rule that comes from the global `MAX_CONTENT_LENGTH`
config in `app.py` — Flask raises 413 before our route runs at all
if the body exceeds the global cap, so each endpoint's `max_bytes`
acts as a tighter per-endpoint limit (audio: 25 MB, image: 8 MB).

The 2026-04-18 audit hardening pass extracted this into
`utils.validate_upload(...)` with a tuple-of-error-or-success return
shape that mirrors the existing `enum_or_400` helper:

```python
body, content_type, err = validate_upload(request, field_name=..., allowed_mime=..., max_bytes=...)
if err:
    response, status = err
    return jsonify(response), status
# body and content_type are usable here
```

Both production callers (`voice_api.py`, `scan_api.py`) already use
this helper. Backlog #19 stayed open on the test/ADR scope. This is
that ADR.

## Decisions

### 1. One helper, not two — shared MIME-stripping is the win

A vendor-specific helper per endpoint (`validate_audio_upload`,
`validate_image_upload`) was rejected because the only thing that
varies between callers is `allowed_mime` and `max_bytes` — both
already first-class kwargs on the generic helper. Two specialised
helpers would duplicate the field-presence, MIME-strip, size, and
empty checks for zero gain.

### 2. Tuple-of-error return, not exceptions

Routes ALREADY use the `enum_or_400` pattern (`val, err =
enum_or_400(payload, "tier", Tier)` → `if err: return err`). The
upload helper follows the same shape so route code stays
straight-line:

```python
audio_bytes, content_type, err = validate_upload(...)
if err:
    response, status = err
    return jsonify(response), status
```

Why not raise? Two reasons:

- **Discoverability**: the function signature shows the failure mode;
  exceptions hide it
- **Local code**: every error response stays in the route handler
  where the rest of the request handling lives, so changing the
  error format (adding rate-limit headers, structured logging) is
  one edit per route, not one global try/except

### 3. Returns RAW content-type, not normalized

The normalized type (`audio/mp4` from `audio/mp4;codecs=mp4a.40.2`)
is used only for the allowlist match. Whisper and other downstream
consumers may want the codec parameters — for example, OpenAI's
multipart contract for `audio/mp4` files prefers the original
`Content-Type` for proper container detection.

So the helper returns the unmodified `Content-Type` header as the
caller saw it, even though it normalized internally. Less
information loss, and the caller can re-normalize if it needs to.

### 4. iOS Safari colon-separator quirk handled in the normalizer

`_normalize_mime` accepts both `;` (RFC 7231) and `:` as parameter
separators because some iOS Safari builds emit
`audio/mp4:codecs-mp4a.40.2` (note the colon AND the dash). This
quirk was the root cause of the 2026-04-18 voice memo iOS regression
(see ADR-005). Keeping the unusual delimiter handling inside
`_normalize_mime` means future callers don't have to remember it.

### 5. Empty-file check AFTER read, not from `Content-Length`

The order is: MIME check → size check (after reading) → empty check.
The empty check happens AFTER the bytes are read because a multipart
form can lie about `Content-Length`, and because Flask's body
streaming might otherwise mask a 0-byte payload that arrived inside
a perfectly-sized multipart envelope.

This matches the cascade-check rule for upload endpoints in
CLAUDE.md: "size check BEFORE read, and empty-file guard AFTER read."

### 6. HTTP status codes follow REST convention

- 400 for "you didn't include the field" or "you sent an empty file"
  (client request shape is wrong)
- 413 for body-too-large (REST standard for payload-size rejection)
- 422 for "MIME type not allowed" (request is structurally valid
  but semantically unprocessable — REST standard for valid-but-
  unacceptable content)

422 specifically (not 400 or 415) was chosen for MIME mismatch
because the request IS well-formed at the HTTP layer; we just
won't accept this Content-Type even though we got the multipart
parsing right. 415 (Unsupported Media Type) was an alternative —
422 was preferred because 415 is conventionally about the request
Content-Type itself (e.g. JSON-only API getting an XML body),
whereas our case is a multipart form whose embedded file part has
the wrong type.

## Consequences

**Easy:**
- New upload routes get safe-by-default validation in 4 lines
- MIME-quirk handling (iOS Safari colons, codec params) lives in
  one place — adding a new browser quirk = one regex tweak in
  `_normalize_mime`
- Cascade-check table in CLAUDE.md already references the rule
  set; future contributor adding an upload route can grep for
  `validate_upload` in the codebase to find the contract

**Accepted trade-offs:**
- The helper returns a 3-tuple of `(body, content_type, err)` with
  `err` being `None | (dict, int)` — slightly clunky compared to
  raising or returning an `Either` monad. Worth it for consistency
  with `enum_or_400`. Adding a `dataclass` for the success/error
  union was considered and rejected as over-engineering for a
  helper used by two callers.
- The `max_bytes` argument is per-endpoint, so a misconfigured
  route could allow a large upload that the global
  `MAX_CONTENT_LENGTH` would still cap. Acceptable because the
  global cap is the actual security boundary; the per-endpoint
  cap is a UX refinement (better error message for under-global-
  but-over-endpoint sizes).

## Alternatives considered

- **Per-endpoint helpers (`validate_audio_upload`,
  `validate_image_upload`)**: rejected. Duplicates four of the five
  steps for zero gain.
- **Raise on failure instead of return-tuple**: rejected. Doesn't
  match the existing route-handler patterns (see Decision 2).
- **Use Flask's `werkzeug.exceptions.RequestEntityTooLarge`**:
  considered. Rejected because we want to surface the SIZE in the
  message ("5 MB; max 1 MB") for actionable user feedback —
  Werkzeug's stock exception just produces "Request Entity Too
  Large" with no detail.
- **Generic `dataclass UploadResult`**: rejected as over-engineering
  for two callers and a helper that's unlikely to grow more outputs.

## Verification

- 18 direct unit tests in `tests/test_upload_helper.py`:
  - `_normalize_mime`: 7 tests (RFC params, iOS colon, clean MIME,
    case folding, whitespace, empty input, charset param)
  - `validate_upload` missing field: 2 tests (no field, empty filename)
  - `validate_upload` MIME enforcement: 3 tests (disallowed → 422,
    iOS codec strip allows match, missing Content-Type → 422)
  - `validate_upload` size enforcement: 3 tests (oversize → 413,
    MB rendering in message, exact-cap boundary passes)
  - `validate_upload` empty-file guard: 1 test (zero-byte → 400)
  - `validate_upload` success-path return shape: 2 tests (body +
    raw content_type, field name appears in error message)
- Both production callers (`voice_api.py:59`, `scan_api.py:63`)
  continue to use the helper without code changes.
- Route-level test suites (`test_voice_memo.py`, `test_scan_api.py`)
  exercise the helper transitively in the route context — those
  remain green.
