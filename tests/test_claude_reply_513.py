"""#513: an empty, refused or cut-off Claude reply reaches the user as a
plain error in every feature that calls Claude.

Each caller used to read ``data.get("content", [{}])[0].get("text", "")``.
A refusal (HTTP 200, ``stop_reason: "refusal"``, ``content: []``) was an
IndexError → a bare 500; a reply cut off at max_tokens parsed as "nothing
found"; an unreadable reply in /weekly-focus said "focus not found" (404).
Now every caller goes through ``claude_client.reply_text``. These tests
drive each route with only the Claude HTTP answer faked.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from models import Task, TaskType, Tier, db

REFUSED = {"content": [], "stop_reason": "refusal"}
CUT_OFF = {"content": [{"type": "text", "text": '[{"title": "Buy mi'}],
           "stop_reason": "max_tokens"}
EMPTY = {"content": [], "stop_reason": "end_turn"}

BAD_REPLIES = pytest.mark.parametrize("reply,says", [
    (REFUSED, "Claude declined"),
    (CUT_OFF, "cut off before it finished"),
    (EMPTY, "empty answer"),
], ids=["refused", "cut-off", "empty"])


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "vision-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")


def _inbox_task(app, title="Sort me"):
    with app.app_context():
        db.session.add(Task(title=title, type=TaskType.WORK, tier=Tier.INBOX))
        db.session.commit()


class TestInboxCategorize:

    @BAD_REPLIES
    def test_bad_reply_is_a_502_saying_why(self, authed_client, app, keys, reply, says):
        _inbox_task(app)
        with patch("inbox_categorize_service._post_to_claude", return_value=reply):
            resp = authed_client.post("/api/inbox/categorize", json={})
        assert resp.status_code == 502
        assert says in resp.get_json()["error"]

    def test_unreadable_reply_is_a_502_not_a_500(self, authed_client, app, keys):
        _inbox_task(app)
        with patch("inbox_categorize_service._post_to_claude",
                   return_value={"content": [{"type": "text", "text": "Sure! Here:"}]}):
            resp = authed_client.post("/api/inbox/categorize", json={})
        assert resp.status_code == 502
        assert resp.get_json()["error"] == (
            "Claude's suggestions came back unreadable — try again.")


class TestWeeklyFocusPlan:

    @pytest.mark.parametrize("url", [
        "/api/weekly-focus/1/plan", "/api/weekly-focus/plan-all"])
    @BAD_REPLIES
    def test_bad_reply_is_a_502_saying_why(self, authed_client, keys, url, reply, says):
        authed_client.patch("/api/weekly-focus/1", json={"text": "Ship it"})
        with patch("weekly_focus_service._post_to_claude", return_value=reply):
            resp = authed_client.post(url)
        assert resp.status_code == 502
        assert says in resp.get_json()["error"]

    @pytest.mark.parametrize("url", [
        "/api/weekly-focus/1/plan", "/api/weekly-focus/plan-all"])
    def test_unreadable_reply_is_a_502_not_not_found(self, authed_client, keys, url):
        # It was a ValueError: 404 "focus not found" / 422 "no focus".
        authed_client.patch("/api/weekly-focus/1", json={"text": "Ship it"})
        with patch("weekly_focus_service._post_to_claude",
                   return_value={"content": [{"text": '{"no_changes": 1}'}]}):
            resp = authed_client.post(url)
        assert resp.status_code == 502
        assert resp.get_json()["error"] == (
            "Claude's plan came back unreadable — try again.")

    def test_plan_all_cut_off_suggests_one_focus_at_a_time(self, authed_client, keys):
        authed_client.patch("/api/weekly-focus/1", json={"text": "Ship it"})
        with patch("weekly_focus_service._post_to_claude", return_value=CUT_OFF):
            resp = authed_client.post("/api/weekly-focus/plan-all")
        assert resp.get_json()["error"].endswith("try planning one focus at a time.")

    def test_a_missing_focus_is_still_404(self, authed_client, keys):
        # The quiet case: ValueError still means "no such focus".
        resp = authed_client.post("/api/weekly-focus/1/plan")
        assert resp.status_code == 404


def _upload(client, kind):
    return client.post(
        "/api/scan/upload",
        data={"image": (io.BytesIO(b"fake jpeg"), "x.jpg", "image/jpeg"),
              "parse_as": kind},
        content_type="multipart/form-data",
    )


class TestScan:

    @pytest.mark.parametrize("kind", ["tasks", "projects", "goals"])
    @BAD_REPLIES
    def test_bad_reply_says_why_not_no_tasks_found(
        self, authed_client, keys, kind, reply, says,
    ):
        with patch("scan_service._call_vision_api", return_value="Buy milk"), \
                patch("scan_service._post_to_claude", return_value=reply):
            resp = _upload(authed_client, kind)
        assert resp.status_code == 422
        error = resp.get_json()["error"]
        assert error.startswith(f"{kind.capitalize()} parsing failed: ")
        assert says in error

    def test_cut_off_photo_hint(self, authed_client, keys):
        with patch("scan_service._call_vision_api", return_value="Buy milk"), \
                patch("scan_service._post_to_claude", return_value=CUT_OFF):
            resp = _upload(authed_client, "tasks")
        assert resp.get_json()["error"].endswith("try a photo with less on it.")

    def test_a_real_empty_list_is_still_no_tasks(self, authed_client, keys):
        # The quiet case: Claude answering "[]" is a 200 with no candidates.
        with patch("scan_service._call_vision_api", return_value="Buy milk"), \
                patch("scan_service._post_to_claude",
                      return_value={"content": [{"text": "[]"}]}):
            resp = _upload(authed_client, "tasks")
        assert resp.status_code == 200
        assert resp.get_json()["candidates"] == []


class TestVoiceMemo:

    @BAD_REPLIES
    def test_bad_reply_keeps_the_transcript_and_says_why(
        self, authed_client, keys, reply, says,
    ):
        with patch("voice_api.transcribe_audio", return_value={
                    "transcript": "buy milk tomorrow", "duration_seconds": 2.0,
                    "cost_usd": 0.0002}), \
                patch("scan_service._post_to_claude", return_value=reply):
            resp = authed_client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"fake webm"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["transcript"] == "buy milk tomorrow"
        assert body["error"].startswith("Parsing failed: ")
        assert says in body["error"]

    def test_cut_off_memo_hint(self, authed_client, keys):
        with patch("voice_api.transcribe_audio", return_value={
                    "transcript": "buy milk", "duration_seconds": 1.0,
                    "cost_usd": 0.0001}), \
                patch("scan_service._post_to_claude", return_value=CUT_OFF):
            resp = authed_client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"fake webm"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.get_json()["error"].endswith("try a shorter memo.")


class TestTranscriptImport:

    @BAD_REPLIES
    def test_bad_reply_says_why_not_no_action_items(
        self, authed_client, keys, reply, says,
    ):
        with patch("claude_client.call_claude", return_value=reply):
            resp = authed_client.post(
                "/api/import/transcript/parse", json={"text": "Action: buy milk"})
        assert resp.status_code == 503
        assert says in resp.get_json()["error"]

    def test_cut_off_transcript_hint(self, authed_client, keys):
        with patch("claude_client.call_claude", return_value=CUT_OFF):
            resp = authed_client.post(
                "/api/import/transcript/parse", json={"text": "Action: buy milk"})
        assert resp.get_json()["error"].endswith("try a shorter transcript.")

    def test_a_good_reply_still_imports(self, authed_client, keys):
        # The quiet case, through the real reader.
        good = {"content": [{"type": "text", "text": json.dumps(
            [{"title": "Buy milk"}])}], "stop_reason": "end_turn"}
        with patch("claude_client.call_claude", return_value=good):
            resp = authed_client.post(
                "/api/import/transcript/parse", json={"text": "Action: buy milk"})
        assert resp.status_code == 200
        assert [c["title"] for c in resp.get_json()["candidates"]] == ["Buy milk"]


@pytest.mark.parametrize("module,name", [
    ("import_service", "_TRANSCRIPT_PROMPT"),
    ("inbox_categorize_service", "_PROMPT_TEMPLATE"),
    ("reflection_service", "_REFLECT_PROMPT"),
    ("scan_service", "_PARSE_PROMPT"),
    ("scan_service", "_GOAL_PARSE_PROMPT"),
    ("scan_service", "_PROJECT_PARSE_PROMPT"),
    ("scan_service", "_VOICE_PARSE_PROMPT"),
    ("weekly_focus_service", "_PROMPT_TEMPLATE"),
    ("weekly_focus_service", "_PROMPT_ALL_TEMPLATE"),
    ("weekly_planner_service", "_PROMPT_TEMPLATE"),
])
def test_every_prompt_placeholder_is_a_name(module, name):
    """Found by #513: the transcript prompt's example JSON had bare
    braces, so ``.format`` raised KeyError('"title"') and every transcript
    import was a 500 from 2026-05-02. Tests mocked the whole Claude call,
    so the prompt was never built. Example JSON in a prompt needs ``{{``."""
    import importlib
    import string

    template = getattr(importlib.import_module(module), name)
    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    assert fields, f"{module}.{name} has no placeholders"
    bad = [f for f in fields if not f.isidentifier()]
    assert not bad, f"{module}.{name}: unescaped braces read as {bad}"


class TestWeeklyPlanner:

    @BAD_REPLIES
    def test_bad_reply_is_a_502_saying_why(self, authed_client, app, keys, reply, says):
        _inbox_task(app)
        with patch("weekly_planner_service._post_to_claude", return_value=reply):
            resp = authed_client.post(
                "/api/planner/weekly", json={"start_date": "2026-05-04"})
        assert resp.status_code == 502
        assert says in resp.get_json()["error"]
