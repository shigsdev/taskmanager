"""#334 - continuing a past reflection.

Reflecting toward a start date weeks out is not one sitting. Every submit
used to be terminal, so the next sitting opened an empty box and the
earlier thinking survived only as the 1200-char snippet the continuity
block carries.

Continuing FORKS. The load-bearing property, and the one most of these
tests circle: **the parent row is read, never written.** The /reflection
page and the Help page both promise every reflection is kept forever, so
a continuation that mutated the original would quietly turn "what I
thought on the 21st" into "what I thought on the 28th".

The second property worth its own tests: an open draft with content is
never clobbered. Drafts are hard-deleted by design (no recycle bin), and
this user's sittings run for hours.
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


CREATE_TASK = {
    "op": "create", "entity": "task",
    "fields": {"title": "Draft the 30/60/90"}, "reason": "you said so",
}


def _saved(client, text="Week one: learn the settlement flow."):
    """A submitted reflection, the way the user makes one."""
    with patch("reflection_service._call_claude", return_value=_fake_claude()):
        resp = client.post("/api/reflection", json={"text": text})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _draft(client, text):
    resp = client.put("/api/reflection/draft", json={"text": text})
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    return resp.get_json()["draft"]


def _get_draft(client):
    return client.get("/api/reflection/draft").get_json()["draft"]


class TestForkingOpensADraft:
    def test_the_parent_text_comes_back_in_full(self, client, monkeypatch):
        """Not the 1200-char continuity snippet - the whole thing. This is
        the difference between continuing a reflection and being reminded
        that one happened."""
        _login(monkeypatch)
        long_text = "Settlement notes. " * 200  # ~3600 chars
        parent = _saved(client, long_text)

        resp = client.post(f"/api/reflection/{parent['id']}/continue")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        draft = resp.get_json()["draft"]
        assert draft["transcript"] == long_text.strip()
        assert len(draft["transcript"]) > 3000

    def test_the_fork_is_a_draft_and_stays_out_of_history(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client)
        client.post(f"/api/reflection/{parent['id']}/continue")

        assert _get_draft(client) is not None
        history = client.get("/api/reflection").get_json()["reflections"]
        assert [r["id"] for r in history] == [parent["id"]]

    def test_it_records_what_it_continues(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client)
        client.patch(f"/api/reflection/{parent['id']}",
                     json={"title": "Sunday planning"})

        draft = client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).get_json()["draft"]
        assert draft["continued_from_id"] == parent["id"]
        # The lineage block carries exactly what the client needs to NAME
        # the parent, so the label rule is not reimplemented per surface.
        assert draft["continued_from"]["title"] == "Sunday planning"
        assert draft["continued_from"]["id"] == parent["id"]
        assert draft["continued_from"]["iso_week"]
        assert draft["continued_from"]["created_at"]

    def test_lineage_is_null_on_an_ordinary_reflection(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client)
        assert parent["continued_from_id"] is None
        assert parent["continued_from"] is None

    def test_the_fork_belongs_to_this_week_not_the_parents(
        self, client, monkeypatch,
    ):
        """It is a new sitting, written now. Inheriting the parent's
        iso_week would file today's thinking under a past week and mis-group
        the history view."""
        _login(monkeypatch)
        import reflection_service
        parent = _saved(client)
        with patch.object(reflection_service, "current_iso_week",
                          return_value="2099-W01"):
            draft = client.post(
                f"/api/reflection/{parent['id']}/continue"
            ).get_json()["draft"]
        assert draft["iso_week"] == "2099-W01"
        assert parent["iso_week"] != "2099-W01"


class TestTheParentIsNeverTouched:
    """The promise on /reflection and in the Help page."""

    def test_transcript_title_and_analysis_all_survive(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "The original words.")
        client.patch(f"/api/reflection/{parent['id']}", json={"title": "Sitting 1"})
        before = client.get(f"/api/reflection/{parent['id']}").get_json()

        client.post(f"/api/reflection/{parent['id']}/continue")

        after = client.get(f"/api/reflection/{parent['id']}").get_json()
        assert after["transcript"] == "The original words."
        assert after["title"] == "Sitting 1"
        assert after["proposed_actions"] == before["proposed_actions"]
        assert after["is_draft"] is False
        assert after["created_at"] == before["created_at"]

    def test_an_applied_parent_keeps_its_audit_trail(self, client, monkeypatch):
        """`applied_at` is the record that these changes were really made.
        A fork must not reset it - unlike #333's interim pass, which resets
        the DRAFT's flag on purpose."""
        _login(monkeypatch)
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            parent = client.post(
                "/api/reflection", json={"text": "Create the plan task."},
            ).get_json()
        client.post(f"/api/reflection/{parent['id']}/confirm",
                    json={"actions": parent["proposed_actions"]["explicit"]})
        applied_at = client.get(
            f"/api/reflection/{parent['id']}"
        ).get_json()["applied_at"]
        assert applied_at is not None

        client.post(f"/api/reflection/{parent['id']}/continue")

        after = client.get(f"/api/reflection/{parent['id']}").get_json()
        assert after["applied_at"] == applied_at
        assert after["applied_actions"] is not None

    def test_editing_the_fork_does_not_edit_the_parent(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "Original.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        _draft(client, "Original. And now a lot more thinking.")

        assert client.get(
            f"/api/reflection/{parent['id']}"
        ).get_json()["transcript"] == "Original."


class TestTheLineageSurvivesTheAutosaveLoop:
    """The realistic path is continue → type → autosave → type → submit.

    `save_draft` upserts the SAME row on every keystroke burst, so a
    version of it that rebuilt the draft (or reset unmentioned columns)
    would silently drop the lineage somewhere between the fork and the
    submit — and nothing on screen would say so. #328 shipped exactly
    this class of bug guard for attachments; the same applies here.
    """

    def test_an_autosave_keeps_the_link(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "First sitting.")
        client.post(f"/api/reflection/{parent['id']}/continue")

        for text in ("First sitting. Typing", "First sitting. Typing more",
                     "First sitting. Typing more and more"):
            draft = _draft(client, text)
            assert draft["continued_from_id"] == parent["id"], text

        assert _get_draft(client)["continued_from_id"] == parent["id"]

    def test_an_autosave_keeps_the_attachments_too(self, client, monkeypatch):
        """Same row, same risk — asserted here because a fork is the one
        case where both the lineage and the files arrive without the user
        having added them in this session."""
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"START DATE: 2 November."), "plan.txt")},
            content_type="multipart/form-data",
        )
        parent = _saved(client, "Reading the plan.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        draft = _draft(client, "Reading the plan. More thoughts.")
        assert len(draft["context_files"]) == 1
        assert draft["continued_from_id"] == parent["id"]

    def test_the_link_reaches_the_submitted_row_after_autosaves(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        parent = _saved(client, "First sitting.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        _draft(client, "First sitting. Plus")
        _draft(client, "First sitting. Plus a whole second sitting.")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            child = client.post("/api/reflection", json={
                "text": "First sitting. Plus a whole second sitting.",
            }).get_json()
        assert child["continued_from_id"] == parent["id"]

    def test_clearing_the_box_does_not_clear_the_link(self, client, monkeypatch):
        """A user who selects-all-deletes has emptied the TEXT, not
        abandoned the fork — "Start fresh instead" is the control for
        that, and it deletes the draft outright."""
        _login(monkeypatch)
        parent = _saved(client, "First sitting.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        draft = _draft(client, "")
        assert draft["continued_from_id"] == parent["id"]


class TestAttachmentsAndSegmentsCarryOver:
    def test_documents_come_with_it_and_reach_the_prompt(
        self, client, monkeypatch,
    ):
        """The backlog row called this out: without the documents the
        continued analysis is quietly weaker than the original, with
        nothing on screen to say so."""
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"START DATE: 2 November."), "plan.txt")},
            content_type="multipart/form-data",
        )
        parent = _saved(client, "Reading the plan.")
        assert len(parent["context_files"]) == 1

        draft = client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).get_json()["draft"]
        assert len(draft["context_files"]) == 1
        assert draft["context_files"][0]["filename"] == "plan.txt"

        # And the TEXT survived, not just the metadata row.
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            assert client.post(
                "/api/reflection/draft/analyze"
            ).status_code == 200
        assert "2 November" in seen["prompt"]

    def test_voice_segments_carry_over_without_their_cost(
        self, client, monkeypatch,
    ):
        """The text and timings are the audit value (#237). The Whisper
        spend is already booked against the parent - copying the number
        onto the fork would double-count it."""
        _login(monkeypatch)
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            parent = client.post("/api/reflection", json={
                "text": "Spoken thoughts.",
                "raw_segments": [{
                    "text": "Spoken thoughts.",
                    "duration_seconds": 12.5,
                    "cost_usd": 0.00125,
                    "recorded_at": "2026-09-24T10:00:00Z",
                }],
            }).get_json()
        assert parent["raw_segments"][0]["cost_usd"] == 0.00125

        draft = client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).get_json()["draft"]
        assert len(draft["raw_segments"]) == 1
        assert draft["raw_segments"][0]["text"] == "Spoken thoughts."
        assert draft["raw_segments"][0]["duration_seconds"] == 12.5
        assert draft["raw_segments"][0]["cost_usd"] is None
        # The parent's own number is untouched.
        assert client.get(
            f"/api/reflection/{parent['id']}"
        ).get_json()["raw_segments"][0]["cost_usd"] == 0.00125

    def test_input_mode_is_inherited(self, client, monkeypatch):
        _login(monkeypatch)
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            parent = client.post("/api/reflection", json={
                "text": "Spoken.",
                "raw_segments": [{"text": "Spoken."}],
            }).get_json()
        assert parent["input_mode"] == "voice"
        draft = client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).get_json()["draft"]
        assert draft["input_mode"] == "voice"


class TestRefusingToClobberAnOpenDraft:
    def test_a_draft_with_text_blocks_the_fork(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client)
        _draft(client, "Two hours of unsaved-anywhere-else thinking.")

        resp = client.post(f"/api/reflection/{parent['id']}/continue")
        assert resp.status_code == 409
        assert "in progress" in resp.get_json()["error"]

    def test_the_refused_draft_is_still_intact(self, client, monkeypatch):
        """The failure that would actually hurt: a 409 that took the text
        with it. Drafts are hard-deleted, so there is no undo."""
        _login(monkeypatch)
        parent = _saved(client)
        _draft(client, "Two hours of thinking.")
        client.post(f"/api/reflection/{parent['id']}/continue")

        draft = _get_draft(client)
        assert draft["transcript"] == "Two hours of thinking."
        assert draft["continued_from_id"] is None

    def test_a_draft_holding_only_an_attachment_also_blocks(
        self, client, monkeypatch,
    ):
        """A file attached before a word was typed is still work. #328
        treats it as restorable on its own; so must this."""
        _login(monkeypatch)
        parent = _saved(client)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"notes"), "notes.txt")},
            content_type="multipart/form-data",
        )
        assert client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).status_code == 409

    def test_an_empty_draft_shell_is_reused_not_refused(
        self, client, monkeypatch,
    ):
        """The autosave loop leaves an empty row behind the moment the user
        clears the box. Refusing on that would make Continue look broken
        for no reason."""
        _login(monkeypatch)
        parent = _saved(client)
        _draft(client, "   ")

        resp = client.post(f"/api/reflection/{parent['id']}/continue")
        assert resp.status_code == 200
        draft = _get_draft(client)
        assert draft["continued_from_id"] == parent["id"]

    def test_reusing_the_shell_leaves_exactly_one_draft(
        self, client, monkeypatch,
    ):
        """Two open drafts would make `get_open_draft` pick by updated_at -
        a coin toss the user cannot see."""
        _login(monkeypatch)
        from models import Reflection, db
        parent = _saved(client)
        _draft(client, "")
        client.post(f"/api/reflection/{parent['id']}/continue")

        drafts = db.session.query(Reflection).filter(
            Reflection.is_draft.is_(True),
        ).all()
        assert len(drafts) == 1


class TestWhatCannotBeContinued:
    def test_unknown_id_is_404(self, client, monkeypatch):
        _login(monkeypatch)
        assert client.post(
            "/api/reflection/11111111-1111-1111-1111-111111111111/continue"
        ).status_code == 404

    def test_a_draft_cannot_be_continued(self, client, monkeypatch):
        """It is already open. Forking it would produce two rows holding
        the same in-progress text."""
        _login(monkeypatch)
        draft = _draft(client, "Still writing this one.")
        assert client.post(
            f"/api/reflection/{draft['id']}/continue"
        ).status_code == 404

    def test_a_soft_deleted_reflection_cannot_be_continued(
        self, client, monkeypatch,
    ):
        """It is in the recycle bin. Restore it first - continuing from the
        bin would resurrect its content without restoring the row."""
        _login(monkeypatch)
        parent = _saved(client)
        client.delete(f"/api/reflection/{parent['id']}")
        assert client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).status_code == 404

    def test_an_archived_reflection_can_still_be_continued(
        self, client, monkeypatch,
    ):
        """Archiving only hides a row from the default list; it is not a
        deletion, so it stays continuable."""
        _login(monkeypatch)
        parent = _saved(client)
        client.post(f"/api/reflection/{parent['id']}/archive")
        assert client.post(
            f"/api/reflection/{parent['id']}/continue"
        ).status_code == 200

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        assert client.post(
            "/api/reflection/11111111-1111-1111-1111-111111111111/continue"
        ).status_code in (302, 401, 403)

    def test_get_is_not_allowed(self, client, monkeypatch):
        """State-mutating routes are POST-only (#190) - a GET would be a
        CSRF surface reachable from an <img src>."""
        _login(monkeypatch)
        parent = _saved(client)
        assert client.get(
            f"/api/reflection/{parent['id']}/continue"
        ).status_code == 405


class TestSubmittingAContinuation:
    def test_both_reflections_exist_afterwards(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "First sitting.")
        client.post(f"/api/reflection/{parent['id']}/continue")

        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            child = client.post("/api/reflection", json={
                "text": "First sitting. Second sitting adds this.",
            }).get_json()

        history = client.get("/api/reflection").get_json()["reflections"]
        assert len(history) == 2
        assert child["continued_from_id"] == parent["id"]
        assert child["continued_from"]["id"] == parent["id"]
        assert client.get(
            f"/api/reflection/{parent['id']}"
        ).get_json()["transcript"] == "First sitting."

    def test_the_lineage_survives_on_the_history_list(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "First sitting.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post("/api/reflection", json={"text": "First. Plus more."})

        rows = client.get("/api/reflection").get_json()["reflections"]
        child = next(r for r in rows if r["continued_from_id"])
        assert child["continued_from"]["id"] == parent["id"]

    def test_the_draft_is_still_retired(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client)
        client.post(f"/api/reflection/{parent['id']}/continue")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            client.post("/api/reflection", json={"text": "Done."})
        assert _get_draft(client) is None

    def test_a_chain_of_three_keeps_every_link(self, client, monkeypatch):
        _login(monkeypatch)
        first = _saved(client, "One.")
        client.post(f"/api/reflection/{first['id']}/continue")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            second = client.post(
                "/api/reflection", json={"text": "One. Two."},
            ).get_json()
        client.post(f"/api/reflection/{second['id']}/continue")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            third = client.post(
                "/api/reflection", json={"text": "One. Two. Three."},
            ).get_json()

        assert second["continued_from_id"] == first["id"]
        assert third["continued_from_id"] == second["id"]
        assert len(client.get("/api/reflection").get_json()["reflections"]) == 3


class TestWhatClaudeIsTold:
    def _prompt_for_continuation(self, client, parent_id, text):
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        client.post(f"/api/reflection/{parent_id}/continue")
        with patch("reflection_service._call_claude", side_effect=_capture):
            resp = client.post("/api/reflection", json={"text": text})
        assert resp.status_code == 201, resp.get_data(as_text=True)
        return seen["prompt"]

    def test_the_carry_over_is_named(self, client, monkeypatch):
        """Without this the model reads a week-old paragraph as today's
        words and dates its proposals wrongly."""
        _login(monkeypatch)
        parent = _saved(client, "Week one thoughts.")
        client.patch(f"/api/reflection/{parent['id']}",
                     json={"title": "Sunday planning"})
        prompt = self._prompt_for_continuation(
            client, parent["id"], "Week one thoughts. Week two thoughts.",
        )
        assert "CONTINUES AN EARLIER SITTING" in prompt
        assert "Sunday planning" in prompt

    def test_already_applied_changes_are_listed(self, client, monkeypatch):
        """They exist in the state snapshot already; re-proposing them
        reads as a duplicate suggestion."""
        _login(monkeypatch)
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            parent = client.post(
                "/api/reflection", json={"text": "Create the plan task."},
            ).get_json()
        client.post(f"/api/reflection/{parent['id']}/confirm",
                    json={"actions": parent["proposed_actions"]["explicit"]})

        prompt = self._prompt_for_continuation(
            client, parent["id"], "Create the plan task. Now also X.",
        )
        assert "ALREADY APPLIED" in prompt
        assert "Draft the 30/60/90" in prompt

    def test_an_unapplied_parent_says_so_instead(self, client, monkeypatch):
        _login(monkeypatch)
        parent = _saved(client, "Thinking out loud.")
        prompt = self._prompt_for_continuation(
            client, parent["id"], "Thinking out loud. And more.",
        )
        assert "Nothing from that sitting was applied" in prompt

    def test_the_parent_is_not_also_listed_as_a_previous_reflection(
        self, client, monkeypatch,
    ):
        """Its full text is already in the transcript. Listing it again,
        truncated, hands Claude the same words twice and invites it to read
        the user's own sentences as a past commitment."""
        _login(monkeypatch)
        parent = _saved(client, "UNIQUEMARKER week one.")
        prompt = self._prompt_for_continuation(
            client, parent["id"], "UNIQUEMARKER week one. Week two.",
        )
        assert prompt.count("UNIQUEMARKER") == 1

    def test_other_past_reflections_are_still_listed(self, client, monkeypatch):
        """Excluding the parent must not switch off continuity entirely."""
        _login(monkeypatch)
        _saved(client, "OTHERSITTING about the handover.")
        parent = _saved(client, "The one being continued.")
        prompt = self._prompt_for_continuation(
            client, parent["id"], "The one being continued. Plus more.",
        )
        assert "OTHERSITTING" in prompt

    def test_an_ordinary_reflection_gets_no_continuation_block(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            client.post("/api/reflection", json={"text": "Just this week."})
        assert "CONTINUES AN EARLIER SITTING" not in seen["prompt"]

    def test_a_checkpoint_on_a_continuation_is_told_too(
        self, client, monkeypatch,
    ):
        """#333's interim pass reads the draft directly, so it needs the
        same framing - otherwise the mid-session proposals are the ones
        that mis-date the carried-over text."""
        _login(monkeypatch)
        parent = _saved(client, "Week one thoughts.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            assert client.post(
                "/api/reflection/draft/analyze"
            ).status_code == 200
        assert "CONTINUES AN EARLIER SITTING" in seen["prompt"]

    def test_re_analyzing_a_saved_continuation_is_told_too(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        parent = _saved(client, "Week one thoughts.")
        client.post(f"/api/reflection/{parent['id']}/continue")
        with patch("reflection_service._call_claude", return_value=_fake_claude()):
            child = client.post(
                "/api/reflection", json={"text": "Week one thoughts. Two."},
            ).get_json()

        seen = {}

        def _capture(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_capture):
            assert client.post(
                f"/api/reflection/{child['id']}/analyze"
            ).status_code == 200
        assert "CONTINUES AN EARLIER SITTING" in seen["prompt"]


class TestContinuationBlockUnit:
    """The prompt block on its own, including the shapes a real
    `applied_actions` record can take after a partial failure."""

    def test_none_parent_renders_nothing(self, app):
        from reflection_service import continuation_block
        with app.app_context():
            assert continuation_block(None) == ""

    def test_a_delete_action_reads_by_id_when_it_has_no_title(self, app):
        from models import Reflection, ReflectionInputMode
        from reflection_service import continuation_block
        with app.app_context():
            parent = Reflection(
                iso_week="2026-W39",
                input_mode=ReflectionInputMode.TYPED,
                transcript="x",
                proposed_actions={},
                applied_actions={
                    "actions": [{
                        "op": "delete", "entity": "task",
                        "id": "abc-123",
                    }],
                    "summary": {},
                },
            )
            out = continuation_block(parent)
        assert "delete task: abc-123" in out

    def test_a_malformed_audit_record_does_not_crash(self, app):
        """`apply_selected_actions` can fail to persist its audit record
        and carry on. The prompt builder must degrade, not raise."""
        from models import Reflection, ReflectionInputMode
        from reflection_service import continuation_block
        with app.app_context():
            for audit in (None, {}, {"actions": "nonsense"},
                          {"actions": [None, 7, "x"]}):
                parent = Reflection(
                    iso_week="2026-W39",
                    input_mode=ReflectionInputMode.TYPED,
                    transcript="x",
                    proposed_actions={},
                    applied_actions=audit,
                )
                out = continuation_block(parent)
                assert "CONTINUES AN EARLIER SITTING" in out
                assert "Nothing from that sitting was applied" in out


class TestDraftHasContent:
    def test_the_states_that_count_as_work(self, app):
        from models import Reflection, ReflectionInputMode
        from reflection_service import draft_has_content

        def _d(**kw):
            base = {
                "iso_week": "2026-W39",
                "input_mode": ReflectionInputMode.TYPED,
                "transcript": "",
                "raw_segments": [],
                "context_files": [],
                "proposed_actions": {},
                "is_draft": True,
            }
            base.update(kw)
            return Reflection(**base)

        with app.app_context():
            assert draft_has_content(None) is False
            assert draft_has_content(_d()) is False
            assert draft_has_content(_d(transcript="   ")) is False
            assert draft_has_content(_d(transcript="a")) is True
            assert draft_has_content(_d(raw_segments=[{"text": "a"}])) is True
            assert draft_has_content(_d(context_files=[{"id": "1"}])) is True
