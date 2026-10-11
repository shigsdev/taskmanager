"""#363: /recurring shows paused templates, and Delete is its own state.

Spec: docs/design/363-paused-templates-visible.md.

Before this, `delete_recurring` wrote the same `is_active=False` as Pause,
and `/recurring` asked for `?active_only=false` — a param the route never
read — so a paused template vanished and Resume could not be reached.
`deleted_at` separates the two: paused = inactive and not deleted, which
`GET /api/recurring?all=1` now lists; deleted = never listed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from models import (
    Project,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskType,
    Tier,
    db,
)

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "versions"
    / "v1d2e3f4a5b6_recurring_deleted_at.py"
)


def _rt(title: str, **kw) -> RecurringTask:
    rt = RecurringTask(
        title=title,
        frequency=kw.pop("frequency", RecurringFrequency.DAILY),
        type=kw.pop("type", TaskType.WORK),
        **kw,
    )
    db.session.add(rt)
    db.session.commit()
    return rt


def _get(rt_id) -> RecurringTask:
    rt = db.session.get(RecurringTask, rt_id)
    db.session.refresh(rt)
    return rt


def _titles(resp) -> list[str]:
    assert resp.status_code == 200
    return [r["title"] for r in resp.get_json()]


# --- the migration (spec §2) -------------------------------------------------


def test_migration_chains_onto_the_previous_head():
    spec = importlib.util.spec_from_file_location("mig_363", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "u0c1d2e3f4a5"


def test_existing_inactive_rows_read_as_paused(authed_client, app):
    """User decision 2026-10-11: no backfill, so every inactive row that
    predates the column has deleted_at NULL and is listed as paused."""
    with app.app_context():
        _rt("Weekly Work Prep", is_active=False)
        assert _get(RecurringTask.query.one().id).deleted_at is None

    assert _titles(authed_client.get("/api/recurring?all=1")) == ["Weekly Work Prep"]


# --- delete is its own state (spec §3.2-3.3) ----------------------------------


class TestDeleteIsNotPause:
    def test_delete_stamps_deleted_at(self, authed_client, app):
        with app.app_context():
            rid = _rt("gone").id

        assert authed_client.delete(f"/api/recurring/{rid}").status_code == 204
        with app.app_context():
            rt = _get(rid)
            assert rt.is_active is False
            assert rt.deleted_at is not None

    def test_bulk_delete_stamps_deleted_at(self, authed_client, app):
        with app.app_context():
            ids = [_rt("a").id, _rt("b").id]

        resp = authed_client.delete(
            "/api/recurring/bulk", json={"template_ids": [str(i) for i in ids]},
        )
        assert resp.get_json()["deleted"] == 2
        with app.app_context():
            assert all(_get(i).deleted_at is not None for i in ids)

    def test_all_lists_paused_but_not_deleted(self, authed_client, app):
        with app.app_context():
            _rt("running")
            _rt("paused", is_active=False)
            gone = _rt("deleted").id

        authed_client.delete(f"/api/recurring/{gone}")
        assert sorted(_titles(authed_client.get("/api/recurring?all=1"))) == [
            "paused", "running",
        ]

    def test_default_list_is_still_active_only(self, authed_client, app):
        with app.app_context():
            _rt("running")
            _rt("paused", is_active=False)

        assert _titles(authed_client.get("/api/recurring")) == ["running"]

    def test_removing_repeat_on_a_task_deletes_the_template(self, authed_client, app):
        """Repeat → none ends the series; it must not linger as PAUSED."""
        with app.app_context():
            rt = _rt("standup")
            t = Task(title="standup", type=TaskType.WORK, tier=Tier.TODAY,
                     recurring_task_id=rt.id)
            db.session.add(t)
            db.session.commit()
            rid, tid = rt.id, t.id

        resp = authed_client.patch(f"/api/tasks/{tid}", json={"repeat": None})
        assert resp.status_code == 200
        with app.app_context():
            assert _get(rid).deleted_at is not None
        assert "standup" not in _titles(authed_client.get("/api/recurring?all=1"))

    def test_resuming_a_deleted_template_undeletes_it(self, authed_client, app):
        """Spec §3.4: the task panel's re-set Repeat revives the same row
        (today's behaviour) — so it must come back as a live template."""
        with app.app_context():
            rid = _rt("back again").id

        authed_client.delete(f"/api/recurring/{rid}")
        resp = authed_client.patch(f"/api/recurring/{rid}", json={"is_active": True})
        assert resp.status_code == 200
        with app.app_context():
            rt = _get(rid)
            assert rt.is_active is True
            assert rt.deleted_at is None


# --- an explicit pause claims an archive-paused template (spec §3.5) ---------


def _archive_paused(app) -> tuple:
    with app.app_context():
        p = Project(name="CoP", is_active=True)
        db.session.add(p)
        db.session.commit()
        rid = _rt("survey", project_id=p.id).id
        return p.id, rid


class TestExplicitPauseClaimsTheTemplate:
    def test_bulk_pause_on_archive_paused_row_survives_unarchive(self, authed_client, app):
        pid, rid = _archive_paused(app)
        authed_client.patch(f"/api/projects/{pid}", json={"is_active": False})
        with app.app_context():
            assert _get(rid).paused_by_project_archive is True

        resp = authed_client.patch("/api/recurring/bulk", json={
            "template_ids": [str(rid)], "updates": {"is_active": False},
        })
        assert resp.status_code == 200
        authed_client.patch(f"/api/projects/{pid}", json={"is_active": True})

        with app.app_context():
            rt = _get(rid)
            assert rt.is_active is False, "unarchive woke a template the user paused"
            assert rt.paused_by_project_archive is False

    def test_editor_save_without_is_active_keeps_the_marker(self, authed_client, app):
        """The /recurring editor re-sends the form, not is_active — a plain
        Save must not cancel the resume."""
        pid, rid = _archive_paused(app)
        authed_client.patch(f"/api/projects/{pid}", json={"is_active": False})

        authed_client.patch(f"/api/recurring/{rid}", json={
            "title": "survey (renamed)", "project_id": str(pid),
        })
        authed_client.patch(f"/api/projects/{pid}", json={"is_active": True})
        with app.app_context():
            assert _get(rid).is_active is True


# --- the row can say why it is paused (spec §3.6) ------------------------------


@pytest.mark.parametrize("project_flag,goal_flag", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_serializer_carries_both_archive_markers(authed_client, app, project_flag, goal_flag):
    with app.app_context():
        rid = _rt("t", is_active=False, paused_by_project_archive=project_flag,
                  paused_by_goal_archive=goal_flag).id

    body = authed_client.get(f"/api/recurring/{rid}").get_json()
    assert body["paused_by_project_archive"] is project_flag
    assert body["paused_by_goal_archive"] is goal_flag
