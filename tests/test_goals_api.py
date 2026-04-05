"""Tests for the goals JSON API."""
from __future__ import annotations

import uuid

import auth
from models import Goal, GoalCategory, GoalPriority, GoalStatus, Task, TaskStatus, TaskType, db


def _make_goal(**overrides) -> Goal:
    fields = {
        "title": "Seed Goal",
        "category": GoalCategory.WORK,
        "priority": GoalPriority.SHOULD,
    }
    fields.update(overrides)
    goal = Goal(**fields)
    db.session.add(goal)
    db.session.commit()
    return goal


# --- Auth --------------------------------------------------------------------


def test_goals_api_requires_login(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
    resp = client.get("/api/goals")
    assert resp.status_code == 302


def test_goals_api_rejects_wrong_email(client, monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "intruder@example.com")
    resp = client.get("/api/goals")
    assert resp.status_code == 403


# --- POST --------------------------------------------------------------------


def test_create_goal_201(authed_client):
    resp = authed_client.post(
        "/api/goals",
        json={
            "title": "Reduce Back Pain",
            "category": "health",
            "priority": "must",
            "priority_rank": 1,
            "actions": "Stretch daily",
            "target_quarter": "Q1,Q2",
            "notes": "Track weekly",
        },
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["title"] == "Reduce Back Pain"
    assert body["category"] == "health"
    assert body["priority"] == "must"
    assert body["priority_rank"] == 1
    assert body["status"] == "not_started"
    assert body["is_active"] is True
    assert body["progress"] == {"total": 0, "completed": 0, "percent": None}
    assert uuid.UUID(body["id"])


def test_create_goal_minimal(authed_client):
    resp = authed_client.post(
        "/api/goals",
        json={"title": "Simple", "category": "work", "priority": "could"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["actions"] is None
    assert body["target_quarter"] is None
    assert body["notes"] is None


def test_create_goal_with_explicit_status(authed_client):
    resp = authed_client.post(
        "/api/goals",
        json={
            "title": "Already going",
            "category": "health",
            "priority": "must",
            "status": "in_progress",
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "in_progress"


def test_create_goal_422_missing_title(authed_client):
    resp = authed_client.post(
        "/api/goals", json={"category": "work", "priority": "must"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "title"


def test_create_goal_422_blank_title(authed_client):
    resp = authed_client.post(
        "/api/goals", json={"title": "  ", "category": "work", "priority": "must"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "title"


def test_create_goal_422_missing_category(authed_client):
    resp = authed_client.post("/api/goals", json={"title": "x", "priority": "must"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "category"


def test_create_goal_422_missing_priority(authed_client):
    resp = authed_client.post("/api/goals", json={"title": "x", "category": "work"})
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "priority"


def test_create_goal_422_invalid_category(authed_client):
    resp = authed_client.post(
        "/api/goals", json={"title": "x", "category": "nope", "priority": "must"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "category"


def test_create_goal_422_invalid_priority(authed_client):
    resp = authed_client.post(
        "/api/goals", json={"title": "x", "category": "work", "priority": "nope"}
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "priority"


def test_create_goal_422_invalid_status(authed_client):
    resp = authed_client.post(
        "/api/goals",
        json={"title": "x", "category": "work", "priority": "must", "status": "bad"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "status"


def test_create_goal_422_invalid_priority_rank(authed_client):
    resp = authed_client.post(
        "/api/goals",
        json={
            "title": "x",
            "category": "work",
            "priority": "must",
            "priority_rank": "abc",
        },
    )
    assert resp.status_code == 422
    assert resp.get_json()["field"] == "priority_rank"


def test_create_goal_400_no_json(authed_client):
    resp = authed_client.post("/api/goals", data="bad", content_type="text/plain")
    assert resp.status_code == 400


# --- GET list ----------------------------------------------------------------


def test_list_goals_active_only_by_default(authed_client, app):
    with app.app_context():
        _make_goal(title="Active")
        _make_goal(title="Hidden", is_active=False)
    resp = authed_client.get("/api/goals")
    assert resp.status_code == 200
    titles = [g["title"] for g in resp.get_json()]
    assert titles == ["Active"]


def test_list_goals_is_active_all(authed_client, app):
    with app.app_context():
        _make_goal(title="A")
        _make_goal(title="B", is_active=False)
    resp = authed_client.get("/api/goals?is_active=all")
    assert len(resp.get_json()) == 2


def test_list_goals_filter_by_category(authed_client, app):
    with app.app_context():
        _make_goal(title="W", category=GoalCategory.WORK)
        _make_goal(title="H", category=GoalCategory.HEALTH)
    resp = authed_client.get("/api/goals?category=health")
    assert [g["title"] for g in resp.get_json()] == ["H"]


def test_list_goals_filter_by_priority(authed_client, app):
    with app.app_context():
        _make_goal(title="M", priority=GoalPriority.MUST)
        _make_goal(title="C", priority=GoalPriority.COULD)
    resp = authed_client.get("/api/goals?priority=must")
    assert [g["title"] for g in resp.get_json()] == ["M"]


def test_list_goals_filter_by_status(authed_client, app):
    with app.app_context():
        _make_goal(title="NS", status=GoalStatus.NOT_STARTED)
        _make_goal(title="IP", status=GoalStatus.IN_PROGRESS)
    resp = authed_client.get("/api/goals?status=in_progress")
    assert [g["title"] for g in resp.get_json()] == ["IP"]


def test_list_goals_sorted_by_category_then_rank(authed_client, app):
    with app.app_context():
        _make_goal(title="W2", category=GoalCategory.WORK, priority_rank=2)
        _make_goal(title="W1", category=GoalCategory.WORK, priority_rank=1)
        _make_goal(title="H1", category=GoalCategory.HEALTH, priority_rank=1)
    resp = authed_client.get("/api/goals")
    titles = [g["title"] for g in resp.get_json()]
    assert titles == ["H1", "W1", "W2"]


def test_list_goals_400_invalid_category(authed_client):
    resp = authed_client.get("/api/goals?category=bogus")
    assert resp.status_code == 400


def test_list_goals_400_invalid_priority(authed_client):
    resp = authed_client.get("/api/goals?priority=bogus")
    assert resp.status_code == 400


def test_list_goals_400_invalid_status(authed_client):
    resp = authed_client.get("/api/goals?status=bogus")
    assert resp.status_code == 400


# --- GET one -----------------------------------------------------------------


def test_show_goal_200(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="Showable")
        goal_id = goal.id
    resp = authed_client.get(f"/api/goals/{goal_id}")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Showable"


def test_show_goal_404(authed_client):
    resp = authed_client.get(f"/api/goals/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- PATCH -------------------------------------------------------------------


def test_patch_update_title(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="Old")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"title": "New"})
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "New"


def test_patch_update_status(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "done"


def test_patch_update_all_fields(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(
        f"/api/goals/{goal_id}",
        json={
            "title": "Updated",
            "category": "health",
            "priority": "must",
            "priority_rank": 5,
            "actions": "Do more",
            "target_quarter": "Q3",
            "status": "in_progress",
            "notes": "tracking",
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["category"] == "health"
    assert body["priority_rank"] == 5
    assert body["target_quarter"] == "Q3"
    assert body["actions"] == "Do more"


def test_patch_clear_optional_fields(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x", actions="stuff", notes="n", target_quarter="Q1")
        goal_id = goal.id
    resp = authed_client.patch(
        f"/api/goals/{goal_id}",
        json={"actions": "", "notes": "", "target_quarter": "", "priority_rank": None},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["actions"] is None
    assert body["notes"] is None
    assert body["target_quarter"] is None
    assert body["priority_rank"] is None


def test_patch_soft_hide_via_is_active(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.get_json()["is_active"] is False


def test_patch_422_blank_title(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"title": "  "})
    assert resp.status_code == 422


def test_patch_422_invalid_is_active(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"is_active": "yes"})
    assert resp.status_code == 422


def test_patch_422_unknown_field(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(f"/api/goals/{goal_id}", json={"nope": 1})
    assert resp.status_code == 422


def test_patch_404(authed_client):
    resp = authed_client.patch(f"/api/goals/{uuid.uuid4()}", json={"title": "x"})
    assert resp.status_code == 404


def test_patch_400_no_json(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="x")
        goal_id = goal.id
    resp = authed_client.patch(
        f"/api/goals/{goal_id}", data="bad", content_type="text/plain"
    )
    assert resp.status_code == 400


# --- DELETE ------------------------------------------------------------------


def test_delete_soft_hides(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="bye")
        goal_id = goal.id
    resp = authed_client.delete(f"/api/goals/{goal_id}")
    assert resp.status_code == 204

    with app.app_context():
        fetched = db.session.get(Goal, goal_id)
        assert fetched is not None
        assert fetched.is_active is False


def test_delete_404(authed_client):
    resp = authed_client.delete(f"/api/goals/{uuid.uuid4()}")
    assert resp.status_code == 404


# --- Progress ----------------------------------------------------------------


def test_progress_endpoint(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="Track me")
        goal_id = goal.id
        # 3 tasks linked: 1 archived (completed), 1 active, 1 deleted (excluded)
        db.session.add(
            Task(title="done", type=TaskType.WORK, goal_id=goal_id, status=TaskStatus.ARCHIVED)
        )
        db.session.add(
            Task(title="wip", type=TaskType.WORK, goal_id=goal_id, status=TaskStatus.ACTIVE)
        )
        db.session.add(
            Task(title="gone", type=TaskType.WORK, goal_id=goal_id, status=TaskStatus.DELETED)
        )
        db.session.commit()

    resp = authed_client.get(f"/api/goals/{goal_id}/progress")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 2  # active + archived (not deleted)
    assert body["completed"] == 1
    assert body["percent"] == 50


def test_progress_no_tasks(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="Empty")
        goal_id = goal.id
    resp = authed_client.get(f"/api/goals/{goal_id}/progress")
    assert resp.status_code == 200
    assert resp.get_json() == {"total": 0, "completed": 0, "percent": None}


def test_progress_404(authed_client):
    resp = authed_client.get(f"/api/goals/{uuid.uuid4()}/progress")
    assert resp.status_code == 404


def test_progress_included_in_serialized_goal(authed_client, app):
    with app.app_context():
        goal = _make_goal(title="With tasks")
        goal_id = goal.id
        db.session.add(
            Task(title="t", type=TaskType.PERSONAL, goal_id=goal_id, status=TaskStatus.ARCHIVED)
        )
        db.session.commit()
    resp = authed_client.get(f"/api/goals/{goal_id}")
    assert resp.status_code == 200
    assert resp.get_json()["progress"]["completed"] == 1
