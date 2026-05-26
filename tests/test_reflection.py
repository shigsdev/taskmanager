"""Tests for the Weekly Reflection feature.

Covers reflection_service (snapshot, Claude-response parsing, action
normalisation, apply) and reflection_api endpoints. The Claude call and
Whisper transcription are mocked — no API keys or network needed.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

import auth
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ImportLog,
    Project,
    ProjectType,
    Reflection,
    ReflectionInputMode,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


def _bypass_auth(monkeypatch):
    monkeypatch.setattr(
        auth, "get_current_user_email", lambda: "me@example.com"
    )


def _seed(app):
    """Insert one project, one goal, one task; return their ids."""
    with app.app_context():
        proj = Project(name="Portal Redesign", type=ProjectType.WORK)
        goal = Goal(
            title="Run a half marathon",
            category=GoalCategory.HEALTH,
            priority=GoalPriority.SHOULD,
            status=GoalStatus.IN_PROGRESS,
        )
        db.session.add_all([proj, goal])
        db.session.flush()
        task = Task(
            title="Email Sarah",
            type=TaskType.WORK,
            tier=Tier.INBOX,
            status=TaskStatus.ACTIVE,
            project_id=proj.id,
        )
        db.session.add(task)
        db.session.commit()
        return str(proj.id), str(goal.id), str(task.id)


# --- current_iso_week --------------------------------------------------------


class TestCurrentIsoWeek:
    def test_format(self):
        from reflection_service import current_iso_week

        assert current_iso_week(date(2026, 5, 16)) == "2026-W20"

    def test_pads_week_number(self):
        from reflection_service import current_iso_week

        assert current_iso_week(date(2026, 1, 5)) == "2026-W02"


# --- Reflection model defaults ----------------------------------------------


class TestReflectionModel:
    def test_defaults(self, app):
        with app.app_context():
            r = Reflection(
                iso_week="2026-W20",
                input_mode=ReflectionInputMode.TYPED,
                transcript="Felt productive this week.",
                proposed_actions={"explicit": [], "suggested": []},
            )
            db.session.add(r)
            db.session.commit()
            assert r.id is not None
            assert r.applied_actions is None
            assert r.applied_at is None
            assert r.audio_cost_usd is None
            assert r.created_at is not None


# --- _extract_action_object --------------------------------------------------


class TestExtractActionObject:
    def test_direct_object(self):
        from reflection_service import _extract_action_object

        out = _extract_action_object(
            '{"explicit": [{"op": "create"}], "suggested": []}'
        )
        assert out["explicit"] == [{"op": "create"}]
        assert out["suggested"] == []

    def test_markdown_fence(self):
        from reflection_service import _extract_action_object

        text = '```json\n{"explicit": [], "suggested": [{"op": "delete"}]}\n```'
        out = _extract_action_object(text)
        assert out["suggested"] == [{"op": "delete"}]

    def test_surrounding_text(self):
        from reflection_service import _extract_action_object

        text = 'Here you go:\n{"explicit": [], "suggested": []}\nDone!'
        assert _extract_action_object(text) == {
            "explicit": [],
            "suggested": [],
        }

    def test_garbage_returns_empty_buckets(self):
        from reflection_service import _extract_action_object

        assert _extract_action_object("not json at all") == {
            "explicit": [],
            "suggested": [],
        }

    def test_missing_keys_coerce_to_lists(self):
        from reflection_service import _extract_action_object

        out = _extract_action_object('{"explicit": "oops"}')
        assert out == {"explicit": [], "suggested": []}


# --- normalize_actions -------------------------------------------------------


def _snapshot(proj_id, goal_id, task_id):
    return {
        "projects": [
            {"id": proj_id, "name": "Portal Redesign", "type": "work",
             "status": "not_started", "priority": None}
        ],
        "goals": [
            {"id": goal_id, "title": "Run a half marathon",
             "category": "health", "priority": "should",
             "status": "in_progress"}
        ],
        "tasks": [
            {"id": task_id, "title": "Email Sarah", "tier": "inbox",
             "type": "work", "due_date": None,
             "project": "Portal Redesign", "goal": None}
        ],
    }


class TestNormalizeActions:
    def test_drops_bad_op_and_entity(self, app):
        from reflection_service import normalize_actions

        snap = _snapshot("p", "g", "t")
        raw = [
            {"op": "frobnicate", "entity": "task"},
            {"op": "create", "entity": "dragon"},
        ]
        assert normalize_actions(raw, snap, "explicit") == []

    def test_update_with_unknown_id_dropped(self, app):
        from reflection_service import normalize_actions

        snap = _snapshot("p1", "g1", "t1")
        raw = [{"op": "update", "entity": "task",
                "id": "does-not-exist", "fields": {"tier": "today"}}]
        assert normalize_actions(raw, snap, "explicit") == []

    def test_update_restricts_fields_and_builds_diff(self, app):
        from reflection_service import normalize_actions

        snap = _snapshot("p1", "g1", "t1")
        raw = [{
            "op": "update", "entity": "task", "id": "t1",
            "fields": {"tier": "today", "bogus_field": "x"},
            "reason": "user said do it today",
        }]
        out = normalize_actions(raw, snap, "explicit")
        assert len(out) == 1
        action = out[0]
        assert action["payload"] == {"tier": "today"}
        assert "bogus_field" not in action["payload"]
        assert action["bucket"] == "explicit"
        assert action["target"] == "Email Sarah"
        assert {"field": "tier", "from": "inbox", "to": "today"} in (
            action["changes"]
        )

    def test_create_requires_title(self, app):
        from reflection_service import normalize_actions

        snap = _snapshot("p1", "g1", "t1")
        raw = [
            {"op": "create", "entity": "goal", "fields": {"title": "  "}},
            {"op": "create", "entity": "goal",
             "fields": {"title": "Read 12 books", "priority": "should"}},
        ]
        out = normalize_actions(raw, snap, "suggested")
        assert len(out) == 1
        assert out[0]["target"] == "Read 12 books"
        assert out[0]["bucket"] == "suggested"

    def test_delete_only_needs_valid_id(self, app):
        from reflection_service import normalize_actions

        snap = _snapshot("p1", "g1", "t1")
        raw = [{"op": "delete", "entity": "project", "id": "p1"}]
        out = normalize_actions(raw, snap, "explicit")
        assert out[0]["op"] == "delete"
        assert out[0]["target"] == "Portal Redesign"


# --- build_state_snapshot ----------------------------------------------------


class TestSnapshot:
    def test_shape(self, app):
        proj_id, goal_id, task_id = _seed(app)
        with app.app_context():
            from reflection_service import build_state_snapshot

            snap = build_state_snapshot()
        assert {p["id"] for p in snap["projects"]} == {proj_id}
        assert snap["goals"][0]["title"] == "Run a half marathon"
        task_row = snap["tasks"][0]
        assert task_row["id"] == task_id
        assert task_row["project"] == "Portal Redesign"


# --- analyze_reflection (Claude mocked) -------------------------------------


class TestAnalyzeReflection:
    def test_normalizes_and_computes_cost(self, app, monkeypatch):
        proj_id, goal_id, task_id = _seed(app)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        fake = {
            "content": [{
                "text": json.dumps({
                    "explicit": [
                        {"op": "update", "entity": "task", "id": task_id,
                         "fields": {"tier": "today"},
                         "reason": "do it now"},
                    ],
                    "suggested": [
                        {"op": "delete", "entity": "project",
                         "id": proj_id, "reason": "looks done"},
                    ],
                }),
            }],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }
        with app.app_context(), patch(
            "reflection_service._call_claude", return_value=fake
        ):
            from reflection_service import analyze_reflection

            out = analyze_reflection("Move the Sarah email to today.")
        assert len(out["explicit"]) == 1
        assert out["explicit"][0]["op"] == "update"
        assert len(out["suggested"]) == 1
        assert out["suggested"][0]["op"] == "delete"
        # 1000/1e6*3 + 200/1e6*15 = 0.003 + 0.003 = 0.006
        assert out["ai_cost_usd"] == pytest.approx(0.006, abs=1e-6)

    def test_empty_transcript_short_circuits(self, app):
        with app.app_context():
            from reflection_service import analyze_reflection

            out = analyze_reflection("   ")
        assert out["explicit"] == []
        assert out["ai_cost_usd"] is None

    def test_missing_api_key_raises(self, app, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with app.app_context(), pytest.raises(
            RuntimeError, match="ANTHROPIC_API_KEY"
        ):
            from reflection_service import analyze_reflection

            analyze_reflection("something")


# --- apply_selected_actions --------------------------------------------------


class TestApplyActions:
    def test_create_update_delete_roundtrip(self, app):
        proj_id, goal_id, task_id = _seed(app)
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )

            reflection = save_reflection(
                transcript="weekly thoughts",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            actions = [
                {"op": "create", "entity": "project",
                 "fields": {"name": "Garden Cleanup", "type": "personal"}},
                {"op": "create", "entity": "goal",
                 "fields": {"title": "Read 12 books",
                            "category": "personal_growth",
                            "priority": "should"}},
                {"op": "create", "entity": "task",
                 "fields": {"title": "Buy seeds", "type": "personal",
                            "tier": "today",
                            "project_hint": "Garden Cleanup"}},
                {"op": "update", "entity": "goal", "id": goal_id,
                 "payload": {"status": "done"}},
                {"op": "delete", "entity": "task", "id": task_id},
            ]
            summary = apply_selected_actions(reflection, actions)

            assert summary["created"]["project"] == 1
            assert summary["created"]["goal"] == 1
            assert summary["created"]["task"] == 1
            assert summary["updated"]["goal"] == 1
            assert summary["deleted"]["task"] == 1
            assert summary["errors"] == []

            # New task linked to the just-created project.
            new_task = db.session.scalars(
                select(Task).where(Task.title == "Buy seeds")
            ).one()
            new_proj = db.session.scalars(
                select(Project).where(Project.name == "Garden Cleanup")
            ).one()
            assert new_task.project_id == new_proj.id
            assert new_task.tier == Tier.TODAY

            # Goal updated, task soft-deleted.
            assert db.session.get(Goal, __import__("uuid").UUID(goal_id)).status == (
                GoalStatus.DONE
            )
            assert db.session.get(
                Task, __import__("uuid").UUID(task_id)
            ).status == TaskStatus.DELETED

            # Reflection audit trail recorded.
            assert reflection.applied_at is not None
            assert reflection.applied_actions["summary"]["created"][
                "task"
            ] == 1

            # Created rows grouped under reflection_* ImportLog batches.
            sources = [
                log.source
                for log in db.session.scalars(select(ImportLog))
            ]
            assert any(s.startswith("reflection") for s in sources)

    def test_bad_id_recorded_as_error_not_crash(self, app):
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )

            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            summary = apply_selected_actions(
                reflection,
                [{"op": "update", "entity": "goal", "id": "not-a-uuid",
                  "payload": {"status": "done"}}],
            )
            assert summary["updated"]["goal"] == 0
            assert summary["errors"]


class TestApplyActionsCorrectnessPR6:
    """PR 6 (#174, #181): reflection-apply correctness.

    #174 — a failure inside a create step used to bubble out of
           apply_selected_actions → opaque 500, partial summary lost.
    #181 — an unresolved project_hint/goal_hint on an UPDATE silently
           CLEARED the task's existing FK (update_task reads explicit
           None as "clear this field").
    """

    # --- #181: unresolved hint must not clear the existing FK ---

    def test_stale_project_hint_keeps_existing_project(self, app):
        """A reflection UPDATE whose project_hint matches nothing must
        leave the task's existing project_id intact — and surface the
        miss in summary["errors"]."""
        proj_id, _goal_id, task_id = _seed(app)
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            summary = apply_selected_actions(
                reflection,
                [{"op": "update", "entity": "task", "id": task_id,
                  "payload": {"project_hint": "Nonexistent Project XYZ",
                              "notes": "touched"}}],
            )
            # The update itself succeeded (notes changed)...
            assert summary["updated"]["task"] == 1
            # ...but the task's project_id is UNCHANGED, not wiped.
            task = db.session.get(Task, __import__("uuid").UUID(task_id))
            assert str(task.project_id) == proj_id, (
                "stale project_hint must NOT clear the existing project"
            )
            assert task.notes == "touched"
            # And the miss is surfaced.
            assert any(
                "project_hint" in e and "not found" in e
                for e in summary["errors"]
            ), f"expected a project_hint miss in errors, got {summary['errors']}"

    def test_resolved_goal_hint_sets_goal_id(self, app):
        """The happy path still works — a hint that DOES match resolves
        to the goal_id."""
        _proj_id, goal_id, task_id = _seed(app)
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            summary = apply_selected_actions(
                reflection,
                [{"op": "update", "entity": "task", "id": task_id,
                  "payload": {"goal_hint": "Run a half marathon"}}],
            )
            assert summary["updated"]["task"] == 1
            task = db.session.get(Task, __import__("uuid").UUID(task_id))
            assert str(task.goal_id) == goal_id
            # A resolved hint produces no error.
            assert not any("goal_hint" in e for e in summary["errors"])

    def test_empty_project_hint_is_silent_no_change(self, app):
        """An empty/blank project_hint is just "no hint" — pop it
        silently, no warning, leave the FK alone."""
        proj_id, _goal_id, task_id = _seed(app)
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            summary = apply_selected_actions(
                reflection,
                [{"op": "update", "entity": "task", "id": task_id,
                  "payload": {"project_hint": "", "notes": "edited"}}],
            )
            assert summary["updated"]["task"] == 1
            task = db.session.get(Task, __import__("uuid").UUID(task_id))
            assert str(task.project_id) == proj_id
            # Empty hint → no warning (only non-empty misses warn).
            assert not any("project_hint" in e for e in summary["errors"])

    # --- #174: a create-step failure is captured, not bubbled ---

    def test_create_failure_is_captured_not_raised(self, app):
        """When one create step raises, apply_selected_actions must NOT
        propagate — it records the failure in summary["errors"], the
        other steps still run, and a summary is always returned."""
        with app.app_context():
            from reflection_service import (
                apply_selected_actions,
                save_reflection,
            )
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            actions = [
                {"op": "create", "entity": "project",
                 "fields": {"name": "Good Project", "type": "work"}},
                {"op": "create", "entity": "goal",
                 "fields": {"title": "Boom goal",
                            "category": "work", "priority": "should"}},
                {"op": "create", "entity": "task",
                 "fields": {"title": "Good task", "type": "work",
                            "tier": "inbox"}},
            ]
            # Make ONLY the goal-create step blow up.
            with patch(
                "import_service.create_goals_from_import",
                side_effect=RuntimeError("simulated goal-create failure"),
            ):
                summary = apply_selected_actions(reflection, actions)

            # Did not raise — summary returned.
            assert isinstance(summary, dict)
            # The good steps still landed.
            assert summary["created"]["project"] == 1
            assert summary["created"]["task"] == 1
            # The failed step is 0 + recorded.
            assert summary["created"]["goal"] == 0
            assert any(
                "create goals" in e and "simulated goal-create failure" in e
                for e in summary["errors"]
            ), f"goal-create failure missing from errors: {summary['errors']}"

    def test_confirm_returns_207_when_summary_has_errors(
        self, app, client, monkeypatch,
    ):
        """The route returns 207 Multi-Status (not opaque 500, not a
        clean 200) when apply produced partial errors — so the client
        can distinguish fully-applied from partially-applied."""
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            rid = str(reflection.id)

        with patch(
            "import_service.create_goals_from_import",
            side_effect=RuntimeError("boom"),
        ):
            resp = client.post(
                f"/api/reflection/{rid}/confirm",
                json={"actions": [
                    {"op": "create", "entity": "goal",
                     "fields": {"title": "G", "category": "work",
                                "priority": "should"}},
                ]},
            )
        assert resp.status_code == 207
        body = resp.get_json()
        assert body["summary"]["errors"], "errors should be populated"
        # applied_at is still present (the audit commit itself succeeded).
        assert "applied_at" in body

    def test_confirm_returns_200_when_clean(self, app, client, monkeypatch):
        """No errors → plain 200, unchanged from the original contract."""
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection
            reflection = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            rid = str(reflection.id)
        resp = client.post(
            f"/api/reflection/{rid}/confirm",
            json={"actions": [
                {"op": "create", "entity": "task",
                 "fields": {"title": "Clean task", "type": "work",
                            "tier": "inbox"}},
            ]},
        )
        assert resp.status_code == 200
        assert resp.get_json()["summary"]["errors"] == []


# --- reflection_api endpoints ------------------------------------------------


class TestNormaliseRawSegments:
    """#237 (2026-05-26): _normalise_raw_segments is the boundary
    between client-supplied JSON and what lands in the DB. Defensive
    cleanup so a malformed client send can't corrupt the audit trail
    or sneak unbounded data past."""

    def test_none_input_returns_empty_list(self):
        from reflection_service import _normalise_raw_segments
        assert _normalise_raw_segments(None) == []

    def test_non_list_input_returns_empty_list(self):
        from reflection_service import _normalise_raw_segments
        assert _normalise_raw_segments("not a list") == []
        assert _normalise_raw_segments({"text": "x"}) == []

    def test_empty_text_dropped(self):
        from reflection_service import _normalise_raw_segments
        assert _normalise_raw_segments([{"text": ""}, {"text": "  "}]) == []

    def test_non_string_text_dropped(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([
            {"text": None},
            {"text": 42},
            {"text": "valid"},
        ])
        assert len(result) == 1
        assert result[0]["text"] == "valid"

    def test_non_dict_entries_dropped(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([
            "not a dict",
            42,
            None,
            ["nested list"],
            {"text": "valid"},
        ])
        assert len(result) == 1

    def test_text_trimmed(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{"text": "  hello world  "}])
        assert result[0]["text"] == "hello world"

    def test_text_length_capped_at_20000(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{"text": "a" * 25000}])
        assert len(result[0]["text"]) == 20000

    def test_telemetry_floats_coerced(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{
            "text": "x",
            "duration_seconds": "12.5",   # str coerced to float
            "cost_usd": 0.001,
        }])
        assert result[0]["duration_seconds"] == 12.5
        assert result[0]["cost_usd"] == 0.001

    def test_bad_telemetry_becomes_none(self):
        """A non-numeric duration shouldn't reject the segment — just
        null out the bad field. The text is what matters most."""
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{
            "text": "x",
            "duration_seconds": "bogus",
            "cost_usd": [1, 2, 3],
        }])
        assert result[0]["duration_seconds"] is None
        assert result[0]["cost_usd"] is None
        # But the segment text survives.
        assert result[0]["text"] == "x"

    def test_unbounded_recorded_at_capped_to_none(self):
        """A client send with a >64-char recorded_at string is
        suspicious — drop it to None rather than persist unbounded
        data."""
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{
            "text": "x",
            "recorded_at": "z" * 200,
        }])
        assert result[0]["recorded_at"] is None

    def test_normal_iso_timestamp_preserved(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([{
            "text": "x",
            "recorded_at": "2026-05-26T13:00:00+00:00",
        }])
        assert result[0]["recorded_at"] == "2026-05-26T13:00:00+00:00"

    def test_multiple_segments_preserve_order(self):
        from reflection_service import _normalise_raw_segments
        result = _normalise_raw_segments([
            {"text": "first"},
            {"text": "second"},
            {"text": "third"},
        ])
        assert [s["text"] for s in result] == ["first", "second", "third"]


class TestReflectionApi:
    def test_submit_typed_persists_and_returns_proposals(
        self, app, client, monkeypatch
    ):
        _bypass_auth(monkeypatch)
        fake_analysis = {
            "explicit": [{"op": "create", "entity": "task",
                          "bucket": "explicit", "id": None,
                          "target": "Call dentist", "reason": "",
                          "changes": [], "fields": {}, "payload": {}}],
            "suggested": [],
            "ai_cost_usd": 0.0042,
            "snapshot": {},
        }
        with patch(
            "reflection_api.analyze_reflection", return_value=fake_analysis
        ):
            resp = client.post(
                "/api/reflection",
                json={"text": "I need to call the dentist."},
            )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["input_mode"] == "typed"
        assert body["ai_cost_usd"] == 0.0042
        assert body["proposed_actions"]["explicit"][0]["target"] == (
            "Call dentist"
        )
        with app.app_context():
            assert db.session.scalar(select(func.count(Reflection.id))) == 1

    def test_submit_audio_transcribes(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        with (
            patch(
                "reflection_api.transcribe_audio",
                return_value={"transcript": "Spoken reflection text.",
                              "duration_seconds": 12.0,
                              "cost_usd": 0.0012},
            ),
            patch(
                "reflection_api.analyze_reflection",
                return_value={"explicit": [], "suggested": [],
                              "ai_cost_usd": None, "snapshot": {}},
            ),
        ):
            resp = client.post(
                "/api/reflection",
                data={"audio": (io.BytesIO(b"fake audio"), "memo.webm",
                                "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["input_mode"] == "voice"
        assert body["audio_cost_usd"] == 0.0012
        assert body["transcript"] == "Spoken reflection text."

    # --- #237 raw_segments persistence (2026-05-26) --------------------

    def test_237_submit_with_raw_segments_persists_them(
        self, app, client, monkeypatch,
    ):
        """User-edited textarea + per-segment Whisper transcripts both
        get saved — the final text on Reflection.transcript, the raw
        verbatim segments on Reflection.raw_segments. So an edit
        doesn't erase the original spoken words."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            return_value={"explicit": [], "suggested": [],
                          "ai_cost_usd": None, "snapshot": {}},
        ):
            resp = client.post(
                "/api/reflection",
                json={
                    "text": "I shipped the auth refresh and almost finished the calendar.",
                    "raw_segments": [
                        {
                            "text": "I shipped the auth refresh",
                            "duration_seconds": 4.2,
                            "cost_usd": 0.00042,
                            "recorded_at": "2026-05-26T13:00:00+00:00",
                        },
                        {
                            "text": "and started the calendar.",
                            "duration_seconds": 3.1,
                            "cost_usd": 0.00031,
                            "recorded_at": "2026-05-26T13:00:30+00:00",
                        },
                    ],
                },
            )
        assert resp.status_code == 201
        body = resp.get_json()
        # Response surfaces raw_segments back (for the history view).
        assert len(body["raw_segments"]) == 2
        assert body["raw_segments"][0]["text"] == "I shipped the auth refresh"
        assert body["raw_segments"][1]["text"] == "and started the calendar."
        # Persisted to DB.
        with app.app_context():
            r = db.session.scalar(select(Reflection))
            assert len(r.raw_segments) == 2
            assert r.raw_segments[0]["duration_seconds"] == 4.2
            assert r.raw_segments[0]["cost_usd"] == 0.00042
            # The final transcript (edited / merged) is what got saved
            # — the raw_segments captured the original phrasing the
            # user said BEFORE editing "started" → "almost finished".
            assert "almost finished" in r.transcript
            assert "started" not in r.transcript
            assert "started" in r.raw_segments[1]["text"]
            # Voice input mode inferred because raw_segments was sent.
            assert r.input_mode == ReflectionInputMode.VOICE

    def test_237_submit_typed_only_persists_empty_raw_segments(
        self, app, client, monkeypatch,
    ):
        """Pure typed reflection (no raw_segments in payload) →
        raw_segments persists as []. Doesn't crash; serializer returns
        []."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            return_value={"explicit": [], "suggested": [],
                          "ai_cost_usd": None, "snapshot": {}},
        ):
            resp = client.post(
                "/api/reflection",
                json={"text": "Just typing this out, no voice."},
            )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["raw_segments"] == []
        with app.app_context():
            r = db.session.scalar(select(Reflection))
            assert r.raw_segments == []
            # Typed mode preserved — empty raw_segments doesn't flip it.
            assert r.input_mode == ReflectionInputMode.TYPED

    def test_237_submit_drops_malformed_segments(
        self, app, client, monkeypatch,
    ):
        """The normaliser drops non-dict entries, empty-text entries,
        and coerces bad telemetry fields to None. Defense against a
        malformed client send."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            return_value={"explicit": [], "suggested": [],
                          "ai_cost_usd": None, "snapshot": {}},
        ):
            resp = client.post(
                "/api/reflection",
                json={
                    "text": "Final text.",
                    "raw_segments": [
                        {"text": "  Real segment  "},   # whitespace-trimmed
                        {"text": ""},                     # dropped (empty)
                        "not-a-dict",                     # dropped (non-dict)
                        {"text": "Another", "duration_seconds": "bogus"},  # bad telemetry → None
                        {"text": None},                   # dropped (non-str text)
                    ],
                },
            )
        assert resp.status_code == 201
        with app.app_context():
            r = db.session.scalar(select(Reflection))
            assert len(r.raw_segments) == 2
            assert r.raw_segments[0]["text"] == "Real segment"
            assert r.raw_segments[1]["text"] == "Another"
            # Bad duration_seconds → None (silently coerced, not 422).
            assert r.raw_segments[1]["duration_seconds"] is None

    def test_237_submit_empty_text_still_422_even_with_raw_segments(
        self, client, monkeypatch,
    ):
        """The text-emptiness check fires BEFORE the raw_segments
        path. raw_segments alone can't carry the reflection — the
        merged text must be present (the user clicked Done with
        nothing in the textarea)."""
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection",
            json={
                "text": "   ",
                "raw_segments": [{"text": "I said something"}],
            },
        )
        assert resp.status_code == 422

    def test_237_serializer_includes_raw_segments_for_pre_237_rows(
        self, app, monkeypatch,
    ):
        """Pre-#237 rows have raw_segments = [] (server_default in the
        migration). The serializer renders that as an empty list."""
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection
            r = save_reflection(
                transcript="Pre-237 typed reflection",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
                # NOT passing raw_segments — simulates pre-#237 code
                # path AND the default-empty-list contract.
            )
            rid = str(r.id)

        # Client (with bypass) — fetch the detail.
        from flask import Flask  # ensure app fixture stays in scope
        assert isinstance(app, Flask)
        with app.test_client() as c:
            resp = c.get(f"/api/reflection/{rid}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["raw_segments"] == []

    def test_submit_empty_text_422(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post("/api/reflection", json={"text": "   "})
        assert resp.status_code == 422

    def test_submit_no_body_400(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection", data="x", content_type="text/plain"
        )
        assert resp.status_code == 400

    def test_analysis_failure_still_persists_transcript(
        self, app, client, monkeypatch
    ):
        """Data-loss regression guard (2026-05-16 review finding).

        The transcript MUST be saved before the Claude call. A
        RuntimeError from analyze_reflection (rate limit / network /
        missing key) must NOT discard the reflection — it returns 422
        with saved:true + the reflection_id, and the row is in the DB
        with empty proposed_actions (analysable later)."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            side_effect=RuntimeError("ANTHROPIC_API_KEY not configured"),
        ):
            resp = client.post(
                "/api/reflection",
                json={"text": "A reflection that must survive a Claude outage."},
            )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["saved"] is True
        assert body["reflection_id"]
        # The transcript is persisted despite the analysis failure.
        with app.app_context():
            assert db.session.scalar(select(func.count(Reflection.id))) == 1
            r = db.session.scalar(select(Reflection))
            assert r.transcript == (
                "A reflection that must survive a Claude outage."
            )
            assert r.proposed_actions == {"explicit": [], "suggested": []}

    def test_analysis_crash_still_persists_transcript(
        self, app, client, monkeypatch
    ):
        """Same guard for the unexpected-exception (500) branch."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            side_effect=ValueError("claude returned garbage"),
        ):
            resp = client.post(
                "/api/reflection",
                json={"text": "Survive an unexpected analyzer crash."},
            )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["saved"] is True
        assert body["reflection_id"]
        with app.app_context():
            assert db.session.scalar(select(func.count(Reflection.id))) == 1

    def test_confirm_applies_and_blocks_double_apply(
        self, app, client, monkeypatch
    ):
        proj_id, goal_id, task_id = _seed(app)
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection

            reflection = save_reflection(
                transcript="t",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            rid = str(reflection.id)

        actions = [{"op": "delete", "entity": "task", "id": task_id}]
        resp = client.post(
            f"/api/reflection/{rid}/confirm", json={"actions": actions}
        )
        assert resp.status_code == 200
        assert resp.get_json()["summary"]["deleted"]["task"] == 1

        # Second apply blocked.
        resp2 = client.post(
            f"/api/reflection/{rid}/confirm", json={"actions": actions}
        )
        assert resp2.status_code == 409

    def test_confirm_unknown_id_404(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection/00000000-0000-0000-0000-000000000000/confirm",
            json={"actions": []},
        )
        assert resp.status_code == 404

    def test_confirm_actions_must_be_list(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection

            reflection = save_reflection(
                transcript="t",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            rid = str(reflection.id)
        resp = client.post(
            f"/api/reflection/{rid}/confirm", json={"actions": "nope"}
        )
        assert resp.status_code == 422

    def test_list_and_detail(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        with app.app_context():
            from reflection_service import save_reflection

            r = save_reflection(
                transcript="history entry",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            rid = str(r.id)
        list_resp = client.get("/api/reflection")
        assert list_resp.status_code == 200
        assert len(list_resp.get_json()["reflections"]) == 1

        detail_resp = client.get(f"/api/reflection/{rid}")
        assert detail_resp.status_code == 200
        assert detail_resp.get_json()["transcript"] == "history entry"

    def test_detail_unknown_404(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.get(
            "/api/reflection/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        # No auth bypass — login_required must reject.
        resp = client.post("/api/reflection", json={"text": "hi"})
        assert resp.status_code != 201


class TestTranscribeSegmentApi:
    """#232 (2026-05-25): POST /api/reflection/transcribe-segment.

    One-segment Whisper transcription for the pause/resume frontend
    flow. Returns just text + duration + cost. Does NOT save a
    Reflection row and does NOT call Claude — those steps run when the
    user clicks Done, which POSTs the merged textarea content to the
    main /api/reflection endpoint (JSON path, no audio).

    These tests exercise the API contract; the frontend pause/resume
    state machine is exercised in `tests/js/unit/reflection_helpers.test.js`
    (helper) and Phase 6 manual regression (full DOM flow).
    """

    def test_segment_returns_transcript_no_reflection_row(
        self, app, client, monkeypatch
    ):
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        with patch(
            "reflection_api.transcribe_audio",
            return_value={
                "transcript": "First chunk of my week.",
                "duration_seconds": 6.0,
                "cost_usd": 0.0006,
            },
        ):
            resp = client.post(
                "/api/reflection/transcribe-segment",
                data={"audio": (io.BytesIO(b"fake audio"), "seg.webm",
                                "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["transcript"] == "First chunk of my week."
        assert body["duration_seconds"] == 6.0
        assert body["cost_usd"] == 0.0006
        # Critically: NO Reflection row is created — Claude isn't called
        # for a segment, only when the user clicks Done.
        with app.app_context():
            assert db.session.scalar(select(func.count(Reflection.id))) == 0

    def test_segment_empty_transcript_is_fine(self, client, monkeypatch):
        # Whisper sometimes returns an empty transcript if the segment
        # was pure silence. Surface that to the frontend as a clean 200
        # with transcript="" — NOT a 422 — so the frontend can decide
        # whether to show "silent segment, try again" UX.
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.transcribe_audio",
            return_value={
                "transcript": "",
                "duration_seconds": 0.5,
                "cost_usd": 0.00005,
            },
        ):
            resp = client.post(
                "/api/reflection/transcribe-segment",
                data={"audio": (io.BytesIO(b"silent audio"), "seg.webm",
                                "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        assert resp.get_json()["transcript"] == ""

    def test_segment_missing_audio_field_rejected(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        # No multipart audio field at all.
        resp = client.post(
            "/api/reflection/transcribe-segment",
            data={},
            content_type="multipart/form-data",
        )
        # validate_upload returns 400 when the field is missing.
        assert resp.status_code == 400

    def test_segment_unsupported_mime_rejected(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection/transcribe-segment",
            data={"audio": (io.BytesIO(b"\x89PNG\r\n"), "not-audio.png",
                            "image/png")},
            content_type="multipart/form-data",
        )
        # MIME whitelist enforced by validate_upload.
        assert resp.status_code in (400, 422)

    def test_segment_whisper_runtime_error_returns_422(
        self, client, monkeypatch
    ):
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.transcribe_audio",
            side_effect=RuntimeError("OPENAI_API_KEY missing"),
        ):
            resp = client.post(
                "/api/reflection/transcribe-segment",
                data={"audio": (io.BytesIO(b"fake"), "seg.webm",
                                "audio/webm")},
                content_type="multipart/form-data",
            )
        # User-facing error message must NOT leak the original error
        # context that could include sensitive details — but a
        # short prose summary is fine.
        assert resp.status_code == 422
        body = resp.get_json()
        assert "Transcription failed" in body["error"]

    def test_segment_whisper_unexpected_exception_returns_500(
        self, client, monkeypatch
    ):
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.transcribe_audio",
            side_effect=ValueError("internal logic bug"),
        ):
            resp = client.post(
                "/api/reflection/transcribe-segment",
                data={"audio": (io.BytesIO(b"fake"), "seg.webm",
                                "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 500
        body = resp.get_json()
        # Generic message, no traceback / no secret leak.
        assert body["error"] == "Transcription failed (unexpected)"

    def test_segment_requires_auth(self, client):
        resp = client.post(
            "/api/reflection/transcribe-segment",
            data={"audio": (io.BytesIO(b"fake"), "seg.webm",
                            "audio/webm")},
            content_type="multipart/form-data",
        )
        # login_required must reject — exact status varies (302 → OAuth
        # or 401 JSON), but it must NOT be a success.
        assert resp.status_code not in (200, 201)


class TestArchiveAndDeleteApi:
    """#238 (2026-05-26): archive (hide from default history) +
    soft-delete (recycle pattern) endpoints."""

    def _seed_reflection(self, app, transcript="seed text"):
        with app.app_context():
            from reflection_service import save_reflection
            r = save_reflection(
                transcript=transcript,
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            return str(r.id)

    def test_archive_endpoint_sets_is_archived_true(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        resp = client.post(f"/api/reflection/{rid}/archive")
        assert resp.status_code == 200
        assert resp.get_json()["is_archived"] is True
        with app.app_context():
            assert db.session.get(Reflection, uuid.UUID(rid)).is_archived is True

    def test_unarchive_endpoint_clears_is_archived(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.post(f"/api/reflection/{rid}/archive")
        resp = client.post(f"/api/reflection/{rid}/unarchive")
        assert resp.status_code == 200
        assert resp.get_json()["is_archived"] is False

    def test_delete_endpoint_sets_is_active_false(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        resp = client.delete(f"/api/reflection/{rid}")
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False
        with app.app_context():
            # Row is STILL in the DB — soft-delete only.
            assert db.session.get(Reflection, uuid.UUID(rid)) is not None

    def test_restore_endpoint_undeletes(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.delete(f"/api/reflection/{rid}")
        resp = client.post(f"/api/reflection/{rid}/restore")
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is True

    def test_list_hides_archived_by_default(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid_a = self._seed_reflection(app, "archived one")
        rid_b = self._seed_reflection(app, "active one")
        client.post(f"/api/reflection/{rid_a}/archive")
        resp = client.get("/api/reflection")
        ids = [r["id"] for r in resp.get_json()["reflections"]]
        assert rid_a not in ids
        assert rid_b in ids

    def test_list_with_include_archived_surfaces_them(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid_a = self._seed_reflection(app)
        client.post(f"/api/reflection/{rid_a}/archive")
        resp = client.get("/api/reflection?include_archived=true")
        ids = [r["id"] for r in resp.get_json()["reflections"]]
        assert rid_a in ids

    def test_list_hides_deleted_by_default(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.delete(f"/api/reflection/{rid}")
        resp = client.get("/api/reflection")
        assert rid not in [r["id"] for r in resp.get_json()["reflections"]]

    def test_list_with_include_deleted_surfaces_them(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.delete(f"/api/reflection/{rid}")
        resp = client.get("/api/reflection?include_deleted=true")
        ids = [r["id"] for r in resp.get_json()["reflections"]]
        assert rid in ids

    def test_archive_idempotent(self, app, client, monkeypatch):
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.post(f"/api/reflection/{rid}/archive")
        # Second archive call → still 200, still archived (no-op).
        resp = client.post(f"/api/reflection/{rid}/archive")
        assert resp.status_code == 200
        assert resp.get_json()["is_archived"] is True

    def test_delete_unknown_id_404(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.delete(
            "/api/reflection/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 404

    def test_archive_unknown_id_404(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection/00000000-0000-0000-0000-000000000000/archive",
        )
        assert resp.status_code == 404

    def test_restore_unknown_id_404(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/reflection/00000000-0000-0000-0000-000000000000/restore",
        )
        assert resp.status_code == 404

    def test_archive_independent_of_delete(self, app, client, monkeypatch):
        """Archive and delete are orthogonal flags — a reflection can be
        archived AND soft-deleted at the same time. Restore handles
        is_active; unarchive handles is_archived."""
        _bypass_auth(monkeypatch)
        rid = self._seed_reflection(app)
        client.post(f"/api/reflection/{rid}/archive")
        client.delete(f"/api/reflection/{rid}")
        with app.app_context():
            r = db.session.get(Reflection, uuid.UUID(rid))
            assert r.is_archived is True
            assert r.is_active is False
        # Restore brings back is_active only — still archived.
        client.post(f"/api/reflection/{rid}/restore")
        with app.app_context():
            r = db.session.get(Reflection, uuid.UUID(rid))
            assert r.is_archived is True
            assert r.is_active is True


class TestReflectionServiceArchiveDelete:
    """Direct service-layer assertions for the #238 archive/delete
    helpers — exercises the path without HTTP routing."""

    def test_set_reflection_archived_toggles_flag(self, app):
        with app.app_context():
            from reflection_service import (
                save_reflection,
                set_reflection_archived,
            )
            r = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            assert r.is_archived is False
            set_reflection_archived(r.id, archived=True)
            assert r.is_archived is True
            set_reflection_archived(r.id, archived=False)
            assert r.is_archived is False

    def test_set_reflection_archived_unknown_id_returns_none(self, app):
        with app.app_context():
            from reflection_service import set_reflection_archived
            assert set_reflection_archived(
                uuid.UUID("00000000-0000-0000-0000-000000000000"),
                archived=True,
            ) is None

    def test_soft_delete_then_restore(self, app):
        with app.app_context():
            from reflection_service import (
                restore_reflection,
                save_reflection,
                soft_delete_reflection,
            )
            r = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            assert r.is_active is True
            soft_delete_reflection(r.id)
            assert r.is_active is False
            restore_reflection(r.id)
            assert r.is_active is True

    def test_list_reflections_default_hides_archived_and_deleted(self, app):
        with app.app_context():
            from reflection_service import (
                list_reflections,
                save_reflection,
                set_reflection_archived,
                soft_delete_reflection,
            )
            active = save_reflection(
                transcript="active",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            archived = save_reflection(
                transcript="archived",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            deleted = save_reflection(
                transcript="deleted",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            set_reflection_archived(archived.id, archived=True)
            soft_delete_reflection(deleted.id)
            results = list_reflections()
            ids = {str(r.id) for r in results}
            assert str(active.id) in ids
            assert str(archived.id) not in ids
            assert str(deleted.id) not in ids

    def test_list_reflections_include_archived_surfaces(self, app):
        with app.app_context():
            from reflection_service import (
                list_reflections,
                save_reflection,
                set_reflection_archived,
            )
            r = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            set_reflection_archived(r.id, archived=True)
            assert r in list_reflections(include_archived=True)

    def test_list_reflections_include_deleted_surfaces(self, app):
        with app.app_context():
            from reflection_service import (
                list_reflections,
                save_reflection,
                soft_delete_reflection,
            )
            r = save_reflection(
                transcript="x",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            soft_delete_reflection(r.id)
            assert r in list_reflections(include_deleted=True)
