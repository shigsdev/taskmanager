"""Tests for claude_client — the single Anthropic Messages-API client (#195).

Before #195, four services each carried a near-identical
`_post_to_claude`. They now delegate to `claude_client.call_claude`
(reflection calls it directly — six callers as of #511); these tests
pin that one shared client's behaviour. How each caller reads the reply
(empty / refused / cut off) is #513's.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import claude_client
from egress import EgressError


def test_model_constants_match_anthropic_ids():
    # The single source of truth for the model ids — a bump happens here.
    assert claude_client.SONNET == "claude-sonnet-4-6"
    assert claude_client.HAIKU == "claude-haiku-4-5-20251001"


def test_call_claude_builds_the_messages_request():
    captured = {}

    def fake_safe_call_api(**kwargs):
        captured.update(kwargs)
        return {"content": [{"text": "hi"}]}

    with patch("egress.safe_call_api", side_effect=fake_safe_call_api):
        out = claude_client.call_claude(
            api_key="secret-key", prompt="hello", max_tokens=128,
            model=claude_client.HAIKU,
        )

    assert out == {"content": [{"text": "hi"}]}
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "secret-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["json"]["model"] == "claude-haiku-4-5-20251001"
    assert captured["json"]["max_tokens"] == 128
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "hello"}
    ]
    assert captured["vendor"] == "Claude"
    # Default timeout when not overridden.
    assert captured["timeout_sec"] == 60


def test_call_claude_honours_a_custom_timeout():
    # The weekly planner and reflection pass 180s for large outputs.
    captured = {}

    def fake_safe_call_api(**kwargs):
        captured.update(kwargs)
        return {}

    with patch("egress.safe_call_api", side_effect=fake_safe_call_api):
        claude_client.call_claude(
            api_key="k", prompt="p", max_tokens=12000,
            model=claude_client.HAIKU, timeout_sec=180,
        )
    assert captured["timeout_sec"] == 180


def test_call_claude_wraps_egress_error_as_runtime_error():
    # Callers catch RuntimeError and map it to HTTP 502 — an EgressError
    # leaking through unwrapped would be an unhandled 500.
    with (
        patch("egress.safe_call_api", side_effect=EgressError("upstream 503")),
        pytest.raises(RuntimeError, match="upstream 503"),
    ):
        claude_client.call_claude(
            api_key="k", prompt="p", max_tokens=10,
            model=claude_client.SONNET,
        )


def test_the_egress_error_is_kept_as_the_cause():
    original = EgressError("Claude API returned HTTP 529: overloaded")
    with (
        patch("egress.safe_call_api", side_effect=original),
        pytest.raises(RuntimeError) as exc,
    ):
        claude_client.call_claude(
            api_key="k", prompt="p", max_tokens=10, model=claude_client.HAIKU)
    assert exc.value.__cause__ is original


def test_the_key_never_reaches_the_error_message():
    """The real egress layer builds the message (vendor + status +
    upstream detail); the key must not be in what callers show."""
    from unittest.mock import MagicMock

    resp = MagicMock(ok=False, status_code=401)
    resp.json.return_value = {"error": {"message": "invalid x-api-key"}}
    with (
        patch("egress.requests.post", return_value=resp) as post,
        pytest.raises(RuntimeError) as exc,
    ):
        claude_client.call_claude(
            api_key="sk-ant-SECRET-123", prompt="p", max_tokens=10,
            model=claude_client.HAIKU)
    assert "sk-ant-SECRET-123" not in str(exc.value)
    assert "401" in str(exc.value)
    # ...and it travelled in the header, never the URL (ADR-007).
    args, kwargs = post.call_args
    assert "sk-ant-SECRET-123" not in args[0]
    assert kwargs["headers"]["x-api-key"] == "sk-ant-SECRET-123"


def test_the_planner_asks_haiku_with_its_long_timeout():
    import weekly_planner_service

    with patch("claude_client.call_claude", return_value={}) as call:
        weekly_planner_service._post_to_claude("k", "prompt", max_tokens=12000)
    kwargs = call.call_args.kwargs
    assert kwargs["model"] == claude_client.HAIKU
    assert kwargs["timeout_sec"] == 180
    assert kwargs["max_tokens"] == 12000
