# ADR-006: SSRF defense for outbound URL fetch (`/api/tasks/url-preview`)

Date: 2026-04-18
Status: ACCEPTED

## Context

`/api/tasks/url-preview` accepts a URL from the user, fetches it
server-side, and returns the page's `<title>`. This pattern is
inherently SSRF-prone: server-side outbound requests can be tricked
into reaching internal services the user couldn't reach directly.

Two known SSRF bypasses against the original implementation:

1. **DNS rebinding**: The original code called `socket.getaddrinfo`
   to resolve the hostname (and reject private/loopback IPs), then
   called `urllib.request.urlopen` separately. These are two distinct
   syscalls — DNS rebinding swaps the answer between them, so a
   "safe" IP at validation becomes `127.0.0.1` at connection.
2. **HTTP redirect following**: The original code used `urlopen`
   default behavior, which auto-follows redirects. A safe URL can
   redirect to `http://localhost/secrets`, and the second hop's IP
   is never re-validated.

Why we care for a single-user app: Railway's internal network has
metadata services (e.g. cloud `169.254.169.254`) that may expose
credentials. An attacker who can trick the user into pasting a
malicious URL (or hijack a saved URL) could exfiltrate secrets.

## Decision

Three layered defenses:

1. **Resolve once, pin into URL.** Call `socket.getaddrinfo` once,
   take the first resolved IP, and rewrite the request URL to use
   that IP directly (e.g. `https://93.184.216.34/path`). Original
   `Host` header preserved so upstream routes correctly. Eliminates
   the rebinding gap because the connect uses the validated IP.
2. **Reject any disallowed IP in the resolution.** If `getaddrinfo`
   returns multiple IPs and ANY of them is private/loopback/
   link-local/reserved/multicast/unspecified, reject the whole URL.
   Defends against round-robin DNS where one answer is safe and one
   isn't.
3. **Disable HTTP redirect following.** Custom `_NoRedirect` handler
   subclass returns `None` from `redirect_request`, which makes
   urllib treat any 3xx as a final response. The first hop is already
   pinned safe; we don't trust any second hop.

Implementation in `tasks_api.url_preview`. Regression tests in
`tests/test_tasks_api.py` cover loopback, link-local, private network,
mixed-IP DNS rebind, and redirect-follow rejection.

## Consequences

**Easy:**
- SSRF closed against the documented attack patterns
- All test cases pass; no behavioral change for legitimate URL fetches

**Hard:**
- A small loss of capability: URLs that legitimately use HTTP redirects
  (e.g. shortened URLs, sites that redirect to canonical) won't have
  their redirect target's title fetched. We get whatever title is at
  the original URL (often empty for shortener URLs). Acceptable trade.
- IPv6 URLs have to bracket the literal IP in the rewritten URL —
  handled by the implementation but easy to break in future edits.

## Alternatives considered

- **Use the `requests` library with `allow_redirects=False`**: cleaner
  than urllib, but requires more refactor; queued as a future cleanup
  (consolidating all outbound HTTP through a single `egress.py` module
  is a separate item)
- **Block on a hostname allowlist instead of IP**: too restrictive for
  a personal app where the user pastes arbitrary URLs from articles
- **No URL preview feature**: addressed separately; the feature has
  enough user value to keep
