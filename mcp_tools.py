"""The five tools the claude.ai MCP connector can call (#522, ADR-044).

Each tool is a thin wrapper over ``task_service``: it builds a ``data``
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

No tool deletes, cancels, or touches goals, recurring templates, settings
or exports. Audit lines (logger ``taskmanager.mcp``) carry the task id and
the action only — never a title or notes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from models import Project, Task, TaskStatus, TaskType, Tier, db
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


_HANDLERS = {
    "create_task": _create,
    "list_tasks": _list,
    "complete_task": _complete,
    "update_task": _update,
    "move_task": _move,
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
