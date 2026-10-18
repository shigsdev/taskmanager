"""#500: the Siri Shortcut's answer and add-a-task routes (ADR-043).

Spec: docs/design/500-siri-add-and-edit-by-voice.md §2, §4. Both routes
take only ``text`` and answer with a ``say`` sentence for Siri on every
path. The load-bearing scope checks: only title / due date / section /
status ever change, and extra JSON keys are ignored.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

import voice_action_token
from models import Task, TaskStatus, TaskType, Tier
from models import db as _db
from utils import local_today_date

SECRET = "test-secret"          # matches conftest app fixture
EMAIL = "me@example.com"        # matches conftest AUTHORIZED_EMAIL


def _hdr() -> dict:
    token = voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=90)
    return {"Authorization": f"Bearer {token}"}


def _make_task(app, *, title="Drive-review task", tier=Tier.TODAY, status=TaskStatus.ACTIVE,
               due_date=None, notes=None) -> str:
    with app.app_context():
        t = Task(title=title, type=TaskType.WORK, tier=tier, status=status,
                 due_date=due_date, notes=notes)
        _db.session.add(t)
        _db.session.commit()
        return str(t.id)


def _task(app, tid) -> Task:
    with app.app_context():
        t = _db.session.get(Task, uuid.UUID(tid))
        _db.session.expunge(t)
        return t


def _answer(client, tid, text, **extra):
    return client.post(f"/api/voice-review/{tid}/answer", json={"text": text, **extra},
                       headers=_hdr())


class TestAnswer:
    def test_complete(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "Complete.")
        assert r.status_code == 200
        assert r.get_json() == {"ok": True, "action": "complete", "id": tid,
                                "say": "Marked complete."}
        assert _task(app, tid).status == TaskStatus.ARCHIVED

    def test_cancel(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "cancel it")
        assert r.get_json()["say"] == "Cancelled."
        assert _task(app, tid).status == TaskStatus.CANCELLED

    def test_move(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "Move it to next week.")
        assert r.get_json()["say"] == "Moved to Next Week."
        assert _task(app, tid).tier == Tier.NEXT_WEEK

    def test_rename(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "Rename to call the dentist.")
        assert r.get_json()["say"] == 'Renamed to "Call the dentist".'
        assert _task(app, tid).title == "Call the dentist"

    def test_due_tomorrow_moves_section(self, app, client):
        tid = _make_task(app, tier=Tier.BACKLOG)
        r = _answer(client, tid, "Due tomorrow.")
        body = r.get_json()
        t = _task(app, tid)
        assert t.due_date == local_today_date() + timedelta(days=1)
        assert t.tier == Tier.TOMORROW
        assert body["ok"] is True and body["action"] == "due"
        assert body["say"].startswith("Due ") and body["say"].endswith("It's in Tomorrow.")

    def test_due_far_date_files_to_backlog(self, app, client):
        tid = _make_task(app, tier=Tier.TODAY)
        r = _answer(client, tid, "due December 24 2030")
        t = _task(app, tid)
        assert t.due_date == date(2030, 12, 24)
        assert t.tier == Tier.BACKLOG
        assert r.get_json()["say"] == "Due Tuesday, December 24. It's in Backlog."

    def test_clear_due(self, app, client):
        tid = _make_task(app, tier=Tier.BACKLOG, due_date=date(2030, 12, 24))
        r = _answer(client, tid, "remove the due date")
        assert r.get_json()["say"] == "Due date removed."
        assert _task(app, tid).due_date is None

    def test_skip_changes_nothing(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "Skip.")
        assert r.get_json() == {"ok": True, "action": "skip", "id": tid, "say": "Skipped."}
        t = _task(app, tid)
        assert t.status == TaskStatus.ACTIVE and t.tier == Tier.TODAY

    @pytest.mark.parametrize("said,say", [
        ("complete it tomorrow", "I didn't catch that, so I left it as it is."),
        ("due someday", "I didn't understand that date, so I left it as it is."),
    ])
    def test_not_understood_changes_nothing(self, app, client, said, say):
        tid = _make_task(app)
        r = _answer(client, tid, said)
        assert r.status_code == 200
        assert r.get_json()["ok"] is False
        assert r.get_json()["say"] == say
        t = _task(app, tid)
        assert t.status == TaskStatus.ACTIVE and t.tier == Tier.TODAY and t.due_date is None

    @pytest.mark.parametrize("status", [TaskStatus.ARCHIVED, TaskStatus.CANCELLED,
                                        TaskStatus.DELETED])
    def test_task_no_longer_open_is_left(self, app, client, status):
        tid = _make_task(app, status=status)
        r = _answer(client, tid, "rename to sneaky")
        assert r.status_code == 200
        assert r.get_json()["ok"] is False
        assert r.get_json()["say"] == "That task isn't open any more, so I skipped it."
        assert _task(app, tid).title == "Drive-review task"

    def test_missing_task_404_still_speaks(self, app, client):
        r = _answer(client, uuid.uuid4(), "complete")
        assert r.status_code == 404
        assert r.get_json()["say"] == "That task isn't there any more, so I skipped it."

    @pytest.mark.parametrize("body", [{}, {"text": 7}, None])
    def test_no_text_400_still_speaks(self, app, client, body):
        tid = _make_task(app)
        r = client.post(f"/api/voice-review/{tid}/answer", json=body, headers=_hdr())
        assert r.status_code == 400
        assert r.get_json()["say"] == "I didn't hear an answer, so I left it as it is."

    def test_too_long_rename_refused(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "rename to " + "x" * 600)
        body = r.get_json()
        assert r.status_code == 200 and body["ok"] is False
        assert body["say"].startswith("I couldn't do that: ")
        assert _task(app, tid).title == "Drive-review task"

    def test_extra_keys_ignored(self, app, client):
        tid = _make_task(app, notes="mine")
        _answer(client, tid, "rename to new name", notes="evil", tier="freezer",
                project_id=str(uuid.uuid4()), status="deleted")
        t = _task(app, tid)
        assert t.title == "New name"
        assert t.notes == "mine" and t.tier == Tier.TODAY and t.status == TaskStatus.ACTIVE

    def test_needs_auth(self, app, client):
        tid = _make_task(app)
        r = client.post(f"/api/voice-review/{tid}/answer", json={"text": "complete"})
        assert r.status_code == 401
        assert _task(app, tid).status == TaskStatus.ACTIVE


def _add(client, text, **extra):
    return client.post("/api/voice-review/tasks", json={"text": text, **extra}, headers=_hdr())


def _only_task(app) -> Task:
    with app.app_context():
        tasks = Task.query.all()
        assert len(tasks) == 1
        _db.session.expunge(tasks[0])
        return tasks[0]


class TestAddTask:
    def test_personal_to_inbox(self, app, client):
        r = _add(client, "Personal buy milk.")
        assert r.status_code == 201
        t = _only_task(app)
        assert (t.title, t.type, t.tier, t.due_date) == (
            "Buy milk", TaskType.PERSONAL, Tier.INBOX, None)
        assert r.get_json() == {"ok": True, "id": str(t.id), "title": "Buy milk",
                                "say": 'Added "Buy milk" to your Inbox as a personal task.'}

    def test_no_type_word_is_personal(self, app, client):
        _add(client, "Water the plants")
        assert _only_task(app).type == TaskType.PERSONAL

    def test_work_with_due_date_files_to_its_section(self, app, client):
        r = _add(client, "Work task call Sam due tomorrow")
        t = _only_task(app)
        assert t.type == TaskType.WORK and t.title == "Call Sam"
        assert t.due_date == local_today_date() + timedelta(days=1)
        assert t.tier == Tier.TOMORROW
        assert r.get_json()["say"].startswith('Added "Call Sam", due ')
        assert r.get_json()["say"].endswith(", to Tomorrow as a work task.")

    def test_extra_keys_ignored(self, app, client):
        _add(client, "work fix the gate", notes="evil", tier="freezer",
             project_id=str(uuid.uuid4()), goal_id=str(uuid.uuid4()), type="personal")
        t = _only_task(app)
        assert (t.type, t.tier, t.notes, t.project_id, t.goal_id) == (
            TaskType.WORK, Tier.INBOX, None, None, None)

    @pytest.mark.parametrize("said", ["", "work", "Personal task."])
    def test_nothing_heard_adds_nothing(self, app, client, said):
        r = _add(client, said)
        assert r.status_code == 200
        assert r.get_json() == {"ok": False, "say": "I didn't hear a task, so nothing was added."}
        with app.app_context():
            assert Task.query.count() == 0

    def test_too_long_adds_nothing(self, app, client):
        r = _add(client, "x" * 600)
        assert r.status_code == 200 and r.get_json()["ok"] is False
        assert r.get_json()["say"].startswith("I couldn't add that: ")
        with app.app_context():
            assert Task.query.count() == 0

    def test_no_text_400(self, app, client):
        r = client.post("/api/voice-review/tasks", json={"title": "x"}, headers=_hdr())
        assert r.status_code == 400
        assert r.get_json()["say"] == "I didn't hear a task, so nothing was added."

    def test_needs_auth(self, app, client):
        r = client.post("/api/voice-review/tasks", json={"text": "buy milk"})
        assert r.status_code == 401
        with app.app_context():
            assert Task.query.count() == 0


class TestScopeStillHolds:
    """ADR-043 widens the token to these two routes only."""

    def test_cannot_create_through_tasks_api(self, app, client):
        r = client.post("/api/tasks", json={"title": "x", "type": "work"}, headers=_hdr())
        assert r.status_code in (401, 403)

    def test_cannot_patch_through_tasks_api(self, app, client):
        tid = _make_task(app)
        r = client.patch(f"/api/tasks/{tid}", json={"notes": "x"}, headers=_hdr())
        assert r.status_code in (401, 403)


class TestHelp:
    """#503 (folded into #500): the Help builds the Shortcut with the answer
    action, and the two steps Shortcuts can't do are gone."""

    def test_help_uses_answer_and_add(self, authed_client):
        html = authed_client.get("/docs").get_data(as_text=True)
        assert "/api/voice-review/tasks" in html
        assert "<code>/answer</code>" in html
        assert "Otherwise If" not in html
        assert "output variable" not in html


class TestTooLong:
    """Security review 2026-10-18: both routes refuse text over 1,000
    characters before parsing it."""

    def test_answer_refuses_long_text(self, app, client):
        tid = _make_task(app)
        r = _answer(client, tid, "rename to " + "x" * 1000)
        assert r.status_code == 400
        assert r.get_json()["say"] == "That was too long, so I left it as it is."
        assert _task(app, tid).title == "Drive-review task"

    def test_add_refuses_long_text(self, app, client):
        r = _add(client, "due " * 300)
        assert r.status_code == 400
        assert r.get_json()["say"] == "That was too long, so nothing was added."
        with app.app_context():
            assert Task.query.count() == 0

    def test_help_has_numbered_steps_and_copy_fields(self, authed_client):
        # #504: the setup guide's numbered steps, with copy fields for the
        # three addresses, and the Apple Health phone test.
        html = authed_client.get("/docs").get_data(as_text=True)
        for field, url in (
            ("docsSiriQueueUrl", "/api/voice-review/queue"),
            ("docsSiriBaseUrl", "/api/voice-review/"),
            ("docsSiriTasksUrl", "/api/voice-review/tasks"),
        ):
            assert f'id="{field}"' in html
            assert f'data-copy-for="{field}"' in html
            assert f'value="https://web-production-3e3ae.up.railway.app{url}"' in html
        assert '<span class="docs-step-num">21</span>' in html
        assert "docs_copy.js" in html and "voice_token_helpers.js" in html
        assert 'id="apple-health"' in html and 'href="#apple-health"' in html
