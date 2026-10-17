# #497 — The log scrubber leaked `Authorization: Basic` credentials

Found 2026-10-17 while researching #371 (iCloud CalDAV uses HTTP Basic).

## What was wrong

`logging_service.scrub_sensitive`'s `authz` pattern knew one scheme:
`Authorization: Bearer <token>`. For any other scheme the fallback matched a
single word, which was the scheme name. So

    Authorization: Basic dXNlckBleGFtcGxlLmNvbTpzM2NyZXQ=

came out as `authorization: [REDACTED] dXNlckBleGFtcGxlLmNvbTpzM2NyZXQ=`, with
the base64 `user:password` still readable in `app_logs` and `/api/debug/logs`.
The same happened to `Token …`, `Proxy-Authorization: Basic …` and the
quoted-dict form.

No code sends Basic auth today, so nothing has leaked. The SMTP fallback
authenticates through `smtplib`, not an Authorization header. #371 would be
the first caller.

## Fix

After `authorization` (any case, `:` or `=`, optionally quoted), match
`<scheme> <credential>` for any scheme word, or fall back to one token as
before. Bearer behaves the same. Plain prose such as "Basic setup" is
untouched, because the rule only fires after "authorization".

## Tests

`tests/test_logging.py::TestScrubSensitive`: five forms (Basic, a quoted
dict, `Token`, `Proxy-Authorization`, an unknown scheme) must not keep the
credential. They were red before (5 failed). The prose quiet case and the
existing Bearer and voice-action-token cases still pass.
