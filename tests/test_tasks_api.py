"""Tests for the tasks JSON API."""
from __future__ import annotations

import uuid

import auth
from models import Task, TaskStatus, TaskType, Tier, db


def _make_task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- Auth --------------------------------------------------------------------


def test_api_requires_login(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/api/tasks")
    assert resp.status_code == 302


def test_api_rejects_wrong_email(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "intruder@example.com")
    resp = client.get("/api/tasks")
    assert resp.status_code == 403


# --- POST --------------------------------------------------------------------


def test_create_task_201(authed_client):
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Review PR", "type": "work", "tier": "today"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["title"] == "Review PR"
    assert body["tier"] == "today"
    assert body["type"] == "work"
    assert body["status"] == "active"
    assert body["checklist"] == []
    assert uuid.UUID(body["id"])


def test_create_task_defaults_tier_to_inbox(authed_client):
    resp = authed_client.post("/api/tasks", json={"title": "Thing", "type": "personal"})
    assert resp.status_code == 201
    assert resp.get_json()["tier"] == "inbox"


def test_create_task_with_all_fields(authed_client):
    resp = authed_client.post(
        "/api/tasks",
        json={
            "title": "Full task",
            "type": "work",
            "tier": "this_week",
            "due_date": "2026-04-10",
            "notes": "background",
            "checklist": [{"id": "a", "text": "step 1", "checked": False}],
            "sort_order": 3,
        },
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["due_date"] == "2026-04-10"
    assert body["sort_order"] == 3
    assert body["checklist"][0]["text"] == "step 1"


def test_create_task_422_missing_title(authed_client):
    resp = authed_client.post("/api/tasks", json={"type": "work"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "title"


def test_create_task_422_blank_title(authed_client):
    resp = authed_client.post("/api/tasks", json={"title": "   ", "type": "work"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "title"


def test_create_task_422_missing_type(authed_client):
    resp = authed_client.post("/api/tasks", json={"title": "x"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "type"


def test_create_task_422_invalid_type(authed_client):
    resp = authed_client.post("/api/tasks", json={"title": "x", "type": "nope"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "type"


def test_create_task_422_invalid_tier(authed_client):
    resp = authed_client.post(
        "/api/tasks", json={"title": "x", "type": "work", "tier": "someday"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "tier"


def test_create_task_422_invalid_date(authed_client):
    resp = authed_client.post(
        "/api/tasks", json={"title": "x", "type": "work", "due_date": "not-a-date"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "due_date"


def test_create_task_422_invalid_uuid(authed_client):
    resp = authed_client.post(
        "/api/tasks", json={"title": "x", "type": "work", "project_id": "not-a-uuid"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "project_id"


def test_create_task_422_invalid_checklist(authed_client):
    resp = authed_client.post(
        "/api/tasks", json={"title": "x", "type": "work", "checklist": "not-a-list"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "checklist"


def test_create_task_422_invalid_sort_order(authed_client):
    resp = authed_client.post(
        "/api/tasks", json={"title": "x", "type": "work", "sort_order": "abc"}
    )
    assert resp.status_code == 422


def test_create_task_400_no_json_body(authed_client):
    resp = authed_client.post("/api/tasks", data="not json", content_type="text/plain")
    assert resp.status_code == 400


# --- GET list ----------------------------------------------------------------


def test_list_tasks_default_active_only(authed_client, app):
    with app.app_context():
        _make_task(title="active")
        _make_task(title="gone", status=TaskStatus.DELETED)
        _make_task(title="old", status=TaskStatus.ARCHIVED)
    resp = authed_client.get("/api/tasks")
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.get_json()]
    assert titles == ["active"]


def test_list_tasks_status_all(authed_client, app):
    with app.app_context():
        _make_task(title="a")
        _make_task(title="b", status=TaskStatus.DELETED)
    resp = authed_client.get("/api/tasks?status=all")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2


def test_list_tasks_filter_by_tier(authed_client, app):
    with app.app_context():
        _make_task(title="today1", tier=Tier.TODAY)
        _make_task(title="backlog1", tier=Tier.BACKLOG)
    resp = authed_client.get("/api/tasks?tier=today")
    assert [t["title"] for t in resp.get_json()] == ["today1"]


def test_list_tasks_filter_by_type(authed_client, app):
    with app.app_context():
        _make_task(title="w", type=TaskType.WORK)
        _make_task(title="p", type=TaskType.PERSONAL)
    resp = authed_client.get("/api/tasks?type=personal")
    assert [t["title"] for t in resp.get_json()] == ["p"]


def test_list_tasks_sort_order_then_created(authed_client, app):
    with app.app_context():
        _make_task(title="z", sort_order=0)
        _make_task(title="a", sort_order=5)
        _make_task(title="m", sort_order=0)
    resp = authed_client.get("/api/tasks")
    titles = [t["title"] for t in resp.get_json()]
    # sort_order=0 first (newest first within), then sort_order=5
    assert titles == ["m", "z", "a"]


def test_list_tasks_400_invalid_filter(authed_client):
    resp = authed_client.get("/api/tasks?tier=bogus")
    assert resp.status_code == 400


def test_list_tasks_400_invalid_status(authed_client):
    resp = authed_client.get("/api/tasks?status=bogus")
    assert resp.status_code == 400


def test_list_tasks_400_invalid_type(authed_client):
    resp = authed_client.get("/api/tasks?type=bogus")
    assert resp.status_code == 400


def test_list_tasks_400_invalid_project_uuid(authed_client):
    resp = authed_client.get("/api/tasks?project_id=not-a-uuid")
    assert resp.status_code == 400


def test_list_tasks_400_invalid_goal_uuid(authed_client):
    resp = authed_client.get("/api/tasks?goal_id=not-a-uuid")
    assert resp.status_code == 400


def test_list_tasks_filter_by_goal_uuid_ok(authed_client, app):
    with app.app_context():
        _make_task(title="no goal")
    resp = authed_client.get(f"/api/tasks?goal_id={uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_list_tasks_filter_by_project_uuid_ok(authed_client, app):
    with app.app_context():
        _make_task(title="no proj")
    resp = authed_client.get(f"/api/tasks?project_id={uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.get_json() == []


# --- GET one -----------------------------------------------------------------


def test_show_task_200(authed_client, app):
    with app.app_context():
        task = _make_task(title="Showable")
        task_id = task.id
    resp = authed_client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Showable"


def test_show_task_404(authed_client):
    resp = authed_client.get(f"/api/tasks/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- PATCH -------------------------------------------------------------------


def test_patch_update_title(authed_client, app):
    with app.app_context():
        task = _make_task(title="old")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"title": "new"})
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "new"


def test_patch_move_tier(authed_client, app):
    with app.app_context():
        task = _make_task(title="x", tier=Tier.INBOX)
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"tier": "today"})
    assert resp.status_code == 200
    assert resp.get_json()["tier"] == "today"


def test_patch_archive_via_status(authed_client, app):
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"status": "archived"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "archived"


def test_patch_update_checklist_and_notes(authed_client, app):
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(
        f"/api/tasks/{task_id}",
        json={
            "notes": "updated note",
            "checklist": [{"id": "1", "text": "a", "checked": True}],
            "due_date": "2026-05-01",
            "last_reviewed": "2026-04-05",
            "sort_order": 7,
            "project_id": None,
            "goal_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["notes"] == "updated note"
    assert body["checklist"][0]["checked"] is True
    assert body["due_date"] == "2026-05-01"
    assert body["last_reviewed"] == "2026-04-05"
    assert body["sort_order"] == 7


def test_patch_clear_notes_with_empty_string(authed_client, app):
    with app.app_context():
        task = _make_task(title="x", notes="something")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"notes": ""})
    assert resp.status_code == 200
    assert resp.get_json()["notes"] is None


def test_patch_422_blank_title(authed_client, app):
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"title": "   "})
    assert resp.status_code == 422


def test_patch_422_unknown_field(authed_client, app):
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"bogus_field": "x"})
    assert resp.status_code == 422


def test_patch_404(authed_client):
    resp = authed_client.patch(f"/api/tasks/{uuid.uuid4()}", json={"title": "x"})
    assert resp.status_code == 404


def test_patch_400_no_json(authed_client, app):
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(
        f"/api/tasks/{task_id}", data="nope", content_type="text/plain"
    )
    assert resp.status_code == 400


# --- DELETE ------------------------------------------------------------------


def test_delete_soft_deletes(authed_client, app):
    with app.app_context():
        task = _make_task(title="bye")
        task_id = task.id
    resp = authed_client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 204

    with app.app_context():
        fetched = db.session.get(Task, task_id)
        assert fetched is not None
        assert fetched.status is TaskStatus.DELETED


def test_delete_404(authed_client):
    resp = authed_client.delete(f"/api/tasks/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- URL field ---------------------------------------------------------------


def test_create_task_with_url(authed_client):
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Read this", "type": "personal", "url": "https://example.com/article"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["url"] == "https://example.com/article"


def test_create_task_url_defaults_to_none(authed_client):
    resp = authed_client.post("/api/tasks", json={"title": "No link", "type": "work"})
    assert resp.status_code == 201
    assert resp.get_json()["url"] is None


def test_create_task_422_invalid_url_scheme(authed_client):
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Bad url", "type": "work", "url": "ftp://bad.example.com"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "url"


def test_patch_add_url_to_task(authed_client, app):
    with app.app_context():
        task = _make_task(title="Article")
        task_id = task.id
    resp = authed_client.patch(
        f"/api/tasks/{task_id}", json={"url": "https://news.example.com/post"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://news.example.com/post"


def test_patch_clear_url(authed_client, app):
    with app.app_context():
        task = _make_task(title="Article", url="https://example.com")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"url": ""})
    assert resp.status_code == 200
    assert resp.get_json()["url"] is None


# --- URL preview endpoint ----------------------------------------------------


def test_url_preview_400_no_json(authed_client):
    resp = authed_client.post(
        "/api/tasks/url-preview", data="nope", content_type="text/plain"
    )
    assert resp.status_code == 400


def test_url_preview_400_invalid_scheme(authed_client):
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "ftp://bad.example.com"}
    )
    assert resp.status_code == 400


def test_url_preview_returns_title_on_success(authed_client, monkeypatch):
    import urllib.request

    class _FakeResp:
        def read(self, n):  # noqa: ARG002
            return b"<html><head><title>My Article Title</title></head></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResp())  # noqa: ARG005
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://example.com/article"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["title"] == "My Article Title"
    assert body["url"] == "https://example.com/article"


def test_url_preview_returns_null_title_on_fetch_failure(authed_client, monkeypatch):
    import urllib.request

    def _boom(req, timeout):  # noqa: ARG001
        raise OSError("network error")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://example.com/article"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["title"] is None


# --- Reorder -----------------------------------------------------------------


class TestReorder:
    """Verify POST /api/tasks/reorder."""

    def test_reorder_updates_sort_order(self, authed_client, app):
        with app.app_context():
            t1 = _make_task(title="First", tier=Tier.TODAY)
            t2 = _make_task(title="Second", tier=Tier.TODAY)
            t3 = _make_task(title="Third", tier=Tier.TODAY)
            ids = [str(t3.id), str(t1.id), str(t2.id)]

        resp = authed_client.post(
            "/api/tasks/reorder",
            json={"tier": "today", "task_ids": ids},
        )
        assert resp.status_code == 200
        assert resp.get_json()["reordered"] == 3

        # Verify order persisted
        resp = authed_client.get("/api/tasks?tier=today")
        titles = [t["title"] for t in resp.get_json()]
        assert titles == ["Third", "First", "Second"]

    def test_reorder_no_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/tasks/reorder",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_reorder_missing_fields_returns_422(self, authed_client):
        resp = authed_client.post(
            "/api/tasks/reorder",
            json={"tier": "today"},
        )
        assert resp.status_code == 422

    def test_reorder_invalid_tier_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/tasks/reorder",
            json={"tier": "invalid", "task_ids": []},
        )
        assert resp.status_code == 400
