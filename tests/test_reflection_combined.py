"""#335 - reading several reflections together.

One sitting says what happened that week. It cannot say "you have
mentioned the handover three weeks running and still have no task for
it" - that only has an answer across sittings, and it is the question a
multi-week run-up to a start date actually needs answered.

Two properties most of these circle:

1. **The sources are read, never written.** Same promise as #334: the
   combined analysis creates a NEW row and touches nothing it read.
2. **The transcripts arrive in FULL.** The continuity block already
   carries the previous three reflections truncated to 1200 characters
   each; a look-back built on snippets would be the very limitation this
   feature exists to remove.
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
        "usage": {"input_tokens": 500, "output_tokens": 40},
    }


def _login(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")


CREATE_TASK = {
    "op": "create", "entity": "task",
    "fields": {"title": "Draft the 30/60/90"}, "reason": "you said so",
}


def _saved(client, text):
    with patch("reflection_service._call_claude", return_value=_fake_claude()):
        resp = client.post("/api/reflection", json={"text": text})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _several(client, *texts):
    return [_saved(client, t) for t in texts]


def _together(client, ids, claude=None):
    with patch("reflection_service._call_claude",
               return_value=claude or _fake_claude()):
        return client.post("/api/reflection/analyze-together", json={"ids": ids})


def _capture_prompt(client, ids):
    seen = {}

    def _cap(api_key, prompt):
        seen["prompt"] = prompt
        return _fake_claude()

    with patch("reflection_service._call_claude", side_effect=_cap):
        resp = client.post("/api/reflection/analyze-together", json={"ids": ids})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return seen["prompt"], resp.get_json()


class TestTheCombinedAnalysis:
    def test_returns_proposals_over_the_whole_set(self, client, monkeypatch):
        _login(monkeypatch)
        a, b = _several(client, "Week one.", "Week two.")
        resp = _together(client, [a["id"], b["id"]],
                         _fake_claude(explicit=[CREATE_TASK]))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["combined"] is True
        assert body["source_count"] == 2
        assert len(body["proposed_actions"]["explicit"]) == 1

    def test_it_records_what_it_read(self, client, monkeypatch):
        _login(monkeypatch)
        a, b, c = _several(client, "One.", "Two.", "Three.")
        body = _together(client, [a["id"], b["id"], c["id"]]).get_json()
        assert set(body["synthesis_of"]) == {a["id"], b["id"], c["id"]}

    def test_its_own_transcript_names_the_sittings(self, client, monkeypatch):
        """The row has to say what it IS without a lookup, or the history
        list needs a query per row to render it."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        client.patch(f"/api/reflection/{a['id']}", json={"title": "Week one"})
        body = _together(client, [a["id"], b["id"]]).get_json()
        assert body["transcript"].startswith("Combined analysis of 2 reflections:")
        assert "Week one" in body["transcript"]

    def test_the_sources_are_untouched(self, client, monkeypatch):
        _login(monkeypatch)
        a, b = _several(client, "The original words.", "And the others.")
        before_a = client.get(f"/api/reflection/{a['id']}").get_json()
        _together(client, [a["id"], b["id"]])
        after_a = client.get(f"/api/reflection/{a['id']}").get_json()
        assert after_a["transcript"] == "The original words."
        assert after_a["proposed_actions"] == before_a["proposed_actions"]
        assert after_a["synthesis_of"] is None
        assert after_a["applied_at"] == before_a["applied_at"]

    def test_an_ordinary_reflection_has_no_synthesis_field_set(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        assert _saved(client, "Just this week.")["synthesis_of"] is None

    def test_the_synthesis_appears_in_history(self, client, monkeypatch):
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        _together(client, [a["id"], b["id"]])
        rows = client.get("/api/reflection").get_json()["reflections"]
        assert len(rows) == 3
        assert sum(1 for r in rows if r["synthesis_of"]) == 1

    def test_its_proposals_can_be_applied(self, client, monkeypatch):
        """`confirm` applies BY reflection id, which is the whole reason a
        synthesis is a row rather than a transient response."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        body = _together(client, [a["id"], b["id"]],
                         _fake_claude(explicit=[CREATE_TASK])).get_json()
        resp = client.post(
            f"/api/reflection/{body['id']}/confirm",
            json={"actions": body["proposed_actions"]["explicit"]},
        )
        assert resp.status_code == 200
        tasks = client.get("/api/tasks").get_json()
        tasks = tasks["tasks"] if isinstance(tasks, dict) else tasks
        assert "Draft the 30/60/90" in [t["title"] for t in tasks]


class TestTheTranscriptsArriveInFull:
    def test_no_1200_char_truncation(self, client, monkeypatch):
        """The limitation this feature exists to remove. A sitting well
        over `_RECENT_REFLECTION_CHARS` must reach Claude whole."""
        _login(monkeypatch)
        long_text = "Settlement handover detail. " * 200  # ~5600 chars
        a, b = _several(client, long_text, "Short one.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert long_text.strip() in prompt

    def test_each_sitting_is_fenced_and_dated(self, client, monkeypatch):
        """Without per-sitting headers a synthesis is one undifferentiated
        wall of text, and "you said this twice, three weeks apart" becomes
        unsayable."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        client.patch(f"/api/reflection/{a['id']}", json={"title": "Week one"})
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert "=== Sitting 1 of 2" in prompt
        assert "=== Sitting 2 of 2" in prompt
        assert "Week one" in prompt

    def test_oldest_first(self, client, monkeypatch):
        """Chronological order: the model is being asked what changed and
        what went quiet, which only reads correctly forwards."""
        _login(monkeypatch)
        a, b = _several(client, "OLDESTMARKER.", "NEWESTMARKER.")
        prompt, _ = _capture_prompt(client, [b["id"], a["id"]])
        assert prompt.index("OLDESTMARKER") < prompt.index("NEWESTMARKER")

    def test_a_huge_set_is_shortened_and_says_so(self, client, monkeypatch):
        """Silently handing Claude half a reflection and presenting the
        result as a complete look-back is the worst outcome here."""
        _login(monkeypatch)
        import reflection_service
        monkeypatch.setattr(reflection_service, "MAX_COMBINED_CHARS", 400)
        a, b = _several(client, "A" * 2000, "B" * 2000)
        prompt, body = _capture_prompt(client, [a["id"], b["id"]])
        assert body["shortened"], "truncation must be reported to the user"
        assert "too long to include in full" in prompt
        assert len(prompt.split("=== Sitting 1")[1]) < 2000

    def test_the_budget_is_shared_not_first_come(self, client, monkeypatch):
        """One enormous sitting must not starve the rest — a look-back
        that only really read the first reflection is worse than useless."""
        _login(monkeypatch)
        import reflection_service
        monkeypatch.setattr(reflection_service, "MAX_COMBINED_CHARS", 400)
        a, b = _several(client, "A" * 5000, "SECONDMARKER " * 5)
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert "SECONDMARKER" in prompt


class TestWhatClaudeIsTold:
    def test_it_is_framed_as_a_look_back(self, client, monkeypatch):
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert "LOOK BACK ACROSS 2 REFLECTIONS" in prompt
        assert "NOT a new weekly reflection" in prompt
        assert "RECURS" in prompt

    def test_already_applied_changes_are_listed(self, client, monkeypatch):
        _login(monkeypatch)
        with patch("reflection_service._call_claude",
                   return_value=_fake_claude(explicit=[CREATE_TASK])):
            a = client.post(
                "/api/reflection", json={"text": "Create the plan task."},
            ).get_json()
        client.post(f"/api/reflection/{a['id']}/confirm",
                    json={"actions": a["proposed_actions"]["explicit"]})
        b = _saved(client, "Second sitting.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert "ALREADY APPLIED" in prompt
        assert "Draft the 30/60/90" in prompt

    def test_the_sources_are_not_also_listed_as_previous_reflections(
        self, client, monkeypatch,
    ):
        """Their full text is already the transcript. Listing them again,
        truncated, hands Claude the same words twice."""
        _login(monkeypatch)
        a, b = _several(client, "UNIQUEONE here.", "UNIQUETWO here.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert prompt.count("UNIQUEONE") == 1
        assert prompt.count("UNIQUETWO") == 1

    def test_an_ordinary_reflection_gets_no_synthesis_block(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        seen = {}

        def _cap(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_cap):
            client.post("/api/reflection", json={"text": "Just this week."})
        assert "LOOK BACK ACROSS" not in seen["prompt"]

    def test_a_synthesis_row_never_becomes_continuity_context(
        self, client, monkeypatch,
    ):
        """Its transcript is a one-line header naming dates. As continuity
        that is noise, and it would displace a real sitting from the three
        the block carries."""
        _login(monkeypatch)
        a, b = _several(client, "REALONE here.", "REALTWO here.")
        _together(client, [a["id"], b["id"]])

        seen = {}

        def _cap(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_cap):
            client.post("/api/reflection", json={"text": "A new sitting."})
        assert "Combined analysis of" not in seen["prompt"]
        # ...and the real sittings it displaced are still there.
        assert "REALONE" in seen["prompt"]
        assert "REALTWO" in seen["prompt"]


class TestAttachmentsAcrossSittings:
    def test_documents_from_every_source_reach_the_prompt(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"ALPHA DOC BODY"), "alpha.txt")},
            content_type="multipart/form-data",
        )
        a = _saved(client, "First, with a doc.")
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"BETA DOC BODY"), "beta.txt")},
            content_type="multipart/form-data",
        )
        b = _saved(client, "Second, with another.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert "ALPHA DOC BODY" in prompt
        assert "BETA DOC BODY" in prompt

    def test_the_same_document_on_two_sittings_is_sent_once(
        self, client, monkeypatch,
    ):
        """Three copies of one job description would burn the 60k document
        budget on a single file and crowd out everything else."""
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"SHARED PLAN BODY"), "plan.txt")},
            content_type="multipart/form-data",
        )
        a = _saved(client, "First.")
        # #334 forking carries the same attachment onto the next sitting.
        client.post(f"/api/reflection/{a['id']}/continue")
        b = _saved(client, "First. Second.")
        prompt, _ = _capture_prompt(client, [a["id"], b["id"]])
        assert prompt.count("SHARED PLAN BODY") == 1

    def test_the_synthesis_row_stores_no_attachments_of_its_own(
        self, client, monkeypatch,
    ):
        """They belong to the sittings that carried them. Copying them
        onto the synthesis would duplicate extracted text for nothing."""
        _login(monkeypatch)
        client.post(
            "/api/reflection/attachment",
            data={"file": (io.BytesIO(b"body"), "plan.txt")},
            content_type="multipart/form-data",
        )
        a = _saved(client, "First.")
        b = _saved(client, "Second.")
        body = _together(client, [a["id"], b["id"]]).get_json()
        assert body["context_files"] == []


class TestRefusingABadSelection:
    def test_one_reflection_is_refused_with_the_alternative(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        a = _saved(client, "One.")
        resp = _together(client, [a["id"]])
        assert resp.status_code == 422
        assert "at least two" in resp.get_json()["error"]

    def test_none_is_refused(self, client, monkeypatch):
        _login(monkeypatch)
        assert _together(client, []).status_code == 422

    def test_too_many_is_refused_and_says_the_limit(self, client, monkeypatch):
        _login(monkeypatch)
        import reflection_service
        rows = _several(client, *[f"Sitting {i}." for i in range(4)])
        monkeypatch.setattr(reflection_service, "MAX_COMBINED", 3)
        resp = _together(client, [r["id"] for r in rows])
        assert resp.status_code == 422
        assert "3 is the most" in resp.get_json()["error"]

    def test_a_repeated_id_is_de_duplicated_not_weighted(
        self, client, monkeypatch,
    ):
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        body = _together(client, [a["id"], b["id"], a["id"]]).get_json()
        assert body["source_count"] == 2
        assert len(body["synthesis_of"]) == 2

    def test_a_repeated_id_cannot_fake_a_pair(self, client, monkeypatch):
        """[x, x] is one reflection, and must be refused as such rather
        than analysed as two."""
        _login(monkeypatch)
        a = _saved(client, "One.")
        assert _together(client, [a["id"], a["id"]]).status_code == 422

    def test_an_unknown_id_is_refused(self, client, monkeypatch):
        _login(monkeypatch)
        a = _saved(client, "One.")
        resp = _together(
            client, [a["id"], "11111111-1111-1111-1111-111111111111"],
        )
        assert resp.status_code == 422
        assert "no longer available" in resp.get_json()["error"]

    def test_garbage_ids_are_refused(self, client, monkeypatch):
        _login(monkeypatch)
        assert _together(client, ["not-a-uuid", "nope"]).status_code == 422
        assert _together(client, "not-a-list").status_code == 422

    def test_a_soft_deleted_source_is_refused(self, client, monkeypatch):
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        client.delete(f"/api/reflection/{b['id']}")
        assert _together(client, [a["id"], b["id"]]).status_code == 422

    def test_a_draft_cannot_be_a_source(self, client, monkeypatch):
        """It is still being written; a look-back reads finished sittings."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        draft = client.put(
            "/api/reflection/draft", json={"text": "In progress."},
        ).get_json()["draft"]
        assert _together(client, [a["id"], draft["id"]]).status_code == 422
        assert _together(client, [a["id"], b["id"]]).status_code == 201

    def test_an_archived_source_is_allowed(self, client, monkeypatch):
        """Archiving hides a row from the default list; it is not a
        deletion, so it stays readable."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        client.post(f"/api/reflection/{b['id']}/archive")
        assert _together(client, [a["id"], b["id"]]).status_code == 201

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        assert client.post(
            "/api/reflection/analyze-together", json={"ids": []},
        ).status_code in (302, 401, 403)

    def test_get_is_not_allowed(self, client, monkeypatch):
        """State-mutating routes are POST-only (#190)."""
        _login(monkeypatch)
        assert client.get(
            "/api/reflection/analyze-together"
        ).status_code == 405


class TestFailureKeepsTheRow:
    def test_a_claude_failure_leaves_a_re_analyzable_row(
        self, client, monkeypatch,
    ):
        """Same order and reason as `submit`: persist before the paid
        call, so a timeout leaves something the user can retry from
        history rather than nothing at all."""
        _login(monkeypatch)
        a, b = _several(client, "One.", "Two.")
        with patch(
            "reflection_service._call_claude",
            side_effect=RuntimeError("Claude API network error: ReadTimeout"),
        ):
            resp = client.post(
                "/api/reflection/analyze-together",
                json={"ids": [a["id"], b["id"]]},
            )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["saved"] is True
        saved = client.get(f"/api/reflection/{body['reflection_id']}").get_json()
        assert len(saved["synthesis_of"]) == 2


class TestReAnalyzingASynthesis:
    def test_it_re_reads_the_sittings_not_its_own_header(
        self, client, monkeypatch,
    ):
        """Its transcript is a list of dates. Running Claude over THAT
        would produce a confident analysis of nothing."""
        _login(monkeypatch)
        a, b = _several(client, "UNIQUEONE here.", "UNIQUETWO here.")
        synthesis = _together(client, [a["id"], b["id"]]).get_json()

        seen = {}

        def _cap(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_cap):
            resp = client.post(f"/api/reflection/{synthesis['id']}/analyze")
        assert resp.status_code == 200
        assert "UNIQUEONE" in seen["prompt"]
        assert "UNIQUETWO" in seen["prompt"]
        assert "LOOK BACK ACROSS" in seen["prompt"]

    def test_a_vanished_source_is_dropped_not_fatal(self, client, monkeypatch):
        """A look-back over the one that remains beats an error about the
        other."""
        _login(monkeypatch)
        a, b = _several(client, "KEPTONE here.", "GONEONE here.")
        synthesis = _together(client, [a["id"], b["id"]]).get_json()
        client.delete(f"/api/reflection/{b['id']}")

        seen = {}

        def _cap(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_cap):
            resp = client.post(f"/api/reflection/{synthesis['id']}/analyze")
        assert resp.status_code == 200
        assert "KEPTONE" in seen["prompt"]

    def test_an_ordinary_reflection_still_re_analyses_itself(
        self, client, monkeypatch,
    ):
        """Guards the branch in the other direction."""
        _login(monkeypatch)
        a = _saved(client, "ITSOWNWORDS here.")

        seen = {}

        def _cap(api_key, prompt):
            seen["prompt"] = prompt
            return _fake_claude()

        with patch("reflection_service._call_claude", side_effect=_cap):
            assert client.post(
                f"/api/reflection/{a['id']}/analyze"
            ).status_code == 200
        assert "ITSOWNWORDS" in seen["prompt"]
        assert "LOOK BACK ACROSS" not in seen["prompt"]


class TestServiceUnits:
    def test_merged_source_files_dedupes_by_id(self, app):
        from models import Reflection, ReflectionInputMode
        from reflection_service import merged_source_files

        def _r(files):
            return Reflection(
                iso_week="2026-W39",
                input_mode=ReflectionInputMode.TYPED,
                transcript="x", proposed_actions={}, context_files=files,
            )

        doc = {"id": "d1", "filename": "plan.txt", "kind": "txt",
               "chars": 4, "text": "body", "added_at": None,
               "source_chars": 4, "truncated": False}
        other = dict(doc, id="d2", filename="other.txt")
        with app.app_context():
            out = merged_source_files([_r([doc]), _r([doc, other])])
        assert [f["id"] for f in out] == ["d1", "d2"]

    def test_synthesis_header_lists_every_source(self, app):
        from models import Reflection, ReflectionInputMode
        from reflection_service import synthesis_header
        with app.app_context():
            rows = [
                Reflection(iso_week="2026-W38", title="Week one",
                           input_mode=ReflectionInputMode.TYPED,
                           transcript="a", proposed_actions={}),
                Reflection(iso_week="2026-W39",
                           input_mode=ReflectionInputMode.TYPED,
                           transcript="b", proposed_actions={}),
            ]
            out = synthesis_header(rows)
        assert out.startswith("Combined analysis of 2 reflections:")
        assert "Week one" in out

    def test_combined_transcript_skips_empty_sittings(self, app):
        from models import Reflection, ReflectionInputMode
        from reflection_service import combined_transcript
        with app.app_context():
            rows = [
                Reflection(iso_week="2026-W39",
                           input_mode=ReflectionInputMode.TYPED,
                           transcript="   ", proposed_actions={}),
                Reflection(iso_week="2026-W39",
                           input_mode=ReflectionInputMode.TYPED,
                           transcript="real words", proposed_actions={}),
            ]
            text, shortened = combined_transcript(rows)
        assert "real words" in text
        assert shortened == []

    def test_synthesis_block_is_empty_without_sources(self, app):
        from reflection_service import synthesis_block
        with app.app_context():
            assert synthesis_block([]) == ""
