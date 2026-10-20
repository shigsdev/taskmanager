"""Integration tests for #12 triage suggestions.

Tests the heuristic in ``triage_service.compute_triage_suggestions`` and
the ``GET /api/triage/suggestions`` endpoint contract.

Heuristic thresholds covered (one positive + one boundary-negative case
per branch — keeps the suite tight):

    INBOX        > 7 days  → move to BACKLOG
    TODAY        past due_date by > 3 days  → move to BACKLOG
    TOMORROW     past due_date by > 3 days  → move to BACKLOG
    THIS_WEEK    > 14 days no movement  → move to BACKLOG
    NEXT_WEEK    > 21 days no movement  → move to BACKLOG
    BACKLOG      > 90 days  → delete
    FREEZER      > 60 days  → delete

#511 refresh: dates use local_today_date() like the code (date.today()
broke under DIGEST_TZ=Europe/London and on the UTC CI runner 8pm-midnight
ET). The Tomorrow / Next Week branches are effectively unreachable in the
running app — the 00:01 roll moves Tomorrow to Today and the weekly
re-sort empties undated Next Week — so their tests write rows directly.
Behaviour gaps the refresh found (a far-future Backlog task offered for
delete, reorders and nightly jobs resetting "staleness", subtasks ignored)
are #514.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import auth
from models import Task, TaskStatus, TaskType, Tier, db
from triage_service import compute_triage_suggestions
from utils import local_today_date


def _make_task(*, title: str, tier: Tier, days_old: int = 0, due_date: date | None = None,
               status: TaskStatus = TaskStatus.ACTIVE, parent_id=None) -> Task:
    """Helper. ``days_old`` shifts both created_at and updated_at backwards
    by exactly that many LOCAL (DIGEST_TZ) days — so the triage-service's
    date math is deterministic regardless of what time-of-day the test
    runs at.

    The original implementation used ``datetime.now(UTC) - timedelta(days=N)``,
    which produced an updated_at whose UTC date was N days back but whose
    LOCAL date could be N-1 days back when the test ran during the early
    UTC morning (the local-vs-UTC date crossover). That made the
    `days_since_update > THRESHOLD` checks flake at that time of day.
    """
    from utils import local_today_date as _today
    when_date = _today() - timedelta(days=days_old)
    # Mid-day timestamp so it sits comfortably inside the local date,
    # not on a midnight boundary. Naive datetime — SQLite drops the tz
    # anyway, and the date() comparison ignores tzinfo.
    when = datetime.combine(when_date, datetime.min.time().replace(hour=12))
    task = Task(
        title=title,
        type=TaskType.WORK,
        tier=tier,
        status=status,
        due_date=due_date,
        parent_id=parent_id,
    )
    db.session.add(task)
    db.session.flush()  # need an id before manual timestamp override
    task.created_at = when
    task.updated_at = when
    db.session.commit()
    return task


class TestInboxHeuristic:
    def test_inbox_8_days_old_suggests_move_to_backlog(self, app):
        with app.app_context():
            _make_task(title="Stale inbox", tier=Tier.INBOX, days_old=8)
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["title"] == "Stale inbox"
        assert out[0]["suggested_action"] == "move"
        assert out[0]["suggested_tier"] == "backlog"
        assert "inbox" in out[0]["reason"].lower()

    def test_inbox_7_days_old_does_not_qualify(self, app):
        with app.app_context():
            _make_task(title="Borderline inbox", tier=Tier.INBOX, days_old=7)
            out = compute_triage_suggestions()
        assert out == []


class TestPastDueHeuristic:
    def test_today_4_days_overdue_suggests_move_to_backlog(self, app):
        with app.app_context():
            _make_task(
                title="Overdue today",
                tier=Tier.TODAY,
                due_date=local_today_date() - timedelta(days=4),
            )
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_action"] == "move"
        assert out[0]["suggested_tier"] == "backlog"
        assert "past due" in out[0]["reason"]

    def test_tomorrow_5_days_overdue_also_qualifies(self, app):
        with app.app_context():
            _make_task(
                title="Overdue tomorrow",
                tier=Tier.TOMORROW,
                due_date=local_today_date() - timedelta(days=5),
            )
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_tier"] == "backlog"

    def test_today_3_days_overdue_does_not_qualify(self, app):
        with app.app_context():
            _make_task(
                title="Just past due",
                tier=Tier.TODAY,
                due_date=local_today_date() - timedelta(days=3),
            )
            out = compute_triage_suggestions()
        assert out == []


class TestPlanningTierHeuristic:
    def test_this_week_15_days_old_suggests_move_to_backlog(self, app):
        with app.app_context():
            _make_task(title="Stuck this-week", tier=Tier.THIS_WEEK, days_old=15)
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_tier"] == "backlog"

    def test_next_week_22_days_old_suggests_move_to_backlog(self, app):
        with app.app_context():
            _make_task(title="Stuck next-week", tier=Tier.NEXT_WEEK, days_old=22)
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_tier"] == "backlog"


class TestDeleteHeuristic:
    def test_backlog_91_days_old_suggests_delete(self, app):
        with app.app_context():
            _make_task(title="Languishing", tier=Tier.BACKLOG, days_old=91)
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_action"] == "delete"
        assert out[0]["suggested_tier"] is None

    def test_freezer_61_days_old_suggests_delete(self, app):
        with app.app_context():
            _make_task(title="Frozen forever", tier=Tier.FREEZER, days_old=61)
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_action"] == "delete"

    def test_backlog_30_days_old_does_not_qualify(self, app):
        with app.app_context():
            _make_task(title="Recent backlog", tier=Tier.BACKLOG, days_old=30)
            out = compute_triage_suggestions()
        assert out == []


class TestExclusions:
    def test_deleted_task_is_excluded(self, app):
        with app.app_context():
            _make_task(
                title="Already deleted",
                tier=Tier.INBOX,
                days_old=30,
                status=TaskStatus.DELETED,
            )
            out = compute_triage_suggestions()
        assert out == []

    def test_subtask_is_excluded(self, app):
        # Subtasks ride along with their parent — they shouldn't generate
        # their own suggestions or the user gets duplicate noise.
        with app.app_context():
            parent = _make_task(title="Parent", tier=Tier.INBOX, days_old=30)
            _make_task(title="Subtask", tier=Tier.INBOX, days_old=30, parent_id=parent.id)
            out = compute_triage_suggestions()
        titles = [s["title"] for s in out]
        assert "Parent" in titles
        assert "Subtask" not in titles

    def test_empty_db_returns_empty_list(self, app):
        with app.app_context():
            out = compute_triage_suggestions()
        assert out == []


class TestSorting:
    def test_results_sorted_by_days_stale_descending(self, app):
        with app.app_context():
            _make_task(title="Mild", tier=Tier.INBOX, days_old=8)
            _make_task(title="Severe", tier=Tier.BACKLOG, days_old=120)
            _make_task(title="Medium", tier=Tier.THIS_WEEK, days_old=20)
            out = compute_triage_suggestions()
        assert [s["title"] for s in out] == ["Severe", "Medium", "Mild"]


class TestApiContract:
    def test_endpoint_returns_json_array(self, authed_client, app):
        with app.app_context():
            _make_task(title="Stale row", tier=Tier.INBOX, days_old=10)
        resp = authed_client.get("/api/triage/suggestions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body, list)
        assert len(body) == 1
        row = body[0]
        # Contract: each row has exactly these keys.
        assert set(row.keys()) == {
            "task_id", "title", "current_tier",
            "suggested_action", "suggested_tier", "reason", "days_stale",
        }

    def test_endpoint_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        assert client.get("/api/triage/suggestions").status_code == 401


class TestTZDriftFix178:
    """Audit fix #178 (2026-05-20): `task.updated_at.date()` returned the
    UTC component even though `today` was already in DIGEST_TZ. A task
    updated at 11pm ET (3am UTC next day) bucketed as updated-tomorrow-UTC
    → ``days_since_update = -1`` → no threshold could ever trigger.
    """

    def test_late_evening_eastern_update_buckets_as_local_date(
        self, app, monkeypatch
    ):
        """11pm ET on day X (= 3am UTC day X+1) must bucket as day X
        when staleness is computed against ``today_local``."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        # Pin "today" to a fixed date so the test isn't time-sensitive.
        # Use a date 8 days after the update → expects "stale inbox".
        monkeypatch.setattr(
            "triage_service.local_today_date", lambda: date(2026, 5, 28)
        )
        with app.app_context():
            task = Task(
                title="LateNight inbox",
                type=TaskType.WORK,
                tier=Tier.INBOX,
                status=TaskStatus.ACTIVE,
            )
            db.session.add(task)
            db.session.flush()
            # 3am UTC on May 21 = 11pm ET on May 20 (during EDT, UTC-4).
            # Pre-fix: `.date()` returned 2026-05-21 → days_since_update
            # = 7 → does NOT trigger > 7 threshold.
            # Post-fix: local-TZ date = 2026-05-20 → days_since_update
            # = 8 → triggers the stale-inbox suggestion.
            task.updated_at = datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
            db.session.commit()
            out = compute_triage_suggestions()

        titles = [s["title"] for s in out]
        assert "LateNight inbox" in titles
        # Find the suggestion for our task and assert the staleness count.
        ours = next(s for s in out if s["title"] == "LateNight inbox")
        assert ours["days_stale"] == 8
        assert ours["suggested_action"] == "move"
        assert ours["suggested_tier"] == "backlog"

    def test_borderline_late_evening_update_does_not_qualify(
        self, app, monkeypatch
    ):
        """Same TZ scenario but at the exact 7-day boundary — still
        not stale. Ensures we didn't accidentally over-shift."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        monkeypatch.setattr(
            "triage_service.local_today_date", lambda: date(2026, 5, 27)
        )
        with app.app_context():
            task = Task(
                title="Borderline late",
                type=TaskType.WORK,
                tier=Tier.INBOX,
                status=TaskStatus.ACTIVE,
            )
            db.session.add(task)
            db.session.flush()
            # 11pm ET May 20 = 3am UTC May 21. Local date is May 20.
            # May 27 - May 20 = 7 days. Threshold is > 7. Does NOT qualify.
            task.updated_at = datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
            db.session.commit()
            out = compute_triage_suggestions()

        assert all(s["title"] != "Borderline late" for s in out)


# --- #511: gaps the refresh found ---------------------------------------------


class TestOnlyOpenDatedWork:

    @pytest.mark.parametrize("status", [
        TaskStatus.ARCHIVED, TaskStatus.CANCELLED, TaskStatus.DELETED,
    ])
    def test_finished_or_binned_tasks_are_never_suggested(self, app, status):
        with app.app_context():
            _make_task(title="old", tier=Tier.INBOX, days_old=30, status=status)
            assert compute_triage_suggestions() == []

    def test_an_undated_today_task_is_not_past_due(self, app):
        with app.app_context():
            _make_task(title="no date", tier=Tier.TODAY, days_old=100)
            assert compute_triage_suggestions() == []


class TestApplyingASuggestion:
    """What the /review triage panel does with a "move to Backlog" row."""

    def test_moving_an_overdue_task_to_backlog_sticks(self, app, authed_client):
        from task_service import realign_tiers_with_due_dates

        with app.app_context():
            t = _make_task(title="overdue", tier=Tier.TODAY,
                           due_date=local_today_date() - timedelta(days=5))
            t_id = str(t.id)
        (row,) = authed_client.get("/api/triage/suggestions").get_json()
        assert (row["task_id"], row["suggested_tier"]) == (t_id, "backlog")

        resp = authed_client.patch(f"/api/tasks/{t_id}", json={"tier": "backlog"})
        assert resp.status_code == 200
        # #466: a date that doesn't fit Backlog is dropped, so the nightly
        # re-sort can't pull it straight back out.
        assert resp.get_json()["due_date"] is None
        with app.app_context():
            realign_tiers_with_due_dates()
            assert db.session.get(Task, t.id).tier == Tier.BACKLOG
        assert authed_client.get("/api/triage/suggestions").get_json() == []
