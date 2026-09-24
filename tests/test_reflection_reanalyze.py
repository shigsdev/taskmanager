"""#337 + #338 — recovering a reflection whose analysis failed.

The incident (2026-09-24): a user dictated a multi-hour reflection with
~44k characters of attached documents. The Claude call ran on the 60s
client default and died with a ReadTimeout. The transcript was saved (it
is written before the Claude call), and the error screen told the user it
"can be re-analyzed later" — but no endpoint existed to do that, so the
reflection was saved forever and analysable never.

These cover both halves: the timeout is now explicit and generous, and a
saved reflection can be re-analysed from its own stored transcript AND
its own attached documents.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import auth


def _fake_claude(explicit=None, suggested=None):
    return {
        "content": [{
            "text": json.dumps({
                "explicit": explicit or [],
                "suggested": suggested or [],
            }),
        }],
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }


class TestAnalysisTimeout:
    """#337 — the call must not run on the 60s default."""

    def test_reflection_analysis_uses_a_generous_timeout(self, app):
        """A ReadTimeout here costs the user a whole reflection, so this
        asserts the value actually handed to the HTTP client — not that a
        constant exists somewhere."""
        with app.app_context(), patch(
            "claude_client.call_claude", return_value=_fake_claude()
        ) as spy:
            import reflection_service

            reflection_service._call_claude("k", "prompt")

        assert spy.call_args.kwargs["timeout_sec"] == 180, (
            "reflection analysis fell back to the 60s default — the exact "
            "regression that stranded a real reflection on 2026-09-24"
        )

    def test_timeout_is_at_least_the_weekly_planner_budget(self):
        """The planner needed 180s for the same 4096-token output shape;
        reflection also ships up to 60k chars of documents on top."""
        import reflection_service

        assert reflection_service._ANALYSIS_TIMEOUT_SEC >= 180


class TestReanalyzeRoute:
    """#338 — POST /api/reflection/<id>/analyze."""

    @staticmethod
    def _saved(client, monkeypatch, transcript="I want to drop the CSV importer."):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            resp = client.post("/api/reflection", json={"text": transcript})
        assert resp.status_code == 201, resp.get_data(as_text=True)
        return resp.get_json()["id"]

    def test_reanalyzes_a_saved_reflection(self, client, monkeypatch):
        rid = self._saved(client, monkeypatch)
        fake = _fake_claude(explicit=[
            {"op": "create", "entity": "task",
             "fields": {"title": "Draft the 30/60/90"},
             "reason": "you said so"},
        ])
        with patch("reflection_service._call_claude", return_value=fake):
            resp = client.post(f"/api/reflection/{rid}/analyze")
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["proposed_actions"]["explicit"]) == 1
        assert body["ai_cost_usd"] is not None

    def test_reanalysis_replaces_the_previous_proposals(self, client, monkeypatch):
        """A stale set from a failed or earlier run alongside a fresh one
        would make the review screen ambiguous about what it is showing."""
        rid = self._saved(client, monkeypatch)
        first = _fake_claude(explicit=[
            {"op": "create", "entity": "task",
             "fields": {"title": "Old idea"}, "reason": "r"},
        ])
        with patch("reflection_service._call_claude", return_value=first):
            client.post(f"/api/reflection/{rid}/analyze")
        second = _fake_claude(explicit=[
            {"op": "create", "entity": "task",
             "fields": {"title": "New idea"}, "reason": "r"},
        ])
        with patch("reflection_service._call_claude", return_value=second):
            resp = client.post(f"/api/reflection/{rid}/analyze")
        titles = [
            a.get("title") or a.get("fields", {}).get("title")
            for a in resp.get_json()["proposed_actions"]["explicit"]
        ]
        assert "New idea" in titles
        assert "Old idea" not in titles

    def test_reanalysis_feeds_the_attached_documents_back_in(
        self, client, monkeypatch
    ):
        """#328 documents live on the reflection. If re-analysis dropped
        them, the second read would silently see less than the first."""
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post(
                "/api/reflection/attachment",
                data={"file": (__import__("io").BytesIO(
                    b"BACKGROUND: the role starts on 2 November."), "plan.txt")},
                content_type="multipart/form-data",
            )
            resp = client.post("/api/reflection", json={"text": "A week of prep."})
        rid = resp.get_json()["id"]

        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            assert client.post(f"/api/reflection/{rid}/analyze").status_code == 200
        assert "2 November" in seen["prompt"], (
            "attached-document text did not reach the re-analysis prompt"
        )

    def test_unknown_reflection_is_404(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.post(
            "/api/reflection/00000000-0000-0000-0000-000000000338/analyze"
        )
        assert resp.status_code == 404

    def test_a_claude_failure_is_422_and_keeps_the_reflection(
        self, client, monkeypatch
    ):
        """The whole point: a failed re-run must leave the transcript
        exactly as safe as it was before the click."""
        rid = self._saved(client, monkeypatch)
        with patch(
            "reflection_service._call_claude",
            side_effect=RuntimeError("Claude API network error: ReadTimeout"),
        ):
            resp = client.post(f"/api/reflection/{rid}/analyze")
        assert resp.status_code == 422
        assert "ReadTimeout" in resp.get_json()["error"]

        still = client.get(f"/api/reflection/{rid}")
        assert still.status_code == 200
        assert still.get_json()["transcript"]

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.post(
            "/api/reflection/00000000-0000-0000-0000-000000000338/analyze"
        )
        assert resp.status_code in (302, 401, 403)
