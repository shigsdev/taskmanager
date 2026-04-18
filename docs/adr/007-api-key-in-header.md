# ADR-007: API keys in headers, not URL query parameters

Date: 2026-04-18
Status: ACCEPTED

## Context

Three external APIs are called server-side: Google Vision, Anthropic
Claude, and OpenAI Whisper. Two of them already pass the API key in
the `Authorization` (or `x-api-key`) header. One — Google Vision —
was originally calling `https://vision.googleapis.com/v1/images:annotate?key=AIza...`
with the API key as a URL query parameter.

URL query parameters end up in:

- Server access logs (anywhere in the chain — load balancers, CDNs,
  egress proxies, the destination server's own logs)
- Browser history (not relevant here since this is server-side, but
  worth knowing as a general principle)
- Referrer headers in subsequent requests
- Crash dumps / stack traces in some HTTP libraries

API keys in headers don't end up in any of those places (well-behaved
log infrastructure strips Authorization headers; query strings are
captured verbatim).

## Decision

ALL outbound API calls put credentials in headers — never URL query
parameters.

Specifically:

- Whisper (`voice_service._call_whisper_api`): `Authorization: Bearer <key>`
- Anthropic (`scan_service._call_claude_api*`): `x-api-key: <key>`
- Google Vision (`scan_service._call_vision_api`): **changed from URL
  query `?key=` to** `X-Goog-Api-Key: <key>` header (which Google's
  REST API supports)

Future external API integrations MUST follow the same pattern. The
Cascade-check table in CLAUDE.md lists this as a required check
when adding any new API caller.

## Consequences

**Easy:**
- Single rule to remember: keys in headers, never URLs
- Automatically scrubbed by `Bearer` and `Authorization`-pattern
  scrubbers in `logging_service.scrub_sensitive`

**Hard:**
- One extra defensive habit when integrating an unfamiliar API —
  some vendors document the URL-key approach as the "easy start"
- For APIs that genuinely only accept query-string auth, we'd need
  case-by-case `X-Goog-Api-Key`-style alternatives or a documented
  exception ADR

## Alternatives considered

- **Keep keys in URLs but ensure log scrubbing strips them**: relies
  on log infrastructure we don't control (Railway, Google's own logs).
  Defense-in-depth scrubbing is fine to keep, but it's not a
  substitute for not putting the key there in the first place.
- **Use SDK clients (e.g. `google-cloud-vision`)**: bigger dependency
  surface, more code to maintain. Raw `requests` calls are fine for
  the small number of API endpoints we hit.
