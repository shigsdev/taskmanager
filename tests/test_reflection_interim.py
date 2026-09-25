"""#333 - analysing without ending the reflection.

``submit`` is a one-way door: it commits a Reflection row, hard-deletes
the draft, and leaves the user on the review screen with no way back
into the same session. A user reflecting for hours wants proposals part
way through - review, apply some, keep dictating.

The property that matters, and the one every test here circles: after an
interim analysis THE DRAFT IS STILL THERE, with its text, its raw
segments and its attachments intact.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import auth


def _fake_claude(explicit=None):
    return {
        "content": [{
            "text": json.dumps({"explicit": explicit or [], "suggested": []}),
        }],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def _login(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")


def _draft(client, text="Half a thought about the new role."):
    resp = client.put("/api/reflection/draft", json={"text": text})
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)


CREATE_TASK = {
    "op": "create", "entity": "task",
    "fields": {"title": "Draft the 30/60/90"}, "reason": "you said so",
}


class TestInterimAnalysis:
    def test_returns_proposals_and_flags_itself_interim(self, client, monkeypatch):
        _login(monkeypatch)
        _draft(client)
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            resp = client.post("/api/reflection/draft/analyze")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["interim"] is True
        assert len(body["proposed_actions"]["explicit"]) == 1

    def test_the_draft_survives(self, client, monkeypatch):
        """The whole point. If the draft were retired, the user would be
        back to an empty box in the middle of a multi-hour session."""
        _login(monkeypatch)
        _draft(client, "Hours of thinking so far.")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post("/api/reflection/draft/analyze")
        draft = client.get("/api/reflection/draft").get_json()["draft"]
        assert draft is not None
        assert draft["transcript"] == "Hours of thinking so far."

    def test_attachments_survive_and_are_read(self, client, monkeypatch):
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"START DATE: 2 November."), "plan.txt")},
            content_type="multipart/form-data",
        )
        _draft(client, "Planning the runway.")
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            assert client.post("/api/reflection/draft/analyze").status_code == 200
        assert "2 November" in seen["prompt"]
        draft = client.get("/api/reflection/draft").get_json()["draft"]
        assert len(draft["context_files"]) == 1

    def test_it_does_not_leak_into_the_finished_history(self, client, monkeypatch):
        """An interim pass must not put a half-finished reflection into
        the permanent list."""
        _login(monkeypatch)
        _draft(client)
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post("/api/reflection/draft/analyze")
        assert client.get("/api/reflection").get_json()["reflections"] == []

    def test_can_be_run_repeatedly_through_a_long_session(self, client, monkeypatch):
        _login(monkeypatch)
        _draft(client, "First hour.")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            assert client.post("/api/reflection/draft/analyze").status_code == 200
        _draft(client, "First hour. Second hour, more detail.")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            assert client.post("/api/reflection/draft/analyze").status_code == 200
        draft = client.get("/api/reflection/draft").get_json()["draft"]
        assert "Second hour" in draft["transcript"]

    def test_a_second_pass_re_enables_apply(self, client, monkeypatch):
        """``confirm`` returns 409 once ``applied_at`` is set - correct for
        a finished reflection, wrong for a draft being analysed again over
        MORE text. Without the reset the user could apply only once per
        session, however long they worked."""
        _login(monkeypatch)
        _draft(client, "Drop the CSV importer.")
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            first = client.post("/api/reflection/draft/analyze").get_json()
        rid = first["id"]
        actions = first["proposed_actions"]["explicit"]
        assert client.post(
            f"/api/reflection/{rid}/confirm", json={"actions": actions}
        ).status_code == 200
        # A second apply of the SAME pass is still refused.
        assert client.post(
            f"/api/reflection/{rid}/confirm", json={"actions": actions}
        ).status_code == 409
        # A fresh pass clears the flag, so the next apply is allowed.
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            second = client.post("/api/reflection/draft/analyze").get_json()
        assert client.post(
            f"/api/reflection/{second['id']}/confirm",
            json={"actions": second["proposed_actions"]["explicit"]},
        ).status_code == 200

    def test_finishing_afterwards_still_works(self, client, monkeypatch):
        """Checkpoint, then finish: the submitted reflection carries the
        full text and the draft is gone."""
        _login(monkeypatch)
        _draft(client, "Everything I have to say.")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post("/api/reflection/draft/analyze")
            resp = client.post(
                "/api/reflection", json={"text": "Everything I have to say."}
            )
        assert resp.status_code == 201
        assert resp.get_json()["transcript"] == "Everything I have to say."
        assert client.get("/api/reflection/draft").get_json()["draft"] is None
        assert len(client.get("/api/reflection").get_json()["reflections"]) == 1

    def test_no_draft_is_404(self, client, monkeypatch):
        _login(monkeypatch)
        assert client.post("/api/reflection/draft/analyze").status_code == 404

    def test_an_empty_draft_is_refused(self, client, monkeypatch):
        _login(monkeypatch)
        _draft(client, "   ")
        assert client.post("/api/reflection/draft/analyze").status_code in (404, 422)

    def test_a_claude_failure_keeps_the_draft(self, client, monkeypatch):
        """The failure that would hurt most: losing hours of text because
        a paid call timed out."""
        _login(monkeypatch)
        _draft(client, "Hours of irreplaceable thinking.")
        with patch(
            "reflection_service._call_claude",
            side_effect=RuntimeError("Claude API network error: ReadTimeout"),
        ):
            resp = client.post("/api/reflection/draft/analyze")
        assert resp.status_code == 422
        draft = client.get("/api/reflection/draft").get_json()["draft"]
        assert draft["transcript"] == "Hours of irreplaceable thinking."

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        assert client.post("/api/reflection/draft/analyze").status_code in (
            302, 401, 403,
        )
