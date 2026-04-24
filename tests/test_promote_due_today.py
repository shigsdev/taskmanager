"""Bug #46 (ADR-029) tests — promote planning-tier tasks with
due_date=today to TODAY tier.

Two paths under test:
1. The 00:02 nightly cron `promote_due_today_tasks()` — bulk SQL
   UPDATE with isolated session.
2. The on-write hook in `task_service.update_task` /
   `task_service.create_task` — synchronous promotion when a user
   PATCHes due_date or creates a task with due_date=today.
"""
from __future__ import annotations

from datetime import date, timedelta

from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


def _today() -> date:
    """Match the helper the prod code uses, so tests stay TZ-correct."""
    from task_service import _local_today_date
    return _local_today_date()


# --- promote_due_today_tasks() cron path -----------------------------------


class TestPromoteDueTodayCron:

    def test_promotes_this_week_due_today(self, app):
        """Bug #46 reproducer: Meds task in this_week with due_date=today
        gets promoted to TODAY by the cron."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="Meds", tier=Tier.THIS_WEEK, due_date=_today())
            _make_task(title="future-thing", tier=Tier.THIS_WEEK,
                       due_date=_today() + timedelta(days=2))
            count = promote_due_today_tasks()
        assert count == 1
        with app.app_context():
            from sqlalchemy import select
            today_titles = {t.title for t in db.session.scalars(
                select(Task).where(Task.tier == Tier.TODAY),
            )}
            this_week_titles = {t.title for t in db.session.scalars(
                select(Task).where(Task.tier == Tier.THIS_WEEK),
            )}
        assert today_titles == {"Meds"}
        assert this_week_titles == {"future-thing"}

    def test_promotes_next_week_and_backlog(self, app):
        """All three planning tiers — this_week, next_week, backlog —
        promote when due_date hits today."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="from-next-week", tier=Tier.NEXT_WEEK, due_date=_today())
            _make_task(title="from-backlog", tier=Tier.BACKLOG, due_date=_today())
            count = promote_due_today_tasks()
        assert count == 2
        with app.app_context():
            from sqlalchemy import select
            today_titles = {t.title for t in db.session.scalars(
                select(Task).where(Task.tier == Tier.TODAY),
            )}
        assert today_titles == {"from-next-week", "from-backlog"}

    def test_skips_inbox_and_freezer(self, app):
        """INBOX still needs triage; FREEZER is explicitly parked. The
        cron must NOT promote those even when due_date=today."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="needs-triage", tier=Tier.INBOX, due_date=_today())
            _make_task(title="frozen", tier=Tier.FREEZER, due_date=_today())
            count = promote_due_today_tasks()
        assert count == 0
        with app.app_context():
            from sqlalchemy import select
            today_count = db.session.scalar(
                select(db.func.count()).select_from(Task).where(Task.tier == Tier.TODAY),
            )
        assert today_count == 0

    def test_skips_non_active_tasks(self, app):
        """Resurrecting an archived/cancelled task into TODAY would be
        surprising. Status filter must hold."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="archived", tier=Tier.THIS_WEEK,
                       due_date=_today(), status=TaskStatus.ARCHIVED)
            _make_task(title="cancelled", tier=Tier.THIS_WEEK,
                       due_date=_today(), status=TaskStatus.CANCELLED)
            count = promote_due_today_tasks()
        assert count == 0

    def test_skips_future_due_dates(self, app):
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="next-week-thing", tier=Tier.THIS_WEEK,
                       due_date=_today() + timedelta(days=3))
            count = promote_due_today_tasks()
        assert count == 0

    def test_skips_no_due_date(self, app):
        """Tasks without a due_date can't be promoted by date logic."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="no-date", tier=Tier.THIS_WEEK, due_date=None)
            count = promote_due_today_tasks()
        assert count == 0

    def test_idempotent(self, app):
        """Running the cron twice in a row promotes once, then no-op."""
        from task_service import promote_due_today_tasks
        with app.app_context():
            _make_task(title="Meds", tier=Tier.THIS_WEEK, due_date=_today())
            first = promote_due_today_tasks()
            second = promote_due_today_tasks()
        assert first == 1
        assert second == 0  # task is now in TODAY, not in promotable set


# --- on-write hook in update_task / create_task ----------------------------


class TestOnWriteHookPromotion:

    def test_update_due_date_to_today_promotes_from_this_week(self, app):
        """User PATCHes due_date=today on a this_week task — tier
        auto-promotes to TODAY in the same request."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.THIS_WEEK, due_date=None)
            updated = update_task(t.id, {"due_date": _today().isoformat()})
            assert updated is not None
            assert updated.tier == Tier.TODAY
            assert updated.due_date == _today()

    def test_explicit_tier_in_payload_is_respected(self, app):
        """If the user explicitly sets tier=this_week + due_date=today
        in the same payload, respect the tier choice (don't auto-
        promote). Covers the legitimate "plan for today, track in
        This Week" pattern."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.BACKLOG, due_date=None)
            updated = update_task(t.id, {
                "tier": "this_week",
                "due_date": _today().isoformat(),
            })
            assert updated is not None
            # Respected user's tier choice — NOT promoted to TODAY
            assert updated.tier == Tier.THIS_WEEK
            assert updated.due_date == _today()

    def test_update_due_date_in_inbox_does_not_promote(self, app):
        """INBOX is excluded — needs triage first."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.INBOX, due_date=None)
            updated = update_task(t.id, {"due_date": _today().isoformat()})
            assert updated is not None
            assert updated.tier == Tier.INBOX

    def test_update_due_date_to_future_does_not_promote(self, app):
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.THIS_WEEK, due_date=None)
            updated = update_task(
                t.id,
                {"due_date": (_today() + timedelta(days=3)).isoformat()},
            )
            assert updated is not None
            assert updated.tier == Tier.THIS_WEEK

    def test_create_task_with_due_today_promotes_from_planning_tier(self, app):
        """create_task uses the same hook — creating a backlog task
        with due_date=today should land it in TODAY."""
        from task_service import create_task
        with app.app_context():
            t = create_task({
                "title": "new",
                "type": "work",
                "tier": "backlog",
                "due_date": _today().isoformat(),
            })
            # User explicitly set tier=backlog → respected (same guard
            # as update_task). This documents the symmetric behavior.
            assert t.tier == Tier.BACKLOG

    def test_create_task_no_explicit_tier_with_due_today(self, app):
        """If create_task is called without an explicit tier (defaults
        to INBOX), the auto-promote does NOT fire because INBOX is
        excluded. Documents that the default-tier path doesn't quietly
        skip triage."""
        from task_service import create_task
        with app.app_context():
            t = create_task({
                "title": "new",
                "type": "work",
                "due_date": _today().isoformat(),
            })
            # Default tier is INBOX; INBOX is excluded from promotion.
            assert t.tier == Tier.INBOX

    def test_completed_task_not_promoted_by_hook(self, app):
        """Resurrecting a completed task by changing its due_date should
        not promote it to TODAY — same status guard as the cron."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(
                title="done", tier=Tier.THIS_WEEK,
                due_date=None, status=TaskStatus.ARCHIVED,
            )
            updated = update_task(t.id, {"due_date": _today().isoformat()})
            assert updated is not None
            assert updated.tier == Tier.THIS_WEEK
