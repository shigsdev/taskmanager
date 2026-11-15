"""The tools the claude.ai MCP connector can call: five on tasks (#522,
ADR-044), three each on goals and projects (#530, ADR-045).

Each task tool is a thin wrapper over ``task_service``: it builds a ``data``
dict holding ONLY the keys the caller passed, so every rule the web app
gets still applies — a dated task files to its section (#386), a date
that doesn't fit a section is dropped (#466), a project of the other type
is refused (#475), closed or binned tasks are refused (#474, #493), open
subtasks close only on request (#433).

``call_tool`` never raises for a bad call: a refused rule or an argument
that breaks the tool's ``inputSchema`` comes back as an ``isError`` result
with a plain message, so Claude can correct itself (MCP 2025-11-25 moved
input validation errors to tool results). Only an unknown tool name
raises ``UnknownTool`` — the protocol layer answers that with ``-32602``.

The goal and project tools wrap ``goal_service`` / ``project_service`` the
same way. A project edit whose cascade can't be undone (#482 re-typing its
tasks, #351 clearing or flattening their goals) is refused until the call
says ``apply_to_tasks: true`` — the app's own confirm rule.

No tool deletes, cancels or archives anything, or touches recurring
templates, settings or exports. Audit lines (logger ``taskmanager.mcp``)
carry the id and the action only — never a title, name or notes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from goal_service import create_goal, get_goal, goal_progress_batch, list_goals, update_goal
from link_service import check_goal_link
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    Project,
    ProjectStatus,
    ProjectType,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)
from project_service import (
    create_project,
    get_project,
    list_projects,
    project_task_counts_batch,
    update_project,
)
from task_service import (
    complete_parent_task,
    create_task,
    get_task,
    list_subtasks,
    list_tasks,
    update_task,
)
from utils import ValidationError, local_today_date

logger = logging.getLogger("taskmanager.mcp")
# Audit lines go out at WARNING: configure_logging keeps WARNING and up by
# default (APP_LOG_LEVEL), so an INFO line would reach no log at all. Same
# reason the dev-bypass audit line is a WARNING.
_audit = logger.warning

# The board's order (static/app.js TIER_ORDER); the enum itself is unordered.
SECTIONS = ["inbox", "today", "tomorrow", "this_week", "next_week", "backlog", "freezer"]
TYPES = [t.value for t in TaskType]
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# What a task's status reads as to Claude.
_STATUS_WORD = {
    TaskStatus.ACTIVE: "open",
    TaskStatus.ARCHIVED: "completed",
    TaskStatus.CANCELLED: "cancelled",
    TaskStatus.DELETED: "deleted",
}
_CLOSED_PHRASE = {
    TaskStatus.ARCHIVED: "completed",
    TaskStatus.CANCELLED: "cancelled",
    TaskStatus.DELETED: "in the Recycle Bin",
}
_LIST_STATUS = {"open": TaskStatus.ACTIVE, "completed": TaskStatus.ARCHIVED}


class UnknownTool(Exception):
    """``call_tool`` was asked for a tool that isn't in ``TOOLS``."""


_TASK_ID = {"type": "string", "description": "The task's id, from list_tasks or a previous result."}
_SECTION = {
    "type": "string",
    "enum": SECTIONS,
    "description": "A board section.",
}
# MCP: destructiveHint false means "only additive updates" — true of
# create_task alone; completing, moving and editing change what was there.
_ADD = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
_CHANGE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}

TOOLS: list[dict] = [
    {
        "name": "create_task",
        "title": "Create a task",
        "description": (
            "Add a task. It lands in the Inbox unless a due_date or section "
            "places it; a due date files it to the section that date falls in."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "What to do."},
                "type": {"type": "string", "enum": TYPES, "description": "Work or personal."},
                "due_date": {"type": "string", "format": "date", "description": "YYYY-MM-DD."},
                "section": _SECTION,
                "project": {
                    "type": "string",
                    "description": "An active project's exact name, of the same type.",
                },
                "notes": {"type": "string"},
            },
            "required": ["title", "type"],
            "additionalProperties": False,
        },
        "annotations": _ADD,
    },
    {
        "name": "list_tasks",
        "title": "List tasks",
        "description": (
            "List tasks, open ones by default, filtered by section, type, project or status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": _SECTION,
                "type": {"type": "string", "enum": TYPES},
                "project": {"type": "string", "description": "An active project's exact name."},
                "status": {"type": "string", "enum": list(_LIST_STATUS), "default": "open"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "default": DEFAULT_LIMIT,
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "complete_task",
        "title": "Complete a task",
        "description": (
            "Mark an open task completed. If it has open subtasks, pass "
            "complete_subtasks: true to complete them too."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": _TASK_ID,
                "complete_subtasks": {"type": "boolean", "default": False},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
        "annotations": _CHANGE,
    },
    {
        "name": "update_task",
        "title": "Edit a task",
        "description": (
            "Change an open task's title, due date, notes or project. "
            "due_date or project set to null clears it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": _TASK_ID,
                "title": {"type": "string"},
                "due_date": {
                    "type": ["string", "null"],
                    "format": "date",
                    "description": "YYYY-MM-DD, or null to clear.",
                },
                "notes": {"type": "string"},
                "project": {
                    "type": ["string", "null"],
                    "description": "An active project's exact name, or null to clear.",
                },
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
        "annotations": _CHANGE,
    },
    {
        "name": "move_task",
        "title": "Move a task",
        "description": "Move an open task to another section.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": _TASK_ID, "section": _SECTION},
            "required": ["task_id", "section"],
            "additionalProperties": False,
        },
        "annotations": _CHANGE,
    },
]

# --- goals and projects (#530, ADR-045) ---------------------------------------
# No tool archives or deletes either one: archiving pauses repeating tasks
# (#353 / #368), and both stay in the app, as task delete / cancel do.

CATEGORIES = [c.value for c in GoalCategory]
PRIORITIES = [p.value for p in GoalPriority]  # ProjectPriority has the same values
STATUSES = [s.value for s in GoalStatus]  # ProjectStatus has the same values
PROJECT_TYPES = [t.value for t in ProjectType]

_GOAL_ID = {"type": "string", "description": "The goal's id, from list_goals or a previous result."}
_PROJECT_ID = {
    "type": "string",
    "description": "The project's id, from list_projects or a previous result.",
}
_QUARTER = {"type": "string", "description": "Target quarter, free text."}
_TEXT_CLEARS = "An empty string clears it."

TOOLS += [
    {
        "name": "list_goals",
        "title": "List goals",
        "description": (
            "List active goals (archived: true for archived ones) with their "
            "progress, filtered by category, priority or status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "priority": {"type": "string", "enum": PRIORITIES},
                "status": {"type": "string", "enum": STATUSES},
                "archived": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "create_goal",
        "title": "Create a goal",
        "description": "Add a goal. It starts not_started unless a status is given.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "category": {"type": "string", "enum": CATEGORIES},
                "priority": {"type": "string", "enum": PRIORITIES},
                "status": {"type": "string", "enum": STATUSES},
                "target_quarter": _QUARTER,
                "actions": {"type": "string", "description": "The steps toward it."},
                "notes": {"type": "string"},
            },
            "required": ["title", "category", "priority"],
            "additionalProperties": False,
        },
        "annotations": _ADD,
    },
    {
        "name": "update_goal",
        "title": "Edit a goal",
        "description": (
            "Change an active goal's title, category, priority, status, target "
            f"quarter, actions or notes. target_quarter null clears it. {_TEXT_CLEARS}"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal_id": _GOAL_ID,
                "title": {"type": "string"},
                "category": {"type": "string", "enum": CATEGORIES},
                "priority": {"type": "string", "enum": PRIORITIES},
                "status": {"type": "string", "enum": STATUSES},
                "target_quarter": {**_QUARTER, "type": ["string", "null"]},
                "actions": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["goal_id"],
            "additionalProperties": False,
        },
        "annotations": _CHANGE,
    },
    {
        "name": "list_projects",
        "title": "List projects",
        "description": (
            "List active projects (archived: true for archived ones) with their "
            "goal and task counts, filtered by type or status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": PROJECT_TYPES},
                "status": {"type": "string", "enum": STATUSES},
                "archived": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "create_project",
        "title": "Create a project",
        "description": (
            "Add a Work or Personal project, optionally on an active goal. Its "
            "name must not match another active project of the same type."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "enum": PROJECT_TYPES},
                "goal_id": _GOAL_ID,
                "priority": {"type": "string", "enum": PRIORITIES},
                "status": {"type": "string", "enum": STATUSES},
                "target_quarter": _QUARTER,
                "actions": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name", "type"],
            "additionalProperties": False,
        },
        "annotations": _ADD,
    },
    {
        "name": "update_project",
        "title": "Edit a project",
        "description": (
            "Change an active project's name, type, goal, priority, status, target "
            "quarter, actions or notes. goal_id, priority or target_quarter null "
            f"clears it. {_TEXT_CLEARS} A new type re-types the project's tasks, "
            "and a new goal moves its tasks to that goal: when that can't be "
            "undone the call is refused with what would change — pass "
            "apply_to_tasks: true to go ahead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": _PROJECT_ID,
                "name": {"type": "string"},
                "type": {"type": "string", "enum": PROJECT_TYPES},
                "goal_id": {**_GOAL_ID, "type": ["string", "null"]},
                "priority": {"type": ["string", "null"], "enum": PRIORITIES},
                "status": {"type": "string", "enum": STATUSES},
                "target_quarter": {**_QUARTER, "type": ["string", "null"]},
                "actions": {"type": "string"},
                "notes": {"type": "string"},
                "apply_to_tasks": {"type": "boolean", "default": False},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        "annotations": _CHANGE,
    },
]
_SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOLS}


# --- argument checking -----------------------------------------------------


def _is_type(value: Any, json_type: str) -> bool:
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "null":
        return value is None
    return False


def _check_args(schema: dict, args: dict) -> str | None:
    """The first way ``args`` breaks ``schema``, as a sentence, or None.
    Covers only what ``TOOLS`` uses: required, additionalProperties,
    type, enum, integer minimum / maximum."""
    props = schema["properties"]
    for key in schema.get("required", []):
        if key not in args:
            return f"Missing required argument: {key}."
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            return f"Unknown argument: {key}. This tool takes: {', '.join(props)}."
        types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not any(_is_type(value, t) for t in types):
            return f"{key} must be {' or '.join(types)}."
        if value is None:
            continue
        if "enum" in spec and value not in spec["enum"]:
            return f"{key} must be one of: {', '.join(spec['enum'])}."
        if "minimum" in spec and value < spec["minimum"]:
            return f"{key} must be at least {spec['minimum']}."
        if "maximum" in spec and value > spec["maximum"]:
            return f"{key} must be at most {spec['maximum']}."
    return None


# --- shared helpers ----------------------------------------------------------


def _label(section: str) -> str:
    return section.replace("_", " ").title()


def task_view(task: Task) -> dict:
    project = db.session.get(Project, task.project_id) if task.project_id else None
    return {
        "id": str(task.id),
        "title": task.title,
        "section": task.tier.value,
        "type": task.type.value,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "project": project.name if project else None,
        "notes": task.notes,
        "status": _STATUS_WORD.get(task.status, task.status.value),
    }


def _resolve_project(name: str, task_type: TaskType | None) -> uuid.UUID:
    """An active project by exact name (case and outer spaces ignored),
    of ``task_type`` when given. Raises ``ValidationError``."""
    projects = list(db.session.scalars(select(Project).where(Project.is_active.is_(True))))
    if task_type is not None:
        projects = [p for p in projects if p.type.value == task_type.value]
    kind = f"{task_type.value} project" if task_type else "project"
    needle = name.strip().casefold()
    matches = [p for p in projects if p.name.strip().casefold() == needle]
    if len(matches) == 1:
        return matches[0].id
    if matches:
        raise ValidationError(
            f'{len(matches)} {kind}s are named "{name.strip()}" — rename one in the app first.',
            "project",
        )
    missing = f'No active {kind} is named "{name.strip()}".'
    if not projects:
        raise ValidationError(f"{missing} There are no active {kind}s.", "project")
    names = ", ".join(sorted(p.name for p in projects))
    raise ValidationError(f"{missing} {kind.capitalize()}s: {names}.", "project")


def _open_task(raw_id: str) -> Task:
    """The open task ``raw_id`` names. Raises ``ValidationError``."""
    try:
        task_id = uuid.UUID(raw_id)
    except ValueError as e:
        raise ValidationError(
            f"task_id must be a task id (a UUID), not {raw_id!r}.", "task_id"
        ) from e
    task = get_task(task_id)
    if task is None:
        raise ValidationError(f"No task with id {raw_id}.", "task_id")
    if task.status != TaskStatus.ACTIVE:
        raise ValidationError(
            f"That task is {_CLOSED_PHRASE.get(task.status, task.status.value)} — "
            "only open tasks can be changed.",
            "task_id",
        )
    return task


def _summary(verb: str, task: Task) -> str:
    view = task_view(task)
    parts = [f'{verb} "{view["title"]}" in {_label(view["section"])}']
    if task.due_date:
        parts.append(f"due {_day(task.due_date)}")
    if view["project"]:
        parts.append(f"project {view['project']}")
    return ", ".join(parts) + f" (id {view['id']})."


def _day(d: date) -> str:
    """``2026-11-06 (Fri)`` — the weekday shows what a relative date
    ("due Fri") resolved to."""
    return f"{d.isoformat()} ({d.strftime('%a')})"


def _result(text: str, structured: dict) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": False,
    }


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# --- the tools ---------------------------------------------------------------


def _create(args: dict) -> dict:
    data: dict[str, Any] = {"title": args["title"], "type": args["type"]}
    if "due_date" in args:
        data["due_date"] = args["due_date"]
    if "section" in args:
        data["tier"] = args["section"]
    if "notes" in args:
        data["notes"] = args["notes"]
    if "project" in args:
        data["project_id"] = _resolve_project(args["project"], TaskType(args["type"]))
    task = create_task(data)
    _audit("mcp: created task %s", task.id)
    return _result(_summary("Created", task), {"task": task_view(task)})


def _list(args: dict) -> dict:
    task_type = TaskType(args["type"]) if "type" in args else None
    project_id = _resolve_project(args["project"], task_type) if "project" in args else None
    status = _LIST_STATUS[args.get("status", "open")]
    matching = list_tasks(
        tier=Tier(args["section"]) if "section" in args else None,
        type=task_type,
        status=status,
        project_id=project_id,
    )
    if status == TaskStatus.ARCHIVED:
        # Most recently completed first ("what did I finish today?").
        matching.sort(key=lambda t: t.updated_at, reverse=True)
    total = len(matching)
    views = [task_view(t) for t in matching[: args.get("limit", DEFAULT_LIMIT)]]
    _audit("mcp: listed %d tasks", len(views))
    lines = []
    for v in views:
        line = f"- {v['title']} · {_label(v['section'])}"
        if v["due_date"]:
            line += f" · due {_day(date.fromisoformat(v['due_date']))}"
        if v["project"]:
            line += f" · {v['project']}"
        lines.append(line + f" (id {v['id']})")
    text = "\n".join(lines) or "No tasks match."
    if total > len(views):
        text += f"\nShowing {len(views)} of {total}."
    structured = {
        "tasks": views,
        "count": len(views),
        "total": total,
        "truncated": total > len(views),
    }
    return _result(text, structured)


def _complete(args: dict) -> dict:
    task = _open_task(args["task_id"])
    try:
        done = complete_parent_task(task.id, complete_subtasks=args.get("complete_subtasks", False))
    except ValidationError as e:
        if e.field != "subtasks":
            raise
        count = len(list_subtasks(task.id))
        raise ValidationError(
            f"This task has {count} open subtasks. Call complete_task again with "
            "complete_subtasks: true to complete them too.",
            "subtasks",
        ) from e
    _audit("mcp: completed task %s", done.id)
    return _result(_summary("Completed", done), {"task": task_view(done)})


def _update(args: dict) -> dict:
    task = _open_task(args["task_id"])
    fields = [k for k in ("title", "due_date", "notes", "project") if k in args]
    if not fields:
        raise ValidationError(
            "Pass at least one of title, due_date, notes or project to change.", "task_id"
        )
    data: dict[str, Any] = {k: args[k] for k in fields if k != "project"}
    if "project" in args:
        data["project_id"] = (
            None if args["project"] is None else _resolve_project(args["project"], task.type)
        )
    updated = update_task(task.id, data)
    _audit("mcp: updated task %s (%s)", updated.id, ", ".join(fields))
    return _result(_summary("Updated", updated), {"task": task_view(updated)})


def _move(args: dict) -> dict:
    task = _open_task(args["task_id"])
    moved = update_task(task.id, {"tier": args["section"]})
    _audit("mcp: moved task %s to %s", moved.id, moved.tier.value)
    return _result(_summary("Moved", moved), {"task": task_view(moved)})


# --- goal and project tools (#530, ADR-045) ----------------------------------

_GOAL_FIELDS = ("title", "category", "priority", "status", "target_quarter", "actions", "notes")
_PROJECT_FIELDS = (
    "name", "type", "goal_id", "priority", "status", "target_quarter", "actions", "notes",
)


def _word(value: str) -> str:
    """``personal_growth`` → ``Personal growth``; ``bau`` → ``BAU``."""
    return "BAU" if value == "bau" else value.replace("_", " ").capitalize()


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _uuid_arg(raw: str, field: str, noun: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as e:
        raise ValidationError(f"{field} must be a {noun} id (a UUID), not {raw!r}.", field) from e


def goal_view(goal: Goal, progress: dict | None = None) -> dict:
    if progress is None:
        progress = goal_progress_batch([goal.id])[goal.id]
    return {
        "id": str(goal.id),
        "title": goal.title,
        "category": goal.category.value,
        "priority": goal.priority.value,
        "status": goal.status.value,
        "target_quarter": goal.target_quarter,
        "actions": goal.actions,
        "notes": goal.notes,
        "archived": not goal.is_active,
        "progress": {"total": progress["total"], "completed": progress["completed"]},
    }


def project_view(project: Project, counts: dict | None = None, goal: Goal | None = None) -> dict:
    if counts is None:
        counts = project_task_counts_batch([project.id])[project.id]
    if goal is None and project.goal_id:
        goal = db.session.get(Goal, project.goal_id)
    return {
        "id": str(project.id),
        "name": project.name,
        "type": project.type.value,
        "status": project.status.value,
        "priority": project.priority.value if project.priority else None,
        "target_quarter": project.target_quarter,
        "goal": {"id": str(goal.id), "title": goal.title} if goal else None,
        "actions": project.actions,
        "notes": project.notes,
        "archived": not project.is_active,
        "task_counts": counts,
    }


def _goal_summary(verb: str, goal: Goal) -> str:
    parts = [_word(goal.category.value), _word(goal.priority.value), _word(goal.status.value)]
    if goal.target_quarter:
        parts.append(goal.target_quarter)
    return f'{verb} goal "{goal.title}" ({", ".join(parts)}) (id {goal.id}).'


def _project_summary(verb: str, project: Project) -> str:
    parts = [_word(project.type.value), _word(project.status.value)]
    goal = db.session.get(Goal, project.goal_id) if project.goal_id else None
    if goal:
        parts.append(f'goal "{goal.title}"')
    return f'{verb} project "{project.name}" ({", ".join(parts)}) (id {project.id}).'


def _open_goal(raw_id: str) -> Goal:
    goal = get_goal(_uuid_arg(raw_id, "goal_id", "goal"))
    if goal is None:
        raise ValidationError(f"No goal with id {raw_id}.", "goal_id")
    if not goal.is_active:
        raise ValidationError(
            f'The goal "{goal.title}" is archived — only active goals can be changed.',
            "goal_id",
        )
    return goal


def _open_project(raw_id: str) -> Project:
    project = get_project(_uuid_arg(raw_id, "project_id", "project"))
    if project is None:
        raise ValidationError(f"No project with id {raw_id}.", "project_id")
    if not project.is_active:
        raise ValidationError(
            f'The project "{project.name}" is archived — only active projects can be changed.',
            "project_id",
        )
    return project


def _check_unique_name(name: str, project_type: str, own_id: uuid.UUID | None = None) -> None:
    """The task tools name a project by its name among the active ones of a
    type, so a twin would make both unusable there (``_resolve_project``)."""
    needle = name.strip().casefold()
    for p in list_projects(project_type=ProjectType(project_type)):
        if p.id != own_id and p.name.strip().casefold() == needle:
            raise ValidationError(
                f'There\'s already a {project_type} project named "{p.name}" — pick another name.',
                "name",
            )


def _goal_titles(ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {g.id: g.title for g in db.session.scalars(select(Goal).where(Goal.id.in_(ids)))}


def _list_goals(args: dict) -> dict:
    goals = list_goals(
        category=GoalCategory(args["category"]) if "category" in args else None,
        priority=GoalPriority(args["priority"]) if "priority" in args else None,
        status=GoalStatus(args["status"]) if "status" in args else None,
        is_active=not args.get("archived", False),
    )
    progress = goal_progress_batch([g.id for g in goals])
    views = [goal_view(g, progress[g.id]) for g in goals]
    _audit("mcp: listed %d goals", len(views))
    lines = [
        f"- {v['title']} · {_word(v['category'])} · {_word(v['priority'])} · "
        f"{_word(v['status'])} · {v['progress']['completed']}/{v['progress']['total']} "
        f"tasks done (id {v['id']})"
        for v in views
    ]
    return _result("\n".join(lines) or "No goals match.", {"goals": views, "count": len(views)})


def _create_goal(args: dict) -> dict:
    goal = create_goal({k: args[k] for k in _GOAL_FIELDS if k in args})
    _audit("mcp: created goal %s", goal.id)
    return _result(_goal_summary("Created", goal), {"goal": goal_view(goal)})


def _update_goal(args: dict) -> dict:
    goal = _open_goal(args["goal_id"])
    fields = [k for k in _GOAL_FIELDS if k in args]
    if not fields:
        raise ValidationError(
            f"Pass at least one of {', '.join(_GOAL_FIELDS)} to change.", "goal_id"
        )
    updated = update_goal(goal.id, {k: args[k] for k in fields})
    _audit("mcp: updated goal %s (%s)", updated.id, ", ".join(fields))
    return _result(_goal_summary("Updated", updated), {"goal": goal_view(updated)})


def _list_projects(args: dict) -> dict:
    projects = list_projects(
        is_active=not args.get("archived", False),
        project_type=ProjectType(args["type"]) if "type" in args else None,
    )
    if "status" in args:
        projects = [p for p in projects if p.status == ProjectStatus(args["status"])]
    counts = project_task_counts_batch([p.id for p in projects])
    goals = {g.id: g for g in db.session.scalars(
        select(Goal).where(Goal.id.in_([p.goal_id for p in projects if p.goal_id]))
    )} if any(p.goal_id for p in projects) else {}
    views = [project_view(p, counts[p.id], goals.get(p.goal_id)) for p in projects]
    _audit("mcp: listed %d projects", len(views))
    lines = []
    for v in views:
        line = (
            f"- {v['name']} · {_word(v['type'])} · {_word(v['status'])} · "
            f"{v['task_counts']['active']} open, {v['task_counts']['done']} done"
        )
        if v["goal"]:
            line += f" · goal {v['goal']['title']}"
        lines.append(line + f" (id {v['id']})")
    return _result(
        "\n".join(lines) or "No projects match.", {"projects": views, "count": len(views)}
    )


def _create_project(args: dict) -> dict:
    _check_unique_name(args["name"], args["type"])
    data = {k: args[k] for k in _PROJECT_FIELDS if k in args}
    if "goal_id" in data:
        data["goal_id"] = str(_uuid_arg(data["goal_id"], "goal_id", "goal"))
    project = create_project(data)
    _audit("mcp: created project %s", project.id)
    return _result(_project_summary("Created", project), {"project": project_view(project)})


def _type_change_warning(project: Project, new_type: str) -> str | None:
    """#482: a new type re-types every task on the project (any status),
    their subtasks, and its repeating tasks — the rows
    ``project_service._retype_project_items`` touches. None when nothing
    moves: an empty project changes type without asking."""
    task_ids = set(db.session.scalars(select(Task.id).where(Task.project_id == project.id)))
    if task_ids:
        task_ids |= set(db.session.scalars(select(Task.id).where(Task.parent_id.in_(task_ids))))
    templates = db.session.scalar(
        select(func.count()).select_from(RecurringTask)
        .where(RecurringTask.project_id == project.id)
    )
    if not task_ids and not templates:
        return None
    parts = []
    if task_ids:
        parts.append(_count(len(task_ids), "task", "tasks"))
    if templates:
        parts.append(_count(templates, "repeating task", "repeating tasks"))
    verb = "becomes" if len(task_ids) + templates == 1 else "become"
    return f'{" and ".join(parts)} on "{project.name}" {verb} {_word(new_type)} too.'


def _goal_change_warning(project: Project, new_goal_id: uuid.UUID | None) -> str | None:
    """#350/#351/#352: a new goal is written onto every task and repeating
    task on the project. The app asks first when that can't be taken back —
    goals cleared from tasks, or tasks on several goals collapsed onto one
    (the project stores one goal, so nothing remembers the spread). A
    one-goal move, or adding a goal where there was none, asks nothing.
    Same rule as static/goal_project_drag_helpers.js."""
    task_goals = list(db.session.scalars(select(Task.goal_id).where(Task.project_id == project.id)))
    template_goals = list(db.session.scalars(
        select(RecurringTask.goal_id).where(RecurringTask.project_id == project.id)
    ))
    changing_tasks = [g for g in task_goals if g != new_goal_id]
    changing_templates = [g for g in template_goals if g != new_goal_id]
    clearing = new_goal_id is None and any(g is not None for g in changing_tasks)
    lost: dict[uuid.UUID, int] = {}
    for g in changing_tasks + changing_templates:
        if g is not None:
            lost[g] = lost.get(g, 0) + 1
    if not clearing and len(lost) < 2:
        return None
    titles = _goal_titles(lost)
    ranked = sorted(lost.items(), key=lambda kv: (-kv[1], titles.get(kv[0], "")))
    spread = ", ".join(
        f'"{titles.get(g, "a goal you can no longer see")}" ({n})' for g, n in ranked
    )
    moved = _count(len(changing_tasks), "task", "tasks")
    if changing_templates:
        moved += " and " + _count(len(changing_templates), "repeating task", "repeating tasks")
    if clearing:
        return (
            f'Clearing the goal of "{project.name}" also clears it from {moved}, '
            f"now on {spread}. There is no undo."
        )
    target = titles.get(new_goal_id) or db.session.get(Goal, new_goal_id).title
    return (
        f'Moving "{project.name}" to "{target}" moves {moved} there from {spread}; '
        "moving the project back can't restore that spread."
    )


def _update_project(args: dict) -> dict:
    project = _open_project(args["project_id"])
    fields = [k for k in _PROJECT_FIELDS if k in args]
    if not fields:
        raise ValidationError(
            f"Pass at least one of {', '.join(_PROJECT_FIELDS)} to change.", "project_id"
        )
    data = {k: args[k] for k in fields}
    new_goal_id = project.goal_id
    if data.get("goal_id") is not None:
        new_goal_id = _uuid_arg(data["goal_id"], "goal_id", "goal")
        data["goal_id"] = str(new_goal_id)
        if new_goal_id != project.goal_id:
            check_goal_link(new_goal_id)  # #475, before asking about it
    elif "goal_id" in data:
        new_goal_id = None

    final_type = data.get("type", project.type.value)
    if "name" in data or "type" in data:
        _check_unique_name(data.get("name", project.name), final_type, own_id=project.id)

    warnings = []
    if final_type != project.type.value:
        warnings.append(_type_change_warning(project, final_type))
    if new_goal_id != project.goal_id:
        warnings.append(_goal_change_warning(project, new_goal_id))
    warnings = [w for w in warnings if w]
    if warnings and not args.get("apply_to_tasks", False):
        raise ValidationError(
            " ".join(warnings) + " Nothing was changed. Check with the user, then call "
            "update_project again with apply_to_tasks: true to go ahead.",
            "apply_to_tasks",
        )

    updated = update_project(project.id, data)
    _audit("mcp: updated project %s (%s)", updated.id, ", ".join(fields))
    return _result(_project_summary("Updated", updated), {"project": project_view(updated)})


_HANDLERS = {
    "create_task": _create,
    "list_tasks": _list,
    "complete_task": _complete,
    "update_task": _update,
    "move_task": _move,
    "list_goals": _list_goals,
    "create_goal": _create_goal,
    "update_goal": _update_goal,
    "list_projects": _list_projects,
    "create_project": _create_project,
    "update_project": _update_project,
}


def call_tool(name: str, arguments: dict) -> dict:
    """Run one tool and return its MCP ``CallToolResult``."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise UnknownTool(name)
    schema = _SCHEMAS[name]
    arguments = _drop_null_optionals(schema, arguments)
    problem = _check_args(schema, arguments)
    if problem:
        return _error(problem)
    try:
        return handler(arguments)
    except ValidationError as e:
        db.session.rollback()
        message = str(e)
        if e.field == "due_date":
            message += f". Today is {_day(local_today_date())}. Use a YYYY-MM-DD date."
        return _error(message)


def _drop_null_optionals(schema: dict, args: dict) -> dict:
    """An optional argument sent as null means "not given" — models often
    fill every optional field. Where null means something (update_task's
    due_date / project: clear it), the schema allows it and it stays."""
    required = set(schema.get("required", []))
    props = schema["properties"]

    def nullable(key: str) -> bool:
        spec = props.get(key, {})
        types = spec.get("type", [])
        return "null" in (types if isinstance(types, list) else [types])

    return {
        k: v
        for k, v in args.items()
        if not (v is None and k in props and k not in required and not nullable(k))
    }
