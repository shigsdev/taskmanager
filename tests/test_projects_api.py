"""Tests for the projects JSON API."""
from __future__ import annotations

import uuid

import auth
from models import Goal, GoalCategory, GoalPriority, Project, ProjectType, db


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
    body = resp.get_json()
    assert body["color"] is None
    assert body["target_quarter"] is None


def test_create_project_with_actions_and_notes(authed_client):
    """#65 (2026-04-25): projects can carry actions and notes text fields."""
    resp = authed_client.post(
        "/api/projects",
        json={"name": "AN", "actions": "Step 1\nStep 2", "notes": "context here"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["actions"] == "Step 1\nStep 2"
    assert body["notes"] == "context here"


def test_patch_project_actions_notes_round_trip(authed_client):
    pid = authed_client.post("/api/projects", json={"name": "RT2"}).get_json()["id"]
    resp = authed_client.patch(
        f"/api/projects/{pid}",
        json={"actions": "do this", "notes": "and remember that"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["actions"] == "do this"
    assert resp.get_json()["notes"] == "and remember that"
    # Clear both with empty string
    resp = authed_client.patch(f"/api/projects/{pid}", json={"actions": "", "notes": ""})
    assert resp.get_json()["actions"] is None
    assert resp.get_json()["notes"] is None


def test_create_project_with_target_quarter(authed_client):
    """Bug #61 (2026-04-25): projects can carry a target_quarter for planning."""
    resp = authed_client.post(
        "/api/projects",
        json={"name": "Q4 Push", "target_quarter": "2026-Q4"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["target_quarter"] == "2026-Q4"


def test_patch_project_target_quarter_round_trip(authed_client):
    """Set target_quarter via PATCH, then GET, then clear it."""
    pid = authed_client.post(
        "/api/projects", json={"name": "RT", "type": "personal"}
    ).get_json()["id"]
    # PATCH a value
    resp = authed_client.patch(f"/api/projects/{pid}", json={"target_quarter": "2026-Q3"})
    assert resp.status_code == 200
    assert resp.get_json()["target_quarter"] == "2026-Q3"
    # GET round-trips
    assert authed_client.get(f"/api/projects/{pid}").get_json()["target_quarter"] == "2026-Q3"
    # Clearing with empty string returns null
    resp = authed_client.patch(f"/api/projects/{pid}", json={"target_quarter": ""})
    assert resp.status_code == 200
    assert resp.get_json()["target_quarter"] is None


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


def test_create_project_personal(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "Fitness", "type": "personal"}
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Fitness"
    assert body["type"] == "personal"


def test_create_project_explicit_work(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "Sprint", "type": "work"}
    )
    assert resp.status_code == 201
    assert resp.get_json()["type"] == "work"


def test_create_project_default_type_is_work(authed_client):
    resp = authed_client.post("/api/projects", json={"name": "NoType"})
    assert resp.status_code == 201
    assert resp.get_json()["type"] == "work"


def test_create_project_422_invalid_type(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "Bad", "type": "banana"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "type"


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


def test_list_projects_filter_by_type_personal(authed_client, app):
    with app.app_context():
        _make_project(name="Work Proj", type=ProjectType.WORK)
        _make_project(name="Personal Proj", type=ProjectType.PERSONAL)
    resp = authed_client.get("/api/projects?type=personal")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()]
    assert names == ["Personal Proj"]


def test_list_projects_filter_by_type_work(authed_client, app):
    with app.app_context():
        _make_project(name="Work Proj", type=ProjectType.WORK)
        _make_project(name="Personal Proj", type=ProjectType.PERSONAL)
    resp = authed_client.get("/api/projects?type=work")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()]
    assert names == ["Work Proj"]


def test_list_projects_no_type_filter_returns_all(authed_client, app):
    with app.app_context():
        _make_project(name="Work Proj", type=ProjectType.WORK)
        _make_project(name="Personal Proj", type=ProjectType.PERSONAL)
    resp = authed_client.get("/api/projects")
    assert len(resp.get_json()) == 2


def test_list_projects_422_invalid_type(authed_client):
    resp = authed_client.get("/api/projects?type=banana")
    assert resp.status_code == 422


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


def test_patch_change_type(authed_client, app):
    with app.app_context():
        p = _make_project(name="X", type=ProjectType.WORK)
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"type": "personal"})
    assert resp.status_code == 200
    assert resp.get_json()["type"] == "personal"


def test_patch_422_invalid_type(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"type": "banana"})
    assert resp.status_code == 422


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
