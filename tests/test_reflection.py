"""Tests for the Weekly Reflection feature.

Covers reflection_service (snapshot, Claude-response parsing, action
normalisation, apply) and reflection_api endpoints. The Claude call and
Whisper transcription are mocked — no API keys or network needed.
"""
from __future__ import annotations

import io
import json
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
