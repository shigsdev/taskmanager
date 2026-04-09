"""Business logic for projects. Routes call into this module."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from models import Project, db
from utils import ValidationError  # noqa: F401 — re-exported for API layer

DEFAULT_PROJECTS = [
    "Portal",
    "Roadmaps",
    "Strategy and Vision",
    "Product Operations",
    "COP",
    "AI for PM",
    "Training",
    "Reading",
    "Backlog",
]

DEFAULT_COLORS = [
    "#3b82f6",  # blue
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#f97316",  # orange
    "#14b8a6",  # teal
    "#84cc16",  # lime
    "#f43f5e",  # rose
    "#06b6d4",  # cyan
    "#a855f7",  # purple
]


def _parse_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"invalid {field}: must be an integer", field) from e


def _parse_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise ValidationError(f"invalid {field}", field) from e


def seed_default_projects() -> list[Project]:
    """Create default work projects if none exist. Safe to call multiple times."""
    existing = db.session.scalar(select(Project).limit(1))
    if existing is not None:
        return list(db.session.scalars(select(Project).order_by(Project.sort_order)))

    projects = []
    for i, name in enumerate(DEFAULT_PROJECTS):
        p = Project(
            name=name,
            color=DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            sort_order=i,
        )
        db.session.add(p)
        projects.append(p)
    db.session.commit()
    return projects


def create_project(data: dict) -> Project:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("name is required", "name")

    project = Project(
        name=name,
        color=(data.get("color") or "").strip() or None,
        goal_id=_parse_uuid(data.get("goal_id"), "goal_id"),
        sort_order=_parse_int(data.get("sort_order", 0), "sort_order"),
    )
    db.session.add(project)
    db.session.commit()
    return project


def get_project(project_id: uuid.UUID) -> Project | None:
    return db.session.get(Project, project_id)


def list_projects(*, is_active: bool | None = True) -> list[Project]:
    stmt = select(Project)
    if is_active is not None:
        stmt = stmt.where(Project.is_active == is_active)
    stmt = stmt.order_by(Project.sort_order.asc(), Project.name.asc())
    return list(db.session.scalars(stmt))


_UPDATABLE_FIELDS = {"name", "color", "goal_id", "is_active", "sort_order"}


def update_project(project_id: uuid.UUID, data: dict) -> Project | None:
    project = get_project(project_id)
    if project is None:
        return None

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ValidationError("name cannot be empty", "name")
        project.name = name

    if "color" in data:
        project.color = (data["color"] or "").strip() or None

    if "goal_id" in data:
        project.goal_id = _parse_uuid(data["goal_id"], "goal_id")

    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ValidationError("is_active must be a boolean", "is_active")
        project.is_active = data["is_active"]

    if "sort_order" in data:
        try:
            project.sort_order = int(data["sort_order"])
        except (TypeError, ValueError) as e:
            raise ValidationError("sort_order must be integer", "sort_order") from e

    unknown = set(data) - _UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", next(iter(unknown)))

    db.session.commit()
    return project


def delete_project(project_id: uuid.UUID) -> bool:
    project = get_project(project_id)
    if project is None:
        return False
    project.is_active = False
    db.session.commit()
    return True
