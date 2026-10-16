"""#483: ✨ Plan / /plan offers only projects of the task's own type.

Since #475 a task can't be put on a project of the other type, but the
planner could still SUGGEST one (applying it was refused), and the /plan
row's Project list had every project. Each per-task suggestion now carries
the task's ``task_type`` (so the row can list that type's projects) and a
suggested project of the other type is dropped.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from models import Project, ProjectType, Task, TaskType, Tier, db


def _claude(plan: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(plan)}]}


def _plan_for(app, monkeypatch, task_type, project_type):
    from weekly_planner_service import compute_weekly_plan

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    with app.app_context():
        t = Task(title="483 task", type=task_type, tier=Tier.INBOX)
        p = Project(name="483 proj", type=project_type)
        db.session.add_all([t, p])
        db.session.commit()
        tid, pid = str(t.id), str(p.id)
        plan = {"per_task_suggestions": [{
            "task_id": tid, "action": "keep", "suggested_tier": None,
            "suggested_due_date": None, "suggested_project_id": pid,
            "suggested_goal_id": None, "reason": "x",
        }], "day_by_day_plan": {}, "goal_hints": [], "velocity_warning": None,
            "stale_freezer_review": []}
        with patch("weekly_planner_service._post_to_claude", return_value=_claude(plan)):
            result = compute_weekly_plan(start_date=date(2026, 10, 19))
    (s,) = [x for x in result["per_task_suggestions"] if x["task_id"] == tid]
    return s, pid


def test_each_suggestion_carries_the_task_type(app, monkeypatch):
    s, pid = _plan_for(app, monkeypatch, TaskType.PERSONAL, ProjectType.PERSONAL)
    assert s["task_type"] == "personal"
    assert s["suggested_project_id"] == pid   # the quiet case: same type is kept


def test_a_suggested_project_of_the_other_type_is_dropped(app, monkeypatch):
    s, _ = _plan_for(app, monkeypatch, TaskType.WORK, ProjectType.PERSONAL)
    assert s["task_type"] == "work"
    assert s["suggested_project_id"] is None


def test_a_backfilled_keep_row_carries_the_task_type_too(app, monkeypatch):
    from weekly_planner_service import compute_weekly_plan

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    with app.app_context():
        t = Task(title="483 omitted", type=TaskType.PERSONAL, tier=Tier.INBOX)
        db.session.add(t)
        db.session.commit()
        tid = str(t.id)
        empty = {"per_task_suggestions": [], "day_by_day_plan": {}, "goal_hints": [],
                 "velocity_warning": None, "stale_freezer_review": []}
        with patch("weekly_planner_service._post_to_claude", return_value=_claude(empty)):
            result = compute_weekly_plan(start_date=date(2026, 10, 19))
    (s,) = [x for x in result["per_task_suggestions"] if x["task_id"] == tid]
    assert s["task_type"] == "personal"
