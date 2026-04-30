"""Business logic for projects. Routes call into this module."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select

from models import Project, ProjectPriority, ProjectStatus, ProjectType, Task, db
from utils import ValidationError  # noqa: F401 — re-exported for API layer
from utils import parse_enum as _parse_enum
from utils import parse_int as _parse_int
from utils import parse_uuid as _parse_uuid

# PR28 audit fix #3: project.color is rendered into an inline `style=`
# attribute via innerHTML on the client (#projectFilterBar chip + the
# project-group header). Without server-side validation, an arbitrary
# string like `red; } body { display:none ` would inject CSS. Single-
# user app, so direct XSS risk is low — but CLAUDE.md "All user input
# sanitized before DB insertion" wasn't being met for this field.
# Allow #RGB, #RRGGBB, #RRGGBBAA hex (with or without # prefix on
# input — we always store with #). Reject anything else.
_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3}([0-9a-fA-F]{2})?)?$")


def _parse_color(value: str | None) -> str | None:
    """Validate + normalise a hex color string. Returns the canonical
    form (with leading #, lowercase) or None for empty input. Raises
    ValidationError on a non-empty value that isn't a valid hex color."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not _HEX_COLOR_RE.match(s):
        raise ValidationError(
            "color must be a hex value like #2563eb (3, 6, or 8 hex digits)",
            "color",
        )
    if not s.startswith("#"):
        s = "#" + s
    return s.lower()

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

# #66 (2026-04-25): per-type default color when caller doesn't specify
# one. Manual override via the color picker still wins.
DEFAULT_TYPE_COLORS = {
    ProjectType.WORK: "#2563eb",       # blue
    ProjectType.PERSONAL: "#16a34a",   # green
}


def _default_color_for_type(project_type: ProjectType) -> str:
    return DEFAULT_TYPE_COLORS.get(project_type, "#2563eb")


def seed_default_projects() -> list[Project]:
    """Create default work projects if none exist. Safe to call multiple times."""
    existing = db.session.scalar(select(Project).limit(1))
    if existing is not None:
        return list(db.session.scalars(select(Project).order_by(Project.priority_order)))

    projects = []
    for i, name in enumerate(DEFAULT_PROJECTS):
        p = Project(
            name=name,
            color=DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            priority_order=i,
        )
        db.session.add(p)
        projects.append(p)
    db.session.commit()
    return projects


def create_project(data: dict) -> Project:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("name is required", "name")

    project_type = _parse_enum(ProjectType, data.get("type", "work"), "type")
    # #66: when caller doesn't pass a color, fill in the per-type default
    # (Work=blue, Personal=green). Manual overrides still flow through.
    # PR28 audit fix #3: validate hex format on caller-provided color.
    color = _parse_color(data.get("color")) or _default_color_for_type(project_type)

    # #62: priority is optional (nullable enum); priority_order is the
    # drag-set integer position within a type group. Accept the legacy
    # `sort_order` key too for backwards-compat with any caller that
    # hasn't been updated yet (will be removed once all callers cycle).
    priority = None
    if data.get("priority"):
        priority = _parse_enum(ProjectPriority, data["priority"], "priority")
    order_raw = data.get("priority_order", data.get("sort_order", 0))
    project = Project(
        name=name,
        type=project_type,
        color=color,
        target_quarter=(data.get("target_quarter") or "").strip() or None,
        actions=(data.get("actions") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        status=_parse_enum(ProjectStatus, data.get("status", "not_started"), "status"),
        priority=priority,
        goal_id=_parse_uuid(data.get("goal_id"), "goal_id"),
        priority_order=_parse_int(order_raw, "priority_order"),
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
    stmt = stmt.order_by(Project.priority_order.asc(), Project.name.asc())
    return list(db.session.scalars(stmt))


def reorder_projects(ordered_ids: list[uuid.UUID]) -> int:
    """Bulk-set priority_order for a list of project ids in display order.

    Each id at position i gets priority_order = i. Returns the number of
    projects updated. Ids that don't resolve are silently skipped.
    """
    by_id = {
        p.id: p for p in db.session.scalars(
            select(Project).where(Project.id.in_(ordered_ids))
        )
    }
    updated = 0
    for i, pid in enumerate(ordered_ids):
        p = by_id.get(pid)
        if p is None:
            continue
        p.priority_order = i
        updated += 1
    db.session.commit()
    return updated


_UPDATABLE_FIELDS = {
    "name", "type", "color", "target_quarter",
    "actions", "notes", "status", "priority",
    "goal_id", "is_active", "priority_order",
    # Legacy alias accepted for in-flight clients; mapped to priority_order.
    "sort_order",
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
        project.color = _parse_color(data["color"])  # PR28 audit fix #3

    if "target_quarter" in data:
        project.target_quarter = (data["target_quarter"] or "").strip() or None

    if "actions" in data:
        project.actions = (data["actions"] or "").strip() or None

    if "notes" in data:
        project.notes = (data["notes"] or "").strip() or None

    if "status" in data:
        project.status = _parse_enum(ProjectStatus, data["status"], "status")

    if "priority" in data:
        if data["priority"] in (None, ""):
            project.priority = None
        else:
            project.priority = _parse_enum(ProjectPriority, data["priority"], "priority")

    if "goal_id" in data:
        project.goal_id = _parse_uuid(data["goal_id"], "goal_id")

    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise ValidationError("is_active must be a boolean", "is_active")
        project.is_active = data["is_active"]

    # Accept either name; both write to priority_order.
    if "priority_order" in data or "sort_order" in data:
        raw = data.get("priority_order", data.get("sort_order"))
        try:
            project.priority_order = int(raw)
        except (TypeError, ValueError) as e:
            raise ValidationError("priority_order must be integer", "priority_order") from e

    unknown = set(data) - _UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}", next(iter(unknown)))

    db.session.commit()
    return project


def delete_project(project_id: uuid.UUID) -> bool:
    """Soft-delete a project and detach all tasks pointing at it.

    PR63 audit fix #129: previously this only flipped ``is_active=False``,
    leaving ``Task.project_id`` pointing at the now-inactive project.
    Joinedload queries returned the dead project; the UI rendered phantom
    project labels and ghost entries in the project filter dropdown. Now
    we also null the foreign key on every Task referencing this project.
    Goal cascade is unchanged (project deletion shouldn't drag a task off
    its goal — the goal is independent intent).
    """
    project = get_project(project_id)
    if project is None:
        return False
    project.is_active = False
    # Detach orphaned tasks. Bulk update so we don't pull every Task into
    # the session — there can be hundreds linked to a single project.
    Task.query.filter_by(project_id=project.id).update(
        {"project_id": None}, synchronize_session=False
    )
    db.session.commit()
    return True


# #90 (PR35, 2026-04-26): bulk-update toolbar on /projects. Mirrors
# task_service.bulk_update_tasks pattern — reuses update_project per
# row so cascade rules + validation behave identically to single-row
# PATCH. Errors on one row don't roll back the others (best-effort).
def bulk_update_projects(project_ids: list[uuid.UUID], updates: dict) -> dict:
    """Apply the same `updates` dict to every project in `project_ids`.

    Returns ``{"updated": int, "not_found": [ids], "errors": [{"id", "field", "message"}]}``.
    """
    updated = 0
    not_found: list[str] = []
    errors: list[dict] = []
    for pid in project_ids:
        try:
            project = update_project(pid, dict(updates))
        except ValidationError as e:
            errors.append({"id": str(pid), "field": e.field, "message": str(e)})
            # PR36 audit BUG-3: rollback only undoes pending unflushed
            # writes from THIS row — prior successfully-committed rows
            # stay durable. That's intentional ("best-effort" per the
            # docstring); the rollback is just to clear any partial
            # state from this row's failed update_project call so the
            # next iteration starts with a clean session.
            db.session.rollback()
            continue
        if project is None:
            not_found.append(str(pid))
            continue
        updated += 1
    return {
        "updated": updated,
        "not_found": not_found,
        "errors": errors,
    }


def bulk_delete_projects(project_ids: list[uuid.UUID]) -> dict:
    """Soft-delete (archive) every project in the list. Returns counts."""
    archived = 0
    not_found: list[str] = []
    for pid in project_ids:
        if delete_project(pid):
            archived += 1
        else:
            not_found.append(str(pid))
    return {"archived": archived, "not_found": not_found}
