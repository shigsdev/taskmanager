"""Integration tests for image scan to tasks (Step 16).

The scan feature converts photos/screenshots into inbox tasks via:
1. Google Vision API (OCR — extracting text from images)
2. Claude API (AI parsing — turning raw text into task candidates)
3. Review screen (user edits/confirms candidates)
4. Task creation (confirmed items land in Inbox)

These tests mock both external APIs so we never make real HTTP calls.
The image is processed in memory only — never written to disk or DB.

Key testing concepts:
- **Mocking external APIs** — replacing Google Vision and Claude API
  calls with fake responses so tests run without API keys or network
- **File upload testing** — simulating multipart form uploads in Flask
- **In-memory processing** — verifying images never touch disk
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest

import auth
from models import GoalCategory, GoalPriority, ImportLog, TaskType, Tier

# --- JSON array extraction (internal helper) ----------------------------------


class TestExtractJsonArray:
    """Verify _extract_json_array handles various Claude response formats.

    Claude might return JSON directly, wrap it in markdown code blocks,
    or include extra commentary. This parser must handle all cases.
    """

    def test_direct_json_array(self):
        from scan_service import _extract_json_array

        result = _extract_json_array('["Buy milk", "Call dentist"]')
        assert result == ["Buy milk", "Call dentist"]

    def test_json_in_markdown_block(self):
        from scan_service import _extract_json_array

        text = '```json\n["Task one", "Task two"]\n```'
        result = _extract_json_array(text)
        assert result == ["Task one", "Task two"]

    def test_json_with_surrounding_text(self):
        from scan_service import _extract_json_array

        text = 'Here are the tasks:\n["Do this", "Do that"]\nHope that helps!'
        result = _extract_json_array(text)
        assert result == ["Do this", "Do that"]

    def test_empty_array(self):
        from scan_service import _extract_json_array

        result = _extract_json_array("[]")
        assert result == []

    def test_no_json_returns_empty(self):
        from scan_service import _extract_json_array

        result = _extract_json_array("No tasks found in this text.")
        assert result == []

    def test_filters_empty_strings(self):
        from scan_service import _extract_json_array

        result = _extract_json_array('["Good task", "", "Another"]')
        assert result == ["Good task", "Another"]


# --- OCR (Google Vision) — mocked ---------------------------------------------


class TestExtractText:
    """Verify extract_text_from_image calls Google Vision correctly."""

    def test_raises_without_api_key(self, app, monkeypatch):
        from scan_service import extract_text_from_image

        monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)

        with app.app_context(), pytest.raises(RuntimeError, match="GOOGLE_VISION_API_KEY"):
            extract_text_from_image(b"fake image data")

    def test_returns_text_on_success(self, app, monkeypatch):
        from scan_service import extract_text_from_image

        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")

        with (
            app.app_context(),
            patch(
                "scan_service._call_vision_api",
                return_value="Buy groceries\nCall dentist",
            ),
        ):
            result = extract_text_from_image(b"fake image")
        assert "Buy groceries" in result

    def test_returns_empty_on_no_text(self, app, monkeypatch):
        from scan_service import extract_text_from_image

        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")

        with (
            app.app_context(),
            patch("scan_service._call_vision_api", return_value=""),
        ):
            result = extract_text_from_image(b"blank image")
        assert result == ""


# --- Task parsing (Claude API) — mocked --------------------------------------


class TestParseTasksFromText:
    """Verify parse_tasks_from_text calls Claude and parses the response."""

    def test_raises_without_api_key(self, app, monkeypatch):
        from scan_service import parse_tasks_from_text

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with app.app_context(), pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            parse_tasks_from_text("Some OCR text")

    def test_returns_tasks_on_success(self, app, monkeypatch):
        from scan_service import parse_tasks_from_text

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with (
            app.app_context(),
            patch(
                "scan_service._call_claude_api",
                return_value=["Buy groceries", "Call dentist"],
            ),
        ):
            result = parse_tasks_from_text("- Buy groceries\n- Call dentist")
        assert result == ["Buy groceries", "Call dentist"]

    def test_empty_text_returns_empty(self, app):
        from scan_service import parse_tasks_from_text

        with app.app_context():
            result = parse_tasks_from_text("")
        assert result == []

    def test_whitespace_only_returns_empty(self, app):
        from scan_service import parse_tasks_from_text

        with app.app_context():
            result = parse_tasks_from_text("   \n  \n  ")
        assert result == []


# --- Task creation from candidates -------------------------------------------


class TestCreateTasksFromCandidates:
    """Verify create_tasks_from_candidates creates correct Task records."""

    def test_creates_included_candidates(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            candidates = [
                {"title": "Task A", "type": "work", "included": True},
                {"title": "Task B", "type": "personal", "included": True},
            ]
            tasks = create_tasks_from_candidates(candidates)
            assert len(tasks) == 2
            assert tasks[0].title == "Task A"
            assert tasks[1].type == TaskType.PERSONAL

    def test_skips_excluded_candidates(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            candidates = [
                {"title": "Include me", "included": True},
                {"title": "Skip me", "included": False},
            ]
            tasks = create_tasks_from_candidates(candidates)
            assert len(tasks) == 1
            assert tasks[0].title == "Include me"

    def test_all_tasks_land_in_inbox(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "Inbox item", "included": True}]
            )
            assert tasks[0].tier == Tier.INBOX

    def test_skips_empty_titles(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "", "included": True}, {"title": "  ", "included": True}]
            )
            assert len(tasks) == 0

    def test_defaults_to_work_type(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "No type", "included": True}]
            )
            assert tasks[0].type == TaskType.WORK

    def test_invalid_type_defaults_to_work(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "Bad type", "type": "invalid", "included": True}]
            )
            assert tasks[0].type == TaskType.WORK


# --- Upload API endpoint (mocked pipeline) ------------------------------------


class TestUploadAPI:
    """Verify POST /api/scan/upload processes images correctly."""

    def test_no_file_returns_400(self, authed_client):
        resp = authed_client.post("/api/scan/upload")
        assert resp.status_code == 400
        assert "No image" in resp.get_json()["error"]

    def test_unsupported_type_returns_422(self, authed_client):
        data = {"image": (io.BytesIO(b"not an image"), "test.txt", "text/plain")}
        resp = authed_client.post(
            "/api/scan/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_empty_file_returns_400(self, authed_client):
        data = {"image": (io.BytesIO(b""), "empty.jpg", "image/jpeg")}
        resp = authed_client.post(
            "/api/scan/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_successful_upload_returns_candidates(self, authed_client, monkeypatch):
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with (
            patch(
                "scan_service._call_vision_api",
                return_value="Buy milk\nWalk dog",
            ),
            patch(
                "scan_service._call_claude_api",
                return_value=["Buy milk", "Walk dog"],
            ),
        ):
            data = {
                "image": (io.BytesIO(b"fake jpeg data"), "photo.jpg", "image/jpeg")
            }
            resp = authed_client.post(
                "/api/scan/upload",
                data=data,
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ocr_text"] == "Buy milk\nWalk dog"
        assert len(body["candidates"]) == 2
        assert body["candidates"][0]["title"] == "Buy milk"

    def test_no_text_detected(self, authed_client, monkeypatch):
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")
        with patch("scan_service._call_vision_api", return_value=""):
            data = {
                "image": (io.BytesIO(b"blank image"), "blank.png", "image/png")
            }
            resp = authed_client.post(
                "/api/scan/upload",
                data=data,
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        assert resp.get_json()["candidates"] == []

    def test_vision_api_not_configured(self, authed_client, monkeypatch):
        monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
        data = {
            "image": (io.BytesIO(b"image data"), "test.jpg", "image/jpeg")
        }
        resp = authed_client.post(
            "/api/scan/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422
        assert "GOOGLE_VISION_API_KEY" in resp.get_json()["error"]


# --- Confirm API endpoint -----------------------------------------------------


class TestConfirmAPI:
    """Verify POST /api/scan/confirm creates tasks in inbox."""

    def test_confirm_creates_tasks(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            json={
                "candidates": [
                    {"title": "New task A", "type": "work", "included": True},
                    {"title": "New task B", "type": "personal", "included": True},
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["created"] == 2

    def test_confirm_skips_excluded(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            json={
                "candidates": [
                    {"title": "Include", "included": True},
                    {"title": "Exclude", "included": False},
                ]
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 1

    def test_confirmed_tasks_in_inbox(self, authed_client):
        authed_client.post(
            "/api/scan/confirm",
            json={"candidates": [{"title": "Scanned task", "included": True}]},
        )
        resp = authed_client.get("/api/tasks?tier=inbox")
        titles = [t["title"] for t in resp.get_json()]
        assert "Scanned task" in titles

    def test_no_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_invalid_candidates_returns_422(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            json={"candidates": "not a list"},
        )
        assert resp.status_code == 422

    def test_empty_candidates_returns_zero(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            json={"candidates": []},
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 0


# --- Goal JSON extraction -----------------------------------------------------


class TestExtractJsonObjectList:
    """Verify _extract_json_object_list parses goal arrays from Claude output."""

    def test_direct_array_of_objects(self):
        from scan_service import _extract_json_object_list

        text = (
            '[{"title": "Lose weight", "category": "health", '
            '"priority": "should"}]'
        )
        result = _extract_json_object_list(text)
        assert len(result) == 1
        assert result[0]["title"] == "Lose weight"
        assert result[0]["category"] == "health"

    def test_markdown_fenced_array(self):
        from scan_service import _extract_json_object_list

        text = (
            '```json\n[{"title": "Ship v2", "category": "work", '
            '"priority": "must"}]\n```'
        )
        result = _extract_json_object_list(text)
        assert result[0]["title"] == "Ship v2"

    def test_surrounding_text(self):
        from scan_service import _extract_json_object_list

        text = (
            'Here you go:\n[{"title": "Read more", "category": '
            '"personal_growth", "priority": "could"}]\nEnjoy!'
        )
        result = _extract_json_object_list(text)
        assert result[0]["category"] == "personal_growth"

    def test_no_array_returns_empty(self):
        from scan_service import _extract_json_object_list

        assert _extract_json_object_list("no goals here") == []

    def test_filters_non_dict_items(self):
        from scan_service import _extract_json_object_list

        text = '[{"title": "Real goal"}, "stray string", 42]'
        result = _extract_json_object_list(text)
        assert len(result) == 1
        assert result[0]["title"] == "Real goal"


# --- Goal parsing (Claude API) — mocked --------------------------------------


class TestParseGoalsFromText:
    """Verify parse_goals_from_text requires the key and forwards results."""

    def test_raises_without_api_key(self, app, monkeypatch):
        from scan_service import parse_goals_from_text

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with app.app_context(), pytest.raises(
            RuntimeError, match="ANTHROPIC_API_KEY"
        ):
            parse_goals_from_text("some notes")

    def test_returns_goal_dicts(self, app, monkeypatch):
        from scan_service import parse_goals_from_text

        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        goal = {
            "title": "Run a marathon",
            "category": "health",
            "priority": "should",
            "target_quarter": "Q4 2026",
            "actions": "Train weekly",
        }
        with (
            app.app_context(),
            patch(
                "scan_service._call_claude_api_goals",
                return_value=[goal],
            ),
        ):
            result = parse_goals_from_text("goal notes")
        assert result == [goal]

    def test_empty_text_returns_empty(self, app):
        from scan_service import parse_goals_from_text

        with app.app_context():
            assert parse_goals_from_text("") == []
            assert parse_goals_from_text("   \n  ") == []


# --- Goal creation from candidates -------------------------------------------


class TestCreateGoalsFromCandidates:
    """Verify create_goals_from_candidates creates Goal records with batch_id."""

    def test_creates_included_goals(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {
                    "title": "Goal A",
                    "category": "health",
                    "priority": "must",
                    "included": True,
                },
                {
                    "title": "Goal B",
                    "category": "work",
                    "priority": "should",
                    "included": True,
                },
            ])
            assert len(goals) == 2
            assert goals[0].category == GoalCategory.HEALTH
            assert goals[1].priority == GoalPriority.SHOULD

    def test_skips_excluded(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {"title": "In", "included": True},
                {"title": "Out", "included": False},
            ])
            assert len(goals) == 1
            assert goals[0].title == "In"

    def test_skips_empty_titles(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {"title": "", "included": True},
                {"title": "  ", "included": True},
            ])
            assert goals == []

    def test_invalid_category_falls_back(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {"title": "Bad cat", "category": "nonsense", "included": True},
            ])
            assert goals[0].category == GoalCategory.PERSONAL_GROWTH

    def test_invalid_priority_falls_back(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {"title": "Bad pri", "priority": "garbage", "included": True},
            ])
            assert goals[0].priority == GoalPriority.NEED_MORE_INFO

    def test_missing_category_defaults(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {"title": "No category", "included": True},
            ])
            assert goals[0].category == GoalCategory.PERSONAL_GROWTH
            assert goals[0].priority == GoalPriority.NEED_MORE_INFO

    def test_shared_batch_id_and_import_log(self, app):
        """All goals created in one call share a batch_id; ImportLog has
        the matching batch_id and source starting with 'scan_'."""
        from sqlalchemy import select

        from scan_service import create_goals_from_candidates

        with app.app_context():
            from models import db

            goals = create_goals_from_candidates([
                {"title": "G1", "included": True},
                {"title": "G2", "included": True},
            ])
            assert goals[0].batch_id is not None
            assert goals[0].batch_id == goals[1].batch_id

            log = db.session.scalar(
                select(ImportLog).where(
                    ImportLog.batch_id == goals[0].batch_id
                )
            )
            assert log is not None
            assert log.source.startswith("scan_")
            assert log.task_count == 2

    def test_truncates_long_fields(self, app):
        from scan_service import create_goals_from_candidates

        with app.app_context():
            goals = create_goals_from_candidates([
                {
                    "title": "x" * 600,
                    "target_quarter": "q" * 50,
                    "included": True,
                },
            ])
            assert len(goals[0].title) == 500
            assert len(goals[0].target_quarter) == 20


# --- Upload API: goal mode ----------------------------------------------------


class TestUploadAPIGoals:
    """Verify POST /api/scan/upload with parse_as=goals routes to goal parser."""

    def test_upload_parses_goals(self, authed_client, monkeypatch):
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with (
            patch(
                "scan_service._call_vision_api",
                return_value="Run marathon\nLearn spanish",
            ),
            patch(
                "scan_service._call_claude_api_goals",
                return_value=[
                    {
                        "title": "Run marathon",
                        "category": "health",
                        "priority": "should",
                        "target_quarter": "Q4 2026",
                        "actions": "Train weekly",
                    },
                    {
                        "title": "Learn Spanish",
                        "category": "personal_growth",
                        "priority": "could",
                    },
                ],
            ),
        ):
            data = {
                "image": (io.BytesIO(b"fake jpeg"), "goals.jpg", "image/jpeg"),
                "parse_as": "goals",
            }
            resp = authed_client.post(
                "/api/scan/upload",
                data=data,
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["kind"] == "goals"
        assert len(body["candidates"]) == 2
        first = body["candidates"][0]
        assert first["title"] == "Run marathon"
        assert first["category"] == "health"
        assert first["priority"] == "should"
        assert first["target_quarter"] == "Q4 2026"

    def test_upload_defaults_to_tasks(self, authed_client, monkeypatch):
        """Omitting parse_as should keep the existing task-parsing behavior."""
        monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        with (
            patch("scan_service._call_vision_api", return_value="Buy milk"),
            patch(
                "scan_service._call_claude_api",
                return_value=["Buy milk"],
            ),
        ):
            data = {
                "image": (io.BytesIO(b"fake"), "a.jpg", "image/jpeg"),
            }
            resp = authed_client.post(
                "/api/scan/upload",
                data=data,
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["kind"] == "tasks"
        assert body["candidates"][0]["type"] == "work"


# --- Confirm API: goal mode ---------------------------------------------------


class TestConfirmAPIGoals:
    """Verify POST /api/scan/confirm with kind=goals creates Goal records."""

    def test_confirm_creates_goals(self, authed_client):
        resp = authed_client.post(
            "/api/scan/confirm",
            json={
                "kind": "goals",
                "candidates": [
                    {
                        "title": "Ship v2",
                        "category": "work",
                        "priority": "must",
                        "included": True,
                    },
                    {
                        "title": "Run 5k",
                        "category": "health",
                        "priority": "should",
                        "included": True,
                    },
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["kind"] == "goals"
        assert body["created"] == 2
        assert body["goals"][0]["category"] == "work"
        assert body["goals"][1]["priority"] == "should"

    def test_confirm_goals_land_in_goals_list(self, authed_client):
        authed_client.post(
            "/api/scan/confirm",
            json={
                "kind": "goals",
                "candidates": [
                    {
                        "title": "Scanned goal",
                        "category": "personal_growth",
                        "priority": "could",
                        "included": True,
                    }
                ],
            },
        )
        # Goals API returns all active goals
        resp = authed_client.get("/api/goals")
        assert resp.status_code == 200
        titles = [g["title"] for g in resp.get_json()]
        assert "Scanned goal" in titles

    def test_confirm_goals_share_batch_id_with_import_log(self, app, authed_client):
        """Goals created via the scan confirm path must be stamped with a
        batch_id that matches an ImportLog row — so the recycle bin undo
        flow can treat the whole scan as one group."""
        from sqlalchemy import select

        authed_client.post(
            "/api/scan/confirm",
            json={
                "kind": "goals",
                "candidates": [
                    {"title": "Batch goal A", "included": True},
                    {"title": "Batch goal B", "included": True},
                ],
            },
        )
        with app.app_context():
            from models import Goal, db

            goals = list(
                db.session.scalars(
                    select(Goal).where(Goal.title.like("Batch goal%"))
                )
            )
            assert len(goals) == 2
            assert goals[0].batch_id is not None
            assert goals[0].batch_id == goals[1].batch_id
            log = db.session.scalar(
                select(ImportLog).where(
                    ImportLog.batch_id == goals[0].batch_id
                )
            )
            assert log is not None
            assert log.source.startswith("scan_")


# --- Scan page HTML -----------------------------------------------------------


class TestScanPageView:
    """Verify the /scan page renders with the expected structure."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/scan")
        assert resp.status_code == 200

    def test_has_upload_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert 'id="scanUpload"' in html
        assert 'id="scanFile"' in html

    def test_has_review_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert 'id="scanReview"' in html
        assert 'id="scanCandidates"' in html

    def test_has_confirm_buttons(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert 'id="scanConfirmAll"' in html
        assert 'id="scanConfirmSelected"' in html

    def test_has_ocr_text_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert 'id="scanOcrText"' in html

    def test_loads_scan_js(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert "scan.js" in html

    def test_omits_capture_attribute(self, client, monkeypatch):
        """iOS Safari forces camera-only when capture='environment' is set,
        blocking Photo Library access. The attribute must be absent from the
        file input tag so the native Take Photo / Photo Library sheet
        appears on tap. (A comment in the template explaining the omission
        is allowed — we only care about the <input> itself.)"""
        import re

        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        # Find the scanFile input tag and confirm it has no capture attr.
        match = re.search(r'<input[^>]*id="scanFile"[^>]*>', html)
        assert match is not None, "scanFile input not found"
        assert "capture=" not in match.group(0)

    def test_has_parse_as_toggle(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/scan").data.decode()
        assert 'name="parseAs"' in html
        assert 'value="tasks"' in html
        assert 'value="goals"' in html

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/scan")
        assert resp.status_code == 302


# --- Blueprint registration --------------------------------------------------


class TestScanBlueprint:
    """Verify the scan_api blueprint is registered."""

    def test_blueprint_registered(self, app):
        assert "scan_api" in app.blueprints

    def test_routes_exist(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/scan/upload" in rules
        assert "/api/scan/confirm" in rules
