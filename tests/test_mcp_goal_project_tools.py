"""Tests for the MCP connector's goal and project tools (#530 / ADR-045).

Six tools sit beside the five task tools: ``list_goals``, ``create_goal``,
``update_goal``, ``list_projects``, ``create_project``, ``update_project``.
Each wraps ``goal_service`` / ``project_service`` with only its own keys,
so every rule the app has still applies. None archives or deletes.

A project edit that rewrites rows you can't get back (#482 a type change
that re-types its tasks; #350/#351 a goal change that clears or flattens
its tasks' goals) is refused until Claude calls again with
``apply_to_tasks: true`` — the same rule the app's confirms follow, so the
quiet cases (an empty project, a one-goal move) ask nothing.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from mcp_tools import TOOLS, call_tool
from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    Project,
    ProjectType,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
)
from models import db as _db


def _goal(title="Ship Apigee", *, category=GoalCategory.WORK, active=True) -> Goal:
    g = Goal(title=title, category=category, priority=GoalPriority.MUST, is_active=active)
    _db.session.add(g)
    _db.session.commit()
    return g


def _project(name="Apigee", type=ProjectType.WORK, *, goal=None, active=True) -> Project:
    p = Project(name=name, type=type, is_active=active)
    if goal is not None:
        p.goal_id = goal.id
    _db.session.add(p)
    _db.session.commit()
    return p


def _task(project, *, goal=None, status=TaskStatus.ACTIVE, type=TaskType.WORK) -> Task:
    t = Task(title="A task", type=type, tier=Tier.INBOX, status=status, project_id=project.id)
    if goal is not None:
        t.goal_id = goal.id
    _db.session.add(t)
    _db.session.commit()
    return t


def _template(project, *, goal=None) -> RecurringTask:
    r = RecurringTask(
        title="Weekly sync", type=TaskType.WORK, frequency=RecurringFrequency.WEEKLY,
        day_of_week=0, project_id=project.id,
    )
    if goal is not None:
        r.goal_id = goal.id
    _db.session.add(r)
    _db.session.commit()
    return r


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _ok(result: dict) -> dict:
    assert result["isError"] is False, _text(result)
    return result["structuredContent"]


def _err(result: dict) -> str:
    assert result["isError"] is True, result
    return _text(result)


def test_new_tools_listed_after_the_task_tools(app):
    assert [t["name"] for t in TOOLS][5:] == [
        "list_goals",
        "create_goal",
        "update_goal",
        "list_projects",
        "create_project",
        "update_project",
    ]
    by_name = {t["name"]: t for t in TOOLS}
    for name in ("list_goals", "list_projects"):
        assert by_name[name]["annotations"]["readOnlyHint"] is True
    for name in ("create_goal", "create_project"):
        assert by_name[name]["annotations"]["destructiveHint"] is False
    for name in ("update_goal", "update_project"):
        assert by_name[name]["annotations"]["destructiveHint"] is True
    for tool in TOOLS:
        assert tool["inputSchema"]["additionalProperties"] is False


def test_no_tool_archives_or_deletes(app):
    """ADR-045 keeps ADR-044's line: nothing is archived or deleted."""
    for tool in TOOLS:
        assert "is_active" not in tool["inputSchema"]["properties"]
        assert "archive" not in tool["name"] and "delete" not in tool["name"]


class TestGoals:
    def test_create_goal(self, app):
        out = _ok(call_tool("create_goal", {
            "title": "Run a half marathon", "category": "health", "priority": "should",
            "target_quarter": "2027-Q1", "actions": "3 runs a week",
        }))
        goal = _db.session.get(Goal, uuid.UUID(out["goal"]["id"]))
        assert goal.title == "Run a half marathon"
        assert goal.category == GoalCategory.HEALTH
        assert goal.status == GoalStatus.NOT_STARTED
        assert out["goal"]["target_quarter"] == "2027-Q1"
        assert out["goal"]["archived"] is False

    @pytest.mark.parametrize("missing", ["title", "category", "priority"])
    def test_create_goal_needs_title_category_priority(self, app, missing):
        args = {"title": "G", "category": "work", "priority": "must"}
        del args[missing]
        assert missing in _err(call_tool("create_goal", args))
        assert Goal.query.count() == 0

    def test_create_goal_long_title_refused(self, app):
        assert "too long" in _err(call_tool(
            "create_goal", {"title": "x" * 501, "category": "work", "priority": "must"},
        ))
        assert Goal.query.count() == 0

    def test_list_goals_active_by_default_with_progress(self, app):
        g = _goal("Ship Apigee")
        _goal("Old goal", active=False)
        p = _project(goal=g)
        _task(p, goal=g)
        _task(p, goal=g, status=TaskStatus.ARCHIVED)
        out = _ok(call_tool("list_goals", {}))
        assert [v["title"] for v in out["goals"]] == ["Ship Apigee"]
        assert out["goals"][0]["progress"] == {"total": 2, "completed": 1}
        assert "Ship Apigee" in _text(call_tool("list_goals", {}))

    def test_list_goals_filters(self, app):
        _goal("Work one")
        _goal("Gym", category=GoalCategory.HEALTH)
        _goal("Old", active=False)
        health = _ok(call_tool("list_goals", {"category": "health"}))["goals"]
        assert [v["title"] for v in health] == ["Gym"]
        archived = _ok(call_tool("list_goals", {"archived": True}))["goals"]
        assert [v["title"] for v in archived] == ["Old"]
        assert archived[0]["archived"] is True

    def test_update_goal_changes_only_given_fields(self, app):
        g = _goal("Ship Apigee")
        out = _ok(call_tool("update_goal", {"goal_id": str(g.id), "status": "in_progress"}))
        assert out["goal"]["status"] == "in_progress"
        assert out["goal"]["title"] == "Ship Apigee"
        assert out["goal"]["priority"] == "must"

    def test_update_goal_clears_quarter(self, app):
        g = _goal()
        g.target_quarter = "2026-Q4"
        _db.session.commit()
        _ok(call_tool("update_goal", {"goal_id": str(g.id), "target_quarter": None}))
        assert _db.session.get(Goal, g.id).target_quarter is None

    def test_update_goal_needs_a_field(self, app):
        g = _goal()
        assert "at least one" in _err(call_tool("update_goal", {"goal_id": str(g.id)}))

    def test_update_archived_goal_refused(self, app):
        g = _goal(active=False)
        msg = _err(call_tool("update_goal", {"goal_id": str(g.id), "title": "New"}))
        assert "archived" in msg
        assert _db.session.get(Goal, g.id).title == "Ship Apigee"

    @pytest.mark.parametrize(
        "raw", ["nope", "00000000-0000-4000-8000-000000000530"], ids=["not-a-uuid", "unknown"]
    )
    def test_update_goal_bad_id(self, app, raw):
        assert "goal" in _err(call_tool("update_goal", {"goal_id": raw, "title": "X"}))

    def test_goal_writes_audit_without_title(self, app, caplog):
        caplog.set_level(logging.WARNING, logger="taskmanager.mcp")
        out = _ok(call_tool("create_goal", {
            "title": "Secret plan", "category": "work", "priority": "must",
        }))
        call_tool("update_goal", {"goal_id": out["goal"]["id"], "notes": "hush"})
        lines = [r.getMessage() for r in caplog.records if r.name == "taskmanager.mcp"]
        assert f"mcp: created goal {out['goal']['id']}" in lines
        assert f"mcp: updated goal {out['goal']['id']} (notes)" in lines
        assert not any("Secret plan" in line or "hush" in line for line in lines)


class TestProjects:
    def test_create_project_with_goal(self, app):
        g = _goal()
        out = _ok(call_tool("create_project", {
            "name": "Apigee", "type": "work", "goal_id": str(g.id), "priority": "must",
        }))
        p = _db.session.get(Project, uuid.UUID(out["project"]["id"]))
        assert p.goal_id == g.id
        assert out["project"]["goal"] == {"id": str(g.id), "title": "Ship Apigee"}
        assert out["project"]["type"] == "work"
        assert out["project"]["status"] == "not_started"

    def test_create_project_archived_goal_refused(self, app):
        g = _goal(active=False)
        msg = _err(call_tool("create_project", {
            "name": "Apigee", "type": "work", "goal_id": str(g.id),
        }))
        assert "archived" in msg
        assert Project.query.count() == 0

    def test_create_project_duplicate_name_refused(self, app):
        """Task tools name projects by name; a twin makes both unusable."""
        _project("Apigee")
        msg = _err(call_tool("create_project", {"name": " apigee ", "type": "work"}))
        assert 'already a work project named "Apigee"' in msg
        assert Project.query.count() == 1

    def test_same_name_other_type_is_fine(self, app):
        _project("Admin")
        _ok(call_tool("create_project", {"name": "Admin", "type": "personal"}))

    def test_list_projects(self, app):
        g = _goal()
        p = _project("Apigee", goal=g)
        _project("Garden", ProjectType.PERSONAL)
        _project("Old", active=False)
        _task(p)
        _task(p, status=TaskStatus.ARCHIVED)
        out = _ok(call_tool("list_projects", {}))
        assert [v["name"] for v in out["projects"]] == ["Apigee", "Garden"]
        apigee = out["projects"][0]
        assert apigee["task_counts"] == {"active": 1, "done": 1}
        assert apigee["goal"]["title"] == "Ship Apigee"
        work = _ok(call_tool("list_projects", {"type": "personal"}))["projects"]
        assert [v["name"] for v in work] == ["Garden"]
        old = _ok(call_tool("list_projects", {"archived": True}))["projects"]
        assert [v["name"] for v in old] == ["Old"]

    def test_update_project_fields(self, app):
        p = _project()
        out = _ok(call_tool("update_project", {
            "project_id": str(p.id), "status": "in_progress", "priority": "could",
            "notes": "vendor call Tues",
        }))
        assert out["project"]["status"] == "in_progress"
        assert out["project"]["priority"] == "could"
        assert out["project"]["notes"] == "vendor call Tues"
        _ok(call_tool("update_project", {"project_id": str(p.id), "priority": None}))
        assert _db.session.get(Project, p.id).priority is None

    def test_rename_onto_a_twin_refused(self, app):
        _project("Apigee")
        p = _project("Hiring")
        assert "already" in _err(call_tool("update_project", {
            "project_id": str(p.id), "name": "APIGEE",
        }))
        assert _db.session.get(Project, p.id).name == "Hiring"

    def test_rename_to_own_name_different_case_is_fine(self, app):
        p = _project("apigee")
        _ok(call_tool("update_project", {"project_id": str(p.id), "name": "Apigee"}))

    def test_update_archived_project_refused(self, app):
        p = _project(active=False)
        assert "archived" in _err(call_tool("update_project", {
            "project_id": str(p.id), "name": "New",
        }))

    def test_update_project_needs_a_field(self, app):
        p = _project()
        msg = _err(call_tool("update_project", {"project_id": str(p.id), "apply_to_tasks": True}))
        assert "at least one" in msg


class TestProjectTypeChange:
    """#482: a type change re-types the project's tasks and templates."""

    def test_empty_project_changes_type_quietly(self, app):
        p = _project()
        out = _ok(call_tool("update_project", {"project_id": str(p.id), "type": "personal"}))
        assert out["project"]["type"] == "personal"

    def test_type_change_with_tasks_asks_first(self, app):
        p = _project("Kitchen")
        t = _task(p)
        _task(p, status=TaskStatus.ARCHIVED)
        _template(p)
        msg = _err(call_tool("update_project", {"project_id": str(p.id), "type": "personal"}))
        assert '2 tasks and 1 repeating task on "Kitchen" become Personal too' in msg
        assert "apply_to_tasks: true" in msg
        assert _db.session.get(Project, p.id).type == ProjectType.WORK
        assert _db.session.get(Task, t.id).type == TaskType.WORK

    def test_type_change_applied(self, app):
        p = _project("Kitchen")
        t = _task(p)
        r = _template(p)
        _ok(call_tool("update_project", {
            "project_id": str(p.id), "type": "personal", "apply_to_tasks": True,
        }))
        assert _db.session.get(Task, t.id).type == TaskType.PERSONAL
        assert _db.session.get(RecurringTask, r.id).type == TaskType.PERSONAL

    def test_same_type_asks_nothing(self, app):
        p = _project()
        _task(p)
        _ok(call_tool("update_project", {"project_id": str(p.id), "type": "work"}))


class TestProjectGoalChange:
    """#350/#351: a goal change rewrites every task's goal; ask only when
    the user couldn't get back what it overwrites."""

    def test_one_goal_move_is_quiet(self, app):
        a, b = _goal("A"), _goal("B")
        p = _project(goal=a)
        t = _task(p, goal=a)
        _ok(call_tool("update_project", {"project_id": str(p.id), "goal_id": str(b.id)}))
        assert _db.session.get(Task, t.id).goal_id == b.id

    def test_no_goal_to_a_goal_is_quiet(self, app):
        b = _goal("B")
        p = _project()
        t = _task(p)
        _ok(call_tool("update_project", {"project_id": str(p.id), "goal_id": str(b.id)}))
        assert _db.session.get(Task, t.id).goal_id == b.id

    def test_flatten_asks_first_naming_the_goals(self, app):
        a, b, c = _goal("Alpha"), _goal("Beta"), _goal("Gamma")
        p = _project("Catch-all")
        t1 = _task(p, goal=a)
        _task(p, goal=a)
        _task(p, goal=b)
        msg = _err(call_tool("update_project", {"project_id": str(p.id), "goal_id": str(c.id)}))
        assert "3 tasks" in msg
        assert '"Alpha" (2), "Beta" (1)' in msg
        assert "apply_to_tasks: true" in msg
        assert _db.session.get(Task, t1.id).goal_id == a.id
        assert _db.session.get(Project, p.id).goal_id is None

    def test_clear_asks_first(self, app):
        a = _goal("Alpha")
        p = _project("Apigee", goal=a)
        t = _task(p, goal=a)
        msg = _err(call_tool("update_project", {"project_id": str(p.id), "goal_id": None}))
        assert "clear" in msg.lower()
        assert '"Alpha" (1)' in msg
        assert _db.session.get(Task, t.id).goal_id == a.id

    def test_template_counts_toward_flatten(self, app):
        a, b, c = _goal("Alpha"), _goal("Beta"), _goal("Gamma")
        p = _project()
        _task(p, goal=a)
        _template(p, goal=b)
        msg = _err(call_tool("update_project", {"project_id": str(p.id), "goal_id": str(c.id)}))
        assert "1 repeating task" in msg

    def test_flatten_applied(self, app):
        a, b, c = _goal("Alpha"), _goal("Beta"), _goal("Gamma")
        p = _project()
        t1, t2 = _task(p, goal=a), _task(p, goal=b)
        _ok(call_tool("update_project", {
            "project_id": str(p.id), "goal_id": str(c.id), "apply_to_tasks": True,
        }))
        assert {_db.session.get(Task, t.id).goal_id for t in (t1, t2)} == {c.id}

    def test_archived_goal_refused(self, app):
        old = _goal("Old", active=False)
        p = _project()
        assert "archived" in _err(call_tool("update_project", {
            "project_id": str(p.id), "goal_id": str(old.id),
        }))

    def test_bad_goal_id(self, app):
        p = _project()
        assert "goal_id" in _err(call_tool("update_project", {
            "project_id": str(p.id), "goal_id": "nope",
        }))

    def test_project_writes_audit_without_name(self, app, caplog):
        caplog.set_level(logging.WARNING, logger="taskmanager.mcp")
        out = _ok(call_tool("create_project", {"name": "Secret", "type": "work"}))
        call_tool("update_project", {"project_id": out["project"]["id"], "status": "done"})
        lines = [r.getMessage() for r in caplog.records if r.name == "taskmanager.mcp"]
        assert f"mcp: created project {out['project']['id']}" in lines
        assert f"mcp: updated project {out['project']['id']} (status)" in lines
        assert not any("Secret" in line for line in lines)
