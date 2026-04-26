"""One-time backfill for #77 (2026-04-26): set every task's goal_id to
its project's goal_id (overwriting whatever's there).

Per the user's scoping decision (b) "always overwrite + go back and
update any missing." After this script runs, all task<-project<-goal
links are consistent. Idempotent: re-running is a no-op when already
in sync.

Run on prod after the #77 deploy goes green:
    railway run python scripts/backfill_task_goal_from_project.py

Or locally against the dev DB:
    python scripts/backfill_task_goal_from_project.py

Prints before/after counts and the number of tasks updated.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from models import Project, Task, db  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        # All tasks that have a project_id.
        tasks_with_project = list(db.session.scalars(
            select(Task).where(Task.project_id.is_not(None))
        ))
        print(f"Tasks with a project: {len(tasks_with_project)}")

        # Pre-load every project keyed by id so the per-task lookup is O(1).
        projects = {p.id: p for p in db.session.scalars(select(Project))}

        updated = 0
        for t in tasks_with_project:
            proj = projects.get(t.project_id)
            if proj is None:
                # Orphaned project_id — leave the task alone, log it.
                print(f"  WARN: task {t.id} references missing project {t.project_id}")
                continue
            new_goal_id = proj.goal_id  # may be None
            if t.goal_id != new_goal_id:
                t.goal_id = new_goal_id
                updated += 1

        db.session.commit()
        print(f"Tasks updated (goal cascaded from project): {updated}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
