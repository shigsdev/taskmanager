"""#438 — week rollover rules (user decisions 2026-10-12).

1. Undated Next Week tasks move to This Week when a new week starts —
   once per ISO week, recorded in AppSetting so a missed Monday run that
   is replayed later still rolls. The first run after deploy only
   records the week (what's in Next Week now means the coming week).
2. A This Week / Next Week task whose date has passed moves to Today
   (overdue stays in sight, like #170 / #386) instead of to Backlog.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from models import AppSetting, Task, TaskStatus, TaskType, Tier, db

MONDAY = date(2026, 10, 19)
KEY = "week_roll_last_iso_week"


@pytest.fixture
def today(monkeypatch):
    holder = {"d": MONDAY}
    monkeypatch.setattr("task_service._local_today_date", lambda: holder["d"])
    return holder


def _task(title, tier, due=None, status=TaskStatus.ACTIVE):
    t = Task(title=title, type=TaskType.WORK, tier=tier, due_date=due, status=status)
    db.session.add(t)
    db.session.commit()
    return t.id


def _tier(tid):
    db.session.expire_all()
    return db.session.get(Task, tid).tier


def _marker():
    row = AppSetting.query.filter_by(key=KEY).first()
    return row.value if row else None


def _run():
    from task_service import realign_tiers_with_due_dates
    return realign_tiers_with_due_dates()


class TestUndatedNextWeekRolls:

    def test_first_run_only_records_the_week(self, app, today):
        with app.app_context():
            tid = _task("438 parked", Tier.NEXT_WEEK)
            _run()
            assert _tier(tid) == Tier.NEXT_WEEK
            assert _marker() == "2026-W43"

    def test_new_week_moves_it_to_this_week_once(self, app, today):
        with app.app_context():
            db.session.add(AppSetting(key=KEY, value="2026-W42"))
            db.session.commit()
            parked = _task("438 parked", Tier.NEXT_WEEK)
            assert _run() >= 1
            assert _tier(parked) == Tier.THIS_WEEK
            assert _marker() == "2026-W43"

            # Same week again (e.g. Tuesday's run): a task parked after
            # Monday's roll means the week after, so it stays.
            today["d"] = MONDAY + timedelta(days=1)
            later = _task("438 parked Tuesday", Tier.NEXT_WEEK)
            _run()
            assert _tier(later) == Tier.NEXT_WEEK

    def test_missed_monday_still_rolls_on_a_later_day(self, app, today):
        with app.app_context():
            db.session.add(AppSetting(key=KEY, value="2026-W42"))
            db.session.commit()
            today["d"] = MONDAY + timedelta(days=2)  # Wednesday replay
            tid = _task("438 parked", Tier.NEXT_WEEK)
            _run()
            assert _tier(tid) == Tier.THIS_WEEK

    def test_only_active_undated_next_week_tasks_roll(self, app, today):
        with app.app_context():
            db.session.add(AppSetting(key=KEY, value="2026-W42"))
            db.session.commit()
            done = _task("438 done", Tier.NEXT_WEEK, status=TaskStatus.ARCHIVED)
            backlog = _task("438 backlog", Tier.BACKLOG)
            dated = _task("438 dated next week", Tier.NEXT_WEEK, MONDAY + timedelta(days=9))
            _run()
            assert _tier(done) == Tier.NEXT_WEEK
            assert _tier(backlog) == Tier.BACKLOG
            assert _tier(dated) == Tier.NEXT_WEEK  # still next week by its date


class TestPassedDateGoesToToday:

    def test_this_week_task_dated_yesterday_moves_to_today(self, app, today):
        with app.app_context():
            today["d"] = MONDAY + timedelta(days=2)  # Wednesday
            tid = _task("438 Tuesday", Tier.THIS_WEEK, MONDAY + timedelta(days=1))
            _run()
            assert _tier(tid) == Tier.TODAY

    def test_last_weeks_this_week_task_moves_to_today_not_backlog(self, app, today):
        with app.app_context():
            tid = _task("438 last Thursday", Tier.THIS_WEEK, MONDAY - timedelta(days=4))
            _run()
            assert _tier(tid) == Tier.TODAY

    def test_next_week_task_with_a_passed_date_moves_to_today(self, app, today):
        with app.app_context():
            tid = _task("438 stale next week", Tier.NEXT_WEEK, MONDAY - timedelta(days=1))
            _run()
            assert _tier(tid) == Tier.TODAY

    def test_this_week_task_dated_later_this_week_stays(self, app, today):
        with app.app_context():
            tid = _task("438 Friday", Tier.THIS_WEEK, MONDAY + timedelta(days=4))
            _run()
            assert _tier(tid) == Tier.THIS_WEEK

    def test_other_sections_keep_their_rules(self, app, today):
        with app.app_context():
            past = MONDAY - timedelta(days=10)
            backlog = _task("438 backlog past", Tier.BACKLOG, past)
            freezer = _task("438 freezer past", Tier.FREEZER, past)
            inbox = _task("438 inbox past", Tier.INBOX, past)
            today_t = _task("438 today past", Tier.TODAY, past)
            _run()
            assert _tier(backlog) == Tier.BACKLOG
            assert _tier(freezer) == Tier.FREEZER
            assert _tier(inbox) == Tier.INBOX
            assert _tier(today_t) == Tier.TODAY  # #170
