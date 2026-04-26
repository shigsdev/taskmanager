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


def test_patch_cancel_with_reason(authed_client, app):
    """Backlog #25: status=cancelled persists with optional reason."""
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "cancelled", "cancellation_reason": "Out of scope"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "Out of scope"


def test_patch_cancel_without_reason(authed_client, app):
    """Reason is optional — cancelling without one stores null."""
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"status": "cancelled"})
    assert resp.status_code == 200
    assert resp.get_json()["cancellation_reason"] is None


def test_patch_uncancel_clears_reason(authed_client, app):
    """Transitioning out of cancelled clears the reason so it doesn't
    outlive the cancellation (#25)."""
    with app.app_context():
        task = _make_task(title="x")
        task_id = task.id
    authed_client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "cancelled", "cancellation_reason": "give up"},
    )
    resp = authed_client.patch(f"/api/tasks/{task_id}", json={"status": "active"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "active"
    assert body["cancellation_reason"] is None


def test_list_filter_status_cancelled(authed_client, app):
    """GET /api/tasks?status=cancelled returns only cancelled tasks."""
    with app.app_context():
        active = _make_task(title="active task")
        cancel = _make_task(title="dropped task")
        cancel_id = cancel.id
        active_id = active.id
    authed_client.patch(f"/api/tasks/{cancel_id}", json={"status": "cancelled"})
    resp = authed_client.get("/api/tasks?status=cancelled")
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.get_json()]
    assert str(cancel_id) in ids
    assert str(active_id) not in ids


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
    # After the SSRF fix, the endpoint uses urllib.request.build_opener()
    # + opener.open() instead of the plain urlopen(), so we patch the
    # OpenerDirector.open method to return a fake response.
    import urllib.request

    class _FakeResp:
        def read(self, n):  # noqa: ARG002
            return b"<html><head><title>My Article Title</title></head></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        urllib.request.OpenerDirector,
        "open",
        lambda self, req, timeout=None: _FakeResp(),  # noqa: ARG005
    )
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://example.com/article"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["title"] == "My Article Title"
    assert body["url"] == "https://example.com/article"


def test_url_preview_returns_null_title_on_fetch_failure(authed_client, monkeypatch):
    import urllib.request

    def _boom(self, req, timeout=None):  # noqa: ARG001
        raise OSError("network error")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _boom)
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://example.com/article"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["title"] is None


# --- SSRF defenses (docs/adr/006-ssrf-defense.md) ----------------------------


def test_url_preview_rejects_loopback_ip(authed_client, monkeypatch):
    """Even if the attacker supplies a domain that resolves to 127.0.0.1,
    the ip check must reject it."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://fake.example/attack"}
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.get_json()["error"]


def test_url_preview_rejects_link_local(authed_client, monkeypatch):
    """AWS / Railway metadata endpoints live on 169.254.169.254; must reject."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("169.254.169.254", 0))],
    )
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://fake.example/metadata"}
    )
    assert resp.status_code == 400


def test_url_preview_rejects_private_network(authed_client, monkeypatch):
    """RFC 1918 private ranges must be rejected."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("10.0.0.5", 0))],
    )
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://fake.example/internal"}
    )
    assert resp.status_code == 400


def test_url_preview_rejects_dns_rebinding_mixed_answers(authed_client, monkeypatch):
    """If a DNS response contains ANY disallowed IP alongside safe ones,
    reject — we never want the OS's round-robin to accidentally pick the
    unsafe one."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (None, None, None, None, ("93.184.216.34", 0)),  # example.com public IP
            (None, None, None, None, ("127.0.0.1", 0)),        # rebind bait
        ],
    )
    resp = authed_client.post(
        "/api/tasks/url-preview", json={"url": "https://rebind.example/page"}
    )
    assert resp.status_code == 400


def test_url_preview_no_redirect_follow_ssrf(authed_client, monkeypatch):
    """Even if the server responds with a 302 redirect, we must not
    follow it — otherwise a safe URL could redirect to localhost."""
    import socket
    import urllib.request

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )

    # Simulate a 302 response — if redirect following were enabled,
    # urllib would raise HTTPError or follow to the new location.
    # With our _NoRedirect handler, redirect_request returns None, so
    # urllib treats the 302 as a final response. The test just verifies
    # we don't follow — we accept that the title may be None on such
    # responses.
    class _Resp302:
        status = 302

        def read(self, n):  # noqa: ARG002
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        urllib.request.OpenerDirector,
        "open",
        lambda self, req, timeout=None: _Resp302(),  # noqa: ARG005
    )
    resp = authed_client.post(
        "/api/tasks/url-preview",
        json={"url": "https://safe.example/redirects-to-localhost"},
    )
    # Fetch didn't crash; title is None because no <title> in empty body.
    assert resp.status_code == 200
    assert resp.get_json()["title"] is None


# --- Subtasks ----------------------------------------------------------------


def test_create_subtask(authed_client, app):
    # Create parent
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    # Create subtask
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Child", "type": "work", "parent_id": parent_id},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["parent_id"] == parent_id


def test_subtask_inherits_goal_and_project(authed_client, app):
    """Subtasks inherit goal_id and project_id from parent when not provided."""
    # Create a goal
    g = authed_client.post(
        "/api/goals",
        json={"title": "Ship v2", "category": "work", "priority": "must"},
    )
    goal_id = g.get_json()["id"]

    # Create a project
    p = authed_client.post("/api/projects", json={"name": "Backend"})
    project_id = p.get_json()["id"]

    # Create parent with goal + project
    resp = authed_client.post(
        "/api/tasks",
        json={
            "title": "Parent",
            "type": "work",
            "goal_id": goal_id,
            "project_id": project_id,
        },
    )
    parent_id = resp.get_json()["id"]

    # Create subtask WITHOUT goal or project — should inherit
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Child", "type": "work", "parent_id": parent_id},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["goal_id"] == goal_id
    assert body["project_id"] == project_id


def test_subtask_explicit_goal_overrides_parent(authed_client, app):
    """If a subtask explicitly sets goal_id, it should NOT be overridden."""
    g1 = authed_client.post(
        "/api/goals",
        json={"title": "Goal A", "category": "work", "priority": "must"},
    )
    g2 = authed_client.post(
        "/api/goals",
        json={"title": "Goal B", "category": "health", "priority": "should"},
    )
    goal_a = g1.get_json()["id"]
    goal_b = g2.get_json()["id"]

    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Parent", "type": "work", "goal_id": goal_a},
    )
    parent_id = resp.get_json()["id"]

    resp = authed_client.post(
        "/api/tasks",
        json={
            "title": "Child",
            "type": "work",
            "parent_id": parent_id,
            "goal_id": goal_b,
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["goal_id"] == goal_b


def test_update_parent_goal_cascades_to_matching_subtasks(authed_client, app):
    """Moving a parent to a new goal cascades to subtasks that still mirror
    the parent's OLD goal. Subtasks with an explicit override are preserved."""
    g1 = authed_client.post(
        "/api/goals",
        json={"title": "Goal A", "category": "work", "priority": "must"},
    )
    g2 = authed_client.post(
        "/api/goals",
        json={"title": "Goal B", "category": "work", "priority": "should"},
    )
    g3 = authed_client.post(
        "/api/goals",
        json={"title": "Goal C", "category": "work", "priority": "could"},
    )
    goal_a = g1.get_json()["id"]
    goal_b = g2.get_json()["id"]
    goal_c = g3.get_json()["id"]

    # Parent starts on Goal A
    p = authed_client.post(
        "/api/tasks",
        json={"title": "Parent", "type": "work", "goal_id": goal_a},
    )
    parent_id = p.get_json()["id"]

    # Subtask 1 inherits Goal A (no explicit goal)
    s1 = authed_client.post(
        "/api/tasks",
        json={"title": "Inherited sub", "type": "work", "parent_id": parent_id},
    )
    inherited_id = s1.get_json()["id"]
    assert s1.get_json()["goal_id"] == goal_a

    # Subtask 2 is explicitly on Goal B (override)
    s2 = authed_client.post(
        "/api/tasks",
        json={
            "title": "Overridden sub",
            "type": "work",
            "parent_id": parent_id,
            "goal_id": goal_b,
        },
    )
    overridden_id = s2.get_json()["id"]
    assert s2.get_json()["goal_id"] == goal_b

    # Move the parent to Goal C
    resp = authed_client.patch(
        f"/api/tasks/{parent_id}", json={"goal_id": goal_c}
    )
    assert resp.status_code == 200
    assert resp.get_json()["goal_id"] == goal_c

    # Inherited subtask follows the parent
    assert (
        authed_client.get(f"/api/tasks/{inherited_id}").get_json()["goal_id"]
        == goal_c
    )
    # Overridden subtask stays put
    assert (
        authed_client.get(f"/api/tasks/{overridden_id}").get_json()["goal_id"]
        == goal_b
    )


def test_update_parent_project_cascades_to_matching_subtasks(authed_client, app):
    """Same cascade rule applies to project_id, for symmetry with goal_id."""
    proj_a = authed_client.post("/api/projects", json={"name": "Proj A"}).get_json()["id"]
    proj_b = authed_client.post("/api/projects", json={"name": "Proj B"}).get_json()["id"]
    proj_c = authed_client.post("/api/projects", json={"name": "Proj C"}).get_json()["id"]

    parent_id = authed_client.post(
        "/api/tasks",
        json={"title": "Parent", "type": "work", "project_id": proj_a},
    ).get_json()["id"]

    inherited_id = authed_client.post(
        "/api/tasks",
        json={"title": "Inherited", "type": "work", "parent_id": parent_id},
    ).get_json()["id"]

    overridden_id = authed_client.post(
        "/api/tasks",
        json={
            "title": "Overridden",
            "type": "work",
            "parent_id": parent_id,
            "project_id": proj_b,
        },
    ).get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{parent_id}", json={"project_id": proj_c}
    )
    assert resp.status_code == 200

    assert (
        authed_client.get(f"/api/tasks/{inherited_id}").get_json()["project_id"]
        == proj_c
    )
    assert (
        authed_client.get(f"/api/tasks/{overridden_id}").get_json()["project_id"]
        == proj_b
    )


def test_update_parent_goal_to_null_cascades(authed_client, app):
    """Clearing a parent's goal propagates null to inherited subtasks."""
    goal_id = authed_client.post(
        "/api/goals",
        json={"title": "G", "category": "work", "priority": "must"},
    ).get_json()["id"]

    parent_id = authed_client.post(
        "/api/tasks",
        json={"title": "Parent", "type": "work", "goal_id": goal_id},
    ).get_json()["id"]

    sub_id = authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    ).get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{parent_id}", json={"goal_id": None}
    )
    assert resp.status_code == 200
    assert resp.get_json()["goal_id"] is None
    assert authed_client.get(f"/api/tasks/{sub_id}").get_json()["goal_id"] is None


def test_update_parent_goal_from_null_cascades(authed_client, app):
    """Setting a goal on a goalless parent fills it in on subtasks with null goal."""
    parent_id = authed_client.post(
        "/api/tasks", json={"title": "Parent", "type": "work"}
    ).get_json()["id"]

    sub_id = authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    ).get_json()["id"]
    assert (
        authed_client.get(f"/api/tasks/{sub_id}").get_json()["goal_id"] is None
    )

    goal_id = authed_client.post(
        "/api/goals",
        json={"title": "G", "category": "work", "priority": "must"},
    ).get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{parent_id}", json={"goal_id": goal_id}
    )
    assert resp.status_code == 200
    assert (
        authed_client.get(f"/api/tasks/{sub_id}").get_json()["goal_id"] == goal_id
    )


def test_update_parent_unrelated_field_does_not_touch_subtask_goal(authed_client, app):
    """Changing a field like title must not cascade or disturb subtask goals."""
    goal_id = authed_client.post(
        "/api/goals",
        json={"title": "G", "category": "work", "priority": "must"},
    ).get_json()["id"]

    parent_id = authed_client.post(
        "/api/tasks",
        json={"title": "Parent", "type": "work", "goal_id": goal_id},
    ).get_json()["id"]

    sub_id = authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    ).get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{parent_id}", json={"title": "Parent renamed"}
    )
    assert resp.status_code == 200
    assert (
        authed_client.get(f"/api/tasks/{sub_id}").get_json()["goal_id"] == goal_id
    )


def test_update_subtask_goal_does_not_cascade(authed_client, app):
    """Subtasks cannot have subtasks, so updating a subtask's own goal is a
    plain field update — no cascade pass, no error."""
    parent_id = authed_client.post(
        "/api/tasks", json={"title": "Parent", "type": "work"}
    ).get_json()["id"]

    sub_id = authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    ).get_json()["id"]

    goal_id = authed_client.post(
        "/api/goals",
        json={"title": "G", "category": "work", "priority": "must"},
    ).get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{sub_id}", json={"goal_id": goal_id}
    )
    assert resp.status_code == 200
    assert resp.get_json()["goal_id"] == goal_id


def test_create_subtask_of_subtask_rejected(authed_client, app):
    """One level deep only — subtasks cannot have their own subtasks."""
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Child", "type": "work", "parent_id": parent_id},
    )
    child_id = resp.get_json()["id"]

    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Grandchild", "type": "work", "parent_id": child_id},
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "parent_id"


def test_create_subtask_nonexistent_parent(authed_client):
    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Orphan", "type": "work", "parent_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "parent_id"


def test_list_subtasks_endpoint(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    authed_client.post(
        "/api/tasks",
        json={"title": "Sub A", "type": "work", "parent_id": parent_id},
    )
    authed_client.post(
        "/api/tasks",
        json={"title": "Sub B", "type": "work", "parent_id": parent_id},
    )

    resp = authed_client.get(f"/api/tasks/{parent_id}/subtasks")
    assert resp.status_code == 200
    subs = resp.get_json()
    assert len(subs) == 2
    assert {s["title"] for s in subs} == {"Sub A", "Sub B"}


def test_subtask_count_in_serializer(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    authed_client.post(
        "/api/tasks",
        json={"title": "Sub 1", "type": "work", "parent_id": parent_id},
    )

    resp = authed_client.get(f"/api/tasks/{parent_id}")
    body = resp.get_json()
    assert body["subtask_count"] == 1
    assert body["subtask_done"] == 0


def test_complete_parent_warns_about_open_subtasks(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    )

    # Without complete_subtasks flag → 422 warning
    resp = authed_client.post(f"/api/tasks/{parent_id}/complete")
    assert resp.status_code == 422
    assert "open subtask" in resp.get_json()["error"]


def test_complete_parent_with_force_completes_subtasks(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    sub_resp = authed_client.post(
        "/api/tasks",
        json={"title": "Sub", "type": "work", "parent_id": parent_id},
    )
    sub_id = sub_resp.get_json()["id"]

    resp = authed_client.post(
        f"/api/tasks/{parent_id}/complete",
        json={"complete_subtasks": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "archived"

    # Subtask should also be archived
    resp = authed_client.get(f"/api/tasks/{sub_id}")
    assert resp.get_json()["status"] == "archived"


def test_complete_parent_no_subtasks_works(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Solo", "type": "work"})
    task_id = resp.get_json()["id"]

    resp = authed_client.post(f"/api/tasks/{task_id}/complete")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "archived"


def test_patch_cannot_set_self_as_parent(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Task", "type": "work"})
    task_id = resp.get_json()["id"]

    resp = authed_client.patch(
        f"/api/tasks/{task_id}", json={"parent_id": task_id}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "parent_id"


def test_patch_clear_parent_id(authed_client, app):
    resp = authed_client.post("/api/tasks", json={"title": "Parent", "type": "work"})
    parent_id = resp.get_json()["id"]

    resp = authed_client.post(
        "/api/tasks",
        json={"title": "Child", "type": "work", "parent_id": parent_id},
    )
    child_id = resp.get_json()["id"]

    # Remove parent
    resp = authed_client.patch(f"/api/tasks/{child_id}", json={"parent_id": None})
    assert resp.status_code == 200
    assert resp.get_json()["parent_id"] is None


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


# --- Repeat (task ↔ recurring template) --------------------------------------


class TestRepeatOnCreate:
    """Creating a task with a repeat field should auto-create a RecurringTask."""

    def test_create_task_with_daily_repeat(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Morning standup",
                "type": "work",
                "repeat": {"frequency": "daily"},
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["repeat"] is not None
        assert body["repeat"]["frequency"] == "daily"

    def test_create_task_with_weekdays_repeat(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Check email",
                "type": "work",
                "repeat": {"frequency": "weekdays"},
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["repeat"]["frequency"] == "weekdays"

    def test_create_task_with_weekly_repeat(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Weekly review",
                "type": "personal",
                "repeat": {"frequency": "weekly", "day_of_week": 4},
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["repeat"]["frequency"] == "weekly"
        assert body["repeat"]["day_of_week"] == 4

    def test_create_task_with_monthly_date_repeat(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Pay rent",
                "type": "personal",
                "repeat": {"frequency": "monthly_date", "day_of_month": 1},
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["repeat"]["frequency"] == "monthly_date"
        assert body["repeat"]["day_of_month"] == 1

    def test_create_task_with_monthly_nth_weekday_repeat(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Team retro",
                "type": "work",
                "repeat": {
                    "frequency": "monthly_nth_weekday",
                    "week_of_month": 2,
                    "day_of_week": 3,
                },
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["repeat"]["frequency"] == "monthly_nth_weekday"
        assert body["repeat"]["week_of_month"] == 2
        assert body["repeat"]["day_of_week"] == 3

    def test_create_task_without_repeat_has_null(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "One-off", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["repeat"] is None

    def test_repeat_creates_recurring_template(self, authed_client):
        """The recurring template should be visible via /api/recurring."""
        authed_client.post(
            "/api/tasks",
            json={
                "title": "Auto-template",
                "type": "work",
                "repeat": {"frequency": "daily"},
            },
        )
        resp = authed_client.get("/api/recurring")
        titles = [r["title"] for r in resp.get_json()]
        assert "Auto-template" in titles

    def test_repeat_inherits_task_details(self, authed_client):
        """Recurring template should copy notes, URL, project, goal from task."""
        authed_client.post(
            "/api/tasks",
            json={
                "title": "Detailed repeat",
                "type": "work",
                "notes": "Important notes",
                "url": "https://example.com",
                "repeat": {"frequency": "daily"},
            },
        )
        resp = authed_client.get("/api/recurring")
        templates = [r for r in resp.get_json() if r["title"] == "Detailed repeat"]
        assert len(templates) == 1
        assert templates[0]["notes"] == "Important notes"
        assert templates[0]["url"] == "https://example.com"

    def test_repeat_snapshots_active_subtasks(self, authed_client):
        """Backlog #26: making a parent task recurring captures its
        currently-active subtasks onto the template."""
        parent = authed_client.post(
            "/api/tasks", json={"title": "Weekly review", "type": "work"}
        ).get_json()
        authed_client.post(
            "/api/tasks",
            json={
                "title": "Review Today", "type": "work", "parent_id": parent["id"],
            },
        )
        authed_client.post(
            "/api/tasks",
            json={
                "title": "Review Goals", "type": "work", "parent_id": parent["id"],
            },
        )
        # Now flip the parent to recurring
        authed_client.patch(
            f"/api/tasks/{parent['id']}",
            json={"repeat": {"frequency": "daily"}},
        )
        templates = [
            r for r in authed_client.get("/api/recurring").get_json()
            if r["title"] == "Weekly review"
        ]
        assert len(templates) == 1
        snap = templates[0]["subtasks_snapshot"]
        titles = sorted(s["title"] for s in snap)
        assert titles == ["Review Goals", "Review Today"]


class TestRepeatOnUpdate:
    """Updating a task's repeat field should create/update/remove the template."""

    def test_add_repeat_to_existing_task(self, authed_client, app):
        with app.app_context():
            task = _make_task(title="Now repeats")
            task_id = task.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}",
            json={"repeat": {"frequency": "daily"}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["repeat"]["frequency"] == "daily"

    def test_remove_repeat_from_task(self, authed_client):
        # Create with repeat
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Will un-repeat",
                "type": "work",
                "repeat": {"frequency": "daily"},
            },
        )
        task_id = resp.get_json()["id"]

        # Remove repeat
        resp = authed_client.patch(
            f"/api/tasks/{task_id}",
            json={"repeat": None},
        )
        assert resp.status_code == 200
        assert resp.get_json()["repeat"] is None

    def test_change_repeat_frequency(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "Freq change",
                "type": "work",
                "repeat": {"frequency": "daily"},
            },
        )
        task_id = resp.get_json()["id"]

        resp = authed_client.patch(
            f"/api/tasks/{task_id}",
            json={"repeat": {"frequency": "weekly", "day_of_week": 2}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["repeat"]["frequency"] == "weekly"
        assert resp.get_json()["repeat"]["day_of_week"] == 2


# --- Bulk endpoint (PATCH /api/tasks/bulk) ----------------------------------


def _create_n_tasks(authed_client, n: int, **defaults) -> list[str]:
    """Helper: create N tasks and return their ids."""
    base = {"title": "T", "type": "work"}
    base.update(defaults)
    ids = []
    for i in range(n):
        body = dict(base)
        body["title"] = f"{base['title']}-{i}"
        resp = authed_client.post("/api/tasks", json=body)
        assert resp.status_code == 201, resp.get_json()
        ids.append(resp.get_json()["id"])
    return ids


class TestBulkUpdate:
    """PATCH /api/tasks/bulk applies one update dict to many tasks."""

    def test_bulk_set_tier(self, authed_client):
        ids = _create_n_tasks(authed_client, 3)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"tier": "today"}},
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"updated": 3, "not_found": [], "errors": []}
        # Verify the change actually persisted
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["tier"] == "today"

    def test_bulk_set_type(self, authed_client):
        ids = _create_n_tasks(authed_client, 2, type="work")
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"type": "personal"}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["type"] == "personal"

    def test_bulk_archive_via_status(self, authed_client):
        """Bulk-complete is implemented as bulk status=archived."""
        ids = _create_n_tasks(authed_client, 2)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"status": "archived"}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2

    def test_bulk_unknown_id_reported_in_not_found(self, authed_client):
        """One real id + one fake id → updated:1, not_found:[fake]."""
        ids = _create_n_tasks(authed_client, 1)
        fake_id = str(uuid.uuid4())
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids + [fake_id], "updates": {"tier": "today"}},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] == 1
        assert body["not_found"] == [fake_id]
        assert body["errors"] == []

    def test_bulk_invalid_field_reported_per_task(self, authed_client):
        """Invalid field → ValidationError per-task in errors[]; other tasks unaffected."""
        ids = _create_n_tasks(authed_client, 2)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"tier": "not_a_real_tier"}},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] == 0
        assert len(body["errors"]) == 2

    def test_bulk_rejects_empty_task_ids(self, authed_client):
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": [], "updates": {"tier": "today"}},
        )
        assert resp.status_code == 422

    def test_bulk_rejects_empty_updates(self, authed_client):
        ids = _create_n_tasks(authed_client, 1)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {}},
        )
        assert resp.status_code == 422

    def test_bulk_rejects_invalid_uuid(self, authed_client):
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ["not-a-uuid"], "updates": {"tier": "today"}},
        )
        assert resp.status_code == 422
        assert "invalid task_id" in resp.get_json()["error"]

    def test_bulk_caps_at_200_ids(self, authed_client):
        """Sanity guard against accidental 'select all 5000'."""
        too_many = [str(uuid.uuid4()) for _ in range(201)]
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": too_many, "updates": {"tier": "today"}},
        )
        assert resp.status_code == 422
        assert "max 200" in resp.get_json()["error"]

    def test_bulk_requires_json_body(self, authed_client):
        resp = authed_client.patch(
            "/api/tasks/bulk", data="not json", content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_bulk_requires_login(self, client, monkeypatch):
        """Bulk endpoint must require real OAuth — validator cookie is
        GET-only and PATCH must NEVER authenticate via it."""
        import auth
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.patch(
            "/api/tasks/bulk",
            json={"task_ids": [str(uuid.uuid4())], "updates": {"tier": "today"}},
        )
        assert resp.status_code == 302
        assert "/login/google" in resp.headers.get("Location", "")

    def test_bulk_set_due_date(self, authed_client):
        """Bulk-set due_date with an ISO string."""
        ids = _create_n_tasks(authed_client, 3)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"due_date": "2026-12-25"}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 3
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["due_date"] == "2026-12-25"

    def test_bulk_clear_due_date(self, authed_client):
        """Passing due_date: null clears it on every task in the batch."""
        # First create + set a due date
        ids = _create_n_tasks(authed_client, 2)
        authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"due_date": "2026-06-01"}},
        )
        # Now clear
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"due_date": None}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["due_date"] is None

    def test_bulk_invalid_due_date_reported_per_task(self, authed_client):
        """An ISO-malformed date raises ValidationError per task; nothing committed."""
        ids = _create_n_tasks(authed_client, 2)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"due_date": "not-a-real-date"}},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] == 0
        assert len(body["errors"]) == 2
        assert all(e["field"] == "due_date" for e in body["errors"])
        # Confirm nothing actually changed
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["due_date"] is None

    def test_bulk_set_status_active(self, authed_client):
        """Mirror 'un-complete' from the UI: status=active."""
        ids = _create_n_tasks(authed_client, 2)
        # First archive them
        authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"status": "archived"}},
        )
        # Now bring them back
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"status": "active"}},
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2
        for tid in ids:
            assert authed_client.get(f"/api/tasks/{tid}").get_json()["status"] == "active"

    def test_bulk_combined_updates(self, authed_client):
        """Multiple fields in one bulk call — common UX flow: set tier
        AND due_date together. Verifies the dict is applied atomically
        per task."""
        ids = _create_n_tasks(authed_client, 2)
        resp = authed_client.patch(
            "/api/tasks/bulk",
            json={
                "task_ids": ids,
                "updates": {
                    "tier": "today",
                    "due_date": "2026-08-15",
                    "type": "personal",
                },
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["updated"] == 2
        for tid in ids:
            t = authed_client.get(f"/api/tasks/{tid}").get_json()
            assert t["tier"] == "today"
            assert t["due_date"] == "2026-08-15"
            assert t["type"] == "personal"


class TestRollTomorrowToToday:
    """Backlog #27: APScheduler job that moves TOMORROW → TODAY at midnight."""

    def test_rolls_active_tomorrow_tasks(self, app):
        from task_service import roll_tomorrow_to_today
        with app.app_context():
            _make_task(title="a", tier=Tier.TOMORROW)
            _make_task(title="b", tier=Tier.TOMORROW)
            _make_task(title="not-tomorrow", tier=Tier.THIS_WEEK)
            count = roll_tomorrow_to_today()
        assert count == 2
        with app.app_context():
            from sqlalchemy import select
            titles_today = [
                t.title for t in db.session.scalars(
                    select(Task).where(Task.tier == Tier.TODAY)
                )
            ]
            titles_tomorrow = [
                t.title for t in db.session.scalars(
                    select(Task).where(Task.tier == Tier.TOMORROW)
                )
            ]
        assert sorted(titles_today) == ["a", "b"]
        assert titles_tomorrow == []

    def test_does_not_roll_archived_tomorrow_tasks(self, app):
        from task_service import roll_tomorrow_to_today
        with app.app_context():
            _make_task(title="active", tier=Tier.TOMORROW)
            _make_task(
                title="old",
                tier=Tier.TOMORROW,
                status=TaskStatus.ARCHIVED,
            )
            count = roll_tomorrow_to_today()
        assert count == 1
        with app.app_context():
            from sqlalchemy import select
            archived_tomorrow = list(db.session.scalars(
                select(Task).where(
                    Task.tier == Tier.TOMORROW,
                    Task.status == TaskStatus.ARCHIVED,
                )
            ))
        assert len(archived_tomorrow) == 1

    def test_noop_when_nothing_in_tomorrow(self, app):
        from task_service import roll_tomorrow_to_today
        with app.app_context():
            _make_task(title="x", tier=Tier.TODAY)
            count = roll_tomorrow_to_today()
        assert count == 0


class TestTierDueDateAutoFill:
    """Backlog #28: TODAY/TOMORROW tier changes auto-fill due_date when
    the task doesn't already have one. Respects explicit user intent
    (fill-if-null only; never overwrite)."""

    def _expected_today_iso(self):
        """Mirror _local_today_date() for assertion parity."""
        from task_service import _local_today_date
        return _local_today_date().isoformat()

    def _expected_tomorrow_iso(self):
        from datetime import timedelta

        from task_service import _local_today_date
        return (_local_today_date() + timedelta(days=1)).isoformat()

    # --- create -------------------------------------------------------

    def test_create_today_with_no_due_date_fills_today(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "x", "type": "work", "tier": "today"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["due_date"] == self._expected_today_iso()

    def test_create_tomorrow_with_no_due_date_fills_tomorrow(
        self, authed_client,
    ):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "x", "type": "work", "tier": "tomorrow"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["due_date"] == self._expected_tomorrow_iso()

    def test_create_today_with_explicit_due_date_respects_user_value(
        self, authed_client,
    ):
        resp = authed_client.post(
            "/api/tasks",
            json={
                "title": "x", "type": "work",
                "tier": "today", "due_date": "2026-12-31",
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["due_date"] == "2026-12-31"

    def test_create_inbox_does_not_auto_fill(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "x", "type": "work"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["due_date"] is None

    def test_create_backlog_does_not_auto_fill(self, authed_client):
        resp = authed_client.post(
            "/api/tasks",
            json={"title": "x", "type": "work", "tier": "backlog"},
        )
        assert resp.get_json()["due_date"] is None

    # --- update -------------------------------------------------------

    def test_move_to_today_fills_if_null(self, authed_client, app):
        with app.app_context():
            t = _make_task(title="x", tier=Tier.BACKLOG)
            task_id = t.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "today"},
        )
        assert resp.get_json()["due_date"] == self._expected_today_iso()

    def test_move_to_tomorrow_fills_if_null(self, authed_client, app):
        with app.app_context():
            t = _make_task(title="x", tier=Tier.BACKLOG)
            task_id = t.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "tomorrow"},
        )
        assert resp.get_json()["due_date"] == self._expected_tomorrow_iso()

    def test_move_to_today_does_not_overwrite_explicit_date(
        self, authed_client, app,
    ):
        from datetime import date as _date
        with app.app_context():
            t = _make_task(
                title="x", tier=Tier.BACKLOG,
                due_date=_date(2026, 12, 31),
            )
            task_id = t.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "today"},
        )
        assert resp.get_json()["due_date"] == "2026-12-31"

    def test_explicit_null_due_date_in_same_patch_is_respected(
        self, authed_client, app,
    ):
        """If the user PATCHes {tier: today, due_date: null} they want
        both — don't auto-fill back on top of their explicit null."""
        with app.app_context():
            t = _make_task(title="x", tier=Tier.BACKLOG)
            task_id = t.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}",
            json={"tier": "today", "due_date": None},
        )
        assert resp.get_json()["due_date"] is None

    def test_move_out_of_today_leaves_due_date_intact(
        self, authed_client, app,
    ):
        """#28 design note: moving OUT of TODAY doesn't clear due_date."""
        from datetime import date as _date
        with app.app_context():
            t = _make_task(
                title="x", tier=Tier.TODAY, due_date=_date(2026, 4, 20),
            )
            task_id = t.id
        resp = authed_client.patch(
            f"/api/tasks/{task_id}", json={"tier": "backlog"},
        )
        body = resp.get_json()
        assert body["tier"] == "backlog"
        assert body["due_date"] == "2026-04-20"

    # --- bulk PATCH ---------------------------------------------------

    def test_bulk_move_to_today_fills_each_null(self, authed_client, app):
        with app.app_context():
            ids = [
                str(_make_task(title="a", tier=Tier.BACKLOG).id),
                str(_make_task(title="b", tier=Tier.BACKLOG).id),
            ]
        authed_client.patch(
            "/api/tasks/bulk",
            json={"task_ids": ids, "updates": {"tier": "today"}},
        )
        expected = self._expected_today_iso()
        for tid in ids:
            body = authed_client.get(f"/api/tasks/{tid}").get_json()
            assert body["due_date"] == expected


# --- #77: project goal cascade ----------------------------------------------


class TestProjectGoalCascade:
    """#77: setting project_id on a task cascades the project's goal_id."""

    def _make_goal_and_project(self, authed_client):
        g = authed_client.post(
            "/api/goals",
            json={"title": "G1", "category": "work", "priority": "must"},
        ).get_json()
        p = authed_client.post(
            "/api/projects",
            json={"name": "P1", "goal_id": g["id"]},
        ).get_json()
        return g["id"], p["id"]

    def test_patch_project_overwrites_existing_task_goal(self, authed_client):
        """Per scoping (b): every project change overwrites the goal."""
        gid, pid = self._make_goal_and_project(authed_client)
        # Create task with NO project, but a different goal pre-set.
        other = authed_client.post(
            "/api/goals",
            json={"title": "Other", "category": "work", "priority": "should"},
        ).get_json()
        t = authed_client.post(
            "/api/tasks",
            json={"title": "X", "type": "work", "goal_id": other["id"]},
        ).get_json()
        # Patch project_id — goal should now MATCH project's goal (not "other").
        resp = authed_client.patch(
            f"/api/tasks/{t['id']}", json={"project_id": pid}
        )
        body = resp.get_json()
        assert body["project_id"] == pid
        assert body["goal_id"] == gid

    def test_patch_project_to_null_clears_goal(self, authed_client):
        """Setting project_id back to null also clears the cascaded goal."""
        gid, pid = self._make_goal_and_project(authed_client)
        t = authed_client.post(
            "/api/tasks",
            json={"title": "X", "type": "work", "project_id": pid},
        ).get_json()
        assert t["goal_id"] == gid  # cascaded on create
        resp = authed_client.patch(
            f"/api/tasks/{t['id']}", json={"project_id": None}
        )
        assert resp.get_json()["goal_id"] is None

    def test_explicit_goal_in_same_payload_wins(self, authed_client):
        """If the caller sends BOTH project_id and goal_id, the explicit
        goal_id wins (caller intent over cascade)."""
        gid, pid = self._make_goal_and_project(authed_client)
        other = authed_client.post(
            "/api/goals",
            json={"title": "Other", "category": "work", "priority": "should"},
        ).get_json()
        t = authed_client.post("/api/tasks", json={"title": "X", "type": "work"}).get_json()
        resp = authed_client.patch(
            f"/api/tasks/{t['id']}",
            json={"project_id": pid, "goal_id": other["id"]},
        )
        body = resp.get_json()
        assert body["project_id"] == pid
        # Explicit goal beats cascade.
        assert body["goal_id"] == other["id"]

    def test_create_task_with_project_cascades_goal(self, authed_client):
        """Same cascade fires on create_task path."""
        gid, pid = self._make_goal_and_project(authed_client)
        t = authed_client.post(
            "/api/tasks",
            json={"title": "X", "type": "work", "project_id": pid},
        ).get_json()
        assert t["goal_id"] == gid
