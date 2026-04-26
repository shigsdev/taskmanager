"""One-time backfill for #93 (2026-04-26): apply the per-type default
color (#66) to existing projects that were created before PR3.

Pre-PR3, every project defaulted to #2563eb (blue) regardless of type.
PR3 added per-type defaults: Work=#2563eb, Personal=#16a34a. New
projects pick the right default; old ones still carry the legacy color.

This script:
  - Walks every active project
  - If project.color matches the LEGACY default ("#2563eb") AND
    project.type would now default to a DIFFERENT color, switch to
    the new per-type default
  - Leaves projects with a manually-overridden color (anything else)
    alone — only the unmistakable "default-blue Personal project" case
    is updated

Idempotent: re-running is a no-op once everything's in sync.

Run on prod after PR27 deploy goes green:
    railway run python scripts/backfill_project_colors.py

Or locally against the dev DB:
    python scripts/backfill_project_colors.py

Prints before/after counts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from models import Project, ProjectType, db  # noqa: E402
from project_service import _default_color_for_type  # noqa: E402

LEGACY_DEFAULT = "#2563eb"


def main() -> int:
    app = create_app()
    with app.app_context():
        projects = list(db.session.scalars(
            select(Project).where(Project.is_active.is_(True))
        ))
        print(f"Active projects scanned: {len(projects)}")

        updated = 0
        for p in projects:
            if p.color != LEGACY_DEFAULT:
                continue  # manually overridden — leave alone
            new_color = _default_color_for_type(p.type)
            if new_color != LEGACY_DEFAULT:
                # Personal project carrying legacy blue — switch to green.
                old = p.color
                p.color = new_color
                updated += 1
                type_name = p.type.value if isinstance(p.type, ProjectType) else p.type
                print(f"  {p.name} ({type_name}): {old} → {new_color}")

        db.session.commit()
        print(f"Projects updated: {updated}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
