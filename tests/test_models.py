"""Tests for SQLAlchemy models — CRUD, constraint validation, enum boundaries."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ImportLog,
    Project,
    ProjectPriority,
    ProjectStatus,
    ProjectType,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
)

# --- Goal --------------------------------------------------------------------


def test_goal_create_and_read(db):
    goal = Goal(
        title="Reduce Back Pain",
        category=GoalCategory.HEALTH,
        priority=GoalPriority.MUST,
        priority_rank=1,
        actions="Stretch daily, PT weekly",
        target_quarter="Q1,Q2",
    )
    db.session.add(goal)
    db.session.commit()

    fetched = db.session.get(Goal, goal.id)
    assert fetched is not None
    assert fetched.title == "Reduce Back Pain"
    assert fetched.category is GoalCategory.HEALTH
    assert fetched.status is GoalStatus.NOT_STARTED  # default
    assert fetched.is_active is True
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_goal_title_required(db):
    goal = Goal(category=GoalCategory.WORK, priority=GoalPriority.SHOULD)
    db.session.add(goal)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_goal_update_touches_updated_at(db):
    goal = Goal(
        title="Next Role Prep", category=GoalCategory.WORK, priority=GoalPriority.MUST
    )
    db.session.add(goal)
    db.session.commit()
    original_updated = goal.updated_at

    goal.status = GoalStatus.IN_PROGRESS
    db.session.commit()
    assert goal.updated_at >= original_updated


def test_goal_delete(db):
    goal = Goal(title="Trial", category=GoalCategory.WORK, priority=GoalPriority.COULD)
    db.session.add(goal)
    db.session.commit()
    goal_id = goal.id

    db.session.delete(goal)
    db.session.commit()
    assert db.session.get(Goal, goal_id) is None


# --- Project -----------------------------------------------------------------


def test_project_create_with_goal_link(db):
    goal = Goal(title="Ship Portal", category=GoalCategory.WORK, priority=GoalPriority.MUST)
    db.session.add(goal)
    db.session.commit()

    project = Project(name="Portal", color="#ff8800", goal_id=goal.id)
    db.session.add(project)
    db.session.commit()

    assert project.goal is goal
    assert goal.projects == [project]
    assert project.type is ProjectType.WORK  # default
    assert project.is_active is True


def test_project_without_goal_is_allowed(db):
    project = Project(name="Backlog")
    db.session.add(project)
    db.session.commit()
    assert project.goal_id is None


def test_project_name_required(db):
    db.session.add(Project())
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --- Task --------------------------------------------------------------------


def test_task_create_minimal(db):
    task = Task(title="Review PR", type=TaskType.WORK)
    db.session.add(task)
    db.session.commit()

    assert task.tier is Tier.INBOX
    assert task.status is TaskStatus.ACTIVE
    assert task.sort_order == 0
    assert task.project_id is None
    assert task.goal_id is None


def test_task_with_project_and_goal(db):
    goal = Goal(
        title="Reduce Back Pain", category=GoalCategory.HEALTH, priority=GoalPriority.MUST
    )
    project = Project(name="Portal")
    db.session.add_all([goal, project])
    db.session.commit()

    task = Task(
        title="Stretch 10 min",
        type=TaskType.PERSONAL,
        tier=Tier.TODAY,
        due_date=date(2026, 4, 6),
        project_id=project.id,
        goal_id=goal.id,
        notes="After morning coffee",
        checklist=[{"id": "a", "text": "Neck", "checked": False}],
    )
    db.session.add(task)
    db.session.commit()

    assert task.project is project
    assert task.goal is goal
    assert task.checklist[0]["text"] == "Neck"
    assert task.due_date == date(2026, 4, 6)


def test_task_title_required(db):
    db.session.add(Task(type=TaskType.WORK))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_task_type_required(db):
    db.session.add(Task(title="Something"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_task_move_between_tiers(db):
    task = Task(title="Draft memo", type=TaskType.WORK, tier=Tier.INBOX)
    db.session.add(task)
    db.session.commit()

    task.tier = Tier.TODAY
    db.session.commit()

    refreshed = db.session.get(Task, task.id)
    assert refreshed.tier is Tier.TODAY


def test_task_soft_delete_via_status(db):
    task = Task(title="Old thing", type=TaskType.PERSONAL)
    db.session.add(task)
    db.session.commit()

    task.status = TaskStatus.DELETED
    db.session.commit()
    assert db.session.get(Task, task.id).status is TaskStatus.DELETED


# --- RecurringTask -----------------------------------------------------------


def test_recurring_task_create(db):
    rt = RecurringTask(
        title="Morning stretch",
        frequency=RecurringFrequency.DAILY,
        type=TaskType.PERSONAL,
    )
    db.session.add(rt)
    db.session.commit()

    assert rt.is_active is True
    assert rt.day_of_week is None


def test_recurring_task_day_of_week(db):
    rt = RecurringTask(
        title="1-1 deck",
        frequency=RecurringFrequency.DAY_OF_WEEK,
        day_of_week=2,
        type=TaskType.WORK,
    )
    db.session.add(rt)
    db.session.commit()

    assert rt.day_of_week == 2
    assert rt.frequency is RecurringFrequency.DAY_OF_WEEK


def test_recurring_task_title_required(db):
    db.session.add(
        RecurringTask(frequency=RecurringFrequency.DAILY, type=TaskType.WORK)
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --- ImportLog ---------------------------------------------------------------


def test_import_log_create(db):
    entry = ImportLog(source="onenote_2026_04_05", task_count=42)
    db.session.add(entry)
    db.session.commit()

    assert entry.id is not None
    assert entry.imported_at is not None
    assert entry.task_count == 42


def test_import_log_source_required(db):
    db.session.add(ImportLog(task_count=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --- Enum boundaries (#413) --------------------------------------------------
#
# CLAUDE.md asks model tests to cover enum boundaries. Every member of every
# enum used as a column must round-trip through the DB — iterating the enum
# itself, so a member added later (TOMORROW / NEXT_WEEK tiers, CANCELLED
# status, a new goal category or recurring frequency) is covered the day it
# lands. The Postgres side of the same risk is /healthz enum_coverage.


def _goal(**kw):
    fields = {"title": "G", "category": GoalCategory.WORK, "priority": GoalPriority.MUST}
    fields.update(kw)
    return Goal(**fields)


def _round_trip(db, row, attr):
    db.session.add(row)
    db.session.commit()
    value = getattr(row, attr)
    db.session.expire_all()
    return value, getattr(db.session.get(type(row), row.id), attr)


@pytest.mark.parametrize("tier", list(Tier))
def test_every_tier_round_trips(db, tier):
    sent, got = _round_trip(db, Task(title="t", type=TaskType.WORK, tier=tier), "tier")
    assert got is sent is tier


@pytest.mark.parametrize("status", list(TaskStatus))
def test_every_task_status_round_trips(db, status):
    _, got = _round_trip(db, Task(title="t", type=TaskType.WORK, status=status), "status")
    assert got is status


@pytest.mark.parametrize("task_type", list(TaskType))
def test_every_task_type_round_trips(db, task_type):
    _, got = _round_trip(db, Task(title="t", type=task_type), "type")
    assert got is task_type


@pytest.mark.parametrize("category", list(GoalCategory))
def test_every_goal_category_round_trips(db, category):
    _, got = _round_trip(db, _goal(category=category), "category")
    assert got is category


@pytest.mark.parametrize("priority", list(GoalPriority))
def test_every_goal_priority_round_trips(db, priority):
    _, got = _round_trip(db, _goal(priority=priority), "priority")
    assert got is priority


@pytest.mark.parametrize("status", list(GoalStatus))
def test_every_goal_status_round_trips(db, status):
    _, got = _round_trip(db, _goal(status=status), "status")
    assert got is status


@pytest.mark.parametrize("ptype", list(ProjectType))
def test_every_project_type_round_trips(db, ptype):
    _, got = _round_trip(db, Project(name="p", type=ptype), "type")
    assert got is ptype


@pytest.mark.parametrize("pstatus", list(ProjectStatus))
def test_every_project_status_round_trips(db, pstatus):
    _, got = _round_trip(db, Project(name="p", status=pstatus), "status")
    assert got is pstatus


@pytest.mark.parametrize("ppriority", list(ProjectPriority))
def test_every_project_priority_round_trips(db, ppriority):
    _, got = _round_trip(db, Project(name="p", priority=ppriority), "priority")
    assert got is ppriority


@pytest.mark.parametrize("freq", list(RecurringFrequency))
def test_every_recurring_frequency_round_trips(db, freq):
    row = RecurringTask(title="r", frequency=freq, type=TaskType.WORK)
    _, got = _round_trip(db, row, "frequency")
    assert got is freq


# --- URL normalization -------------------------------------------------------


def test_normalize_postgres_url():
    from app import _normalize_db_url

    assert (
        _normalize_db_url("postgres://u:p@h/d")
        == "postgresql+psycopg://u:p@h/d"
    )
    assert (
        _normalize_db_url("postgresql://u:p@h/d")
        == "postgresql+psycopg://u:p@h/d"
    )
    assert _normalize_db_url("sqlite:///dev.db") == "sqlite:///dev.db"
