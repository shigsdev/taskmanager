"""#436 — what the AI planners are told.

1. The weekly planner sends the recurring fires in its window (it used to
   call compute_previews_in_range positionally; the TypeError was
   swallowed and the prompt always said "no recurring fires").
2. None of the three AI planners is offered an archived goal (#349).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskType,
    Tier,
    db,
)

MONDAY = date(2026, 5, 4)


def _goals():
    live = Goal(title="Live goal 436", category=GoalCategory.WORK,
                priority=GoalPriority.MUST)
    old = Goal(title="Archived goal 436", category=GoalCategory.WORK,
               priority=GoalPriority.MUST, is_active=False)
    db.session.add_all([live, old])
    db.session.commit()
    return str(live.id), str(old.id)


class TestRecurringFires:

    def test_loader_returns_fires_in_the_window(self, app):
        from weekly_planner_service import _load_recurring_fires
        with app.app_context():
            db.session.add(RecurringTask(
                title="Daily standup 436", type=TaskType.WORK,
                frequency=RecurringFrequency.DAILY,
            ))
            db.session.commit()
            fires = _load_recurring_fires(MONDAY, date(2026, 5, 10))
        mine = [f for f in fires if f["title"] == "Daily standup 436"]
        assert [f["fire_day"] for f in mine] == [
            f"2026-05-{d:02d}" for d in range(4, 11)
        ]

    def test_prompt_lists_the_fires(self, app, monkeypatch):
        from weekly_planner_service import compute_weekly_plan
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        with app.app_context():
            db.session.add(Task(title="Some task", type=TaskType.WORK, tier=Tier.INBOX))
            db.session.add(RecurringTask(
                title="Weekly review 436", type=TaskType.WORK,
                frequency=RecurringFrequency.DAILY,
            ))
            db.session.commit()
            with (
                patch("weekly_planner_service._post_to_claude",
                      side_effect=RuntimeError("stop")) as post,
                pytest.raises(RuntimeError),  # only the prompt matters
            ):
                compute_weekly_plan(start_date=MONDAY)
        prompt = post.call_args.args[1]
        assert "Weekly review 436 fires 2026-05-04" in prompt
        assert "(no recurring fires this week)" not in prompt


class TestArchivedGoalsNotOffered:

    def test_weekly_planner(self, app):
        from weekly_planner_service import _load_goals
        with app.app_context():
            live, old = _goals()
            ids = {g["id"] for g in _load_goals()}
        assert live in ids
        assert old not in ids

    def test_inbox_categorize(self, app):
        from inbox_categorize_service import _load_inbox_context
        with app.app_context():
            live, old = _goals()
            _tasks, _projects, goals = _load_inbox_context()
        ids = {g["id"] for g in goals}
        assert live in ids
        assert old not in ids

    def test_weekly_focus(self, app):
        from weekly_focus_service import _load_plan_context
        with app.app_context():
            live, old = _goals()
            _tasks, _projects, goals = _load_plan_context()
        ids = {g["id"] for g in goals}
        assert live in ids
        assert old not in ids
