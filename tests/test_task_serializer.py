"""Tests for the canonical ``task_service.serialize_task`` (#200).

Three hand-written Task→dict serializers (``tasks_api._serialize``,
``review_api._serialize``, ``app.export_data``'s inline ``serialize_task``)
drifted apart — the export one silently dropped columns, so a "full
backup" lost data. ``serialize_task`` is the single source of truth.

The contract these tests lock:

- ``view="export"`` includes EVERY ``Task`` model column — derived from
  ``Task.__table__.columns`` so adding a future column without updating
  the serializer FAILS here (drift gate). This is the test that catches
  the #200 data-loss bug class.
- ``view="full"`` reproduces the exact key set ``tasks_api._serialize``
  emitted before the consolidation.
- ``view="review"`` reproduces the exact key set ``review_api._serialize``
  emitted before the consolidation.
"""
from __future__ import annotations

import pytest

from models import Task
from task_service import create_task, serialize_task

# The exact key set tasks_api._serialize emitted before #200. Locking it
# here means a change to the "full" view that drops/renames a key fails
# loudly rather than silently breaking an API consumer.
_FULL_KEYS = {
    "id", "title", "tier", "type", "status", "parent_id", "project_id",
    "goal_id", "due_date", "url", "notes", "cancellation_reason",
    "checklist", "sort_order", "last_reviewed", "repeat", "subtask_count",
    "subtask_done", "created_at", "updated_at",
}

# The exact key set review_api._serialize emitted before #200.
_REVIEW_KEYS = {
    "id", "title", "tier", "type", "status", "project_id", "goal_id",
    "due_date", "notes", "checklist", "last_reviewed", "created_at",
    "updated_at",
}


@pytest.fixture
def task(app):
    """A persisted Task with a representative spread of populated fields."""
    return create_task(
        {
            "title": "Serialize me",
            "type": "work",
            "tier": "today",
            "due_date": "2026-06-01",
            "notes": "some notes",
            "url": "https://example.com",
            "checklist": [{"text": "a", "done": False}],
        }
    )


class TestExportView:
    def test_export_includes_every_task_column(self, task):
        """Drift gate: export view must cover every Task model column.

        Derives the expected column set from ``Task.__table__.columns``
        so a future ``Task`` column that the serializer forgot fails
        this test instead of silently vanishing from the JSON backup.
        """
        out = serialize_task(task, view="export")
        model_columns = {c.name for c in Task.__table__.columns}
        assert set(out) >= model_columns, (
            "export view is missing columns: "
            f"{sorted(model_columns - set(out))}"
        )

    def test_export_includes_columns_the_old_serializer_dropped(self, task):
        """The old inline export serializer silently omitted these."""
        out = serialize_task(task, view="export")
        for col in (
            "parent_id", "cancellation_reason", "last_reviewed",
            "batch_id", "recurring_task_id", "planner_ignore",
        ):
            assert col in out, f"{col} missing from export view"

    def test_export_coerces_uuid_and_date_to_json_safe(self, task):
        out = serialize_task(task, view="export")
        # id (UUID) → str
        assert isinstance(out["id"], str)
        # due_date (date) → ISO string
        assert out["due_date"] == "2026-06-01"
        # created_at (datetime) → ISO string
        assert isinstance(out["created_at"], str)
        # enum → its .value
        assert out["tier"] == "today"
        assert out["type"] == "work"
        assert out["status"] == "active"

    def test_export_keeps_none_as_none(self, app):
        t = create_task({"title": "Bare", "type": "personal"})
        out = serialize_task(t, view="export")
        assert out["due_date"] is None
        assert out["parent_id"] is None
        assert out["cancellation_reason"] is None

    def test_export_omits_computed_relationship_fields(self, task):
        """A full export must not trigger N+1 subtask queries — no
        ``repeat`` / ``subtask_count`` in the export view."""
        out = serialize_task(task, view="export")
        assert "repeat" not in out
        assert "subtask_count" not in out
        assert "subtask_done" not in out


class TestFullView:
    def test_full_view_key_set_matches_legacy_contract(self, task):
        out = serialize_task(task, view="full")
        assert set(out) == _FULL_KEYS

    def test_full_view_includes_subtask_counts(self, app):
        parent = create_task({"title": "Parent", "type": "work"})
        create_task(
            {"title": "Sub", "type": "work", "parent_id": str(parent.id)}
        )
        out = serialize_task(parent, view="full")
        assert out["subtask_count"] == 1
        assert out["subtask_done"] == 0

    def test_full_view_repeat_is_none_without_template(self, task):
        out = serialize_task(task, view="full")
        assert out["repeat"] is None

    def test_full_view_default_view_is_full(self, task):
        assert serialize_task(task) == serialize_task(task, view="full")


class TestReviewView:
    def test_review_view_key_set_matches_legacy_contract(self, task):
        out = serialize_task(task, view="review")
        assert set(out) == _REVIEW_KEYS

    def test_review_view_omits_full_only_fields(self, task):
        out = serialize_task(task, view="review")
        # Review subset deliberately excludes these full-view fields.
        for k in ("url", "cancellation_reason", "sort_order", "repeat",
                  "subtask_count", "subtask_done", "parent_id"):
            assert k not in out


class TestUnknownView:
    def test_unknown_view_raises(self, task):
        with pytest.raises(ValueError, match="unknown serializer view"):
            serialize_task(task, view="bogus")
