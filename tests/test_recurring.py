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

    def test_create_multi_day_of_week_via_api(self, authed_client):
        """#75: POST creates a MULTI_DAY_OF_WEEK template; days_of_week
        round-trips through the serializer, deduped + sorted."""
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Workout",
                "frequency": "multi_day_of_week",
                "type": "personal",
                # Out-of-order + duplicate to verify dedup + sort.
                "days_of_week": [6, 5, 6],
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["frequency"] == "multi_day_of_week"
        assert body["days_of_week"] == [5, 6]

    def test_create_multi_day_of_week_missing_days_422(self, authed_client):
        """#75: MULTI_DAY_OF_WEEK without days_of_week is rejected."""
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Workout",
                "frequency": "multi_day_of_week",
                "type": "personal",
            },
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "days_of_week"

    def test_create_multi_day_of_week_bad_day_422(self, authed_client):
        """#75: out-of-range entry in days_of_week is rejected."""
        resp = authed_client.post(
            "/api/recurring",
            json={
                "title": "Bad",
                "frequency": "multi_day_of_week",
                "type": "personal",
                "days_of_week": [5, 9],
            },
        )
        assert resp.status_code == 422

    def test_bulk_patch_updates_multiple_templates(self, authed_client, app):
        """#63 (2026-04-26): PATCH /api/recurring/bulk updates a list of
        templates with one updates dict."""
        with app.app_context():
            t1 = _make_recurring(title="A", frequency=RecurringFrequency.DAILY)
            t2 = _make_recurring(title="B", frequency=RecurringFrequency.DAILY)
            ids = [str(t1.id), str(t2.id)]
        resp = authed_client.patch(
            "/api/recurring/bulk",
            json={"template_ids": ids, "updates": {"is_active": False}},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] == 2
        assert body["errors"] == []
        # Verify via GET
        for tid in ids:
            assert authed_client.get(f"/api/recurring/{tid}").get_json()["is_active"] is False

    def test_bulk_patch_422_on_bad_input(self, authed_client):
        """#63: missing template_ids or updates -> 422."""
        resp = authed_client.patch("/api/recurring/bulk", json={"updates": {"is_active": False}})
        assert resp.status_code == 422
        resp = authed_client.patch("/api/recurring/bulk", json={"template_ids": ["not-uuid"]})
        assert resp.status_code == 422

    def test_bulk_delete_removes_templates(self, authed_client, app):
        """#63: DELETE /api/recurring/bulk soft-deletes a list."""
        with app.app_context():
            t1 = _make_recurring(title="X", frequency=RecurringFrequency.DAILY)
            t2 = _make_recurring(title="Y", frequency=RecurringFrequency.DAILY)
            ids = [str(t1.id), str(t2.id)]
        resp = authed_client.delete(
            "/api/recurring/bulk", json={"template_ids": ids},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["deleted"] == 2

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


class TestSpawnDueDateAndCrossTierDedup:
    """Backlog #38: spawned tasks must (a) get due_date=target_date so
    they match the auto-fill behaviour from #28, and (b) deduplicate
    across ALL active tiers (not just TODAY title-match), so a planned-
    ahead this_week task with the same recurring_task_id + due_date
    doesn't get duplicated when the cron fires."""

    def test_spawned_task_has_due_date_set(self, app):
        """Gap A — cron-spawned tasks must have due_date populated, just
        like manually-created TODAY tasks do via _auto_fill_tier_due_date."""
        from datetime import date

        from recurring_service import spawn_today_tasks
        with app.app_context():
            _make_recurring(title="Gap A test", frequency=RecurringFrequency.DAILY)
            target = date(2026, 4, 24)
            spawned = spawn_today_tasks(target_date=target)
            assert len(spawned) == 1
            assert spawned[0].due_date == target

    def test_spawn_skipped_when_planned_ahead_in_this_week(self, app):
        """Gap B — user manually created a task in this_week with the
        same recurring_task_id and a due_date matching the fire date.
        Spawn must NOT create a duplicate in TODAY (the "Meds" case
        from the 2026-04-22 diagnosis)."""
        from datetime import date

        from models import Task, Tier
        from recurring_service import spawn_today_tasks
        with app.app_context():
            rt = _make_recurring(title="Meds", frequency=RecurringFrequency.DAILY)
            target = date(2026, 4, 24)
            # Simulate the user planning ahead — same template, due Friday,
            # parked in this_week.
            planned = Task(
                title="Meds",
                type=TaskType.PERSONAL,
                tier=Tier.THIS_WEEK,
                due_date=target,
                recurring_task_id=rt.id,
            )
            db.session.add(planned)
            db.session.commit()

            spawned = spawn_today_tasks(target_date=target)
            # spawn must skip when (rt_id, due_date) matches a this_week task
            assert spawned == []

            # Confirm the planned task is the only one with this template
            # — no TODAY duplicate created.
            from sqlalchemy import select
            all_meds = list(db.session.scalars(
                select(Task).where(Task.recurring_task_id == rt.id),
            ))
            assert len(all_meds) == 1
            assert all_meds[0].tier == Tier.THIS_WEEK

    def test_spawn_dedup_keys_on_due_date_not_just_title(self, app):
        """Counterpoint to the planned-ahead test: if the existing
        this_week task has a DIFFERENT due_date than today's fire
        date (e.g. yesterday's spawn that got moved to this_week),
        the new spawn for TODAY's date SHOULD proceed."""
        from datetime import date

        from models import Task, Tier
        from recurring_service import spawn_today_tasks
        with app.app_context():
            rt = _make_recurring(title="Walk", frequency=RecurringFrequency.DAILY)
            yesterday = date(2026, 4, 23)
            today = date(2026, 4, 24)
            old = Task(
                title="Walk",
                type=TaskType.PERSONAL,
                tier=Tier.THIS_WEEK,
                due_date=yesterday,  # different fire date
                recurring_task_id=rt.id,
            )
            db.session.add(old)
            db.session.commit()

            spawned = spawn_today_tasks(target_date=today)
            assert len(spawned) == 1
            assert spawned[0].due_date == today

    def test_spawn_dedup_ignores_completed_tasks(self, app):
        """If yesterday's spawn was completed, today's spawn should
        proceed normally — completed tasks must NOT block new spawns
        because the dedup query filters status == ACTIVE."""
        from datetime import date

        from models import Task, TaskStatus, Tier
        from recurring_service import spawn_today_tasks
        with app.app_context():
            rt = _make_recurring(title="Daily check-in", frequency=RecurringFrequency.DAILY)
            target = date(2026, 4, 24)
            done = Task(
                title="Daily check-in",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                due_date=target,
                recurring_task_id=rt.id,
                status=TaskStatus.ARCHIVED,  # completed
            )
            db.session.add(done)
            db.session.commit()

            spawned = spawn_today_tasks(target_date=target)
            assert len(spawned) == 1
            assert spawned[0].status == TaskStatus.ACTIVE


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


class TestSpawnWithSubtasks:
    """Backlog #26: recurring templates clone their subtasks on every spawn."""

    def test_spawn_clones_subtasks_from_snapshot(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="Weekly review",
                frequency=RecurringFrequency.DAILY,
                subtasks_snapshot=[
                    {"title": "Review Today"},
                    {"title": "Review Goals"},
                    {"title": "Plan next week"},
                ],
            )
        authed_client.post("/api/recurring/spawn")
        resp = authed_client.get("/api/tasks?tier=today").get_json()
        parents = [t for t in resp if t["title"] == "Weekly review"]
        assert len(parents) == 1
        parent = parents[0]
        # Subtasks should exist as their own Tasks with parent_id = parent.id
        subs = [t for t in resp if t.get("parent_id") == parent["id"]]
        titles = sorted(s["title"] for s in subs)
        assert titles == ["Plan next week", "Review Goals", "Review Today"]

    def test_spawn_clones_subtasks_on_every_cycle(self, authed_client, app):
        """Archiving the parent + re-spawning produces a fresh set of subtasks."""
        with app.app_context():
            _make_recurring(
                title="Cycle",
                frequency=RecurringFrequency.DAILY,
                subtasks_snapshot=[{"title": "Step A"}, {"title": "Step B"}],
            )
        # First cycle
        authed_client.post("/api/recurring/spawn")
        first = authed_client.get("/api/tasks?tier=today").get_json()
        parent1 = next(t for t in first if t["title"] == "Cycle")
        sub_ids_1 = {
            t["id"] for t in first if t.get("parent_id") == parent1["id"]
        }
        assert len(sub_ids_1) == 2

        # Archive everything (simulating completion), then re-spawn
        for t in first:
            authed_client.patch(
                f"/api/tasks/{t['id']}", json={"status": "archived"}
            )
        authed_client.post("/api/recurring/spawn")

        second_resp = authed_client.get("/api/tasks?tier=today").get_json()
        parent2 = next(t for t in second_resp if t["title"] == "Cycle")
        sub_ids_2 = {
            t["id"] for t in second_resp if t.get("parent_id") == parent2["id"]
        }
        # New cycle → new subtask IDs, but same two titles
        assert len(sub_ids_2) == 2
        assert sub_ids_1.isdisjoint(sub_ids_2)

    def test_spawn_empty_snapshot_creates_parent_only(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="No subs",
                frequency=RecurringFrequency.DAILY,
                subtasks_snapshot=[],
            )
        authed_client.post("/api/recurring/spawn")
        resp = authed_client.get("/api/tasks?tier=today").get_json()
        parents = [t for t in resp if t["title"] == "No subs"]
        subs = [t for t in resp if t.get("parent_id") == parents[0]["id"]]
        assert len(parents) == 1 and subs == []

    def test_spawn_null_snapshot_creates_parent_only(self, authed_client, app):
        """Legacy rows (before #26) have NULL; spawn must not crash."""
        with app.app_context():
            _make_recurring(
                title="Legacy",
                frequency=RecurringFrequency.DAILY,
            )
            # Force NULL via direct SQL since the helper defaults to []
            from models import RecurringTask, db
            rt = db.session.scalars(
                db.select(RecurringTask).where(RecurringTask.title == "Legacy")
            ).first()
            rt.subtasks_snapshot = None
            db.session.commit()
        authed_client.post("/api/recurring/spawn")
        resp = authed_client.get("/api/tasks?tier=today").get_json()
        assert any(t["title"] == "Legacy" for t in resp)

    def test_spawn_skips_malformed_snapshot_entries(self, authed_client, app):
        """Non-dict entries, missing title, blank title — all silently skipped."""
        with app.app_context():
            _make_recurring(
                title="Malformed",
                frequency=RecurringFrequency.DAILY,
                subtasks_snapshot=[
                    {"title": "Good"},
                    {"title": ""},
                    {"title": "  "},
                    {},
                    "not a dict",
                    None,
                    {"title": "Also good"},
                ],
            )
        authed_client.post("/api/recurring/spawn")
        resp = authed_client.get("/api/tasks?tier=today").get_json()
        parent = next(t for t in resp if t["title"] == "Malformed")
        subs = [t for t in resp if t.get("parent_id") == parent["id"]]
        titles = sorted(s["title"] for s in subs)
        assert titles == ["Also good", "Good"]


class TestPreviewsEndpoint:
    """Backlog #32: /api/recurring/previews expands active templates
    across a date range into per-day preview instances."""

    def test_missing_params_returns_400(self, authed_client):
        resp = authed_client.get("/api/recurring/previews")
        assert resp.status_code == 400

    def test_invalid_date_returns_400(self, authed_client):
        resp = authed_client.get(
            "/api/recurring/previews?start=nope&end=2026-04-20"
        )
        assert resp.status_code == 400

    def test_range_too_large_rejected(self, authed_client):
        resp = authed_client.get(
            "/api/recurring/previews?start=2026-01-01&end=2027-01-01"
        )
        assert resp.status_code == 400

    def test_daily_template_fires_every_day(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="Daily stuff", frequency=RecurringFrequency.DAILY,
            )
        resp = authed_client.get(
            "/api/recurring/previews?start=2026-04-20&end=2026-04-22"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        daily = [p for p in body if p["title"] == "Daily stuff"]
        assert len(daily) == 3
        assert [p["fire_date"] for p in daily] == [
            "2026-04-20", "2026-04-21", "2026-04-22",
        ]

    def test_weekly_template_fires_once_in_range(self, authed_client, app):
        # 2026-04-20 is Monday (weekday=0)
        with app.app_context():
            _make_recurring(
                title="Monday review",
                frequency=RecurringFrequency.WEEKLY,
                day_of_week=0,
            )
        resp = authed_client.get(
            "/api/recurring/previews?start=2026-04-20&end=2026-04-26"
        )
        fires = [
            p for p in resp.get_json() if p["title"] == "Monday review"
        ]
        assert len(fires) == 1
        assert fires[0]["fire_date"] == "2026-04-20"

    def test_multi_day_of_week_fires_on_each_listed_day(self, authed_client, app):
        """#75: MULTI_DAY_OF_WEEK template fires on every listed weekday
        within the preview range. Sat+Sun = workout fires Saturday + Sunday."""
        with app.app_context():
            _make_recurring(
                title="Workout",
                frequency=RecurringFrequency.MULTI_DAY_OF_WEEK,
                days_of_week=[5, 6],  # Sat=5, Sun=6
            )
        # 2026-04-20 Mon … 2026-04-26 Sun. Should fire on Sat (Apr 25) + Sun (Apr 26).
        resp = authed_client.get(
            "/api/recurring/previews?start=2026-04-20&end=2026-04-26"
        )
        fires = sorted(
            p["fire_date"] for p in resp.get_json() if p["title"] == "Workout"
        )
        assert fires == ["2026-04-25", "2026-04-26"]

    def test_inactive_template_not_previewed(self, authed_client, app):
        with app.app_context():
            _make_recurring(
                title="Quiet one",
                frequency=RecurringFrequency.DAILY,
                is_active=False,
            )
        resp = authed_client.get(
            "/api/recurring/previews?start=2026-04-20&end=2026-04-21"
        )
        titles = [p["title"] for p in resp.get_json()]
        assert "Quiet one" not in titles

    def test_task_with_due_date_suppresses_preview_for_that_day(
        self, authed_client, app,
    ):
        """Backlog #34 regression: a task created today with
        due_date=Friday and a weekly-Friday recurring template must
        suppress Friday's preview. Before the fix, the collision
        filter keyed only on created_at (today), missing a Friday
        fire_date entirely — double-rendered in the UI.

        User-reported via screenshot 2026-04-20. Fix: additionally
        key spawned_by_template_and_day by task.due_date."""
        from datetime import date, timedelta

        from models import RecurringFrequency, Task, TaskType, Tier, db
        with app.app_context():
            rt = _make_recurring(
                title="Weekly Friday",
                frequency=RecurringFrequency.WEEKLY,
                day_of_week=4,  # Friday
            )
            rt_id = rt.id
            # Task created today with due_date 3 days from now (Friday-ish)
            future_due = date.today() + timedelta(days=3)
            task = Task(
                title="Weekly Friday",
                type=TaskType.WORK,
                tier=Tier.THIS_WEEK,
                due_date=future_due,
                recurring_task_id=rt_id,
            )
            db.session.add(task)
            db.session.commit()
        # Query previews for the full week covering today + future_due
        start = date.today().isoformat()
        end = (date.today() + timedelta(days=6)).isoformat()
        resp = authed_client.get(
            f"/api/recurring/previews?start={start}&end={end}"
        )
        body = resp.get_json()
        fire_dates = [
            p["fire_date"] for p in body if p["title"] == "Weekly Friday"
        ]
        # The Friday-fire within the range must be suppressed because
        # the real task's due_date matches. If the weekly fire day
        # doesn't fall in the next 6 days (i.e. today IS Friday), the
        # real task's due_date IS today and it's suppressed anyway.
        assert future_due.isoformat() not in fire_dates

    def test_spawned_task_suppresses_same_day_preview(self, authed_client, app):
        """Key invariant: if the template already spawned a Task today,
        don't also render a preview for today — that'd be a phantom."""
        from datetime import date, timedelta

        from models import Task, TaskType, Tier, db
        with app.app_context():
            rt = _make_recurring(
                title="Dup", frequency=RecurringFrequency.DAILY,
            )
            rt_id = rt.id
            task = Task(
                title="Dup",
                type=TaskType.WORK,
                tier=Tier.TODAY,
                recurring_task_id=rt_id,
            )
            db.session.add(task)
            db.session.commit()
        start = (date.today() - timedelta(days=1)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()
        resp = authed_client.get(
            f"/api/recurring/previews?start={start}&end={end}"
        )
        dup_dates = [
            p["fire_date"] for p in resp.get_json() if p["title"] == "Dup"
        ]
        assert date.today().isoformat() not in dup_dates
        assert len(dup_dates) == 2
