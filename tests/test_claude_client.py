"""Tests for claude_client — the single Anthropic Messages-API client (#195).

Before #195, four services each carried a near-identical
`_post_to_claude`. They now delegate to `claude_client.call_claude`;
these tests pin that one shared client's behaviour.
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
    # The weekly planner passes 180s for its large-output calls.
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
