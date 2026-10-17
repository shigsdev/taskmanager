"""#501: set and change a repeating task's start date.

The template has had ``start_date`` since #147 (the spawn cron and the
previews skip every day before it), but no screen could show or change it.
These pin what the task panel and the /recurring editor now rely on:

- a task's ``repeat`` carries ``start_date`` so the panel can show it;
- through the task API, ``repeat.start_date`` set = change it, explicit
  null = clear it ("start right away"), the key left out = keep it (#426:
  a save never derives it from the task's own due date);
- a NEW repeat with no start_date key still starts from the task's due
  date (#147), and an explicit one wins;
- a start date after the Stop-after date is refused in plain words.
"""
from __future__ import annotations

import uuid
from datetime import date

from models import RecurringTask, db


def _make(client, **repeat_extra):
    body = client.post("/api/tasks", json={
        "title": "Weekly Work Prep", "type": "work",
        "due_date": "2026-10-12",  # a Monday
        "repeat": {"frequency": "weekly", "day_of_week": 0, **repeat_extra},
    })
    assert body.status_code == 201, body.get_json()
    return body.get_json()


def _template(app, task):
    with app.app_context():
        return db.session.get(RecurringTask, uuid.UUID(task["repeat"]["template_id"]))


def _save(client, task, repeat):
    resp = client.patch(f"/api/tasks/{task['id']}", json={"repeat": repeat})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


class TestTheTaskShowsItsStartDate:

    def test_repeat_carries_start_date(self, authed_client):
        task = _make(authed_client)
        assert task["repeat"]["start_date"] == "2026-10-12"   # #147 default

    def test_no_start_date_no_key(self, authed_client, app):
        task = _make(authed_client)
        with app.app_context():
            rt = db.session.get(RecurringTask, uuid.UUID(task["repeat"]["template_id"]))
            rt.start_date = None
            db.session.commit()
        got = authed_client.get(f"/api/tasks/{task['id']}").get_json()
        assert "start_date" not in got["repeat"]


class TestANewRepeat:

    def test_without_the_key_it_starts_from_the_due_date(self, authed_client, app):
        task = _make(authed_client)
        assert _template(app, task).start_date == date(2026, 10, 12)

    def test_an_explicit_start_date_wins(self, authed_client, app):
        task = _make(authed_client, start_date="2026-11-02")
        assert _template(app, task).start_date == date(2026, 11, 2)

    def test_an_explicit_null_means_right_away(self, authed_client, app):
        task = _make(authed_client, start_date=None)
        assert _template(app, task).start_date is None


class TestChangingIt:

    def test_set_a_later_start_date(self, authed_client, app):
        task = _make(authed_client)
        saved = _save(authed_client, task, {"frequency": "weekly", "day_of_week": 0,
                                            "start_date": "2026-11-02"})
        assert _template(app, task).start_date == date(2026, 11, 2)
        assert saved["repeat"]["start_date"] == "2026-11-02"

    def test_an_explicit_null_clears_it(self, authed_client, app):
        task = _make(authed_client)
        _save(authed_client, task, {"frequency": "weekly", "day_of_week": 0, "start_date": None})
        assert _template(app, task).start_date is None

    def test_leaving_the_key_out_keeps_it(self, authed_client, app):
        """The quiet case (#426): an older tab's save, or any client that
        doesn't know the field, changes nothing."""
        task = _make(authed_client, start_date="2026-11-02")
        _save(authed_client, task, {"frequency": "weekly", "day_of_week": 0})
        assert _template(app, task).start_date == date(2026, 11, 2)

    def test_previews_follow_the_new_start_date(self, authed_client):
        task = _make(authed_client)
        _save(authed_client, task, {"frequency": "weekly", "day_of_week": 0,
                                    "start_date": "2026-11-02"})
        rows = authed_client.get(
            "/api/recurring/previews?start=2026-10-12&end=2026-11-15").get_json()
        mine = sorted(r["fire_date"] for r in rows if r["title"] == "Weekly Work Prep")
        assert mine == ["2026-11-02", "2026-11-09"]

    def test_moving_it_later_leaves_spawned_tasks_alone(self, authed_client):
        task = _make(authed_client)
        _save(authed_client, task, {"frequency": "weekly", "day_of_week": 0,
                                    "start_date": "2026-12-07"})
        got = authed_client.get(f"/api/tasks/{task['id']}")
        assert got.status_code == 200
        assert got.get_json()["status"] == "active"


class TestTheRecurringEditorPath:

    def test_patch_sets_and_clears(self, authed_client, app):
        task = _make(authed_client)
        tid = task["repeat"]["template_id"]
        resp = authed_client.patch(f"/api/recurring/{tid}", json={"start_date": "2026-11-02"})
        assert resp.status_code == 200
        assert resp.get_json()["start_date"] == "2026-11-02"
        resp = authed_client.patch(f"/api/recurring/{tid}", json={"start_date": None})
        assert resp.get_json()["start_date"] is None

    def test_start_after_stop_is_refused_in_plain_words(self, authed_client):
        task = _make(authed_client)
        tid = task["repeat"]["template_id"]
        resp = authed_client.patch(f"/api/recurring/{tid}", json={
            "start_date": "2026-12-01", "end_date": "2026-11-01",
        })
        assert resp.status_code == 422
        assert resp.get_json()["error"] == (
            "The start date must be on or before the Stop after date."
        )

    def test_the_same_through_the_task_panel(self, authed_client):
        task = _make(authed_client)
        resp = authed_client.patch(f"/api/tasks/{task['id']}", json={"repeat": {
            "frequency": "weekly", "day_of_week": 0,
            "start_date": "2026-12-01", "end_date": "2026-11-01",
        }})
        assert resp.status_code == 422
        assert "Stop after" in resp.get_json()["error"]
