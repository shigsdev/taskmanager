"""Integration tests for recurring tasks.

Recurring tasks are *templates* — they define tasks that should be
auto-created on certain days. This is different from regular tasks:

- **RecurringTask** = the template (e.g., "Walk" every day)
- **Task** = the actual item that appears in Today tier on a given day

Key concepts tested:
- CRUD for recurring templates via /api/recurring
- Seeding system defaults (morning/evening routines, day-specific tasks)
- Spawning: creating real Tasks from templates based on today's day
- Frequency types: daily, weekdays, weekly/day_of_week, monthly_date,
  monthly_nth_weekday
- Soft-disable: deactivating a template so it stops spawning
- Full-detail inheritance on spawn (notes, checklist, goal, url)
"""
from __future__ import annotations

from datetime import date

from models import RecurringFrequency, RecurringTask, TaskType, db


def _make_recurring(**overrides) -> RecurringTask:
    """Helper to create a recurring task template in the database."""
    fields = {
        "title": "Test recurring",
        "frequency": RecurringFrequency.DAILY,
        "type": TaskType.WORK,
    }
    fields.update(overrides)
    rt = RecurringTask(**fields)
    db.session.add(rt)
    db.session.commit()
    return rt


# --- CRUD via API -------------------------------------------------------------


class TestRecurringCreate:
    """Verify creating recurring task templates via the API."""

    def test_create_daily_recurring(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "Daily standup", "frequency": "daily", "type": "work"},
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["title"] == "Daily standup"
        assert body["frequency"] == "daily"
        assert body["is_active"] is True

    def test_create_day_of_week_recurring(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Monday meeting",
                "frequency": "day_of_week",
                "type": "work",
                "day_of_week": 0,
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["frequency"] == "day_of_week"
        assert body["day_of_week"] == 0

    def test_create_weekly_recurring(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Weekly review",
                "frequency": "weekly",
                "type": "personal",
                "day_of_week": 4,
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["frequency"] == "weekly"

    def test_create_missing_title_422(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"frequency": "daily", "type": "work"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "title"

    def test_create_missing_frequency_422(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "No freq", "type": "work"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "frequency"

    def test_create_missing_type_422(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "No type", "frequency": "daily"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "type"

    def test_create_weekly_missing_day_422(self, authed_client):
        """Weekly/day_of_week frequency requires day_of_week field."""
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "No day", "frequency": "weekly", "type": "work"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "day_of_week"

    def test_create_day_of_week_out_of_range_422(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Bad day",
                "frequency": "day_of_week",
                "type": "work",
                "day_of_week": 9,
            },
        )
        assert resp.status_code == 422

    def test_create_no_json_400(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400


class TestRecurringList:
    """Verify listing recurring templates."""

    def test_list_returns_active_only_by_default(self, authed_client, app):
        with app.app_context():
            _make_recurring(title="Active one")
            _make_recurring(title="Disabled one", is_active=False)

        resp = authed_client.get("/api/recurring")
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.get_json()]
        assert "Active one" in titles
        assert "Disabled one" not in titles

    def test_list_all_includes_inactive(self, authed_client, app):
        with app.app_context():
            _make_recurring(title="Active")
            _make_recurring(title="Inactive", is_active=False)

        resp = authed_client.get("/api/recurring?all=1")
        titles = [r["title"] for r in resp.get_json()]
        assert "Active" in titles
        assert "Inactive" in titles


class TestRecurringShow:
    """Verify getting a single recurring template."""

    def test_show_existing(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring(title="Show me")
            rt_id = str(rt.id)

        resp = authed_client.get(f"/api/recurring/{rt_id}")
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "Show me"

    def test_show_not_found_404(self, authed_client):
        import uuid

        fake_id = str(uuid.uuid4())
        resp = authed_client.get(f"/api/recurring/{fake_id}")
        assert resp.status_code == 404


class TestRecurringUpdate:
    """Verify updating recurring templates."""

    def test_update_title(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring(title="Old title")
            rt_id = str(rt.id)

        resp = authed_client.patch(
            f"/api/recurring/{rt_id}", json={"title": "New title"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "New title"

    def test_update_frequency(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring(frequency=RecurringFrequency.DAILY)
            rt_id = str(rt.id)

        resp = authed_client.patch(
            f"/api/recurring/{rt_id}",
            json={"frequency": "day_of_week", "day_of_week": 3},
        )
        assert resp.status_code == 200
        assert resp.get_json()["frequency"] == "day_of_week"
        assert resp.get_json()["day_of_week"] == 3

    def test_disable_template(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring(title="Disable me")
            rt_id = str(rt.id)

        resp = authed_client.patch(
            f"/api/recurring/{rt_id}", json={"is_active": False}
        )
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False

    def test_update_empty_title_422(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring()
            rt_id = str(rt.id)

        resp = authed_client.patch(
            f"/api/recurring/{rt_id}", json={"title": ""}
        )
        assert resp.status_code == 422

    def test_update_not_found_404(self, authed_client):
        import uuid

        fake_id = str(uuid.uuid4())
        resp = authed_client.patch(
            f"/api/recurring/{fake_id}", json={"title": "X"}
        )
        assert resp.status_code == 404


class TestRecurringDelete:
    """Verify soft-deleting (disabling) recurring templates."""

    def test_delete_sets_inactive(self, authed_client, app):
        with app.app_context():
            rt = _make_recurring(title="Delete me")
            rt_id = str(rt.id)

        resp = authed_client.delete(f"/api/recurring/{rt_id}")
        assert resp.status_code == 204

        # Should no longer appear in active list
        resp = authed_client.get("/api/recurring")
        titles = [r["title"] for r in resp.get_json()]
        assert "Delete me" not in titles

    def test_delete_not_found_404(self, authed_client):
        import uuid

        fake_id = str(uuid.uuid4())
        resp = authed_client.delete(f"/api/recurring/{fake_id}")
        assert resp.status_code == 404


# --- Seed defaults ------------------------------------------------------------


class TestSeedDefaults:
    """Verify seeding system default recurring tasks.

    The seed endpoint creates the pre-configured recurring templates
    from the spec (morning routine, evening routine, day-specific tasks).
    """

    def test_seed_creates_defaults(self, authed_client):
        resp = authed_client.post("/api/recurring/seed")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["created"] >= 10  # spec has 16 defaults
        titles = [r["title"] for r in body["items"]]
        assert "Walk" in titles
        assert "Meditate" in titles
        assert "Read 10 min" in titles

    def test_seed_idempotent(self, authed_client):
        """Calling seed twice should not create duplicates."""
        authed_client.post("/api/recurring/seed")
        resp = authed_client.post("/api/recurring/seed")
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 0

    def test_seed_includes_day_specific(self, authed_client):
        resp = authed_client.post("/api/recurring/seed")
        items = resp.get_json()["items"]
        monday_items = [r for r in items if r["day_of_week"] == 0]
        assert len(monday_items) >= 1  # "Agenda for working group meeting"


# --- Spawn logic --------------------------------------------------------------


class TestSpawnTasks:
    """Verify spawning actual tasks from recurring templates.

    'Spawning' means creating real Task records in the Today tier
    based on which recurring templates match today's day of the week.
    """

    def test_spawn_daily_creates_task(self, authed_client, app):
        with app.app_context():
            _make_recurring(title="Daily spawn", frequency=RecurringFrequency.DAILY)

        resp = authed_client.post("/api/recurring/spawn")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["spawned"] >= 1
        spawned_titles = [t["title"] for t in body["tasks"]]
        assert "Daily spawn" in spawned_titles

    def test_spawned_task_in_today_tier(self, authed_client, app):
        with app.app_context():
            _make_recurring(title="Goes to Today", frequency=RecurringFrequency.DAILY)

        resp = authed_client.post("/api/recurring/spawn")
        for t in resp.get_json()["tasks"]:
            assert t["tier"] == "today"

    def test_spawn_day_of_week_matching(self, authed_client, app):
        """A day_of_week template should only spawn if today matches."""
        today_dow = date.today().weekday()
        with app.app_context():
            _make_recurring(
                title="Today's DOW",
                frequency=RecurringFrequency.DAY_OF_WEEK,
                day_of_week=today_dow,
            )

        resp = authed_client.post("/api/recurring/spawn")
        titles = [t["title"] for t in resp.get_json()["tasks"]]
        assert "Today's DOW" in titles

    def test_spawn_day_of_week_non_matching(self, authed_client, app):
        """A day_of_week template for a different day should NOT spawn."""
        today_dow = date.today().weekday()
        other_dow = (today_dow + 3) % 7  # pick a different day
        with app.app_context():
            _make_recurring(
                title="Wrong day",
                frequency=RecurringFrequency.DAY_OF_WEEK,
                day_of_week=other_dow,
            )

        resp = authed_client.post("/api/recurring/spawn")
        titles = [t["title"] for t in resp.get_json()["tasks"]]
        assert "Wrong day" not in titles

    def test_spawn_skips_inactive_templates(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="Disabled",
                frequency=RecurringFrequency.DAILY,
                is_active=False,
            )

        resp = authed_client.post("/api/recurring/spawn")
        titles = [t["title"] for t in resp.get_json()["tasks"]]
        assert "Disabled" not in titles

    def test_spawn_creates_real_tasks_in_db(self, authed_client, app):
        """Spawned tasks should be real Task records visible via the tasks API."""
        with app.app_context():
            _make_recurring(title="Real task", frequency=RecurringFrequency.DAILY)

        authed_client.post("/api/recurring/spawn")

        resp = authed_client.get("/api/tasks?tier=today")
        titles = [t["title"] for t in resp.get_json()]
        assert "Real task" in titles

    def test_spawn_empty_when_no_templates(self, authed_client):
        resp = authed_client.post("/api/recurring/spawn")
        assert resp.status_code == 201
        assert resp.get_json()["spawned"] == 0

    def test_spawn_idempotent_no_duplicates(self, authed_client, app):
        """Calling spawn twice should not create duplicate tasks."""
        with app.app_context():
            _make_recurring(title="Idempotent test", frequency=RecurringFrequency.DAILY)

        resp1 = authed_client.post("/api/recurring/spawn")
        assert resp1.status_code == 201
        count1 = resp1.get_json()["spawned"]
        assert count1 >= 1

        # Second spawn should create 0 new tasks for the same title
        resp2 = authed_client.post("/api/recurring/spawn")
        assert resp2.status_code == 201
        titles = [t["title"] for t in resp2.get_json()["tasks"]]
        assert "Idempotent test" not in titles


# --- Blueprint registration --------------------------------------------------


class TestRecurringBlueprint:
    """Verify the recurring_api blueprint is registered."""

    def test_blueprint_registered(self, app):
        assert "recurring_api" in app.blueprints

    def test_routes_exist(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/recurring" in rules
        assert "/api/recurring/seed" in rules
        assert "/api/recurring/spawn" in rules


# --- New frequency types -----------------------------------------------------


class TestWeekdaysFrequency:
    """Weekdays frequency fires Mon-Fri only."""

    def test_weekday_spawn(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(title="Weekday task", frequency=RecurringFrequency.WEEKDAYS)

            # Monday (weekday=0) should fire
            result = tasks_due_today(target_date=date(2026, 4, 13))  # Monday
            assert any(rt.title == "Weekday task" for rt in result)

    def test_weekend_no_spawn(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(title="Weekday only", frequency=RecurringFrequency.WEEKDAYS)

            # Saturday (weekday=5) should NOT fire
            result = tasks_due_today(target_date=date(2026, 4, 18))  # Saturday
            assert not any(rt.title == "Weekday only" for rt in result)

    def test_create_weekdays_via_api(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "Weekday thing", "frequency": "weekdays", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["frequency"] == "weekdays"


class TestMonthlyDateFrequency:
    """Monthly date frequency fires on a specific day of month."""

    def test_matching_day_fires(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(
                title="Pay rent",
                frequency=RecurringFrequency.MONTHLY_DATE,
                day_of_month=15,
            )

            result = tasks_due_today(target_date=date(2026, 5, 15))
            assert any(rt.title == "Pay rent" for rt in result)

    def test_non_matching_day_skips(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(
                title="Pay rent skip",
                frequency=RecurringFrequency.MONTHLY_DATE,
                day_of_month=15,
            )

            result = tasks_due_today(target_date=date(2026, 5, 14))
            assert not any(rt.title == "Pay rent skip" for rt in result)

    def test_create_monthly_date_via_api(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Monthly bill",
                "frequency": "monthly_date",
                "type": "personal",
                "day_of_month": 1,
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["frequency"] == "monthly_date"
        assert body["day_of_month"] == 1

    def test_422_missing_day_of_month(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={"title": "No day", "frequency": "monthly_date", "type": "work"},
        )
        assert resp.status_code == 422


class TestMonthlyNthWeekdayFrequency:
    """Monthly nth weekday fires on e.g. the 'first Monday' of the month."""

    def test_first_monday_fires(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(
                title="First Monday",
                frequency=RecurringFrequency.MONTHLY_NTH_WEEKDAY,
                day_of_week=0,  # Monday
                week_of_month=1,  # first
            )

            # 2026-04-06 is the first Monday of April 2026
            result = tasks_due_today(target_date=date(2026, 4, 6))
            assert any(rt.title == "First Monday" for rt in result)

    def test_second_monday_skips_first(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(
                title="Second Monday",
                frequency=RecurringFrequency.MONTHLY_NTH_WEEKDAY,
                day_of_week=0,
                week_of_month=2,
            )

            # First Monday (2026-04-06) should NOT fire for second-Monday template
            result = tasks_due_today(target_date=date(2026, 4, 6))
            assert not any(rt.title == "Second Monday" for rt in result)

            # Second Monday (2026-04-13) SHOULD fire
            result = tasks_due_today(target_date=date(2026, 4, 13))
            assert any(rt.title == "Second Monday" for rt in result)

    def test_third_friday(self, app):
        from recurring_service import tasks_due_today

        with app.app_context():
            _make_recurring(
                title="Third Friday",
                frequency=RecurringFrequency.MONTHLY_NTH_WEEKDAY,
                day_of_week=4,  # Friday
                week_of_month=3,
            )

            # 2026-04-17 is the third Friday of April 2026
            result = tasks_due_today(target_date=date(2026, 4, 17))
            assert any(rt.title == "Third Friday" for rt in result)

    def test_422_missing_week_of_month(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "No week",
                "frequency": "monthly_nth_weekday",
                "type": "work",
                "day_of_week": 0,
            },
        )
        assert resp.status_code == 422

    def test_422_missing_day_of_week(self, authed_client):
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "No day",
                "frequency": "monthly_nth_weekday",
                "type": "work",
                "week_of_month": 1,
            },
        )
        assert resp.status_code == 422


class TestSpawnFullDetails:
    """Spawned tasks should inherit full details from templates."""

    def test_spawn_copies_notes_and_url(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="Full detail spawn",
                frequency=RecurringFrequency.DAILY,
                notes="Remember to check X",
                url="https://example.com/guide",
            )

        authed_client.post("/api/recurring/spawn")

        resp = authed_client.get("/api/tasks?tier=today")
        tasks = [t for t in resp.get_json() if t["title"] == "Full detail spawn"]
        assert len(tasks) == 1
        assert tasks[0]["notes"] == "Remember to check X"
        assert tasks[0]["url"] == "https://example.com/guide"

    def test_spawn_copies_checklist(self, authed_client, app):
        checklist = [{"id": "1", "text": "Step 1", "checked": False}]
        with app.app_context():
            _make_recurring(
                title="Checklist spawn",
                frequency=RecurringFrequency.DAILY,
                checklist=checklist,
            )

        authed_client.post("/api/recurring/spawn")

        resp = authed_client.get("/api/tasks?tier=today")
        tasks = [t for t in resp.get_json() if t["title"] == "Checklist spawn"]
        assert len(tasks) == 1
        assert len(tasks[0]["checklist"]) == 1
        assert tasks[0]["checklist"][0]["text"] == "Step 1"

    def test_spawn_sets_recurring_task_id(self, authed_client, app):
        with app.app_context():
            _make_recurring(title="Linked spawn", frequency=RecurringFrequency.DAILY)

        authed_client.post("/api/recurring/spawn")

        resp = authed_client.get("/api/tasks?tier=today")
        tasks = [t for t in resp.get_json() if t["title"] == "Linked spawn"]
        assert len(tasks) == 1
        assert tasks[0]["repeat"] is not None
        assert tasks[0]["repeat"]["frequency"] == "daily"
