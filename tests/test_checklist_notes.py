"""Integration tests for checklist and notes on tasks.

Checklists are stored as a JSONB column (a database type that holds
structured data like lists and objects, rather than plain text). Each
checklist item is an object with three fields:
  - id: a unique identifier for the item
  - text: what the item says (e.g. "Buy milk")
  - checked: whether it's been completed (true/false)

Notes are a plain text field — any free-form text the user wants to
attach to a task.

These tests verify that checklists and notes can be created, read,
updated, and cleared through the API, and that the data survives
a round-trip (write to database → read back unchanged).
"""
from __future__ import annotations

from models import Task, TaskType, db


def _make_task(**overrides) -> Task:
    """Helper to create a task directly in the database."""
    fields = {"title": "Checklist test", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- Checklist creation -------------------------------------------------------


class TestChecklistCreate:
    """Verify checklist data is saved correctly when creating a task."""

    def test_create_with_empty_checklist(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "No checklist", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["checklist"] == []

    def test_create_with_single_item(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "One item",
                "type": "work",
                "checklist": [{"id": "1", "text": "Do this", "checked": False}],
            },
        )
        assert resp.status_code == 201
        cl = resp.get_json()["checklist"]
        assert len(cl) == 1
        assert cl[0]["text"] == "Do this"
        assert cl[0]["checked"] is False

    def test_create_with_multiple_items(self, authed_client):
        """Verify a checklist with 3+ items round-trips correctly."""
        items = [
            {"id": "1", "text": "Step one", "checked": False},
            {"id": "2", "text": "Step two", "checked": True},
            {"id": "3", "text": "Step three", "checked": False},
        ]
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Multi", "type": "work", "checklist": items},
        )
        assert resp.status_code == 201
        cl = resp.get_json()["checklist"]
        assert len(cl) == 3
        assert cl[0]["text"] == "Step one"
        assert cl[1]["checked"] is True
        assert cl[2]["text"] == "Step three"

    def test_create_with_explicit_null_checklist(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Null CL", "type": "work", "checklist": None},
        )
        assert resp.status_code == 201
        assert resp.get_json()["checklist"] == []


# --- Checklist update ---------------------------------------------------------


class TestChecklistUpdate:
    """Verify checklist data can be modified after task creation.

    'PATCH' means a partial update — you send only the fields you want
    to change, and everything else stays the same.
    """

    def test_add_checklist_to_task_that_had_none(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="No CL yet")
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}",
            json={"checklist": [{"id": "1", "text": "New item", "checked": False}]},
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["checklist"]) == 1

    def test_replace_entire_checklist(self, authed_client, app):
        """Sending a new checklist array replaces the old one completely."""
        with app.app_context():
            task = _make_task(
                checklist=[{"id": "old", "text": "Old item", "checked": False}]
            )
            task_id = str(task.id)

        new_items = [
            {"id": "a", "text": "New A", "checked": False},
            {"id": "b", "text": "New B", "checked": True},
        ]
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"checklist": new_items}
        )
        assert resp.status_code == 200
        cl = resp.get_json()["checklist"]
        assert len(cl) == 2
        assert cl[0]["text"] == "New A"
        assert cl[1]["text"] == "New B"

    def test_check_individual_item(self, authed_client, app):
        """Simulate checking one item while leaving others unchecked.

        The frontend sends the entire updated checklist array — there's
        no API to toggle a single item. This matches how the detail
        panel works: it reads the checklist, the user clicks a checkbox,
        and the whole array is sent back on save.
        """
        with app.app_context():
            task = _make_task(
                checklist=[
                    {"id": "1", "text": "First", "checked": False},
                    {"id": "2", "text": "Second", "checked": False},
                ]
            )
            task_id = str(task.id)

        # Check only the second item
        updated = [
            {"id": "1", "text": "First", "checked": False},
            {"id": "2", "text": "Second", "checked": True},
        ]
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"checklist": updated}
        )
        assert resp.status_code == 200
        cl = resp.get_json()["checklist"]
        assert cl[0]["checked"] is False
        assert cl[1]["checked"] is True

    def test_clear_checklist_with_empty_array(self, authed_client, app):
        """Remove all checklist items by sending an empty array."""
        with app.app_context():
            task = _make_task(
                checklist=[{"id": "1", "text": "Gone soon", "checked": False}]
            )
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"checklist": []}
        )
        assert resp.status_code == 200
        assert resp.get_json()["checklist"] == []

    def test_invalid_checklist_rejected(self, authed_client, app):
        """Sending a non-list value for checklist should fail with a 422
        (HTTP status meaning 'I understood your request but the data is wrong')."""
        with app.app_context():
            task = _make_task()
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"checklist": "not a list"}
        )
        assert resp.status_code == 422
        assert resp.get_json()["field"] == "checklist"


# --- Checklist progress -------------------------------------------------------


class TestChecklistProgress:
    """Verify checklist progress is correctly represented in API responses.

    The task card in the UI shows a progress indicator like "2/5" meaning
    2 out of 5 checklist items are checked. The API returns the raw
    checklist array, and the JavaScript calculates the display. Here we
    verify the data is correct so the JS can do its job.
    """

    def test_all_unchecked(self, authed_client, app):
        with app.app_context():
            task = _make_task(
                checklist=[
                    {"id": "1", "text": "A", "checked": False},
                    {"id": "2", "text": "B", "checked": False},
                ]
            )
            task_id = str(task.id)

        resp = authed_client.get(f"/api/tasks/{task_id}")
        cl = resp.get_json()["checklist"]
        done = sum(1 for item in cl if item["checked"])
        assert done == 0
        assert len(cl) == 2

    def test_partial_progress(self, authed_client, app):
        with app.app_context():
            task = _make_task(
                checklist=[
                    {"id": "1", "text": "A", "checked": True},
                    {"id": "2", "text": "B", "checked": False},
                    {"id": "3", "text": "C", "checked": True},
                ]
            )
            task_id = str(task.id)

        resp = authed_client.get(f"/api/tasks/{task_id}")
        cl = resp.get_json()["checklist"]
        done = sum(1 for item in cl if item["checked"])
        assert done == 2
        assert len(cl) == 3

    def test_all_checked(self, authed_client, app):
        with app.app_context():
            task = _make_task(
                checklist=[
                    {"id": "1", "text": "A", "checked": True},
                    {"id": "2", "text": "B", "checked": True},
                ]
            )
            task_id = str(task.id)

        resp = authed_client.get(f"/api/tasks/{task_id}")
        cl = resp.get_json()["checklist"]
        done = sum(1 for item in cl if item["checked"])
        assert done == 2


# --- Notes creation and update ------------------------------------------------


class TestNotes:
    """Verify free-text notes can be created, read, updated, and cleared."""

    def test_create_task_with_notes(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Has notes", "type": "personal", "notes": "Remember this"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["notes"] == "Remember this"

    def test_create_task_without_notes_defaults_to_null(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "No notes", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["notes"] is None

    def test_update_notes(self, authed_client, app):
        with app.app_context():
            task = _make_task(notes="Old note")
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"notes": "New note"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["notes"] == "New note"

    def test_clear_notes_with_empty_string(self, authed_client, app):
        """Sending an empty string for notes should set it to null (no note),
        not store an empty string."""
        with app.app_context():
            task = _make_task(notes="Will be removed")
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"notes": ""}
        )
        assert resp.status_code == 200
        assert resp.get_json()["notes"] is None

    def test_notes_with_long_text(self, authed_client):
        """Notes is a TEXT column — no practical length limit."""
        long_note = "A" * 5000
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Long note", "type": "work", "notes": long_note},
        )
        assert resp.status_code == 201
        assert resp.get_json()["notes"] == long_note

    def test_notes_with_special_characters(self, authed_client):
        """Notes should handle newlines, unicode, and special chars safely."""
        note = "Line 1\nLine 2\n• Bullet point\n— Em dash\n🎯 Emoji"
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "Special", "type": "work", "notes": note},
        )
        assert resp.status_code == 201
        assert resp.get_json()["notes"] == note

    def test_update_notes_without_affecting_checklist(self, authed_client, app):
        """Updating just notes should leave the checklist untouched.

        PATCH only changes the fields you send. This test confirms that
        sending only 'notes' doesn't wipe out an existing checklist.
        """
        with app.app_context():
            task = _make_task(
                notes="Original",
                checklist=[{"id": "1", "text": "Keep me", "checked": False}],
            )
            task_id = str(task.id)

        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"notes": "Updated"}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["notes"] == "Updated"
        assert body["checklist"][0]["text"] == "Keep me"


# --- View integration: HTML elements exist ------------------------------------


class TestChecklistNotesViews:
    """Verify the HTML has the elements the JavaScript needs to render
    checklists and notes in the detail panel."""

    def test_detail_panel_has_notes_field(self, client, monkeypatch):
        import auth

        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="detailNotes"' in html

    def test_detail_panel_has_checklist_container(self, client, monkeypatch):
        import auth

        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="checklistItems"' in html

    def test_detail_panel_has_add_checklist_button(self, client, monkeypatch):
        import auth

        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/").data.decode()
        assert 'id="addChecklistItem"' in html
