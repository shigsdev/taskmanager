"""#481: a batch keeps its rows when a project / goal link doesn't fit.

#475 checks the links a single write sets; the batch creators (import,
scan, voice memo, reflection) wrote ``project_id`` / ``goal_id`` straight
onto the new rows. On Postgres a dangling id failed the WHOLE batch at
commit ("Database error"); an archived project or goal was linked
silently; and a task could land on a project of the other type (an Excel
``linked_project``, a voice ``@project`` hint, a reflection
``project_hint``, or a pick on the review screen). Now a link that doesn't
fit is dropped from that row only, and the answer says which and why.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from models import Goal, Project, ProjectType, ReflectionInputMode, Task, TaskType, db

TAG = "B481"


def _project(name, type_=ProjectType.WORK, *, active=True):
    p = Project(name=name, type=type_, is_active=active)
    db.session.add(p)
    db.session.commit()
    return p


def _goal(title, *, active=True):
    from models import GoalCategory, GoalPriority
    g = Goal(title=title, category=GoalCategory.WORK, priority=GoalPriority.MUST,
             is_active=active)
    db.session.add(g)
    db.session.commit()
    return g


def _task(title) -> Task:
    db.session.expire_all()
    return db.session.scalars(select(Task).where(Task.title == title)).one()


# --- link_service.fit_batch_links ---------------------------------------------


class TestFitBatchLinks:
    def test_good_links_are_kept(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            p, g = _project(f"{TAG} work proj"), _goal(f"{TAG} goal")
            assert fit_batch_links(p.id, g.id, item_type=TaskType.WORK) == (p.id, g.id, [])

    def test_no_links_is_fine(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            assert fit_batch_links(None, None, item_type=TaskType.WORK) == (None, None, [])

    def test_a_missing_project_is_dropped(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            g = _goal(f"{TAG} goal")
            assert fit_batch_links(uuid.uuid4(), g.id, item_type=TaskType.WORK) == (
                None, g.id, ["its project no longer exists"])

    def test_an_archived_project_is_dropped(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            p = _project(f"{TAG} old", active=False)
            assert fit_batch_links(p.id, None, item_type=TaskType.WORK) == (
                None, None, [f'the project "{TAG} old" is archived'])

    def test_a_project_of_the_other_type_is_dropped(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            p = _project(f"{TAG} home", ProjectType.PERSONAL)
            assert fit_batch_links(p.id, None, item_type=TaskType.WORK) == (
                None, None, [f'"{TAG} home" is a personal project and this is a work task'])

    def test_a_missing_or_archived_goal_is_dropped(self, app):
        from link_service import fit_batch_links
        with app.app_context():
            g = _goal(f"{TAG} done goal", active=False)
            assert fit_batch_links(None, uuid.uuid4(), item_type=TaskType.WORK) == (
                None, None, ["its goal no longer exists"])
            assert fit_batch_links(None, g.id, item_type=TaskType.WORK) == (
                None, None, [f'the goal "{TAG} done goal" is archived'])


class TestBatchLinkWarning:
    def test_nothing_dropped_says_nothing(self):
        from link_service import batch_link_warning
        assert batch_link_warning([]) is None

    def test_names_each_row(self):
        from link_service import batch_link_warning
        assert batch_link_warning(['"A" — its goal no longer exists']) == (
            'Added without a link: "A" — its goal no longer exists.')

    def test_three_then_a_count(self):
        from link_service import batch_link_warning
        notes = [f'"{n}" — x' for n in "ABCDE"]
        assert batch_link_warning(notes) == (
            'Added without a link: "A" — x; "B" — x; "C" — x; and 2 more.')


# --- the batch endpoints --------------------------------------------------------


class TestImportTasksConfirm:
    def test_a_dangling_project_drops_that_link_and_keeps_the_batch(self, app, authed_client):
        with app.app_context():
            good = _project(f"{TAG} good")
            good_id = str(good.id)
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": f"{TAG} stale", "type": "work", "project_id": str(uuid.uuid4())},
            {"title": f"{TAG} fine", "type": "work", "project_id": good_id},
        ]})
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body["created"] == 2
        assert body["warning"] == (
            f'Added without a link: "{TAG} stale" — its project no longer exists.')
        with app.app_context():
            assert _task(f"{TAG} stale").project_id is None
            assert str(_task(f"{TAG} fine").project_id) == good_id

    def test_an_excel_linked_project_of_the_other_type_is_dropped(self, app, authed_client):
        with app.app_context():
            _project(f"{TAG} garden", ProjectType.PERSONAL)
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": f"{TAG} mow", "type": "work", "linked_project": f"{TAG} garden"},
        ]})
        assert r.status_code == 201
        why = f'"{TAG} garden" is a personal project and this is a work task'
        assert why in r.get_json()["warning"]
        with app.app_context():
            assert _task(f"{TAG} mow").project_id is None

    def test_all_links_fine_answers_no_warning(self, app, authed_client):
        # The quiet case.
        with app.app_context():
            gid = str(_goal(f"{TAG} g").id)
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": f"{TAG} plain", "type": "work", "goal_id": gid},
        ]})
        assert r.status_code == 201
        assert "warning" not in r.get_json()


class TestScanConfirm:
    def test_an_archived_goal_is_dropped_and_said(self, app, authed_client):
        with app.app_context():
            gid = str(_goal(f"{TAG} retired", active=False).id)
        r = authed_client.post("/api/scan/confirm", json={"kind": "tasks", "candidates": [
            {"title": f"{TAG} scanned", "type": "work", "goal_id": gid, "included": True},
        ]})
        assert r.status_code == 201, r.get_json()
        assert r.get_json()["warning"] == (
            f'Added without a link: "{TAG} scanned" — the goal "{TAG} retired" is archived.')
        with app.app_context():
            assert _task(f"{TAG} scanned").goal_id is None

    def test_all_links_fine_answers_no_warning(self, app, authed_client):
        r = authed_client.post("/api/scan/confirm", json={"kind": "tasks", "candidates": [
            {"title": f"{TAG} scan plain", "type": "work", "included": True},
        ]})
        assert r.status_code == 201
        assert "warning" not in r.get_json()


class TestVoiceConfirm:
    def test_a_hinted_project_of_the_other_type_is_dropped_and_said(self, app, authed_client):
        with app.app_context():
            pid = str(_project(f"{TAG} chores", ProjectType.PERSONAL).id)
        r = authed_client.post("/api/voice-memo/confirm", json={"candidates": [
            {"title": f"{TAG} spoken", "type": "work", "route": "task",
             "project_id": pid, "included": True},
        ]})
        assert r.status_code == 201, r.get_json()
        why = f'"{TAG} chores" is a personal project and this is a work task'
        assert why in r.get_json()["warning"]
        with app.app_context():
            assert _task(f"{TAG} spoken").project_id is None


class TestReflectionApply:
    @pytest.fixture
    def reflection(self, app):
        from reflection_service import save_reflection
        with app.app_context():
            r = save_reflection(transcript="481", input_mode=ReflectionInputMode.TYPED,
                                proposed={"explicit": [], "suggested": []})
            return r.id

    def test_a_hint_to_a_project_of_the_other_type_is_dropped_into_notes(self, app, reflection):
        from models import Reflection
        from reflection_service import apply_selected_actions
        with app.app_context():
            _project(f"{TAG} yard", ProjectType.PERSONAL)
            refl = db.session.get(Reflection, reflection)
            summary = apply_selected_actions(refl, [
                {"op": "create", "entity": "task",
                 "fields": {"title": f"{TAG} reflected", "type": "work",
                            "project_hint": f"{TAG} yard"}},
            ])
            assert summary["created"]["task"] == 1
            assert summary["errors"] == []
            assert summary["failed"] == []
            assert summary["notes"] == [
                f'"{TAG} reflected" — "{TAG} yard" is a personal project and this is a work task']
            assert _task(f"{TAG} reflected").project_id is None

    def test_fine_links_leave_no_notes(self, app, reflection):
        from models import Reflection
        from reflection_service import apply_selected_actions
        with app.app_context():
            refl = db.session.get(Reflection, reflection)
            summary = apply_selected_actions(refl, [
                {"op": "create", "entity": "task",
                 "fields": {"title": f"{TAG} plain reflected", "type": "work"}},
            ])
            assert summary["notes"] == []
