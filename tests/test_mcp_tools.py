"""Tests for the five MCP connector tools (#522 / ADR-044).

``mcp_tools.call_tool`` is the layer between Claude's tool calls and
``task_service``: each tool passes only its own keys, so every task rule
(#386 sections by date, #475 project types, #474/#493 closed tasks, #433
subtasks) still applies. Refusals come back as ``isError`` results with a
message Claude can act on, never as an exception.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import pytest

from mcp_tools import TOOLS, UnknownTool, call_tool
from models import Project, ProjectType, Task, TaskStatus, TaskType, Tier
from models import db as _db
from utils import local_today_date


def _task(
    title="A task",
    *,
    type=TaskType.WORK,
    tier=Tier.INBOX,
    status=TaskStatus.ACTIVE,
    parent=None,
    project=None,
) -> Task:
    t = Task(title=title, type=type, tier=tier, status=status)
    if parent is not None:
        t.parent_id = parent.id
    if project is not None:
        t.project_id = project.id
    _db.session.add(t)
    _db.session.commit()
    return t


def _project(name, type=ProjectType.WORK) -> Project:
    p = Project(name=name, type=type)
    _db.session.add(p)
    _db.session.commit()
    return p


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _ok(result: dict) -> dict:
    assert result["isError"] is False, _text(result)
    return result["structuredContent"]


def _err(result: dict) -> str:
    assert result["isError"] is True, result
    assert "structuredContent" not in result
    return _text(result)


def test_tools_listed_in_order(app):
    assert [t["name"] for t in TOOLS] == [
        "create_task",
        "list_tasks",
        "complete_task",
        "update_task",
        "move_task",
    ]
    for tool in TOOLS:
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["description"]
    by_name = {t["name"]: t for t in TOOLS}
    assert by_name["list_tasks"]["annotations"]["readOnlyHint"] is True
    assert by_name["move_task"]["annotations"]["destructiveHint"] is True


def test_sections_in_board_order(app):
    """The spec's section list, in the board's order (Inbox first)."""
    section = TOOLS[0]["inputSchema"]["properties"]["section"]
    assert section["enum"] == [
        "inbox",
        "today",
        "tomorrow",
        "this_week",
        "next_week",
        "backlog",
        "freezer",
    ]
    assert set(section["enum"]) == {t.value for t in Tier}


class TestCreate:
    def test_create_minimal_lands_in_inbox(self, app):
        out = _ok(
            call_tool("create_task", {"title": "Draft Apigee vendor questions", "type": "work"})
        )
        assert out["task"]["section"] == "inbox"
        assert out["task"]["status"] == "open"
        assert _db.session.get(Task, uuid.UUID(out["task"]["id"])) is not None

    def test_create_with_date_files_by_date(self, app):
        tomorrow = local_today_date() + timedelta(days=1)
        out = _ok(
            call_tool(
                "create_task",
                {
                    "title": "Call vendor",
                    "type": "work",
                    "due_date": tomorrow.isoformat(),
                },
            )
        )
        assert out["task"]["section"] == "tomorrow"
        assert out["task"]["due_date"] == tomorrow.isoformat()

    def test_create_with_section(self, app):
        out = _ok(
            call_tool("create_task", {"title": "Someday", "type": "personal", "section": "backlog"})
        )
        assert out["task"]["section"] == "backlog"
        assert out["task"]["type"] == "personal"

    def test_create_with_project_by_name(self, app):
        _project("Apigee")
        out = _ok(call_tool("create_task", {"title": "Q", "type": "work", "project": "Apigee"}))
        assert out["task"]["project"] == "Apigee"

    def test_project_match_ignores_case_and_spaces(self, app):
        _project("Apigee")
        out = _ok(call_tool("create_task", {"title": "Q", "type": "work", "project": "  apigee "}))
        assert out["task"]["project"] == "Apigee"

    def test_project_duplicate_name_is_tool_error(self, app):
        _project("Apigee")
        _project("apigee")
        msg = _err(call_tool("create_task", {"title": "Q", "type": "work", "project": "Apigee"}))
        assert "2 work projects are named" in msg
        assert Task.query.count() == 0

    def test_unknown_project_names_the_choices(self, app):
        _project("Apigee")
        _project("Hiring")
        _project("Garden", ProjectType.PERSONAL)
        msg = _err(call_tool("create_task", {"title": "Q", "type": "work", "project": "Nope"}))
        assert 'No active work project is named "Nope"' in msg
        assert "Apigee, Hiring" in msg
        assert "Garden" not in msg

    def test_other_type_project_is_tool_error(self, app):
        _project("Apigee")
        msg = _err(
            call_tool("create_task", {"title": "Q", "type": "personal", "project": "Apigee"})
        )
        assert 'No active personal project is named "Apigee"' in msg

    def test_create_bad_date_is_tool_error(self, app):
        msg = _err(call_tool("create_task", {"title": "Q", "type": "work", "due_date": "Fri"}))
        assert "YYYY-MM-DD" in msg
        assert Task.query.count() == 0

    def test_create_long_title_is_tool_error(self, app):
        msg = _err(call_tool("create_task", {"title": "x" * 501, "type": "work"}))
        assert "too long" in msg
        assert Task.query.count() == 0

    def test_create_blank_title_is_tool_error(self, app):
        _err(call_tool("create_task", {"title": "   ", "type": "work"}))
        assert Task.query.count() == 0


class TestArguments:
    @pytest.mark.parametrize(
        "name,args,word",
        [
            ("create_task", {"title": "Q"}, "type"),
            ("create_task", {"title": "Q", "type": "chores"}, "type"),
            ("create_task", {"title": "Q", "type": "work", "priority": 1}, "priority"),
            ("create_task", {"title": 5, "type": "work"}, "title"),
            ("list_tasks", {"limit": 500}, "limit"),
            ("list_tasks", {"limit": "ten"}, "limit"),
            ("complete_task", {"task_id": "x", "complete_subtasks": "yes"}, "complete_subtasks"),
            ("move_task", {"task_id": "x"}, "section"),
        ],
    )
    def test_schema_errors_are_tool_errors(self, app, name, args, word):
        assert word in _err(call_tool(name, args))

    def test_unknown_tool_raises(self, app):
        with pytest.raises(UnknownTool):
            call_tool("delete_task", {"task_id": "x"})


class TestList:
    def test_list_defaults_open_top_50(self, app):
        for i in range(60):
            _task(f"t{i}")
        _task("done", status=TaskStatus.ARCHIVED)
        out = _ok(call_tool("list_tasks", {}))
        assert out["count"] == 50
        assert len(out["tasks"]) == 50
        assert {t["status"] for t in out["tasks"]} == {"open"}

    def test_list_filters(self, app):
        apigee = _project("Apigee")
        _task("in today", tier=Tier.TODAY)
        _task("personal", type=TaskType.PERSONAL)
        _task("on apigee", project=apigee)
        _task("finished", status=TaskStatus.ARCHIVED)

        def titles(args):
            return {t["title"] for t in _ok(call_tool("list_tasks", args))["tasks"]}

        assert titles({"section": "today"}) == {"in today"}
        assert titles({"type": "personal"}) == {"personal"}
        assert titles({"project": "apigee"}) == {"on apigee"}
        assert titles({"status": "completed"}) == {"finished"}
        assert len(_ok(call_tool("list_tasks", {"limit": 2}))["tasks"]) == 2

    def test_list_unknown_project_is_tool_error(self, app):
        assert "Nope" in _err(call_tool("list_tasks", {"project": "Nope"}))


class TestComplete:
    def test_complete_task(self, app):
        t = _task()
        out = _ok(call_tool("complete_task", {"task_id": str(t.id)}))
        assert out["task"]["status"] == "completed"

    def test_complete_with_open_subtasks_needs_flag(self, app):
        parent = _task("parent")
        subs = [_task("s1", parent=parent), _task("s2", parent=parent)]
        msg = _err(call_tool("complete_task", {"task_id": str(parent.id)}))
        assert "2 open subtasks" in msg
        assert "complete_subtasks: true" in msg
        assert _db.session.get(Task, parent.id).status == TaskStatus.ACTIVE

        _ok(call_tool("complete_task", {"task_id": str(parent.id), "complete_subtasks": True}))
        for t in (parent, *subs):
            assert _db.session.get(Task, t.id).status == TaskStatus.ARCHIVED


class TestClosedAndMissing:
    @pytest.mark.parametrize(
        "status", [TaskStatus.ARCHIVED, TaskStatus.CANCELLED, TaskStatus.DELETED]
    )
    @pytest.mark.parametrize(
        "name,extra",
        [
            ("complete_task", {}),
            ("update_task", {"title": "New"}),
            ("move_task", {"section": "today"}),
        ],
    )
    def test_closed_task_is_refused(self, app, status, name, extra):
        t = _task("closed", status=status)
        msg = _err(call_tool(name, {"task_id": str(t.id), **extra}))
        assert "only open tasks" in msg
        row = _db.session.get(Task, t.id)
        assert row.status == status
        assert row.title == "closed"
        assert row.tier == Tier.INBOX

    @pytest.mark.parametrize(
        "name,extra",
        [
            ("complete_task", {}),
            ("update_task", {"title": "New"}),
            ("move_task", {"section": "today"}),
        ],
    )
    def test_unknown_id_is_tool_error(self, app, name, extra):
        assert "No task with id" in _err(call_tool(name, {"task_id": str(uuid.uuid4()), **extra}))
        assert "task_id" in _err(call_tool(name, {"task_id": "abc", **extra}))


class TestUpdateAndMove:
    def test_update_fields(self, app):
        apigee = _project("Apigee")
        t = _task("old")
        when = local_today_date() + timedelta(days=30)
        out = _ok(
            call_tool(
                "update_task",
                {
                    "task_id": str(t.id),
                    "title": "new",
                    "notes": "n",
                    "due_date": when.isoformat(),
                    "project": "Apigee",
                },
            )
        )["task"]
        assert (out["title"], out["notes"], out["due_date"], out["project"]) == (
            "new",
            "n",
            when.isoformat(),
            "Apigee",
        )
        out = _ok(
            call_tool("update_task", {"task_id": str(t.id), "due_date": None, "project": None})
        )["task"]
        assert out["due_date"] is None
        assert out["project"] is None
        assert _db.session.get(Task, t.id).project_id is None
        assert apigee.id is not None

    def test_update_needs_a_field(self, app):
        t = _task()
        _err(call_tool("update_task", {"task_id": str(t.id)}))

    def test_move_task(self, app):
        t = _task()
        out = _ok(call_tool("move_task", {"task_id": str(t.id), "section": "next_week"}))
        assert out["task"]["section"] == "next_week"
        assert _db.session.get(Task, t.id).tier == Tier.NEXT_WEEK


def test_audit_lines_have_id_not_title(app, caplog):
    caplog.set_level(logging.INFO, logger="taskmanager.mcp")
    created = _ok(call_tool("create_task", {"title": "secret-title-xyz", "type": "work"}))
    task_id = created["task"]["id"]
    _ok(call_tool("move_task", {"task_id": task_id, "section": "today"}))

    messages = [r.getMessage() for r in caplog.records if r.name == "taskmanager.mcp"]
    assert f"mcp: created task {task_id}" in messages
    assert f"mcp: moved task {task_id} to today" in messages
    assert not any("secret-title-xyz" in m for m in messages)


# --- final-review fixes ------------------------------------------------------


def test_audit_lines_reach_the_default_log_level(app, caplog):
    """configure_logging persists WARNING and up by default (APP_LOG_LEVEL);
    an INFO audit line would never reach /api/debug/logs or stdout."""
    caplog.set_level(logging.DEBUG, logger="taskmanager.mcp")
    created = _ok(call_tool("create_task", {"title": "x", "type": "work"}))
    _ok(call_tool("list_tasks", {}))
    _ok(call_tool("move_task", {"task_id": created["task"]["id"], "section": "today"}))
    records = [r for r in caplog.records if r.name == "taskmanager.mcp"]
    assert len(records) == 3
    assert all(r.levelno >= logging.WARNING for r in records)


def test_overwriting_tools_are_marked_destructive(app):
    hints = {t["name"]: t["annotations"] for t in TOOLS}
    assert hints["create_task"]["destructiveHint"] is False
    for name in ("complete_task", "update_task", "move_task"):
        assert hints[name]["destructiveHint"] is True, name


def test_list_reports_total_when_cut(app):
    for i in range(60):
        _task(f"t{i}")
    result = call_tool("list_tasks", {})
    out = _ok(result)
    assert (out["count"], out["total"], out["truncated"]) == (50, 60, True)
    assert _text(result).endswith("Showing 50 of 60.")
    small = _ok(call_tool("list_tasks", {"limit": 100}))
    assert (small["count"], small["total"], small["truncated"]) == (60, 60, False)


def test_summary_shows_the_weekday(app):
    when = local_today_date() + timedelta(days=9)
    result = call_tool("create_task", {"title": "Q", "type": "work", "due_date": when.isoformat()})
    assert f"due {when.isoformat()} ({when.strftime('%a')})" in _text(result)


def test_bad_date_error_names_today(app):
    msg = _err(call_tool("create_task", {"title": "Q", "type": "work", "due_date": "Fri"}))
    today = local_today_date()
    assert msg.startswith("invalid date: 'Fri'. ")
    assert f"Today is {today.isoformat()} ({today.strftime('%a')})" in msg


def test_null_optional_arguments_count_as_absent(app):
    out = _ok(
        call_tool(
            "create_task",
            {
                "title": "Q",
                "type": "work",
                "section": None,
                "due_date": None,
                "project": None,
                "notes": None,
            },
        )
    )
    assert out["task"]["section"] == "inbox"
    assert (
        _ok(call_tool("list_tasks", {"section": None, "limit": None, "status": None}))["count"] == 1
    )
    # A required argument sent as null is still missing.
    assert "type" in _err(call_tool("create_task", {"title": "Q", "type": None}))


def test_completed_listed_newest_completion_first(app):
    from datetime import datetime

    first = _task("finished long ago", status=TaskStatus.ARCHIVED)
    second = _task("finished yesterday", status=TaskStatus.ARCHIVED)
    first.updated_at = datetime(2026, 10, 29, 12, 0)
    second.updated_at = datetime(2026, 10, 1, 12, 0)
    _db.session.commit()
    out = _ok(call_tool("list_tasks", {"status": "completed"}))
    assert [t["title"] for t in out["tasks"]] == ["finished long ago", "finished yesterday"]
