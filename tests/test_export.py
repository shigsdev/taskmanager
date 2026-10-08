"""#366: ``GET /api/export`` is a complete copy of the user's data.

Before #366 the export hand-picked three tables, hid archived goals and
projects (``list_goals()`` / ``list_projects()`` default to active), and
dropped 8 of 14 project columns — so a task's ``recurring_task_id`` and an
archived project's id pointed at rows that were not in the file. The export
now walks ``db.Model.registry``: every table except an explicit, reasoned
exclusion list, every column, every row. Spec:
``docs/design/366-export-complete.md``.
"""

from datetime import UTC, date, datetime

import pytest

import auth
from export_service import EXPORT_EXCLUDED_TABLES, build_export
from models import (
    AppLog,
    AppSetting,
    CronAudit,
    FlareState,
    GlobalContextFile,
    Goal,
    GoalCategory,
    GoalPriority,
    ImportLog,
    Project,
    RecurringFrequency,
    RecurringTask,
    Reflection,
    ReflectionInputMode,
    Task,
    TaskType,
    WeeklyFocus,
    WorkoutSession,
    WorkoutSet,
)


def _all_tables(db):
    return {m.class_.__table__.name for m in db.Model.registry.mappers}


@pytest.fixture
def seeded(db):
    """One row in EVERY table, including an archived goal + project and a
    task spawned from a template, so each test sees a full database."""
    live_goal = Goal(title="Live goal", category=GoalCategory.WORK,
                     priority=GoalPriority.MUST)
    archived_goal = Goal(title="Archived goal", category=GoalCategory.HEALTH,
                         priority=GoalPriority.COULD, is_active=False)
    db.session.add_all([live_goal, archived_goal])
    db.session.flush()

    archived_project = Project(name="Archived project", type=TaskType.WORK,
                               goal_id=archived_goal.id, notes="kept notes",
                               is_active=False)
    db.session.add(archived_project)
    db.session.flush()

    template = RecurringTask(title="Weekly report", type=TaskType.WORK,
                             frequency=RecurringFrequency.WEEKLY, day_of_week=0,
                             project_id=archived_project.id)
    db.session.add(template)
    db.session.flush()

    spawned = Task(title="Weekly report", type=TaskType.WORK,
                   recurring_task_id=template.id,
                   project_id=archived_project.id, goal_id=archived_goal.id)
    session = WorkoutSession(plan_type="bands", session_date=date(2026, 10, 1))
    db.session.add_all([spawned, session])
    db.session.flush()

    db.session.add_all([
        WorkoutSet(workout_session_id=session.id, exercise_id="row",
                   exercise_name="Band row", reps=12),
        WeeklyFocus(week_start_date=date(2026, 10, 5), slot_order=1,
                    text="Ship #366", goal_id=live_goal.id),
        Reflection(iso_week="2026-W41", input_mode=ReflectionInputMode.TYPED,
                   transcript="A typed reflection."),
        GlobalContextFile(filename="notes.md", kind="md", text="context",
                          chars=7),
        AppSetting(key="weekly_focus_slot_count", value="3"),
        ImportLog(source="excel_tasks", task_count=1),
        FlareState(started_on=date(2026, 9, 30)),
        # Ops tables — present in the DB, must NOT be exported.
        AppLog(level="ERROR", logger_name="test", message="boom"),
        CronAudit(job_id="daily_digest", last_status="ok",
                  last_fire_at=datetime(2026, 10, 8, tzinfo=UTC)),
    ])
    db.session.commit()
    return {"archived_goal": archived_goal, "archived_project": archived_project,
            "template": template, "spawned": spawned}


class TestExportCoversEverything:
    def test_every_user_data_table_is_exported(self, app, db, seeded):
        """Drift gate: a new model fails this until it is exported or added
        to EXPORT_EXCLUDED_TABLES with a reason."""
        out = build_export()
        assert set(out) == _all_tables(db) - EXPORT_EXCLUDED_TABLES

    def test_excluded_tables_are_ops_only_and_absent(self, app, db, seeded):
        assert set(EXPORT_EXCLUDED_TABLES) == {"app_logs", "cron_audit"}
        out = build_export()
        assert not set(out) & EXPORT_EXCLUDED_TABLES

    def test_every_column_of_every_table_is_exported(self, app, db, seeded):
        out = build_export()
        for mapper in db.Model.registry.mappers:
            table = mapper.class_.__table__
            if table.name in EXPORT_EXCLUDED_TABLES:
                continue
            assert out[table.name], f"seed has no {table.name} row"
            expected = {c.name for c in table.columns}
            for row in out[table.name]:
                assert set(row) == expected, table.name


class TestExportKeepsArchivedRowsAndLinks:
    def test_archived_goal_and_project_are_exported(self, app, db, seeded):
        out = build_export()
        goals = {g["id"]: g for g in out["goals"]}
        projects = {p["id"]: p for p in out["projects"]}

        goal = goals[str(seeded["archived_goal"].id)]
        assert goal["is_active"] is False
        project = projects[str(seeded["archived_project"].id)]
        assert project["is_active"] is False
        assert project["goal_id"] == str(seeded["archived_goal"].id)
        assert project["notes"] == "kept notes"

    def test_every_reference_resolves_inside_the_file(self, app, db, seeded):
        out = build_export()
        ids = {table: {r["id"] for r in rows} for table, rows in out.items()}
        task = next(t for t in out["tasks"] if t["id"] == str(seeded["spawned"].id))

        assert task["recurring_task_id"] in ids["recurring_tasks"]
        assert task["project_id"] in ids["projects"]
        assert task["goal_id"] in ids["goals"]
        template = next(r for r in out["recurring_tasks"]
                        if r["id"] == str(seeded["template"].id))
        assert template["project_id"] in ids["projects"]


class TestExportRoute:
    def test_route_returns_every_table_plus_exported_at(self, client, db, seeded,
                                                        monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/api/export")
        assert resp.status_code == 200
        body = resp.get_json()
        assert set(body) == (_all_tables(db) - EXPORT_EXCLUDED_TABLES) | {"exported_at"}
        assert "attachment;" in resp.headers["Content-Disposition"]

    def test_route_requires_login(self, client):
        resp = client.get("/api/export")
        assert resp.status_code in (302, 401)
