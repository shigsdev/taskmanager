"""Single Anthropic (Claude) Messages-API client — #195.

Before this module, four services (`scan_service`,
`inbox_categorize_service`, `weekly_focus_service`,
`weekly_planner_service`) each carried a near-identical
`_post_to_claude` — the same `egress.safe_call_api` POST to
``/v1/messages`` — and a fifth (`import_service`) inlined the same
call. The model id was a bare hardcoded string in five places.

Six callers use it today: those five plus ``reflection_service``
(#511 recount), which calls :func:`call_claude` directly. The five read
the reply through :func:`reply_text` (#513); reflection keeps its own
reader because it retries a cut-off analysis with more room (#342).

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

# Default per-request timeout. The weekly planner (180s) and reflection
# (180s, 300s on retry) override it: large max_tokens outputs genuinely
# take 60-150s end to end.
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


def reply_text(response: Any, *, cut_off_hint: str = "try again") -> str:
    """The text of a Messages-API reply, or a RuntimeError saying why not (#513).

    ``data["content"][0]["text"]`` is not safe: a refusal arrives as HTTP
    200 with ``stop_reason: "refusal"`` and can carry ``content: []``
    (IndexError → a bare 500), and a reply cut off at ``max_tokens`` is
    half a JSON document that parsers read as "nothing found". Every
    caller turns the RuntimeError into an error the user sees, like an
    egress failure from :func:`call_claude`.

    Args:
        response: the dict :func:`call_claude` returned.
        cut_off_hint: what to tell the user when the answer ran out of
            room, e.g. ``"try a shorter transcript"``.
    """
    data = response if isinstance(response, dict) else {}
    stop = data.get("stop_reason")
    if stop == "refusal":
        raise RuntimeError(
            "Claude declined to answer this one — try rewording it.",
        )
    if stop == "max_tokens":
        raise RuntimeError(
            f"Claude's answer was cut off before it finished — {cut_off_hint}.",
        )
    content = data.get("content")
    blocks = content if isinstance(content, list) else []
    text = "".join(
        b["text"] for b in blocks
        if isinstance(b, dict) and isinstance(b.get("text"), str)
    )
    if not text.strip():
        raise RuntimeError("Claude sent back an empty answer — try again.")
    return text
