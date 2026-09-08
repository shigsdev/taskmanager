#!/opt/venv/bin/python
"""Clean up duplicate recurring-task instances left behind by #319.

Background
----------
Until #319, ``cron_audit_service.replay_missed`` computed "today's scheduled
fire" in **UTC** while the scheduler actually fires in ``DIGEST_TZ``. Every
night, between 00:05 UTC and the real local fire, any container boot judged the
four nightly jobs "missed" and replayed them hours early — re-running
``recurring_spawn`` for a day that had already spawned. The spawn dedup also
filtered ``status == ACTIVE``, so a task you had already COMPLETED was invisible
to it and got re-created.

#319 fixed both, so no NEW duplicates are produced. This script cleans up the
rows the bug already created.

What it removes
---------------
Only ACTIVE tasks that came from a recurring template (``recurring_task_id``
is set), grouped by ``(recurring_task_id, due_date)`` — the true spawn identity,
so a manually-created task that merely shares a title is never touched.

  Rule A — 2+ ACTIVE rows for the same (template, due date).
      Unambiguous: a template cannot legitimately fire twice for one day.
      Keeps the OLDEST row (the real cron spawn) and removes the newer copies.

  Rule B — exactly 1 ACTIVE row that has an ARCHIVED/CANCELLED sibling for the
      same (template, due date). You already finished (or cancelled) that day's
      task and the bug resurrected it. Removes the active row and keeps your
      completion record. Skip with ``--no-resurrected``.

NEVER touched: archived, cancelled, or already-deleted rows. Those are your
history — removing them would corrupt completion stats.

Removal is a SOFT delete (``task_service.delete_task`` → ``status=DELETED``),
so everything lands in the recycle bin and is recoverable.

Usage
-----
Dry-run is the DEFAULT — it prints the plan and writes nothing::

    railway ssh
    /app/scripts/dedupe_recurring_tasks.py
    /app/scripts/dedupe_recurring_tasks.py --apply
    /app/scripts/dedupe_recurring_tasks.py --apply --no-resurrected

From a laptop (slower, hits Railway's DNS edge)::

    railway run python scripts/dedupe_recurring_tasks.py

Exit codes: 0 = clean/planned OK, 1 = an error occurred.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _plan(tasks):
    """Pure planning step: return (rule_a, rule_b) removal lists.

    ``tasks`` is any iterable of objects exposing ``id``, ``title``,
    ``due_date``, ``status`` (``.value`` str enum) and ``recurring_task_id``.
    Returns two lists of ``(keep, [remove, ...])`` tuples so the caller can
    print and/or apply. Kept free of DB/Flask so it is unit-testable.
    """
    groups = defaultdict(list)
    for t in tasks:
        rt_id = getattr(t, "recurring_task_id", None)
        if rt_id is None or t.due_date is None:
            continue  # not a spawned instance — out of scope
        groups[(rt_id, t.due_date)].append(t)

    def _status(t):
        s = getattr(t, "status", None)
        return getattr(s, "value", s)

    rule_a, rule_b = [], []
    for rows in groups.values():
        active = sorted(
            [r for r in rows if _status(r) == "active"],
            key=lambda r: (getattr(r, "created_at", None) or 0, str(r.id)),
        )
        settled = [r for r in rows if _status(r) in ("archived", "cancelled")]
        if len(active) > 1:
            rule_a.append((active[0], active[1:]))
        elif len(active) == 1 and settled:
            rule_b.append((settled[0], [active[0]]))
    return rule_a, rule_b


def _describe(removals):
    lines = []
    for k, drops in sorted(removals, key=lambda p: str(p[1][0].due_date)):
        lines.append(f"  {k.due_date} | {k.title[:52]}")
        kept_status = getattr(getattr(k, "status", None), "value", "?")
        lines.append(f"      KEEP   {str(k.id)[:8]}  ({kept_status})")
        for d in drops:
            created = getattr(d, "created_at", None)
            stamp = str(created)[:19] if created else "?"
            lines.append(f"      REMOVE {str(d.id)[:8]}  created {stamp}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply", action="store_true",
        help="actually soft-delete (default is a dry run that writes nothing)",
    )
    ap.add_argument(
        "--no-resurrected", action="store_true",
        help="skip Rule B (active copies that have a completed/cancelled sibling)",
    )
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    from app import create_app
    from models import Task, TaskStatus, db
    from task_service import delete_task

    app = create_app()
    with app.app_context():
        rows = db.session.scalars(
            db.select(Task).where(Task.recurring_task_id.isnot(None))
        ).all()
        rule_a, rule_b = _plan(rows)
        if args.no_resurrected:
            rule_b = []

        print("Duplicate recurring-task cleanup (#319)")
        print("=" * 60)
        print(f"spawned rows scanned: {len(rows)}")
        print()
        print(f"RULE A — 2+ ACTIVE copies of the same (template, day): "
              f"{len(rule_a)} group(s)")
        for line in _describe(rule_a):
            print(line)
        print()
        print(f"RULE B — active copy resurrected after you completed it: "
              f"{len(rule_b)} group(s)")
        for line in _describe(rule_b):
            print(line)

        to_remove = [d for _k, drops in (rule_a + rule_b) for d in drops]
        untouched = sum(1 for t in rows if t.status != TaskStatus.ACTIVE)
        print()
        print(f"rows to remove:            {len(to_remove)}")
        print(f"archived/cancelled kept:   {untouched} (never touched)")

        if not to_remove:
            print("\nNothing to do.")
            return 0

        if not args.apply:
            print("\nDRY RUN — nothing was written. Re-run with --apply to remove.")
            return 0

        removed = 0
        for t in to_remove:
            if delete_task(t.id):
                removed += 1
        print(f"\nSoft-deleted {removed} row(s) → recoverable from the recycle bin.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
