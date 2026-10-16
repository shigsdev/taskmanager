"""#435 — a section-only move to Today / Tomorrow re-dates the task.

Paths that send `tier` without `due_date` (bulk toolbar Section ▾, the
voice Shortcut's /move, ✨ Plan promote, Inbox triage, AI review) used to
keep the old date: a Today task moved to Tomorrow showed in both panels,
an overdue task moved to Today stayed overdue. update_task now gives the
task that day's date, like the board's own tier buttons do.

#466 (user decision 2026-10-16): a section-only move to This Week /
Backlog clears a date that doesn't fit that section, as Next Week already
did (#220), so the nightly re-sort doesn't move the task straight back out.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

import voice_action_token
from models import Task, TaskStatus, TaskType, Tier, db

SECRET = "test-secret"          # matches conftest app fixture
EMAIL = "me@example.com"        # matches conftest AUTHORIZED_EMAIL


def _today() -> date:
    from task_service import _local_today_date
    return _local_today_date()


def _make(app, **fields) -> str:
    base = {"title": "Seed", "type": TaskType.WORK}
    base.update(fields)
    with app.app_context():
        task = Task(**base)
        db.session.add(task)
        db.session.commit()
        return str(task.id)


def _get(app, tid: str) -> Task:
    with app.app_context():
        task = db.session.get(Task, uuid.UUID(tid))
        db.session.expunge(task)
        return task


def _patch(app, tid: str, data: dict) -> Task:
    from task_service import update_task
    with app.app_context():
        update_task(uuid.UUID(tid), data)
        db.session.commit()
    return _get(app, tid)


class TestSectionOnlyMove:

    def test_today_task_moved_to_tomorrow_gets_tomorrows_date(self, app):
        tid = _make(app, tier=Tier.TODAY, due_date=_today())
        task = _patch(app, tid, {"tier": "tomorrow"})
        assert task.tier == Tier.TOMORROW
        assert task.due_date == _today() + timedelta(days=1)

    def test_overdue_task_moved_to_today_gets_todays_date(self, app):
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() - timedelta(days=9))
        task = _patch(app, tid, {"tier": "today"})
        assert task.tier == Tier.TODAY
        assert task.due_date == _today()

    def test_overdue_today_task_moved_to_today_again_gets_todays_date(self, app):
        """The voice Shortcut's case: an overdue task already in Today
        (#170 keeps it there). "Move to today" means do it today."""
        tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=3))
        task = _patch(app, tid, {"tier": "today"})
        assert task.due_date == _today()

    def test_future_dated_task_moved_to_today_gets_todays_date(self, app):
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() + timedelta(days=40))
        task = _patch(app, tid, {"tier": "today"})
        assert task.tier == Tier.TODAY
        assert task.due_date == _today()

    def test_explicit_due_date_in_same_write_wins(self, app):
        later = _today() + timedelta(days=5)
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() - timedelta(days=2))
        task = _patch(app, tid, {"tier": "today", "due_date": later.isoformat()})
        assert task.tier == Tier.TODAY
        assert task.due_date == later

    def test_explicit_blank_due_date_wins(self, app):
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() - timedelta(days=2))
        task = _patch(app, tid, {"tier": "tomorrow", "due_date": None})
        assert task.tier == Tier.TOMORROW
        assert task.due_date is None

    def test_undated_task_still_filled(self, app):
        """The #28 fill-if-null rule still holds."""
        tid = _make(app, tier=Tier.INBOX)
        task = _patch(app, tid, {"tier": "tomorrow"})
        assert task.due_date == _today() + timedelta(days=1)

    def test_other_field_only_leaves_date_alone(self, app):
        old = _today() - timedelta(days=4)
        tid = _make(app, tier=Tier.TODAY, due_date=old)
        task = _patch(app, tid, {"title": "Renamed"})
        assert task.due_date == old

    def test_moves_to_inbox_and_freezer_keep_the_date(self, app):
        """Inbox (triage) and Freezer (a park) keep any date; This Week and
        Backlog are #466, below."""
        old = _today() - timedelta(days=4)
        for tier in ("inbox", "freezer"):
            tid = _make(app, tier=Tier.TODAY, due_date=old)
            task = _patch(app, tid, {"tier": tier})
            assert task.tier.value == tier
            assert task.due_date == old, tier

    def test_inactive_task_not_redated(self, app):
        old = _today() - timedelta(days=4)
        tid = _make(app, tier=Tier.BACKLOG, due_date=old, status=TaskStatus.ARCHIVED)
        task = _patch(app, tid, {"tier": "today"})
        assert task.due_date == old

    def test_restore_to_today_in_same_write_is_redated(self, app):
        """A completed task brought back into Today is active after the
        write, so it gets today's date."""
        tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=6),
                    status=TaskStatus.ARCHIVED)
        task = _patch(app, tid, {"tier": "today", "status": "active"})
        assert task.status == TaskStatus.ACTIVE
        assert task.due_date == _today()


class TestSectionOnlyMoveEndpoints:

    def test_bulk_section_to_tomorrow(self, app, authed_client):
        ids = [
            _make(app, tier=Tier.TODAY, due_date=_today()),
            _make(app, tier=Tier.BACKLOG, due_date=_today() - timedelta(days=8)),
        ]
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"tier": "tomorrow"}},
        )
        assert resp.status_code == 200
        tomorrow = (_today() + timedelta(days=1)).isoformat()
        for tid in ids:
            body = authed_client.get(f"/api/tasks/{tid}").get_json()
            assert body["tier"] == "tomorrow"
            assert body["due_date"] == tomorrow

    def test_voice_move_to_today_leaves_the_overdue_queue(self, app, client):
        tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=2))
        hdr = {"Authorization": "Bearer "
               + voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=90)}
        r = client.post(f"/api/voice-review/{tid}/move", json={"tier": "today"},
                        headers=hdr)
        assert r.status_code == 200
        assert _get(app, tid).due_date == _today()
        queue = client.get("/api/voice-review/queue", headers=hdr).get_json()
        assert queue["counts"]["overdue"] == 0
        assert [i["bucket"] for i in queue["items"]] == ["today"]


def _later_this_week():
    """A date after tomorrow inside this Mon-Sun week, or None (Sat / Sun)."""
    from task_service import _tier_for_due_date
    for n in range(2, 7):
        d = _today() + timedelta(days=n)
        if _tier_for_due_date(d) == Tier.THIS_WEEK:
            return d
    return None


def _next_week_date():
    from task_service import _tier_for_due_date
    for n in range(2, 15):
        d = _today() + timedelta(days=n)
        if _tier_for_due_date(d) == Tier.NEXT_WEEK:
            return d
    raise AssertionError("no next-week date")


FAR = 40  # days out: always Backlog's own range


class TestSectionMoveClearsUnfittingDate:
    """#466: This Week / Backlog keep only a date that fits them."""

    def test_far_dated_task_promoted_to_this_week_loses_the_date(self, app):
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() + timedelta(days=FAR))
        task = _patch(app, tid, {"tier": "this_week"})
        assert task.tier == Tier.THIS_WEEK
        assert task.due_date is None

    def test_promoted_task_stays_put_overnight(self, app):
        """The point of the fix: the 00:03 re-sort no longer undoes it."""
        from task_service import realign_tiers_with_due_dates
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today() + timedelta(days=FAR))
        _patch(app, tid, {"tier": "this_week"})
        with app.app_context():
            realign_tiers_with_due_dates()
        assert _get(app, tid).tier == Tier.THIS_WEEK

    def test_today_task_moved_to_backlog_loses_todays_date(self, app):
        tid = _make(app, tier=Tier.TODAY, due_date=_today())
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.tier == Tier.BACKLOG
        assert task.due_date is None

    def test_overdue_task_moved_to_backlog_or_this_week_loses_the_date(self, app):
        for tier in ("backlog", "this_week"):
            tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=3))
            task = _patch(app, tid, {"tier": tier})
            assert task.due_date is None, tier

    def test_tomorrow_date_does_not_fit_this_week(self, app):
        tid = _make(app, tier=Tier.TOMORROW, due_date=_today() + timedelta(days=1))
        task = _patch(app, tid, {"tier": "this_week"})
        assert task.due_date is None

    def test_next_week_date_does_not_fit_backlog(self, app):
        d = _next_week_date()
        tid = _make(app, tier=Tier.NEXT_WEEK, due_date=d)
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.due_date is None

    def test_a_far_date_fits_backlog(self, app):
        d = _today() + timedelta(days=FAR)
        tid = _make(app, tier=Tier.THIS_WEEK, due_date=d)
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.tier == Tier.BACKLOG
        assert task.due_date == d

    def test_a_later_this_week_date_fits_this_week(self, app):
        d = _later_this_week()
        if d is None:
            pytest.skip("no day after tomorrow left in this week")
        tid = _make(app, tier=Tier.BACKLOG, due_date=d)
        task = _patch(app, tid, {"tier": "this_week"})
        assert task.due_date == d

    def test_explicit_due_date_in_same_write_wins(self, app):
        d = _today() + timedelta(days=FAR)
        tid = _make(app, tier=Tier.BACKLOG, due_date=_today())
        task = _patch(app, tid, {"tier": "this_week", "due_date": d.isoformat()})
        assert task.due_date == d

    def test_same_section_write_keeps_the_date(self, app):
        """Like #220: only an actual move clears (a re-save of the same
        section isn't one)."""
        old = _today() - timedelta(days=3)
        tid = _make(app, tier=Tier.BACKLOG, due_date=old)
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.due_date == old

    def test_inactive_task_keeps_the_date(self, app):
        old = _today() - timedelta(days=3)
        tid = _make(app, tier=Tier.TODAY, due_date=old, status=TaskStatus.ARCHIVED)
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.due_date == old

    def test_reopened_into_backlog_with_a_stale_date_loses_it(self, app):
        """Re-open from Completed sends {status, tier}; active after the write."""
        tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=9),
                    status=TaskStatus.ARCHIVED)
        task = _patch(app, tid, {"tier": "backlog", "status": "active"})
        assert task.status == TaskStatus.ACTIVE
        assert task.due_date is None

    def test_undated_task_unchanged(self, app):
        tid = _make(app, tier=Tier.TODAY, due_date=None)
        task = _patch(app, tid, {"tier": "backlog"})
        assert task.due_date is None


class TestSectionMoveClearsUnfittingDateEndpoints:

    def test_bulk_section_to_backlog(self, app, authed_client):
        tid = _make(app, tier=Tier.TODAY, due_date=_today())
        r = authed_client.patch("/api/tasks/bulk", json={
            "task_ids": [tid], "updates": {"tier": "backlog"},
        })
        assert r.status_code == 200
        task = _get(app, tid)
        assert task.tier == Tier.BACKLOG
        assert task.due_date is None

    def test_voice_move_to_backlog_leaves_the_overdue_queue(self, app, client):
        tid = _make(app, tier=Tier.TODAY, due_date=_today() - timedelta(days=2))
        hdr = {"Authorization": "Bearer "
               + voice_action_token.mint(secret_key=SECRET, email=EMAIL, days=90)}
        r = client.post(f"/api/voice-review/{tid}/move", json={"tier": "backlog"},
                        headers=hdr)
        assert r.status_code == 200
        assert _get(app, tid).due_date is None
        queue = client.get("/api/voice-review/queue", headers=hdr).get_json()
        assert queue["counts"]["overdue"] == 0
