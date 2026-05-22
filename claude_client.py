"""Single Anthropic (Claude) Messages-API client — #195.

Before this module, four services (`scan_service`,
`inbox_categorize_service`, `weekly_focus_service`,
`weekly_planner_service`) each carried a near-identical
`_post_to_claude` — the same `egress.safe_call_api` POST to
``/v1/messages`` — and a fifth (`import_service`) inlined the same
call. The model id was a bare hardcoded string in five places.

This centralises the HTTP mechanics and the model ids so a model
bump, an `anthropic-version` change, or an egress-policy tweak is a
single edit. The call still routes through `egress.safe_call_api`
(ADR-006/007/023): API key in a header (never the URL), SSRF-safe,
vendor-scrubbed logging.

Each service keeps its own ``_post_to_claude`` *name* as a one-line
delegator to `call_claude`, so existing
``patch("<service>._post_to_claude")`` test mocks keep working
unchanged — the consolidation is invisible to the test suite.
"""
from __future__ import annotations

from typing import Any

# --- Anthropic model ids — the single source of truth. Bump here. -----------
# Sonnet: reasoning over prose (image/transcript extraction).
SONNET = "claude-sonnet-4-6"
# Haiku: cheap, well-defined classification (inbox triage, weekly focus +
# planner). ~10x cheaper than Sonnet; used where the task is structured.
HAIKU = "claude-haiku-4-5-20251001"

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# Default per-request timeout. The weekly planner overrides this (180s)
# because large max_tokens outputs genuinely take 60-150s end to end.
_DEFAULT_TIMEOUT_SEC = 60


def call_claude(
    *,
    api_key: str,
    prompt: str,
    max_tokens: int,
    model: str,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """POST a single user-message ``prompt`` to the Anthropic Messages API.

    Args:
        api_key: Anthropic API key (goes in the ``x-api-key`` header).
        prompt: the user-message content.
        max_tokens: response token cap.
        model: one of :data:`SONNET` / :data:`HAIKU`.
        timeout_sec: per-request timeout; defaults to 60s.

    Returns:
        The parsed JSON response dict (caller extracts ``content``).

    Raises:
        RuntimeError: on any egress failure (network error, 4xx/5xx) —
            callers surface it as an HTTP 502. The underlying
            ``egress.EgressError`` is chained as ``__cause__``.
    """
    from egress import EgressError, safe_call_api

    try:
        return safe_call_api(
            url=_ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout_sec=timeout_sec,
            vendor="Claude",
        )
    except EgressError as e:
        raise RuntimeError(str(e)) from e
