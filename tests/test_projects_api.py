"""Tests for the projects JSON API."""
from __future__ import annotations

import uuid

import auth
from models import Goal, GoalCategory, GoalPriority, Project, db


def _make_project(**overrides) -> Project:
    fields = {"name": "Seed Project"}
    fields.update(overrides)
    project = Project(**fields)
    db.session.add(project)
    db.session.commit()
    return project


# --- Auth --------------------------------------------------------------------


def test_projects_api_requires_login(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/api/projects")
    assert resp.status_code == 302


def test_projects_api_rejects_wrong_email(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "intruder@example.com")
    resp = client.get("/api/projects")
    assert resp.status_code == 403


# --- POST --------------------------------------------------------------------


def test_create_project_201(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "Portal", "color": "#ff8800"}
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Portal"
    assert body["color"] == "#ff8800"
    assert body["type"] == "work"
    assert body["is_active"] is True
    assert uuid.UUID(body["id"])


def test_create_project_minimal(authed_client):
    resp = authed_client.post("/api/projects", json={"name": "Minimal"})
    assert resp.status_code == 201
    assert resp.get_json()["color"] is None


def test_create_project_with_goal(authed_client, app):
    with app.app_context():
        goal = Goal(
            title="Ship it", category=GoalCategory.WORK, priority=GoalPriority.MUST
        )
        db.session.add(goal)
        db.session.commit()
        goal_id = str(goal.id)
    resp = authed_client.post(
        "/api/projects", json={"name": "Linked", "goal_id": goal_id}
    )
    assert resp.status_code == 201
    assert resp.get_json()["goal_id"] == goal_id


def test_create_project_422_missing_name(authed_client):
    resp = authed_client.post("/api/projects", json={})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "name"


def test_create_project_422_blank_name(authed_client):
    resp = authed_client.post("/api/projects", json={"name": "  "})
    assert resp.status_code == 422


def test_create_project_400_no_json(authed_client):
    resp = authed_client.post("/api/projects", data="bad", content_type="text/plain")
    assert resp.status_code == 400


# --- GET list ----------------------------------------------------------------


def test_list_projects_active_only(authed_client, app):
    with app.app_context():
        _make_project(name="Active")
        _make_project(name="Hidden", is_active=False)
    resp = authed_client.get("/api/projects")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()]
    assert names == ["Active"]


def test_list_projects_all(authed_client, app):
    with app.app_context():
        _make_project(name="A")
        _make_project(name="B", is_active=False)
    resp = authed_client.get("/api/projects?is_active=all")
    assert len(resp.get_json()) == 2


def test_list_projects_sorted_by_order(authed_client, app):
    with app.app_context():
        _make_project(name="B", sort_order=2)
        _make_project(name="A", sort_order=1)
    resp = authed_client.get("/api/projects")
    names = [p["name"] for p in resp.get_json()]
    assert names == ["A", "B"]


# --- GET one -----------------------------------------------------------------


def test_show_project(authed_client, app):
    with app.app_context():
        p = _make_project(name="Show")
        pid = p.id
    resp = authed_client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Show"


def test_show_project_404(authed_client):
    resp = authed_client.get(f"/api/projects/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- PATCH -------------------------------------------------------------------


def test_patch_rename(authed_client, app):
    with app.app_context():
        p = _make_project(name="Old")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"name": "New"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "New"


def test_patch_update_all(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(
        f"/api/projects/{pid}",
        json={
            "name": "Updated",
            "color": "#123456",
            "is_active": False,
            "sort_order": 9,
            "goal_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["color"] == "#123456"
    assert body["is_active"] is False
    assert body["sort_order"] == 9


def test_patch_422_blank_name(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"name": "  "})
    assert resp.status_code == 422


def test_patch_422_bad_is_active(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"is_active": "yes"})
    assert resp.status_code == 422


def test_patch_422_bad_sort_order(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"sort_order": "abc"})
    assert resp.status_code == 422


def test_patch_422_unknown_field(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"nope": 1})
    assert resp.status_code == 422


def test_patch_404(authed_client):
    resp = authed_client.patch(f"/api/projects/{uuid.uuid4()}", json={"name": "x"})
    assert resp.status_code == 404


def test_patch_400_no_json(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(
        f"/api/projects/{pid}", data="bad", content_type="text/plain"
    )
    assert resp.status_code == 400


# --- DELETE ------------------------------------------------------------------


def test_delete_soft_hides(authed_client, app):
    with app.app_context():
        p = _make_project(name="Bye")
        pid = p.id
    resp = authed_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204
    with app.app_context():
        fetched = db.session.get(Project, pid)
        assert fetched.is_active is False


def test_delete_404(authed_client):
    resp = authed_client.delete(f"/api/projects/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- Seed defaults -----------------------------------------------------------


def test_seed_creates_defaults(authed_client, app):
    resp = authed_client.post("/api/projects/seed")
    assert resp.status_code == 200
    body = resp.get_json()
    names = [p["name"] for p in body]
    assert "Portal" in names
    assert "Roadmaps" in names
    assert len(body) == 9


def test_seed_idempotent(authed_client, app):
    authed_client.post("/api/projects/seed")
    resp = authed_client.post("/api/projects/seed")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 9


def test_seed_does_not_overwrite_existing(authed_client, app):
    with app.app_context():
        _make_project(name="Custom")
    resp = authed_client.post("/api/projects/seed")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()]
    assert names == ["Custom"]
