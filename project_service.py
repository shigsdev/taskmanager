"""Business logic for projects. Routes call into this module."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from models import Project, ProjectStatus, ProjectType, db
from utils import ValidationError  # noqa: F401 — re-exported for API layer
from utils import parse_enum as _parse_enum
from utils import parse_int as _parse_int
from utils import parse_uuid as _parse_uuid

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
        type=_parse_enum(ProjectType, data.get("type", "work"), "type"),
        color=(data.get("color") or "").strip() or None,
        target_quarter=(data.get("target_quarter") or "").strip() or None,
        actions=(data.get("actions") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        status=_parse_enum(ProjectStatus, data.get("status", "not_started"), "status"),
        goal_id=_parse_uuid(data.get("goal_id"), "goal_id"),
        sort_order=_parse_int(data.get("sort_order", 0), "sort_order"),
    )
    db.session.add(project)
    db.session.commit()
    return project


def get_project(project_id: uuid.UUID) -> Project | None:
    return db.session.get(Project, project_id)


def list_projects(
    *, is_active: bool | None = True, project_type: ProjectType | None = None,
) -> list[Project]:
    stmt = select(Project)
    if is_active is not None:
        stmt = stmt.where(Project.is_active == is_active)
    if project_type is not None:
        stmt = stmt.where(Project.type == project_type)
    stmt = stmt.order_by(Project.sort_order.asc(), Project.name.asc())
    return list(db.session.scalars(stmt))


_UPDATABLE_FIELDS = {
    "name", "type", "color", "target_quarter",
    "actions", "notes", "status",
    "goal_id", "is_active", "sort_order",
}


def update_project(project_id: uuid.UUID, data: dict) -> Project | None:
    project = get_project(project_id)
    if project is None:
        return None

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ValidationError("name cannot be empty", "name")
        project.name = name

    if "type" in data:
        project.type = _parse_enum(ProjectType, data["type"], "type")

    if "color" in data:
        project.color = (data["color"] or "").strip() or None

    if "target_quarter" in data:
        project.target_quarter = (data["target_quarter"] or "").strip() or None

    if "actions" in data:
        project.actions = (data["actions"] or "").strip() or None

    if "notes" in data:
        project.notes = (data["notes"] or "").strip() or None

    if "status" in data:
        project.status = _parse_enum(ProjectStatus, data["status"], "status")

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
