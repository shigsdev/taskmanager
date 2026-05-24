"""Tests for the /api/utilities/* endpoints (#222, 2026-05-24).

OAuth-gated UI wrappers over the same backfill logic exposed via
admin-token-gated /api/debug/backfill/clear-stale-next-week-due-dates.
This test file covers the route registration, auth, and the
count/run pair against a known DB state.
"""
from __future__ import annotations

from datetime import timedelta

from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


def _today():
    from utils import local_today_date
    return local_today_date()


class TestUtilitiesAuth:
    """Both endpoints require OAuth — anonymous requests must be
    rejected (the single-user AUTHORIZED_EMAIL gate). The admin-token
    SPLIT used by /api/debug/backfill/* does NOT apply here because
    these are surfaced through the UI to the OAuth'd owner."""

    def test_count_endpoint_requires_auth(self, client):
        resp = client.get("/api/utilities/clear-stale-next-week-due-dates/count")
        assert resp.status_code in (302, 401, 403)

    def test_run_endpoint_requires_auth(self, client):
        resp = client.post("/api/utilities/clear-stale-next-week-due-dates")
        assert resp.status_code in (302, 401, 403)

    def test_run_endpoint_rejects_GET(self, client):
        # Mutating routes must NEVER accept GET — same #190 / #185 rule.
        resp = client.get("/api/utilities/clear-stale-next-week-due-dates")
        assert resp.status_code in (302, 401, 403, 404, 405)


class TestClearStaleNextWeekDueDates:
    """Behavior pair: count returns the number of would-be-cleared
    tasks (preview, no mutation); POST clears them and returns the
    same number."""

    def test_count_returns_zero_when_clean(self, app, authed_client):
        with app.app_context():
            # A clean DB state — only a future-dated next_week task
            # which is correctly placed and shouldn't count.
            next_tue = _today() + timedelta(days=8)
            _make_task(title="ok", tier=Tier.NEXT_WEEK, due_date=next_tue)
        resp = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"count": 0}

    def test_count_includes_today_and_past_dated_next_week(
        self, app, authed_client
    ):
        with app.app_context():
            today = _today()
            week_ago = today - timedelta(days=7)
            next_tue = today + timedelta(days=8)
            _make_task(title="today", tier=Tier.NEXT_WEEK, due_date=today)
            _make_task(title="past", tier=Tier.NEXT_WEEK, due_date=week_ago)
            _make_task(title="future-ok", tier=Tier.NEXT_WEEK, due_date=next_tue)
        resp = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp.status_code == 200
        # 2 stuck (today + week_ago), 1 future preserved.
        assert resp.get_json() == {"count": 2}

    def test_count_is_readonly(self, app, authed_client):
        """Calling count twice MUST NOT mutate — the user previews
        before running."""
        with app.app_context():
            _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
        resp1 = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        resp2 = authed_client.get(
            "/api/utilities/clear-stale-next-week-due-dates/count"
        )
        assert resp1.get_json() == {"count": 1}
        assert resp2.get_json() == {"count": 1}

    def test_run_clears_stuck_tasks(self, app, authed_client):
        with app.app_context():
            t = _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
            tid = t.id
        resp = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"updated": 1}
        with app.app_context():
            db.session.expire_all()
            t2 = db.session.get(Task, tid)
            assert t2.tier == Tier.NEXT_WEEK
            assert t2.due_date is None

    def test_run_is_idempotent(self, app, authed_client):
        """Re-running after clean returns updated: 0."""
        with app.app_context():
            _make_task(title="stuck", tier=Tier.NEXT_WEEK, due_date=_today())
        first = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        second = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert first.get_json() == {"updated": 1}
        assert second.get_json() == {"updated": 0}

    def test_run_leaves_non_active_alone(self, app, authed_client):
        with app.app_context():
            today = _today()
            _make_task(
                title="archived", tier=Tier.NEXT_WEEK,
                due_date=today, status=TaskStatus.ARCHIVED,
            )
        resp = authed_client.post(
            "/api/utilities/clear-stale-next-week-due-dates"
        )
        assert resp.get_json() == {"updated": 0}


class TestUtilitiesPageRenders:
    """The /utilities page itself must render under OAuth without
    console errors — covered mechanically by tests/e2e/ui_audit.spec.js
    (route in ROUTES) AND server-side here."""

    def test_page_renders_under_oauth(self, authed_client):
        resp = authed_client.get("/utilities")
        assert resp.status_code == 200
        # Cheap content assertion — the page should at least mention
        # the only utility currently shipped.
        body = resp.get_data(as_text=True)
        assert "Utilities" in body
        assert "clear-stale-next-week-due-dates" in body

    def test_page_requires_auth(self, client):
        resp = client.get("/utilities")
        assert resp.status_code in (302, 401, 403)
