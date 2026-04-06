"""SQLAlchemy models for the Task Manager.

Schema is intentionally thin — no business logic lives here, per CLAUDE.md.
Enums mirror the spec exactly and are portable across PostgreSQL (prod) and
SQLite (tests/dev).
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

db = SQLAlchemy()


# --- Enums -------------------------------------------------------------------


class Tier(enum.StrEnum):
    TODAY = "today"
    THIS_WEEK = "this_week"
    BACKLOG = "backlog"
    FREEZER = "freezer"
    INBOX = "inbox"


class TaskType(enum.StrEnum):
    WORK = "work"
    PERSONAL = "personal"


class TaskStatus(enum.StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ProjectType(enum.StrEnum):
    WORK = "work"


class RecurringFrequency(enum.StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    DAY_OF_WEEK = "day_of_week"


class GoalCategory(enum.StrEnum):
    HEALTH = "health"
    PERSONAL_GROWTH = "personal_growth"
    RELATIONSHIPS = "relationships"
    WORK = "work"


class GoalPriority(enum.StrEnum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    NEED_MORE_INFO = "need_more_info"


class GoalStatus(enum.StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ON_HOLD = "on_hold"


# --- Helpers -----------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


# Use JSONB on PostgreSQL (indexable, faster) and plain JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


# --- Tables ------------------------------------------------------------------


class Goal(db.Model):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[GoalCategory] = mapped_column(Enum(GoalCategory), nullable=False)
    priority: Mapped[GoalPriority] = mapped_column(Enum(GoalPriority), nullable=False)
    priority_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actions: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_quarter: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus), nullable=False, default=GoalStatus.NOT_STARTED
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    tasks: Mapped[list[Task]] = relationship(back_populates="goal")
    projects: Mapped[list[Project]] = relationship(back_populates="goal")


class Project(db.Model):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[ProjectType] = mapped_column(
        Enum(ProjectType), nullable=False, default=ProjectType.WORK
    )
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("goals.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    goal: Mapped[Goal | None] = relationship(back_populates="projects")
    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Task(db.Model):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    tier: Mapped[Tier] = mapped_column(Enum(Tier), nullable=False, default=Tier.INBOX)
    type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("goals.id"), nullable=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    checklist: Mapped[list | None] = mapped_column(JSONType, nullable=True, default=list)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), nullable=False, default=TaskStatus.ACTIVE
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reviewed: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    goal: Mapped[Goal | None] = relationship(back_populates="tasks")


class RecurringTask(db.Model):
    __tablename__ = "recurring_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    frequency: Mapped[RecurringFrequency] = mapped_column(
        Enum(RecurringFrequency), nullable=False
    )
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ImportLog(db.Model):
    __tablename__ = "import_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
