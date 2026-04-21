# ADR-023: Central egress module for all outbound HTTP

Date: 2026-04-21
Status: ACCEPTED

## Context

Backlog #17 completed the "catch secret leaks" layer of our outbound-
security posture. This ADR documents the *other* outbound-security
layer: how all server-originated HTTP traffic is routed through a
single `egress.py` module.

Historically, each external API caller rolled its own HTTP:

- `scan_service.py` — two callers for Claude (image OCR + voice memo
  parse), one for Google Vision OCR — each built their own
  `requests.post(...)` with hand-written timeout + error handling
- `voice_service.py` — Whisper transcription
- `tasks_api.url_preview` — user-supplied URL fetch with SSRF defense

Five separate sites means five places to forget a timeout, five places
to accidentally log an API key in an error message, five places to
miss the `timeout=` kwarg when adding a new caller, and five places
that have to be updated if (for example) we ever want to add global
egress observability.

The 2026-04-18 audit hardening pass consolidated these into
`egress.py` (commit 89880b6) with two functions:

- `safe_fetch_user_url(url, ...)` — for user-influenced URLs; full
  SSRF defense per ADR-006
- `safe_call_api(url=..., headers=..., vendor=..., ...)` — for
  fixed-target vendor APIs where the hostname is a compile-time
  constant

Backlog #18 committed to writing this ADR once the module was in
place and covered by direct tests. This is that ADR.

## Decisions

### 1. Two functions, not one

Different security models demand different defenses. User-influenced
URLs need IP-pinning, DNS-rebind mitigation, and no-redirect rules
(ADR-006). Fixed-target vendor calls need a consistent auth-header
interface and error shape but NOT SSRF checks (the destination is
trusted and constant).

Collapsing both into one function with a `ssrf_defense: bool` flag
was considered and rejected — an all-in-one function invites callers
to pass the wrong flag (especially the dangerous wrong: SSRF=False
for a user URL). Two functions with different names mean the wrong
choice reads incorrectly at the call site.

### 2. Fixed-target helper uses `requests`, user-URL helper uses `urllib`

`requests` is more ergonomic but doesn't expose the low-level hooks
needed for IP-pinning (overriding `build_opener`, inspecting
`getaddrinfo` resolution, refusing redirects via a custom
`HTTPRedirectHandler`). `urllib` does. Using `urllib` ONLY for the
SSRF-defended function keeps its scope tiny and legible.

### 3. `safe_fetch_user_url` NEVER raises; returns `None` on any failure

Contract: any failure (DNS error, disallowed IP, redirect, timeout,
unexpected exception) → `None`. Callers use the `None` return to
fall through to a "title unknown" UX path — no `try/except` needed
at the call site.

This is enforced by a trailing bare `except Exception: return None`
so that even a RuntimeError from a future library upgrade doesn't
leak out and 500 the route.

### 4. `safe_call_api` raises `EgressError` with a sanitized message

Fixed-target calls DO want to surface upstream errors (rate limits,
invalid request, upstream 5xx) so the user sees "Claude API returned
HTTP 429: rate limit exceeded" instead of a silent failure.

The error message shape is strict:

```
<vendor> API <reason>: <safe detail>
```

- **Never** contains the API key (sanitized by construction — we
  only include `type(exc).__name__` for network errors, never the
  original exception's args which may echo the URL)
- **Never** contains the full URL (even fixed-target URLs may contain
  identifiers worth not logging)
- Body detail is truncated at 200 chars to prevent upstream HTML
  error pages from blowing up the surface

`EgressError` subclasses `RuntimeError` so existing `except
RuntimeError` catches continue to work for backward compat with
older error handling.

### 5. Keyword-only required args on `safe_call_api`

`safe_call_api` uses `*,` to force keyword-only calls. `url`,
`headers`, and `vendor` are the three most error-prone positional
args to get wrong (swap headers with body, forget vendor label) —
requiring kwarg names surfaces mistakes at the call site instead of
at runtime.

### 6. Auth headers are the caller's responsibility, not the module's

`safe_call_api` takes a `headers` dict; the caller populates the
vendor-specific auth header (`Authorization: Bearer`, `x-api-key`,
`X-Goog-Api-Key`). Reasons:

- Each vendor has a different scheme; a generic `api_key=` kwarg
  would need branching logic inside the module — we'd still have
  vendor-specific code, just hidden
- Per ADR-007, keys go in headers not URLs; the caller is already
  responsible for assembling the request correctly
- Testing is simpler — asserting `headers={"x-api-key": "fake"}` in
  the caller's test is clearer than `api_key="fake"` + reading
  the module source to see which header it gets stuffed into

### 7. No retry / backoff logic

Every call is one-shot. Rationale:

- Single-user app — retries don't meaningfully improve availability
  at our traffic level
- Whisper calls on long audio (up to 120s) are expensive; silent
  retries would double-charge the user
- Claude rate-limit backoff should be user-visible, not papered
  over — a 429 surfaced through `EgressError` lets the UI show
  "try again in a moment" with intent
- If we ever need retries, adding them here is the right place —
  all five callers get them uniformly

## Consequences

**Easy:**
- New external-API integrations get safe-by-default timeout + error
  wrapping by calling `safe_call_api` — no opportunity to miss a
  defense
- Cascade-check table in CLAUDE.md can add a rule: "new external
  API caller → must go through egress.safe_call_api" and enforce
  via grep in a future `scripts/*_check.py`
- Tests mock `egress.requests.post` / `egress.socket.getaddrinfo`
  in one place; no mock-per-caller sprawl

**Accepted trade-offs:**
- `requests` + `urllib` both in the module = two HTTP client
  vocabularies in one file. Worth it for the reasons in Decision 2.
- The sanitized `EgressError` message format means some upstream
  diagnostics are lost (full URL, original exception args). The
  `__cause__` chain preserves them for server-side debugging; users
  only see the sanitized string.

## Alternatives considered

- **One unified function with SSRF flag**: rejected. Per Decision 1,
  the wrong flag is too easy to pass.
- **Vendor-specific subclasses (`ClaudeClient`, `WhisperClient`)**:
  rejected. Overkill for a single-user app with 5 callers. Each
  caller's vendor-specific concerns (prompt construction, multipart
  assembly) live in the caller; only the HTTP boundary is shared.
- **`httpx` instead of `requests`**: rejected. No async needed in
  Flask sync routes; `requests` is already a transitive dep; no
  benefit to adding another HTTP library.
- **Built-in retry (urllib3.Retry)**: rejected per Decision 7.
- **Opentelemetry / observability hooks at the egress boundary**:
  deferred. When we add external call tracing, this is the right
  place — but we don't need it today.

## Verification

- 17 direct unit tests in `tests/test_egress.py`:
  - `safe_fetch_user_url` input-validation: 5 tests (non-string,
    non-http scheme, missing hostname, unresolvable, never-raises)
  - `safe_call_api` happy path: 3 tests (json body, multipart body,
    custom timeout)
  - `safe_call_api` error shapes: 6 tests (network error, timeout,
    HTTP error with JSON detail, HTTP error with text fallback,
    long-body truncation, invalid-JSON response, empty-error
    trailing-colon guard)
  - `EgressError` contract: 2 tests (RuntimeError subclass,
    sanitized str() doesn't leak secrets from chained cause)
- SSRF behavior continues to be exercised by the route-level tests
  in `tests/test_tasks_api.py` (loopback, link-local, private,
  DNS-rebinding, no-redirect).
- All 5 production callers verified via import-check: egress imports
  from `scan_service.py` (2 helpers), `voice_service.py`,
  `tasks_api.py` — no caller left on raw `requests.post`.
