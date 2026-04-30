"""Central outbound HTTP module — all server-side HTTP calls go here.

Why this exists
---------------
We make outbound HTTP calls in several places (Whisper, Claude, Google
Vision, the URL preview feature). Without a central module, each
caller reimplements the same defensive concerns:

- Timeout (so a hung upstream doesn't pin a Gunicorn worker)
- Error wrapping (so the user-facing error doesn't leak the API key
  or full URL)
- For user-supplied URLs only: SSRF defense (DNS rebinding, redirect
  follow, private/loopback IP rejection)

This module exposes two functions that bake in safe defaults:

- :func:`safe_fetch_user_url` — for fetching URLs the user can
  influence (e.g. paste into the capture bar). Full SSRF defense.
- :func:`safe_call_api` — for calling fixed third-party APIs whose
  hostnames are hard-coded in the codebase. Skips SSRF checks (the
  destination is trusted and constant) but enforces timeout +
  consistent error shape.

See ADR-006 for the SSRF design decisions, ADR-007 for the
key-in-header rule.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

# --- Errors -----------------------------------------------------------------


class EgressError(RuntimeError):
    """Raised by egress functions on any failure. Message is safe to
    surface to end users — never includes the API key or full URL."""


# --- User-URL fetch (SSRF-defended) ----------------------------------------


def _is_disallowed_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib redirect handler that refuses to follow redirects.

    Without this, a safe URL could redirect to ``http://localhost/...``
    and our IP check would never re-validate the second hop.
    """

    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None  # disables redirect; caller sees the 3xx as final


def is_user_url_allowed(url: str) -> bool:
    """Return True iff the resolved IP(s) for ``url`` pass the SSRF allowlist.

    PR63 audit fix #125: extracted from safe_fetch_user_url so callers
    that need to distinguish "URL is in a forbidden network range, reject
    with 400" from "fetch failed for some other reason, return null title"
    can do so via a SINGLE canonical resolution path. Previously
    tasks_api.url_preview duplicated the resolution loop; that left a
    cosmetic TOCTOU window between the route's pre-check and
    safe_fetch_user_url's re-resolution, and was a footgun if anyone
    ever changed safe_fetch_user_url to trust a caller-supplied IP.

    Returns False on:
      - URL not http(s)
      - Hostname missing or unresolvable
      - ANY resolved IP in private/loopback/link-local/reserved/multicast/
        unspecified ranges (defense against round-robin DNS where one
        answer is safe and one isn't)
    """
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        resolved = socket.getaddrinfo(hostname, None)
        if not resolved:
            return False
        for _, _, _, _, addr in resolved:
            if _is_disallowed_ip(ipaddress.ip_address(addr[0])):
                return False
        return True
    except (socket.gaierror, ValueError):
        return False


def safe_fetch_user_url(
    url: str,
    *,
    max_bytes: int = 32 * 1024,
    timeout_sec: float = 5.0,
    user_agent: str = "Mozilla/5.0 TaskManager/1.0",
) -> str | None:
    """Fetch a user-supplied URL with SSRF protection.

    Defenses (see ADR-006):
      1. Resolve hostname to IP, reject if private/loopback/link-local/
         reserved/multicast/unspecified
      2. Pin the resolved IP into the request URL so DNS rebinding
         cannot swap IPs between validation and connection
      3. Reject if ANY IP in the resolution set is disallowed (defense
         against round-robin DNS where one answer is safe and one isn't)
      4. Refuse HTTP redirects (no second-hop IP check possible)

    Args:
        url: User-supplied URL. Must start with http:// or https://.
        max_bytes: Truncate the response body to this many bytes.
            Default 32 KB — enough for any HTML <head> block.
        timeout_sec: Request timeout in seconds.
        user_agent: User-Agent header to send.

    Returns:
        The (possibly truncated) response body as a UTF-8 string with
        replacement characters for invalid bytes, or None if the fetch
        failed (any exception, any disallowed IP, any redirect).

        None means "couldn't get the page" — never raises so callers
        can fall through to a "title unknown" UX path.
    """
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return None
        resolved = socket.getaddrinfo(hostname, None)
        if not resolved:
            return None

        # Use the first resolved IP for both validation AND the request,
        # so an attacker who returns one safe and one unsafe IP can't
        # win — we only ever connect to the one we validated.
        first_addr = resolved[0][4][0]
        first_ip = ipaddress.ip_address(first_addr)
        if _is_disallowed_ip(first_ip):
            return None
        # Also reject if any other IP in the list is disallowed.
        for _, _, _, _, addr in resolved[1:]:
            if _is_disallowed_ip(ipaddress.ip_address(addr[0])):
                return None

        # Pin IP into the URL we actually fetch; preserve original Host
        # header so upstream routes correctly. IPv6 needs brackets.
        netloc_ip = f"[{first_addr}]" if ":" in first_addr else first_addr
        if parsed.port:
            netloc_ip = f"{netloc_ip}:{parsed.port}"
        safe_url = urlunparse(parsed._replace(netloc=netloc_ip))

        host_header = hostname if not parsed.port else f"{hostname}:{parsed.port}"
        req = urllib.request.Request(  # noqa: S310
            safe_url,
            headers={"User-Agent": user_agent, "Host": host_header},
        )
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(req, timeout=timeout_sec) as resp:  # noqa: S310
            raw = resp.read(max_bytes).decode("utf-8", errors="replace")
        return raw
    except (
        socket.gaierror,
        ValueError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ):
        return None
    except Exception:  # noqa: BLE001
        # Defensive: the contract is "never raise". An unexpected
        # exception during fetching would otherwise bubble up to the
        # route, defeating the user-facing fall-through.
        return None


# --- Fixed-target API call --------------------------------------------------


def safe_call_api(
    *,
    url: str,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout_sec: float = 60.0,
    vendor: str,
) -> dict[str, Any]:
    """POST to a fixed-target third-party API; return parsed JSON.

    "Fixed-target" means the URL hostname is a constant in code (e.g.
    ``api.anthropic.com``), not user-influenced — so SSRF defenses
    are not required. We just enforce timeout + consistent error
    handling and ensure no credentials leak into raised messages.

    Args:
        url: Full request URL (no query-string secrets — keys go in
            headers per ADR-007).
        headers: Request headers including auth (Authorization,
            X-Goog-Api-Key, x-api-key, etc.).
        json: JSON body (mutually exclusive with files+data — pick one).
        files: Multipart files (mutually exclusive with json).
        data: Multipart non-file fields (used with files=).
        timeout_sec: Hard timeout. Default 60s — generous for Whisper
            transcription of long audio.
        vendor: Short label for error messages (e.g. "Whisper",
            "Claude", "Vision"). Surfaced to users; do NOT include
            anything sensitive.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        EgressError: On any failure. Message format:
            "<vendor> API <reason>: <safe detail>" — never contains
            the API key, full URL with query string, or stack trace.
    """
    try:
        if json is not None:
            resp = requests.post(url, headers=headers, json=json, timeout=timeout_sec)
        else:
            resp = requests.post(
                url, headers=headers, files=files, data=data, timeout=timeout_sec,
            )
    except requests.RequestException as e:
        # Don't include the full URL — even fixed-target URLs may
        # contain identifiers worth not logging.
        raise EgressError(
            f"{vendor} API network error: {type(e).__name__}",
        ) from e

    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") or ""
        except (ValueError, AttributeError):
            detail = (resp.text or "")[:200]
        raise EgressError(
            f"{vendor} API returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else ""),
        )

    try:
        return resp.json()
    except ValueError as e:
        raise EgressError(f"{vendor} API returned invalid JSON") from e
