"""Full JSON export of the user's data — backs ``GET /api/export`` (#366).

Walks ``db.Model.registry`` rather than hand-picking tables: every table
except ``EXPORT_EXCLUDED_TABLES``, every column, every row (archived goals
and projects included). Before #366 the export listed three tables by hand,
filtered goals/projects to active, and dropped 8 of 14 project columns, so
a task's ``recurring_task_id`` or an archived project's id pointed at rows
not in the file. ``tests/test_export.py`` fails if a new table is neither
exported nor excluded here with a reason.

This file is a readable copy, not the backup of record — that is the daily
encrypted ``pg_dump`` (#154). Nothing restores from it.
"""

from sqlalchemy import select

from models import db
from task_service import _column_value

# Server bookkeeping, not user data. Each entry needs a reason.
EXPORT_EXCLUDED_TABLES = frozenset({
    "app_logs",    # server/client log rows (#24) — operational, high-volume
    "cron_audit",  # scheduler last-fire status per job — operational
})


def _serialize_row(row, mapper, table) -> dict:
    # Keyed by COLUMN name; read through the mapped attribute, whose name
    # may differ from the column's.
    return {
        col.name: _column_value(getattr(row, mapper.get_property_by_column(col).key))
        for col in table.columns
    }


def build_export() -> dict:
    """Return ``{table name: [row dict, ...]}`` for every exported table.

    Rows are ordered by primary key so two exports of the same data match.
    ``exported_at`` is added by the route (it owns the DIGEST_TZ date, #180).
    """
    out = {}
    for mapper in sorted(db.Model.registry.mappers, key=lambda m: m.class_.__table__.name):
        model = mapper.class_
        table = model.__table__
        if table.name in EXPORT_EXCLUDED_TABLES:
            continue
        rows = db.session.scalars(select(model).order_by(*table.primary_key.columns))
        out[table.name] = [_serialize_row(r, mapper, table) for r in rows]
    return out
