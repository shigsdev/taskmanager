"""#484: a batch row of the wrong shape is skipped and said, not fatal.

The confirm endpoints checked only that ``candidates`` is a list. A row that
isn't an object, or a number where text belongs (title, due date, a goal's
quarter), raised in the creator → 500 for the WHOLE batch; and
``included: "false"`` (any non-empty string) counted as included.
"""
from __future__ import annotations

from sqlalchemy import select

from models import Goal, Project, Task, db

TAG = "S484"


def _titles(app, model, attr="title"):
    with app.app_context():
        db.session.expire_all()
        col = getattr(model, attr)
        return sorted(db.session.scalars(select(col).where(col.like(f"{TAG}%"))))


# --- batch_input (pure) ---------------------------------------------------------


class TestRowIncluded:
    def test_missing_or_true_is_included(self):
        from batch_input import row_included
        assert row_included({}) is True
        assert row_included({"included": True}) is True
        assert row_included({"included": "yes"}) is True
        assert row_included({"included": 1}) is True

    def test_false_in_any_spelling_is_left_out(self):
        from batch_input import row_included
        for v in (False, 0, "false", "False", " no ", "0", ""):
            assert row_included({"included": v}) is False, v


class TestCleanRow:
    def test_not_an_object_is_none(self):
        from batch_input import clean_row
        for v in ("a", 5, None, ["x"]):
            assert clean_row(v) is None

    def test_numbers_in_text_fields_become_text(self):
        from batch_input import clean_row
        row = clean_row({"title": 5, "due_date": 20261020, "target_quarter": 2026.0})
        assert row["title"] == "5"
        assert row["due_date"] == "20261020"
        assert row["target_quarter"] == "2026.0"

    def test_other_shapes_in_text_fields_are_dropped(self):
        from batch_input import clean_row
        row = clean_row({"title": "ok", "notes": ["a"], "url": {"x": 1}, "type": True})
        assert row["title"] == "ok"
        assert "notes" not in row and "url" not in row and "type" not in row

    def test_other_keys_pass_through_and_included_is_a_bool(self):
        from batch_input import clean_row
        rep = {"frequency": "daily"}
        row = clean_row({"title": "t", "repeat": rep, "route": "task", "included": "false"})
        assert row["repeat"] is rep and row["route"] == "task"
        assert row["included"] is False

    def test_clean_rows_counts_what_it_skips(self):
        from batch_input import clean_rows, skipped_warning
        rows, skipped = clean_rows([{"title": "a"}, "junk", None, {"title": "b"}])
        assert [r["title"] for r in rows] == ["a", "b"]
        assert skipped == 2
        assert skipped_warning(0) is None
        assert skipped_warning(1) == "1 row couldn't be read and was skipped."
        assert skipped_warning(2) == "2 rows couldn't be read and were skipped."


# --- the endpoints ------------------------------------------------------------------


class TestImportConfirm:
    def test_bad_rows_are_skipped_and_said_the_rest_saves(self, app, authed_client):
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": f"{TAG} good", "type": "work"},
            "not a row",
            {"title": f"{TAG} dated", "type": "work", "due_date": 20261020},
            {"title": f"{TAG} left out", "type": "work", "included": "false"},
        ]})
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body["created"] == 2
        assert body["warning"] == "1 row couldn't be read and was skipped."
        assert _titles(app, Task) == [f"{TAG} dated", f"{TAG} good"]

    def test_a_number_title_is_saved_as_text(self, app, authed_client):
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": 484, "type": "work"},
        ]})
        assert r.status_code == 201, r.get_json()
        with app.app_context():
            assert db.session.scalars(select(Task).where(Task.title == "484")).first()

    def test_goal_quarter_number_is_fine(self, app, authed_client):
        r = authed_client.post("/api/import/goals/confirm", json={"candidates": [
            {"title": f"{TAG} goal", "category": "work", "target_quarter": 2026},
        ]})
        assert r.status_code == 201, r.get_json()
        assert _titles(app, Goal) == [f"{TAG} goal"]

    def test_projects_confirm_skips_a_bad_row(self, app, authed_client):
        r = authed_client.post("/api/import/projects/confirm", json={"candidates": [
            42, {"name": f"{TAG} proj", "type": "work"},
        ]})
        assert r.status_code == 201, r.get_json()
        assert r.get_json()["warning"] == "1 row couldn't be read and was skipped."
        assert _titles(app, Project, "name") == [f"{TAG} proj"]

    def test_well_formed_rows_answer_no_warning(self, app, authed_client):
        # The quiet case.
        r = authed_client.post("/api/import/tasks/confirm", json={"candidates": [
            {"title": f"{TAG} plain", "type": "work"},
        ]})
        assert r.status_code == 201
        assert "warning" not in r.get_json()


class TestScanAndVoice:
    def test_scan_confirm_skips_a_bad_row(self, app, authed_client):
        r = authed_client.post("/api/scan/confirm", json={"kind": "tasks", "candidates": [
            None, {"title": f"{TAG} scanned", "type": "work", "included": True},
            {"title": f"{TAG} not me", "type": "work", "included": "no"},
        ]})
        assert r.status_code == 201, r.get_json()
        assert r.get_json()["warning"] == "1 row couldn't be read and was skipped."
        assert _titles(app, Task) == [f"{TAG} scanned"]

    def test_voice_confirm_honours_included_false_strings(self, app, authed_client):
        r = authed_client.post("/api/voice-memo/confirm", json={"candidates": [
            {"title": f"{TAG} spoken", "type": "work", "route": "task"},
            {"title": f"{TAG} unspoken", "type": "work", "route": "task", "included": "false"},
            "junk",
        ]})
        assert r.status_code == 201, r.get_json()
        assert "1 row couldn't be read and was skipped." in r.get_json()["warning"]
        assert _titles(app, Task) == [f"{TAG} spoken"]
