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


# --- #220: tier-punt clears stale due_date ---------------------------------


class TestTierPuntClearsStaleDueDate:
    """#220 (2026-05-24): when user moves a task to NEXT_WEEK via the
    tier button on the home board, clear the stale due_date so the
    task moves off the today/yesterday cell on /calendar and lands in
    Unscheduled. User-reported: "I moved all Sunday tasks to next week
    and it still shows today on the calendar — immediate reflection
    is not working." The fix is in `update_task` right after `tier` is
    parsed: if tier changed TO NEXT_WEEK, no due_date in payload, and
    task had a due_date, clear it.
    """

    def test_today_tier_to_next_week_clears_today_due_date(self, app):
        """The user-reported scenario: tier=TODAY + due_date=today →
        PATCH {tier: next_week} → due_date cleared."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="punt me", tier=Tier.TODAY, due_date=_today())
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date is None

    def test_tomorrow_tier_to_next_week_clears_due_date(self, app):
        """Same punt from TOMORROW tier."""
        from task_service import update_task
        with app.app_context():
            tomorrow = _today() + timedelta(days=1)
            t = _make_task(title="punt me", tier=Tier.TOMORROW, due_date=tomorrow)
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date is None

    def test_this_week_tier_to_next_week_clears_due_date(self, app):
        """Punt from THIS_WEEK with a mid-week date → clear; user is
        moving the task off the current week."""
        from task_service import update_task
        with app.app_context():
            wednesday = _today() + timedelta(days=2)  # something in-week
            t = _make_task(title="punt me", tier=Tier.THIS_WEEK, due_date=wednesday)
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date is None

    def test_overdue_today_tier_to_next_week_clears_due_date(self, app):
        """An overdue today task being punted → clear the past date."""
        from task_service import update_task
        with app.app_context():
            week_ago = _today() - timedelta(days=7)
            t = _make_task(title="punt me", tier=Tier.TODAY, due_date=week_ago)
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date is None

    def test_no_due_date_no_change(self, app):
        """If task had no due_date, hook is a no-op."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="dateless", tier=Tier.TODAY, due_date=None)
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date is None

    def test_explicit_due_date_in_payload_wins(self, app):
        """If user explicitly sets BOTH tier=next_week AND due_date in
        the same payload, the explicit due_date wins — do NOT clear."""
        from task_service import update_task
        with app.app_context():
            next_friday = _today() + timedelta(days=12)
            t = _make_task(title="schedule me", tier=Tier.TODAY, due_date=_today())
            updated = update_task(t.id, {
                "tier": "next_week",
                "due_date": next_friday.isoformat(),
            })
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date == next_friday

    def test_tier_already_next_week_no_change(self, app):
        """If tier was ALREADY next_week and PATCH re-saves it (e.g.
        the panel re-emitted tier as part of a reorder), the existing
        due_date must be preserved."""
        from task_service import update_task
        with app.app_context():
            next_tuesday = _today() + timedelta(days=8)
            t = _make_task(title="already there", tier=Tier.NEXT_WEEK, due_date=next_tuesday)
            updated = update_task(t.id, {"tier": "next_week"})
            assert updated is not None
            assert updated.tier == Tier.NEXT_WEEK
            assert updated.due_date == next_tuesday

    def test_punt_to_this_week_does_NOT_clear(self, app):
        """Scope: hook only fires for tier→NEXT_WEEK. Tier→THIS_WEEK
        is a different mental model (re-schedule within the week)
        and should preserve the date as a reminder."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="re-tier", tier=Tier.TODAY, due_date=_today())
            updated = update_task(t.id, {"tier": "this_week"})
            assert updated is not None
            assert updated.tier == Tier.THIS_WEEK
            assert updated.due_date == _today()

    def test_punt_to_backlog_does_NOT_clear(self, app):
        """Scope: hook only fires for tier→NEXT_WEEK. BACKLOG keeps
        the date so the user can see "this was originally due X"."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="park", tier=Tier.TODAY, due_date=_today())
            updated = update_task(t.id, {"tier": "backlog"})
            assert updated is not None
            assert updated.tier == Tier.BACKLOG
            assert updated.due_date == _today()


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

    def test_update_due_date_in_inbox_now_promotes_under_74(self, app):
        """#74 (2026-04-26): semantics changed — INBOX with due_date=today
        now auto-routes to TODAY. Was previously skipped (#46 era). Per
        scoping decision (b) "always overwrite"."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.INBOX, due_date=None)
            updated = update_task(t.id, {"due_date": _today().isoformat()})
            assert updated is not None
            assert updated.tier == Tier.TODAY

    def test_update_due_date_to_future_routes_to_appropriate_tier(self, app):
        """#74: future date routes to THIS_WEEK / NEXT_WEEK / BACKLOG
        based on the date — not just promote-to-today. The exact bucket
        depends on day-of-week; assert the date is consistent with the
        chosen tier."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="thing", tier=Tier.TODAY, due_date=None)
            updated = update_task(
                t.id,
                {"due_date": (_today() + timedelta(days=20)).isoformat()},
            )
            assert updated is not None
            # 20 days out is past next week — should land in BACKLOG.
            assert updated.tier == Tier.BACKLOG

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

    def test_create_task_no_explicit_tier_with_due_today_now_promotes(self, app):
        """#74: changed from #46. Default tier is INBOX, but now the
        date-routing hook promotes to TODAY since INBOX no longer guards
        against the auto-route."""
        from task_service import create_task
        with app.app_context():
            t = create_task({
                "title": "new",
                "type": "work",
                "due_date": _today().isoformat(),
            })
            assert t.tier == Tier.TODAY

    def test_freezer_task_not_routed_by_due_date(self, app):
        """#74: FREEZER is the only tier that survives an auto-route.
        User explicitly parked it; treat the date as a reminder."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(title="frozen", tier=Tier.FREEZER, due_date=None)
            updated = update_task(t.id, {"due_date": _today().isoformat()})
            assert updated is not None
            assert updated.tier == Tier.FREEZER

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


class TestTierForDueDate:
    """#218 (2026-05-24): Mon-Sun ISO-week boundary tests for
    `_tier_for_due_date`. Mirrors the Jest tests in
    `tests/js/unit/tier_helpers.test.js` so the server-side authoritative
    decision and the client-side preview agree on every boundary day.

    Was Mon-Sat under #72 — a Sunday due_date orphaned to BACKLOG (the
    user-reported #218 bug). These tests lock in the Sun-in-this_week
    / Sun-in-next_week classifications so a future refactor can't
    quietly regress to the old behavior.

    Each test monkey-patches `_local_today_date` to a known weekday so
    the boundary math is reproducible regardless of the wall-clock day
    the test suite runs on.
    """

    def _patch_today(self, monkeypatch, target_date):
        from utils import local_today_date  # noqa: F401  for the symbol
        # _tier_for_due_date imports as `_local_today_date` alias
        monkeypatch.setattr(
            "task_service._local_today_date",
            lambda: target_date,
        )

    def test_today_returns_today_tier(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 6)) == Tier.TODAY

    def test_tomorrow_returns_tomorrow_tier(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 7)) == Tier.TOMORROW

    def test_this_monday_is_this_week_left_boundary(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 4)) == Tier.THIS_WEEK

    def test_this_sunday_is_this_week_right_boundary(self, app, monkeypatch):
        """#218 fix: was BACKLOG under #72 Mon-Sat — the user's exact bug."""
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 10)) == Tier.THIS_WEEK

    def test_next_monday_is_next_week_left_boundary(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 11)) == Tier.NEXT_WEEK

    def test_next_sunday_is_next_week_right_boundary(self, app, monkeypatch):
        """#218 fix: was BACKLOG under #72."""
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 17)) == Tier.NEXT_WEEK

    def test_two_weeks_out_is_backlog(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            # 5/18 is next-next Monday — outside both Mon-Sun windows.
            assert _tier_for_due_date(date(2026, 5, 18)) == Tier.BACKLOG

    def test_past_date_before_this_monday_is_backlog(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 6))  # Wed
            assert _tier_for_due_date(date(2026, 5, 1)) == Tier.BACKLOG  # Fri prior

    # --- Sunday-today edge (the user's exact reporting state) -----------

    def test_sunday_today_sunday_due_date_is_today_tier(self, app, monkeypatch):
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 10))  # Sun
            assert _tier_for_due_date(date(2026, 5, 10)) == Tier.TODAY

    def test_sunday_today_saturday_due_date_is_this_week(self, app, monkeypatch):
        """Yesterday (Sat) on a Sunday today → this_week (includes today)."""
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 10))  # Sun
            assert _tier_for_due_date(date(2026, 5, 9)) == Tier.THIS_WEEK

    def test_sunday_today_next_monday_is_tomorrow(self, app, monkeypatch):
        """today/tomorrow shortcut wins over next_week range."""
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 10))  # Sun
            assert _tier_for_due_date(date(2026, 5, 11)) == Tier.TOMORROW

    def test_sunday_today_next_sunday_is_next_week(self, app, monkeypatch):
        """#218 critical case: user on a Sunday + due_date set to next
        Sunday must NOT be BACKLOG. Under #72 Mon-Sat this returned
        BACKLOG because Sundays were outside every week range."""
        from task_service import _tier_for_due_date
        with app.app_context():
            self._patch_today(monkeypatch, date(2026, 5, 10))  # Sun
            assert _tier_for_due_date(date(2026, 5, 17)) == Tier.NEXT_WEEK


class TestRealignTiersWithDueDates:
    """#108 (PR43): nightly tier-vs-due-date realignment cron.

    Bug: tasks set days ago land in THIS_WEEK because that was the
    correct bucket at the time. Calendar advances; the bucket changes
    but the row doesn't update. This cron re-runs _tier_for_due_date
    for every active non-frozen non-inbox task with a due_date and
    corrects drift.
    """

    def test_drifted_this_week_task_with_due_tomorrow_moves_to_tomorrow(
        self, app
    ):
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Drifted into tomorrow",
                type=TaskType.WORK,
                tier=Tier.THIS_WEEK,  # was correct N days ago
                status=TaskStatus.ACTIVE,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            updated = realign_tiers_with_due_dates()
            assert updated >= 1
            db.session.expire_all()  # cross-session: invalidate identity map
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.TOMORROW

    def test_freezer_tasks_are_left_alone(self, app):
        """User explicitly parked it; date is just a reminder."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Frozen w/ tomorrow date",
                type=TaskType.WORK,
                tier=Tier.FREEZER,
                status=TaskStatus.ACTIVE,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.FREEZER

    def test_inbox_tasks_are_left_alone(self, app):
        """Still need triage; auto-route would skip the user's review."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Inbox w/ tomorrow date",
                type=TaskType.WORK,
                tier=Tier.INBOX,
                status=TaskStatus.ACTIVE,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.INBOX

    def test_archived_tasks_are_left_alone(self, app):
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Archived",
                type=TaskType.WORK,
                tier=Tier.THIS_WEEK,
                status=TaskStatus.ARCHIVED,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.THIS_WEEK

    def test_idempotent(self, app):
        """Re-run is a no-op when everything's in sync."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Already correct", type=TaskType.WORK,
                tier=Tier.TOMORROW, status=TaskStatus.ACTIVE,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            realign_tiers_with_due_dates()
            second = realign_tiers_with_due_dates()
            # First might pick up other drifted rows from prior tests in same session
            # (test ordering quirk); second must be 0.
            assert second == 0

    def test_admin_endpoint_requires_token(self, client):
        """POST without a debug token = 302/401/403/405."""
        resp = client.post("/api/debug/realign-tiers")
        assert resp.status_code in (302, 401, 403, 405)


class TestRealignPreservesOverdueToday:
    """#170 (PR 3, 2026-05-21): the 00:03 realign cron must NOT demote a
    TODAY task with a past due_date. `_tier_for_due_date` maps a past
    date to THIS_WEEK or BACKLOG, so without the guard the cron
    silently moved "I didn't finish this yesterday" tasks off the
    Today panel overnight with no notification. Inverse of #108 — that
    fix corrects genuine drift; this preserves a deliberate placement.
    """

    def test_overdue_today_task_stays_in_today(self, app):
        """due_date 7 days ago, tier=TODAY → realign leaves it alone.

        Without the #170 guard `_tier_for_due_date` would return
        BACKLOG (a date a week back is outside this/next Mon-Sun) and
        the task would silently leave the Today panel."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            week_ago = _local_today_date() - timedelta(days=7)
            t = Task(
                title="Overdue, kept in Today as a nag",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                status=TaskStatus.ACTIVE,
                due_date=week_ago,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.TODAY

    def test_recently_overdue_today_task_still_within_this_week_stays_in_today(
        self, app
    ):
        """due_date 2 days ago (still inside this Mon-Sun) → without the
        guard `_tier_for_due_date` returns THIS_WEEK; with it the task
        stays in TODAY. Covers the other branch of the past-date map."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            two_days_ago = _local_today_date() - timedelta(days=2)
            t = Task(
                title="Recently overdue, kept in Today",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                status=TaskStatus.ACTIVE,
                due_date=two_days_ago,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.TODAY

    def test_on_day_today_task_stays_in_today(self, app):
        """due_date == today, tier=TODAY → already correct, no change.
        Confirms the guard doesn't accidentally break the happy path."""
        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            today = _local_today_date()
            t = Task(
                title="Due today, in Today",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                status=TaskStatus.ACTIVE,
                due_date=today,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.TODAY

    def test_future_dated_today_task_still_realigns(self, app):
        """due_date == tomorrow, tier=TODAY → the #170 guard only
        protects PAST dates. A TODAY task whose date drifted to the
        future is genuine drift and must still re-route to TOMORROW."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            tomorrow = _local_today_date() + timedelta(days=1)
            t = Task(
                title="Future-dated, in Today by mistake",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                status=TaskStatus.ACTIVE,
                due_date=tomorrow,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.TOMORROW

    def test_overdue_non_today_task_still_realigns(self, app):
        """The #170 guard is scoped to tier==TODAY only. A THIS_WEEK
        task with a past due_date is genuine drift and must still move
        to BACKLOG — the guard must not over-reach to other tiers."""
        from datetime import timedelta

        from models import Task, TaskStatus, TaskType, Tier, db
        from task_service import _local_today_date, realign_tiers_with_due_dates
        with app.app_context():
            long_ago = _local_today_date() - timedelta(days=30)
            t = Task(
                title="Overdue This Week task",
                type=TaskType.WORK,
                tier=Tier.THIS_WEEK,
                status=TaskStatus.ACTIVE,
                due_date=long_ago,
            )
            db.session.add(t)
            db.session.commit()
            tid = t.id
            realign_tiers_with_due_dates()
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.BACKLOG
