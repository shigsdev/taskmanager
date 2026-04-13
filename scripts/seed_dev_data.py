"""Seed the local dev database with realistic synthetic data.

Usage:
    /usr/local/bin/python3.14 scripts/seed_dev_data.py

Populates tasks across all tiers, goals, projects, recurring templates,
subtasks, completed tasks, and recycle-bin items.  Safe to re-run — it
wipes existing data first so the seed is idempotent.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import (  # noqa: E402
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ImportLog,
    Project,
    ProjectType,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


def _seed():
    app = create_app()
    with app.app_context():
        # Wipe existing data (order matters for FK constraints)
        Task.query.delete()
        RecurringTask.query.delete()
        ImportLog.query.delete()
        Project.query.delete()
        Goal.query.delete()
        db.session.commit()

        today = date.today()

        # --- Goals -----------------------------------------------------------
        goals = [
            Goal(
                title="Ship recurring tasks MVP",
                category=GoalCategory.WORK,
                priority=GoalPriority.MUST,
                priority_rank=1,
                status=GoalStatus.IN_PROGRESS,
                target_quarter="2026-Q2",
                actions="Build repeat UI, spawn logic, full-detail inheritance",
                notes="Core feature for daily workflow automation.",
            ),
            Goal(
                title="Read 12 books this year",
                category=GoalCategory.PERSONAL_GROWTH,
                priority=GoalPriority.SHOULD,
                priority_rank=2,
                status=GoalStatus.IN_PROGRESS,
                target_quarter="2026-Q4",
                actions="Read 30 min daily, track on Goodreads",
            ),
            Goal(
                title="Run a half marathon",
                category=GoalCategory.HEALTH,
                priority=GoalPriority.COULD,
                priority_rank=3,
                status=GoalStatus.NOT_STARTED,
                target_quarter="2026-Q3",
                actions="Follow 12-week training plan, 3 runs/week",
            ),
            Goal(
                title="Strengthen family connections",
                category=GoalCategory.RELATIONSHIPS,
                priority=GoalPriority.MUST,
                priority_rank=1,
                status=GoalStatus.IN_PROGRESS,
                target_quarter="2026-Q2",
                actions="Weekly family dinner, monthly video call with parents",
            ),
        ]
        db.session.add_all(goals)
        db.session.flush()

        # --- Projects --------------------------------------------------------
        projects = [
            Project(name="Task Manager App", color="#4285f4", goal_id=goals[0].id),
            Project(name="Q2 OKRs", color="#ea4335"),
            Project(name="Home Renovation", color="#34a853", type=ProjectType.PERSONAL),
            Project(
                name="Book Club", color="#fbbc05",
                type=ProjectType.PERSONAL, goal_id=goals[1].id,
            ),
            Project(
                name="Fitness", color="#ef4444",
                type=ProjectType.PERSONAL, goal_id=goals[2].id,
            ),
        ]
        db.session.add_all(projects)
        db.session.flush()

        # --- Recurring Templates ---------------------------------------------
        recurring = [
            RecurringTask(
                title="Morning standup",
                frequency=RecurringFrequency.WEEKDAYS,
                type=TaskType.WORK,
                project_id=projects[1].id,
                notes="Check Slack, review PRs, update JIRA board.",
            ),
            RecurringTask(
                title="Weekly meal prep",
                frequency=RecurringFrequency.WEEKLY,
                day_of_week=6,  # Sunday
                type=TaskType.PERSONAL,
                checklist=[
                    {"text": "Plan recipes", "done": False},
                    {"text": "Grocery list", "done": False},
                    {"text": "Shop", "done": False},
                    {"text": "Prep containers", "done": False},
                ],
            ),
            RecurringTask(
                title="Monthly budget review",
                frequency=RecurringFrequency.MONTHLY_DATE,
                day_of_month=1,
                type=TaskType.PERSONAL,
                notes="Review spending in YNAB, adjust categories for next month.",
            ),
            RecurringTask(
                title="Team retro",
                frequency=RecurringFrequency.MONTHLY_NTH_WEEKDAY,
                day_of_week=4,  # Friday
                week_of_month=2,  # 2nd Friday
                type=TaskType.WORK,
                project_id=projects[1].id,
                goal_id=goals[0].id,
                notes="Prepare 3 things that went well, 1 improvement.",
            ),
            RecurringTask(
                title="Exercise — run or gym",
                frequency=RecurringFrequency.DAILY,
                type=TaskType.PERSONAL,
                goal_id=goals[2].id,
                notes="At least 30 minutes. Log distance in Strava.",
            ),
        ]
        db.session.add_all(recurring)
        db.session.flush()

        # --- Tasks -----------------------------------------------------------
        tasks = []

        # TODAY tier (5 tasks)
        tasks.extend([
            Task(
                title="Morning standup",
                tier=Tier.TODAY,
                type=TaskType.WORK,
                project_id=projects[1].id,
                recurring_task_id=recurring[0].id,
                notes="Check Slack, review PRs, update JIRA board.",
                sort_order=0,
            ),
            Task(
                title="Fix mobile nav overflow on 375px viewport",
                tier=Tier.TODAY,
                type=TaskType.WORK,
                project_id=projects[0].id,
                goal_id=goals[0].id,
                notes="The nav bar clips 'Print' and 'Log out' at mobile widths. "
                      "Consider hamburger menu or horizontal scroll indicator.",
                url="https://github.com/shigsdev/taskmanager/issues/42",
                sort_order=1,
            ),
            Task(
                title="Read Chapter 5 of 'Designing Data-Intensive Applications'",
                tier=Tier.TODAY,
                type=TaskType.PERSONAL,
                project_id=projects[3].id,
                goal_id=goals[1].id,
                due_date=today,
                sort_order=2,
            ),
            Task(
                title="Exercise — run or gym",
                tier=Tier.TODAY,
                type=TaskType.PERSONAL,
                project_id=projects[4].id,
                recurring_task_id=recurring[4].id,
                goal_id=goals[2].id,
                notes="At least 30 minutes. Log distance in Strava.",
                sort_order=3,
            ),
            Task(
                title="Call Mom for birthday",
                tier=Tier.TODAY,
                type=TaskType.PERSONAL,
                goal_id=goals[3].id,
                due_date=today,
                notes="She mentioned wanting the new Kindle.",
                sort_order=4,
            ),
        ])

        # INBOX tier (3 tasks)
        tasks.extend([
            Task(
                title="Research CI/CD options for Railway",
                tier=Tier.INBOX,
                type=TaskType.WORK,
                sort_order=0,
            ),
            Task(
                title="Dentist appointment — schedule cleaning",
                tier=Tier.INBOX,
                type=TaskType.PERSONAL,
                sort_order=1,
            ),
            Task(
                title="Review PR #38: add batch import undo",
                tier=Tier.INBOX,
                type=TaskType.WORK,
                project_id=projects[0].id,
                url="https://github.com/shigsdev/taskmanager/pull/38",
                sort_order=2,
            ),
        ])

        # THIS_WEEK tier (4 tasks)
        tasks.extend([
            Task(
                title="Write integration tests for repeat feature",
                tier=Tier.THIS_WEEK,
                type=TaskType.WORK,
                project_id=projects[0].id,
                goal_id=goals[0].id,
                checklist=[
                    {"text": "Test daily spawn", "done": True},
                    {"text": "Test weekday filtering", "done": True},
                    {"text": "Test monthly nth weekday", "done": False},
                    {"text": "Test full detail inheritance", "done": False},
                ],
                sort_order=0,
            ),
            Task(
                title="Grocery shopping for the week",
                tier=Tier.THIS_WEEK,
                type=TaskType.PERSONAL,
                due_date=today + timedelta(days=2),
                checklist=[
                    {"text": "Vegetables", "done": False},
                    {"text": "Chicken breast", "done": False},
                    {"text": "Rice", "done": False},
                    {"text": "Olive oil", "done": False},
                    {"text": "Eggs", "done": False},
                ],
                sort_order=1,
            ),
            Task(
                title="Prepare Q2 OKR presentation",
                tier=Tier.THIS_WEEK,
                type=TaskType.WORK,
                project_id=projects[1].id,
                due_date=today + timedelta(days=4),
                notes="Focus on shipping metrics and user feedback themes.",
                sort_order=2,
            ),
            Task(
                title="Plan family dinner menu for Sunday",
                tier=Tier.THIS_WEEK,
                type=TaskType.PERSONAL,
                goal_id=goals[3].id,
                sort_order=3,
            ),
        ])

        # BACKLOG tier (4 tasks)
        tasks.extend([
            Task(
                title="Add dark mode toggle to settings",
                tier=Tier.BACKLOG,
                type=TaskType.WORK,
                project_id=projects[0].id,
                notes="Use prefers-color-scheme media query as default, "
                      "allow manual override in settings.",
                sort_order=0,
            ),
            Task(
                title="Set up automatic database backups",
                tier=Tier.BACKLOG,
                type=TaskType.WORK,
                project_id=projects[0].id,
                sort_order=1,
            ),
            Task(
                title="Research half marathon training plans",
                tier=Tier.BACKLOG,
                type=TaskType.PERSONAL,
                goal_id=goals[2].id,
                url="https://www.halhigdon.com/training-programs/half-marathon-training/",
                sort_order=2,
            ),
            Task(
                title="Update resume with recent projects",
                tier=Tier.BACKLOG,
                type=TaskType.PERSONAL,
                sort_order=3,
            ),
        ])

        # FREEZER tier (3 tasks)
        tasks.extend([
            Task(
                title="Learn Rust basics",
                tier=Tier.FREEZER,
                type=TaskType.PERSONAL,
                notes="Start with The Rust Book. Low priority until Q3.",
                sort_order=0,
            ),
            Task(
                title="Migrate from SendGrid to Resend",
                tier=Tier.FREEZER,
                type=TaskType.WORK,
                project_id=projects[0].id,
                notes="SendGrid works fine for now. Revisit if pricing changes.",
                sort_order=1,
            ),
            Task(
                title="Build a personal blog",
                tier=Tier.FREEZER,
                type=TaskType.PERSONAL,
                notes="Maybe Astro or Hugo. No rush.",
                sort_order=2,
            ),
        ])

        db.session.add_all(tasks)
        db.session.flush()

        # --- Subtasks --------------------------------------------------------
        # Add subtasks to "Fix mobile nav overflow"
        parent_nav = tasks[1]  # "Fix mobile nav overflow"
        subtasks_nav = [
            Task(
                title="Audit current nav CSS at 375px",
                tier=parent_nav.tier,
                type=parent_nav.type,
                project_id=parent_nav.project_id,
                goal_id=parent_nav.goal_id,
                parent_id=parent_nav.id,
                sort_order=0,
            ),
            Task(
                title="Implement hamburger menu or overflow scroll",
                tier=parent_nav.tier,
                type=parent_nav.type,
                project_id=parent_nav.project_id,
                goal_id=parent_nav.goal_id,
                parent_id=parent_nav.id,
                sort_order=1,
            ),
            Task(
                title="Test on iPhone SE and Pixel 5 viewports",
                tier=parent_nav.tier,
                type=parent_nav.type,
                project_id=parent_nav.project_id,
                goal_id=parent_nav.goal_id,
                parent_id=parent_nav.id,
                sort_order=2,
            ),
        ]
        db.session.add_all(subtasks_nav)

        # Add subtasks to "Prepare Q2 OKR presentation"
        parent_okr = tasks[12]  # "Prepare Q2 OKR presentation"
        subtasks_okr = [
            Task(
                title="Pull shipping metrics from Railway dashboard",
                tier=parent_okr.tier,
                type=parent_okr.type,
                project_id=parent_okr.project_id,
                parent_id=parent_okr.id,
                sort_order=0,
            ),
            Task(
                title="Summarize user feedback themes",
                tier=parent_okr.tier,
                type=parent_okr.type,
                project_id=parent_okr.project_id,
                parent_id=parent_okr.id,
                sort_order=1,
            ),
        ]
        db.session.add_all(subtasks_okr)

        # --- Completed tasks -------------------------------------------------
        completed = [
            Task(
                title="Set up Railway deployment pipeline",
                tier=Tier.TODAY,
                type=TaskType.WORK,
                project_id=projects[0].id,
                status=TaskStatus.ARCHIVED,
                sort_order=0,
            ),
            Task(
                title="Implement Google OAuth login",
                tier=Tier.TODAY,
                type=TaskType.WORK,
                project_id=projects[0].id,
                status=TaskStatus.ARCHIVED,
                sort_order=1,
            ),
            Task(
                title="Build weekly review swipe interface",
                tier=Tier.TODAY,
                type=TaskType.WORK,
                project_id=projects[0].id,
                goal_id=goals[0].id,
                status=TaskStatus.ARCHIVED,
                sort_order=2,
            ),
            Task(
                title="Read Chapter 4 of DDIA",
                tier=Tier.TODAY,
                type=TaskType.PERSONAL,
                project_id=projects[3].id,
                goal_id=goals[1].id,
                status=TaskStatus.ARCHIVED,
                sort_order=3,
            ),
            Task(
                title="Finish Couch to 5K week 3",
                tier=Tier.TODAY,
                type=TaskType.PERSONAL,
                goal_id=goals[2].id,
                status=TaskStatus.ARCHIVED,
                sort_order=4,
            ),
        ]
        db.session.add_all(completed)

        # --- Recycle bin (soft-deleted) tasks ---------------------------------
        batch_id = uuid.uuid4()
        deleted = [
            Task(
                title="Old brainstorm: gamify task completion",
                tier=Tier.BACKLOG,
                type=TaskType.WORK,
                status=TaskStatus.DELETED,
                batch_id=batch_id,
                sort_order=0,
            ),
            Task(
                title="Old brainstorm: social features for accountability",
                tier=Tier.BACKLOG,
                type=TaskType.WORK,
                status=TaskStatus.DELETED,
                batch_id=batch_id,
                sort_order=1,
            ),
            Task(
                title="Cancelled: migrate to MongoDB",
                tier=Tier.FREEZER,
                type=TaskType.WORK,
                status=TaskStatus.DELETED,
                notes="Decided to stick with PostgreSQL.",
                sort_order=2,
            ),
        ]
        db.session.add_all(deleted)

        # Import log for the batch
        import_log = ImportLog(
            source="seed_dev_data",
            task_count=2,
            batch_id=batch_id,
            undone_at=datetime.now(UTC),
        )
        db.session.add(import_log)

        db.session.commit()

        # --- Summary ---------------------------------------------------------
        active_count = Task.query.filter_by(status=TaskStatus.ACTIVE).count()
        archived_count = Task.query.filter_by(status=TaskStatus.ARCHIVED).count()
        deleted_count = Task.query.filter_by(status=TaskStatus.DELETED).count()
        goal_count = Goal.query.count()
        project_count = Project.query.count()
        recurring_count = RecurringTask.query.count()

        print("Seed complete!")  # noqa: T201
        print(f"  Tasks:     {active_count} active, {archived_count} completed, "  # noqa: T201
              f"{deleted_count} in recycle bin")
        print(f"  Goals:     {goal_count}")  # noqa: T201
        print(f"  Projects:  {project_count}")  # noqa: T201
        print(f"  Recurring: {recurring_count} templates")  # noqa: T201


if __name__ == "__main__":
    _seed()
