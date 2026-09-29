"""#342: a cut-off analysis must never be reported as "no changes".

The incident (2026-09-29): a 12,687-char reflection with 44k chars of
attached PDFs was analysed for $0.1224 and came back with zero proposed
actions. The screen said "Claude didn't propose any changes — your week
sounds aligned with your current plan already."

Nothing about that was true. The reply had been cut off at the
4096-token ceiling, the truncated JSON would not parse, and
``_extract_action_object`` turned any parse failure into empty buckets —
so an incomplete answer and a genuine "nothing to do" were the same
value. Worse, the API hands back ``stop_reason: "max_tokens"`` saying
exactly this, and nothing in the codebase read it.

Three rules pinned here:

1. Truncation is DETECTED, not inferred.
2. Truncation is RETRIED once with more room, because that is the only
   failure a bigger ceiling actually fixes — and both calls are billed,
   so both are reported.
3. Anything still unreadable RAISES, landing on the existing
   "saved, analysis failed" path. A reflection is never lost (#165), and
   the user is never told they are aligned when we simply could not read
   the answer.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from reflection_service import (
    _ANALYSIS_MAX_TOKENS,
    _ANALYSIS_MAX_TOKENS_RETRY,
    _ANALYSIS_TIMEOUT_SEC,
    _extract_action_object,
    analyze_reflection,
)

TEXT = "A long reflection about the first ninety days at the new job."

_ACTIONS = {
    "explicit": [{
        "op": "create", "entity": "task",
        "fields": {"title": "Draft first-90-days plan"},
        "reason": "you said it slipped",
    }],
    "suggested": [],
}


def _reply(text: str, *, stop_reason="end_turn", in_tok=20000, out_tok=500):
    """A Claude API response envelope, shaped like the real one."""
    return {
        "content": [{"text": text}],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }


def _good():
    import json
    return _reply(json.dumps(_ACTIONS))


def _cut_off():
    """What a truncated reply actually looks like: valid JSON, then cut."""
    return _reply(
        '{"explicit": [{"op": "create", "entity": "task", "target": "Draft',
        stop_reason="max_tokens", out_tok=_ANALYSIS_MAX_TOKENS,
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


class TestTheExtractorReportsFailure:
    """The root of it: unreadable and empty must not be the same value."""

    def test_unreadable_returns_none(self):
        assert _extract_action_object("not json at all") is None
        assert _extract_action_object("") is None
        assert _extract_action_object(
            '{"explicit": [{"op": "create", "target": "Draft'
        ) is None

    def test_a_real_but_empty_answer_is_still_an_answer(self):
        """Claude saying "nothing to propose" is valid and must survive."""
        got = _extract_action_object('{"explicit": [], "suggested": []}')
        assert got == {"explicit": [], "suggested": []}

    def test_a_fenced_reply_still_parses(self):
        got = _extract_action_object(
            '```json\n{"explicit": [], "suggested": []}\n```'
        )
        assert got == {"explicit": [], "suggested": []}


class TestTruncationIsRetried:
    def test_a_cut_off_reply_is_retried_with_more_room(self, app):
        calls = []

        def fake(api_key, prompt, *, max_tokens=_ANALYSIS_MAX_TOKENS,
                 timeout_sec=_ANALYSIS_TIMEOUT_SEC):
            calls.append(max_tokens)
            return _cut_off() if len(calls) == 1 else _good()

        with patch("reflection_service._call_claude", side_effect=fake):
            out = analyze_reflection(TEXT)

        assert calls == [_ANALYSIS_MAX_TOKENS, _ANALYSIS_MAX_TOKENS_RETRY]
        assert len(out["explicit"]) == 1
        assert out["retried"] is True

    def test_both_calls_are_billed_and_reported(self, app):
        """The user pays for two calls; showing one would understate it."""
        def fake(api_key, prompt, *, max_tokens=_ANALYSIS_MAX_TOKENS,
                 timeout_sec=_ANALYSIS_TIMEOUT_SEC):
            if max_tokens == _ANALYSIS_MAX_TOKENS:
                return _cut_off()                       # 20000 in, 8192 out
            return _reply(
                __import__("json").dumps(_ACTIONS), in_tok=20000, out_tok=600
            )

        with patch("reflection_service._call_claude", side_effect=fake):
            out = analyze_reflection(TEXT)

        first = 20000 / 1e6 * 3.0 + _ANALYSIS_MAX_TOKENS / 1e6 * 15.0
        second = 20000 / 1e6 * 3.0 + 600 / 1e6 * 15.0
        assert out["ai_cost_usd"] == pytest.approx(first + second)

    def test_a_normal_analysis_makes_exactly_one_call(self, app):
        """The retry must not fire on every reflection."""
        calls = []

        def fake(api_key, prompt, *, max_tokens=_ANALYSIS_MAX_TOKENS,
                 timeout_sec=_ANALYSIS_TIMEOUT_SEC):
            calls.append(max_tokens)
            return _good()

        with patch("reflection_service._call_claude", side_effect=fake):
            out = analyze_reflection(TEXT)

        assert calls == [_ANALYSIS_MAX_TOKENS]
        assert out["retried"] is False

    def test_the_retry_gets_a_longer_timeout(self, app):
        """A genuinely bigger answer takes proportionally longer to stream."""
        seen = []

        def fake(api_key, prompt, *, max_tokens=_ANALYSIS_MAX_TOKENS,
                 timeout_sec=_ANALYSIS_TIMEOUT_SEC):
            seen.append(timeout_sec)
            return _cut_off() if len(seen) == 1 else _good()

        with patch("reflection_service._call_claude", side_effect=fake):
            analyze_reflection(TEXT)

        assert seen[1] > seen[0]


class TestUnrecoverableFailsHonestly:
    """The bit that makes the 2026-09-29 outcome impossible."""

    def test_truncated_twice_raises_instead_of_claiming_no_changes(self, app):
        with (
            patch("reflection_service._call_claude", return_value=_cut_off()),
            pytest.raises(RuntimeError) as e,
        ):
            analyze_reflection(TEXT)
        msg = str(e.value).lower()
        assert "too long" in msg
        # It must tell the user their words are safe and what to do next.
        assert "saved" in msg
        assert "re-analyz" in msg

    def test_an_unreadable_reply_raises_without_a_second_call(self, app):
        """A bigger ceiling cannot fix a reply that was not cut off."""
        calls = []

        def fake(api_key, prompt, *, max_tokens=_ANALYSIS_MAX_TOKENS,
                 timeout_sec=_ANALYSIS_TIMEOUT_SEC):
            calls.append(max_tokens)
            return _reply("I'm afraid I can't help with that.")

        with (
            patch("reflection_service._call_claude", side_effect=fake),
            pytest.raises(RuntimeError) as e,
        ):
            analyze_reflection(TEXT)
        assert len(calls) == 1, "must not pay for a retry that cannot help"
        assert "could not be read" in str(e.value).lower()

    def test_an_empty_answer_is_NOT_an_error(self, app):
        """Claude genuinely proposing nothing is a real, valid outcome.

        The whole fix would be worthless if it turned every quiet week
        into a scary error — the message the user reads must still be
        earned.
        """
        with patch(
            "reflection_service._call_claude",
            return_value=_reply('{"explicit": [], "suggested": []}'),
        ):
            out = analyze_reflection(TEXT)
        assert out["explicit"] == []
        assert out["suggested"] == []
        assert out["retried"] is False


class TestTheCeilingWasRaised:
    def test_the_first_attempt_has_more_room_than_the_incident(self):
        """4096 is what the 2026-09-29 reflection hit.

        max_tokens is a ceiling, not a reservation — billing is on tokens
        actually written — so raising it costs nothing on a normal
        reflection and removes almost every truncation.
        """
        assert _ANALYSIS_MAX_TOKENS > 4096
        assert _ANALYSIS_MAX_TOKENS_RETRY > _ANALYSIS_MAX_TOKENS
