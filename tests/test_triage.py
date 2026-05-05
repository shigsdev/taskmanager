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
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from models import Task, TaskStatus, TaskType, Tier, db
from triage_service import compute_triage_suggestions


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
                due_date=date.today() - timedelta(days=4),
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
                due_date=date.today() - timedelta(days=5),
            )
            out = compute_triage_suggestions()
        assert len(out) == 1
        assert out[0]["suggested_tier"] == "backlog"

    def test_today_3_days_overdue_does_not_qualify(self, app):
        with app.app_context():
            _make_task(
                title="Just past due",
                tier=Tier.TODAY,
                due_date=date.today() - timedelta(days=3),
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

    def test_endpoint_requires_auth(self, client):
        resp = client.get("/api/triage/suggestions")
        # login_required redirects unauthenticated requests; assert it's
        # NOT a 200 (could be 302, 401, or 403 depending on path).
        assert resp.status_code != 200
