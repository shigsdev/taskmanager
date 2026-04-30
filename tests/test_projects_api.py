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
    # #66 (2026-04-25): no color now defaults to per-type (work=blue).
    # Was previously None — semantics changed when auto-color shipped.
    assert body["color"] == "#2563eb"
    assert body["target_quarter"] is None


def test_create_project_no_color_defaults_to_blue_for_work(authed_client):
    """#66 (2026-04-25): work projects without explicit color get the per-type default."""
    resp = authed_client.post("/api/projects", json={"name": "AutoColor W", "type": "work"})
    assert resp.status_code == 201
    assert resp.get_json()["color"] == "#2563eb"


def test_create_project_no_color_defaults_to_green_for_personal(authed_client):
    """#66: personal projects default to green."""
    resp = authed_client.post("/api/projects", json={"name": "AutoColor P", "type": "personal"})
    assert resp.status_code == 201
    assert resp.get_json()["color"] == "#16a34a"


def test_create_project_explicit_color_wins_over_type_default(authed_client):
    """#66: manual color override is preserved."""
    resp = authed_client.post(
        "/api/projects",
        json={"name": "AutoColor M", "type": "personal", "color": "#ff8800"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["color"] == "#ff8800"


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


def test_create_project_default_status_is_not_started(authed_client):
    """#69 (2026-04-25): new projects start at not_started."""
    resp = authed_client.post("/api/projects", json={"name": "S1"})
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "not_started"


def test_create_project_with_explicit_status(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "S2", "status": "in_progress"}
    )
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "in_progress"


def test_create_project_invalid_status_422(authed_client):
    resp = authed_client.post(
        "/api/projects", json={"name": "S3", "status": "bogus"}
    )
    assert resp.status_code == 422


def test_patch_project_status_round_trip(authed_client):
    pid = authed_client.post("/api/projects", json={"name": "S4"}).get_json()["id"]
    for s in ("in_progress", "on_hold", "done", "not_started"):
        resp = authed_client.patch(f"/api/projects/{pid}", json={"status": s})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == s


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
        _make_project(name="B", priority_order=2)
        _make_project(name="A", priority_order=1)
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
            "priority_order": 9,
            "goal_id": None,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["color"] == "#123456"
    assert body["is_active"] is False
    assert body["priority_order"] == 9


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


def test_patch_422_bad_priority_order(authed_client, app):
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"priority_order": "abc"})
    assert resp.status_code == 422


def test_patch_legacy_sort_order_alias_still_works(authed_client, app):
    """#62 backwards-compat: PATCH with old sort_order key still updates priority_order."""
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    resp = authed_client.patch(f"/api/projects/{pid}", json={"sort_order": 7})
    assert resp.status_code == 200
    assert resp.get_json()["priority_order"] == 7


def test_patch_priority_round_trip(authed_client, app):
    """#62: ProjectPriority enum round-trips through PATCH."""
    with app.app_context():
        p = _make_project(name="X")
        pid = p.id
    for v in ("must", "should", "could", "need_more_info"):
        resp = authed_client.patch(f"/api/projects/{pid}", json={"priority": v})
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["priority"] == v
    # Clear back to null
    resp = authed_client.patch(f"/api/projects/{pid}", json={"priority": None})
    assert resp.get_json()["priority"] is None


def test_reorder_endpoint(authed_client, app):
    """#62: POST /api/projects/reorder bulk-sets priority_order from a list."""
    with app.app_context():
        a = _make_project(name="A", priority_order=10)
        b = _make_project(name="B", priority_order=20)
        c = _make_project(name="C", priority_order=30)
        ids = [str(c.id), str(a.id), str(b.id)]
    resp = authed_client.post("/api/projects/reorder", json={"ordered_ids": ids})
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == 3
    listed = authed_client.get("/api/projects").get_json()
    by_name = {p["name"]: p["priority_order"] for p in listed}
    assert by_name == {"C": 0, "A": 1, "B": 2}


def test_reorder_endpoint_422_on_bad_input(authed_client):
    resp = authed_client.post("/api/projects/reorder", json={"ordered_ids": "nope"})
    assert resp.status_code == 422
    resp = authed_client.post("/api/projects/reorder", json={"ordered_ids": ["not-a-uuid"]})
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


def test_delete_nulls_task_project_fk(authed_client, app):
    """PR63 audit fix #129: soft-deleting a project must null
    Task.project_id on every linked task. Previously the project flipped
    is_active=False but linked tasks still pointed at the dead project,
    leaving phantom labels and ghost filter dropdown entries."""
    from models import Task, TaskType

    with app.app_context():
        p = _make_project(name="Cascade test")
        pid = p.id
        t1 = Task(title="Task A", type=TaskType.WORK, project_id=pid)
        t2 = Task(title="Task B", type=TaskType.WORK, project_id=pid)
        db.session.add_all([t1, t2])
        db.session.commit()
        t1_id, t2_id = t1.id, t2.id

    resp = authed_client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    with app.app_context():
        # Project soft-deleted
        fetched = db.session.get(Project, pid)
        assert fetched.is_active is False
        # Both tasks now have project_id = None
        assert db.session.get(Task, t1_id).project_id is None
        assert db.session.get(Task, t2_id).project_id is None


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


# --- PR28 audit fix #3: color hex validation ---------------------------------


class TestProjectColorValidation:
    """PR28: project.color is rendered into an inline style= attribute on
    the client. Server must reject non-hex strings to close the CSS-injection
    surface that CLAUDE.md's 'sanitize all user input' rule was missing."""

    def test_create_accepts_valid_hex(self, authed_client):
        resp = authed_client.post(
            "/api/projects",
            json={"name": "Valid Color", "type": "work", "color": "#abc123"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["color"] == "#abc123"

    def test_create_normalises_no_hash_to_hash_lowercase(self, authed_client):
        resp = authed_client.post(
            "/api/projects",
            json={"name": "No Hash", "type": "work", "color": "ABC123"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["color"] == "#abc123"

    def test_create_rejects_css_injection_attempt(self, authed_client):
        resp = authed_client.post(
            "/api/projects",
            json={
                "name": "Sneaky",
                "type": "work",
                "color": "red; } body { display:none } .x {",
            },
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert "color" in str(body).lower()

    def test_create_rejects_named_color(self, authed_client):
        # Named colors like "red" are not hex — caller should send #ff0000.
        resp = authed_client.post(
            "/api/projects",
            json={"name": "Named", "type": "work", "color": "red"},
        )
        assert resp.status_code == 422

    def test_patch_rejects_invalid_hex(self, authed_client):
        p = authed_client.post(
            "/api/projects",
            json={"name": "Patch Me", "type": "work"},
        ).get_json()
        resp = authed_client.patch(
            f"/api/projects/{p['id']}",
            json={"color": "javascript:alert(1)"},
        )
        assert resp.status_code == 422

    def test_create_empty_color_falls_back_to_per_type_default(self, authed_client):
        """Empty / missing color → per-type default (#66 unchanged)."""
        resp = authed_client.post(
            "/api/projects",
            json={"name": "Default", "type": "personal", "color": ""},
        )
        assert resp.status_code == 201
        assert resp.get_json()["color"] == "#16a34a"  # personal default


# --- #90 (PR35): bulk PATCH/DELETE -------------------------------------------


class TestProjectsBulk:
    """Bulk endpoints mirror /api/tasks/bulk semantics."""

    def test_bulk_patch_changes_status(self, authed_client):
        a = authed_client.post("/api/projects", json={"name": "A", "type": "work"}).get_json()
        b = authed_client.post("/api/projects", json={"name": "B", "type": "work"}).get_json()
        resp = authed_client.patch("/api/projects/bulk", json={
            "project_ids": [a["id"], b["id"]],
            "updates": {"status": "in_progress"},
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["updated"] == 2
        # Confirm
        a2 = authed_client.get(f"/api/projects/{a['id']}").get_json()
        assert a2["status"] == "in_progress"

    def test_bulk_patch_rejects_empty_list(self, authed_client):
        resp = authed_client.patch("/api/projects/bulk", json={
            "project_ids": [], "updates": {"status": "done"},
        })
        assert resp.status_code == 422

    def test_bulk_patch_rejects_too_many(self, authed_client):
        resp = authed_client.patch("/api/projects/bulk", json={
            "project_ids": [str(uuid.uuid4()) for _ in range(201)],
            "updates": {"status": "done"},
        })
        assert resp.status_code == 422
        assert "max 200" in resp.get_json()["error"]

    def test_bulk_patch_invalid_uuid(self, authed_client):
        resp = authed_client.patch("/api/projects/bulk", json={
            "project_ids": ["not-a-uuid"], "updates": {"status": "done"},
        })
        assert resp.status_code == 422

    def test_bulk_delete_archives(self, authed_client):
        a = authed_client.post(
            "/api/projects",
            json={"name": "ToArchive", "type": "personal"},
        ).get_json()
        resp = authed_client.delete(
            "/api/projects/bulk",
            json={"project_ids": [a["id"]]},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["archived"] == 1
        # Verify is_active=false
        a2 = authed_client.get(f"/api/projects/{a['id']}").get_json()
        assert a2["is_active"] is False


# --- PR38 audit C5: linked-tasks count + content per project ---------------


class TestProjectLinkedTasksData:
    """The /projects page shows linked tasks under each project (#95).
    The render path is JS, but the underlying fact — `task.project_id ==
    project.id` returned by the API — must be guaranteed. This is the
    same pattern as the goals task-count test."""

    def test_active_tasks_linked_to_project_appear_in_api(self, app, authed_client):
        """A task with project_id set must come back via /api/tasks
        and be findable by the project's id."""
        from models import Task, TaskStatus, TaskType, Tier, db
        # Create the project
        proj = authed_client.post(
            "/api/projects",
            json={"name": "DataTest", "type": "work"},
        ).get_json()
        # Three tasks: 2 active linked, 1 active unlinked, 1 archived linked.
        with app.app_context():
            from uuid import UUID
            pid = UUID(proj["id"])
            db.session.add_all([
                Task(title="L1", type=TaskType.WORK, tier=Tier.INBOX,
                     status=TaskStatus.ACTIVE, project_id=pid),
                Task(title="L2", type=TaskType.WORK, tier=Tier.TODAY,
                     status=TaskStatus.ACTIVE, project_id=pid),
                Task(title="UnlinkedX", type=TaskType.WORK, tier=Tier.INBOX,
                     status=TaskStatus.ACTIVE),
                Task(title="ArchivedL", type=TaskType.WORK, tier=Tier.INBOX,
                     status=TaskStatus.ARCHIVED, project_id=pid),
            ])
            db.session.commit()

        # The frontend computes per-project counts client-side from
        # /api/tasks. Mirror that contract and assert correctness.
        all_tasks = authed_client.get("/api/tasks").get_json()
        linked_active = [
            t for t in all_tasks
            if t.get("project_id") == proj["id"] and t.get("status") == "active"
        ]
        assert len(linked_active) == 2
        titles = {t["title"] for t in linked_active}
        assert titles == {"L1", "L2"}, (
            "Active linked tasks must be exactly the 2 we created — "
            "ArchivedL must NOT appear in active filter, UnlinkedX must "
            "NOT appear when filtered by project_id."
        )

    def test_unlinked_tasks_have_null_project_id_in_api(self, app, authed_client):
        """Defensive: a task created without project_id must return
        project_id=None. A regression that auto-fills project_id on
        create would silently link tasks to the wrong project on
        the /projects page. The /projects page filter logic relies
        on null != any-real-uuid, so this test guards that assumption."""
        from models import Task, TaskStatus, TaskType, Tier, db
        with app.app_context():
            db.session.add(Task(
                title="NoProj", type=TaskType.WORK, tier=Tier.INBOX,
                status=TaskStatus.ACTIVE,
            ))
            db.session.commit()
        all_tasks = authed_client.get("/api/tasks").get_json()
        no_proj = [t for t in all_tasks if t["title"] == "NoProj"]
        assert len(no_proj) == 1
        assert no_proj[0]["project_id"] is None
