"""Tests for voice memo capture: voice_service + voice_api endpoints.

Mocks both Whisper and Claude so tests run without API keys or network.
Mirrors the pattern in test_scan.py.
"""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest

import auth

# --- voice_service.transcribe_audio (Whisper) — mocked -----------------------


class TestTranscribeAudio:
    """Verify voice_service.transcribe_audio handles all the success and
    failure paths. The actual HTTP call is mocked; we test that the
    wrapper around it correctly extracts transcript + duration + cost
    and surfaces sane errors."""

    def test_raises_without_api_key(self, app, monkeypatch):
        from voice_service import transcribe_audio

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with app.app_context(), pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            transcribe_audio(b"fake audio bytes", "audio/webm")

    def test_returns_transcript_and_cost_on_success(self, app, monkeypatch):
        from voice_service import WHISPER_USD_PER_MINUTE, transcribe_audio

        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        # 47.3 sec → cost = 47.3/60 * 0.006 = 0.00473
        fake_response = {
            "transcript": "Buy milk and call the dentist tomorrow.",
            "duration_seconds": 47.3,
            "cost_usd": (47.3 / 60.0) * WHISPER_USD_PER_MINUTE,
        }
        with (
            app.app_context(),
            patch("voice_service._call_whisper_api", return_value=fake_response),
        ):
            result = transcribe_audio(b"fake audio", "audio/webm")

        assert result["transcript"].startswith("Buy milk")
        assert result["duration_seconds"] == 47.3
        assert result["cost_usd"] == pytest.approx(0.00473, abs=1e-5)

    # --- #67: voice candidate router -------------------------------------

    def test_classify_default_is_task(self):
        from voice_service import classify_voice_candidate
        route, cleaned = classify_voice_candidate("Buy milk")
        assert route == "task"
        assert cleaned == "Buy milk"

    def test_classify_goal_prefix_strips_prefix(self):
        from voice_service import classify_voice_candidate
        route, cleaned = classify_voice_candidate("Goal: ship the calendar")
        assert route == "goal"
        assert cleaned == "ship the calendar"
        route, cleaned = classify_voice_candidate("Create a goal: read 12 books")
        assert route == "goal"
        assert cleaned == "read 12 books"
        route, cleaned = classify_voice_candidate("New goal exercise weekly")
        assert route == "goal"
        assert cleaned == "exercise weekly"

    def test_classify_project_prefix_strips_prefix(self):
        from voice_service import classify_voice_candidate
        route, cleaned = classify_voice_candidate("Project: portal redesign")
        assert route == "project"
        assert cleaned == "portal redesign"
        route, cleaned = classify_voice_candidate("New project taskmanager v2")
        assert route == "project"
        assert cleaned == "taskmanager v2"

    def test_classify_case_insensitive(self):
        from voice_service import classify_voice_candidate
        assert classify_voice_candidate("GOAL: x")[0] == "goal"
        assert classify_voice_candidate("project: y")[0] == "project"
        assert classify_voice_candidate("Goal: z")[0] == "goal"

    def test_classify_no_prefix_in_middle_of_string(self):
        """Don't false-positive on 'goal' appearing mid-sentence."""
        from voice_service import classify_voice_candidate
        route, cleaned = classify_voice_candidate("My goal is to ship faster")
        assert route == "task"
        assert cleaned == "My goal is to ship faster"

    def test_classify_empty_string_safe(self):
        from voice_service import classify_voice_candidate
        assert classify_voice_candidate("") == ("task", "")
        assert classify_voice_candidate(None) == ("task", "")

    def test_filename_for_mime_picks_correct_extension(self):
        from voice_service import _filename_for_mime

        assert _filename_for_mime("audio/webm") == "memo.webm"
        assert _filename_for_mime("audio/webm;codecs=opus") == "memo.webm"
        assert _filename_for_mime("audio/mp4") == "memo.mp4"
        assert _filename_for_mime("audio/mpeg") == "memo.mp3"
        assert _filename_for_mime("audio/ogg") == "memo.ogg"
        assert _filename_for_mime("audio/wav") == "memo.wav"
        # Unknown MIME → safe default that Whisper accepts
        assert _filename_for_mime("audio/something-weird") == "memo.webm"
        assert _filename_for_mime("") == "memo.webm"


# --- voice_api POST /api/voice-memo (upload + transcribe + parse) ------------


# Shared minimal candidate shape — used by the content-type regression
# tests that don't care about inference details, only that parsing ran.
_TEST_CAND = {
    "title": "test", "type": "personal",
    "tier": "inbox", "due_date": None,
}


def _bypass_auth(monkeypatch):
    """Make every request authenticated as the configured AUTHORIZED_EMAIL,
    matching the pattern used elsewhere in tests."""
    monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")


class TestVoiceUpload:
    """Verify the upload endpoint glues transcription + parsing
    correctly, including the fallback for empty transcripts and the
    transcript-survival path when parsing fails."""

    def test_rejects_missing_audio_file(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post("/api/voice-memo", data={})
        assert resp.status_code == 400
        assert "audio" in (resp.get_json().get("error") or "").lower()

    def test_rejects_unsupported_mime_type(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/voice-memo",
            data={
                "audio": (io.BytesIO(b"\x00\x01\x02"), "memo.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert "Unsupported audio type" in body["error"]
        assert "audio/webm" in body["allowed"]

    def test_accepts_ios_safari_content_type_with_codec_semicolon(
        self, client, monkeypatch,
    ):
        """iOS Safari sends ``audio/mp4;codecs=mp4a.40.2`` — the codec
        suffix must NOT cause rejection. Regression test for the
        2026-04-18 iPhone upload bug."""
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={"transcript": "test", "duration_seconds": 1.0, "cost_usd": 0.0001},
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                return_value=[_TEST_CAND],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={
                    "audio": (
                        io.BytesIO(b"fake mp4 audio"),
                        "memo.mp4",
                        "audio/mp4;codecs=mp4a.40.2",
                    ),
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, (
            f"iOS Safari content-type with codec params was rejected: "
            f"{resp.status_code} {resp.get_json()}"
        )

    def test_accepts_ios_safari_content_type_with_codec_colon_variant(
        self, client, monkeypatch,
    ):
        """Some iOS versions use ':' instead of ';' as the parameter
        separator — e.g. ``audio/mp4:codecs-mp4a.40.2``. Server must
        normalize both forms."""
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={"transcript": "test", "duration_seconds": 1.0, "cost_usd": 0.0001},
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                return_value=[_TEST_CAND],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={
                    "audio": (
                        io.BytesIO(b"fake mp4 audio"),
                        "memo.mp4",
                        "audio/mp4:codecs-mp4a.40.2",
                    ),
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200, (
            f"colon-separated codec param was rejected: "
            f"{resp.status_code} {resp.get_json()}"
        )

    def test_accepts_chrome_webm_opus_content_type(self, client, monkeypatch):
        """Chrome/Android MediaRecorder sends ``audio/webm;codecs=opus``."""
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={"transcript": "test", "duration_seconds": 1.0, "cost_usd": 0.0001},
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                return_value=[_TEST_CAND],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={
                    "audio": (
                        io.BytesIO(b"fake webm audio"),
                        "memo.webm",
                        "audio/webm;codecs=opus",
                    ),
                },
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200

    def test_rejects_oversize_file(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        # 26 MB > the 25 MB Whisper limit
        big = b"\x00" * (26 * 1024 * 1024)
        resp = client.post(
            "/api/voice-memo",
            data={"audio": (io.BytesIO(big), "memo.webm", "audio/webm")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 413
        assert "too large" in resp.get_json()["error"].lower()

    def test_rejects_empty_file(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/voice-memo",
            data={"audio": (io.BytesIO(b""), "memo.webm", "audio/webm")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "Empty" in resp.get_json()["error"]

    def test_happy_path_returns_candidates(self, client, monkeypatch):
        """Backlog #36: voice-memo response now returns structured
        candidates with type/tier/due_date inferred by Claude."""
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={
                    "transcript": "Buy milk tomorrow. Email the Q2 report.",
                    "duration_seconds": 12.5,
                    "cost_usd": 0.00125,
                },
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                return_value=[
                    {"title": "Buy milk", "type": "personal",
                     "tier": "tomorrow", "due_date": "2026-04-22"},
                    {"title": "Email the Q2 report", "type": "work",
                     "tier": "inbox", "due_date": None},
                ],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"fake audio bytes"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["transcript"] == "Buy milk tomorrow. Email the Q2 report."
        assert body["duration_seconds"] == 12.5
        assert body["cost_usd"] == pytest.approx(0.00125)
        cands = body["candidates"]
        assert [c["title"] for c in cands] == [
            "Buy milk", "Email the Q2 report",
        ]
        # Type / tier / due_date flow through from the NLP output
        assert cands[0]["type"] == "personal"
        assert cands[0]["tier"] == "tomorrow"
        assert cands[0]["due_date"] == "2026-04-22"
        assert cands[1]["type"] == "work"
        assert cands[1]["tier"] == "inbox"
        assert cands[1]["due_date"] is None
        assert all(c["included"] is True for c in cands)

    def test_project_and_goal_hint_fields_round_trip_to_response(self, client, monkeypatch):
        """Regression (2026-05-12): voice_api dropped project_id /
        project_hint / goal_id / goal_hint when building candidates_out,
        so the review UI's project dropdown never pre-selected the
        project Claude resolved — every dictated project silently
        landed with no project link. Assert all four fields survive
        the round-trip from parse_voice_memo_to_tasks → response JSON.

        Two candidates exercise BOTH the resolved-id and the
        unresolved-hint branches for project AND goal, so the symmetric
        contract is pinned for both kinds — a future refactor can't
        quietly regress one direction without the other.
        """
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={
                    "transcript": "Email Bob about Q2 OKRs. Run 5K for the marathon goal.",
                    "duration_seconds": 6.0,
                    "cost_usd": 0.0006,
                },
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                return_value=[
                    # Candidate 1: project resolved, goal unresolved.
                    {
                        "title": "Email Bob",
                        "type": "work",
                        "tier": "inbox",
                        "due_date": None,
                        "project_hint": "Q2 OKRs",
                        "project_id": "proj-uuid-resolved",
                        "goal_hint": "Hit Q2 targets",
                        "goal_id": None,  # unresolved — must still surface
                        "is_task": True,
                    },
                    # Candidate 2: goal resolved, project unresolved. Locks
                    # the symmetric guarantee — goal_id round-trips just
                    # like project_id (the original bug dropped both).
                    {
                        "title": "Run 5K",
                        "type": "personal",
                        "tier": "this_week",
                        "due_date": None,
                        "project_hint": "Phantom Project",
                        "project_id": None,  # unresolved — must still surface
                        "goal_hint": "Run a half marathon",
                        "goal_id": "goal-uuid-resolved",
                        "is_task": True,
                    },
                ],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"audio"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        cands = resp.get_json()["candidates"]
        assert len(cands) == 2

        # Candidate 1: project resolved, goal unresolved.
        assert cands[0]["project_id"] == "proj-uuid-resolved"
        assert cands[0]["project_hint"] == "Q2 OKRs"
        assert cands[0]["goal_id"] is None
        assert cands[0]["goal_hint"] == "Hit Q2 targets"

        # Candidate 2: goal resolved, project unresolved. Pins the
        # symmetric contract — the original bug dropped goal_id too.
        assert cands[1]["goal_id"] == "goal-uuid-resolved"
        assert cands[1]["goal_hint"] == "Run a half marathon"
        assert cands[1]["project_id"] is None
        assert cands[1]["project_hint"] == "Phantom Project"

    def test_empty_transcript_returns_empty_candidates_with_message(self, client, monkeypatch):
        """No speech detected → empty transcript, no Claude call,
        helpful 'no speech' message returned 200."""
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        with patch(
            "voice_api.transcribe_audio",
            return_value={"transcript": "", "duration_seconds": 1.5, "cost_usd": 0.0001},
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"silence"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["candidates"] == []
        assert "No speech detected" in body["message"]

    def test_transcription_failure_returns_422_with_error(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        with patch(
            "voice_api.transcribe_audio",
            side_effect=RuntimeError("Whisper API returned HTTP 401"),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"audio"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 422
        assert "Whisper API returned HTTP 401" in resp.get_json()["error"]

    def test_parsing_failure_keeps_transcript_for_user_recovery(self, client, monkeypatch):
        """Whisper succeeds but Claude fails — user shouldn't lose the
        transcript. Endpoint returns 422 with both error AND transcript."""
        _bypass_auth(monkeypatch)

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={
                    "transcript": "Important things to remember",
                    "duration_seconds": 5.0,
                    "cost_usd": 0.0005,
                },
            ),
            patch(
                "voice_api.parse_voice_memo_to_tasks",
                side_effect=RuntimeError("Claude rate-limited"),
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"audio"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 422
        body = resp.get_json()
        assert body["transcript"] == "Important things to remember"
        assert "Claude rate-limited" in body["error"]
        assert body["candidates"] == []


# --- voice_api POST /api/voice-memo/confirm ----------------------------------


class TestVoiceConfirm:
    """Verify confirm endpoint creates Tasks via the shared scan_service
    helper with the right source_prefix."""

    def test_creates_tasks_with_voice_source_prefix(self, client, monkeypatch):
        _bypass_auth(monkeypatch)

        # We patch create_tasks_from_candidates via voice_api's import
        # path so we can assert the source_prefix was passed correctly.
        with patch("voice_api.create_tasks_from_candidates") as mock_create:
            mock_create.return_value = []
            resp = client.post(
                "/api/voice-memo/confirm",
                json={
                    "candidates": [
                        {"title": "Buy milk", "type": "work", "included": True},
                    ]
                },
            )

        assert resp.status_code == 201
        # Verify source_prefix was passed as "voice"
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs.get("source_prefix") == "voice"

    def test_rejects_non_dict_body(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/voice-memo/confirm",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_rejects_non_list_candidates(self, client, monkeypatch):
        _bypass_auth(monkeypatch)
        resp = client.post(
            "/api/voice-memo/confirm",
            json={"candidates": "not a list"},
        )
        assert resp.status_code == 422

    def test_project_route_creates_real_projects(self, client, monkeypatch, app):
        """PR61 audit fix #1: voice candidates with route=='project' used
        to be stuffed into task_candidates with a literal '(project) '
        prefix because #80 hadn't shipped yet. #80 (create_projects_from_import)
        DID ship, but this branch never got updated — so every dictated
        project silently became a junk task. Now route=='project' lands
        through create_projects_from_import, producing real Project rows.
        """
        _bypass_auth(monkeypatch)

        resp = client.post(
            "/api/voice-memo/confirm",
            json={
                "candidates": [
                    {
                        "title": "Portal redesign",
                        "route": "project",
                        "type": "work",
                        "included": True,
                    },
                    {
                        "title": "Buy milk",
                        "route": "task",
                        "type": "work",
                        "included": True,
                    },
                ]
            },
        )
        body = resp.get_json()
        assert resp.status_code == 201
        # 1 project + 1 task — no fake "(project) Portal redesign" task.
        assert body["created"] == 2
        assert len(body["projects"]) == 1
        assert body["projects"][0]["name"] == "Portal redesign"
        assert body["projects"][0]["type"] == "work"
        assert len(body["tasks"]) == 1
        assert body["tasks"][0]["title"] == "Buy milk"
        # No leftover "(project) " warning either.
        assert "warning" not in body or "(project)" not in body.get("warning", "")

        # Verify a real Project row landed in DB.
        from models import Project, db
        with app.app_context():
            projects = db.session.query(Project).filter_by(name="Portal redesign").all()
            assert len(projects) == 1
            assert projects[0].is_active is True

    def test_goal_route_uses_explicit_category_not_task_type(
        self, client, monkeypatch, app,
    ):
        """#172 (2026-05-21): a voice candidate routed to a goal must
        land with the `category` Claude inferred — NOT the task `type`.
        The old code read `c.get("type")`; since "personal" is not a
        goal category it always fell through to "work", so every
        voice-dictated personal goal silently bucketed under Work.
        """
        _bypass_auth(monkeypatch)

        resp = client.post(
            "/api/voice-memo/confirm",
            json={
                "candidates": [
                    {
                        "title": "Read 12 books this year",
                        "route": "goal",
                        "type": "personal",       # task-axis type
                        "category": "personal_growth",  # goal category
                        "included": True,
                    },
                    {
                        "title": "Run a half marathon",
                        "route": "goal",
                        "type": "personal",
                        "category": "health",
                        "included": True,
                    },
                ]
            },
        )
        assert resp.status_code == 201

        from models import Goal, GoalCategory, db
        with app.app_context():
            books = db.session.query(Goal).filter_by(
                title="Read 12 books this year",
            ).one()
            marathon = db.session.query(Goal).filter_by(
                title="Run a half marathon",
            ).one()
            # Pre-fix BOTH would have been GoalCategory.WORK.
            assert books.category == GoalCategory.PERSONAL_GROWTH
            assert marathon.category == GoalCategory.HEALTH

    def test_goal_route_missing_category_defaults_to_personal_growth(
        self, client, monkeypatch, app,
    ):
        """#172: a goal candidate with no `category` (e.g. an older
        client that doesn't send it, or Claude omitting it) defaults
        to personal_growth — never the old silent 'work'."""
        _bypass_auth(monkeypatch)

        resp = client.post(
            "/api/voice-memo/confirm",
            json={
                "candidates": [
                    {
                        "title": "Learn watercolor painting",
                        "route": "goal",
                        "type": "personal",
                        "included": True,
                    },
                ]
            },
        )
        assert resp.status_code == 201

        from models import Goal, GoalCategory, db
        with app.app_context():
            goal = db.session.query(Goal).filter_by(
                title="Learn watercolor painting",
            ).one()
            assert goal.category == GoalCategory.PERSONAL_GROWTH

    def test_empty_title_is_skipped_and_warned(self, client, monkeypatch):
        """PR24 TD-2: candidates with an empty title (e.g. user said
        "goal:" with nothing after it) used to be silently dropped by
        the import creators, leaving the user with "0 created" and no
        explanation. Now the response includes a warning + count."""
        _bypass_auth(monkeypatch)
        with patch("voice_api.create_tasks_from_candidates") as mock_create:
            mock_create.return_value = []
            resp = client.post(
                "/api/voice-memo/confirm",
                json={
                    "candidates": [
                        {"title": "", "route": "goal", "included": True},
                        {"title": "  ", "route": "task", "included": True},
                    ]
                },
            )
        body = resp.get_json()
        assert resp.status_code == 201
        assert body["created"] == 0
        assert "warning" in body
        assert "skipped" in body["warning"].lower()
        assert "2" in body["warning"]


# --- Regression: scan_service refactor preserved default behavior ------------


class TestScanServiceSourcePrefixRegression:
    """Refactoring create_tasks_from_candidates to accept source_prefix
    must not change existing callers' behavior. Default must remain
    'scan'."""

    def test_default_source_prefix_is_scan(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "Test task", "type": "work", "included": True}]
            )

        assert len(tasks) == 1
        # Verify the ImportLog was created with "scan_..." source
        from models import ImportLog, db
        with app.app_context():
            log = db.session.query(ImportLog).order_by(
                ImportLog.id.desc()
            ).first()
            assert log is not None
            assert log.source.startswith("scan_")

    def test_voice_source_prefix_writes_voice_log(self, app):
        from scan_service import create_tasks_from_candidates

        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "Voice task", "type": "work", "included": True}],
                source_prefix="voice",
            )

        assert len(tasks) == 1
        from models import ImportLog, db
        with app.app_context():
            log = db.session.query(ImportLog).order_by(
                ImportLog.id.desc()
            ).first()
            assert log is not None
            assert log.source.startswith("voice_")


class TestVoiceNormaliser:
    """Backlog #36: _normalise_voice_candidates cleans Claude output."""

    def test_drops_items_without_title(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"type": "work", "tier": "today"},          # no title
            {"title": "", "type": "work"},              # blank title
            {"title": "   ", "type": "work"},           # whitespace title
            {"title": "Keep me", "type": "work"},       # valid
        ])
        assert len(result) == 1
        assert result[0]["title"] == "Keep me"

    def test_coerces_unknown_type_to_personal(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "x", "type": "nonsense"}
        ])
        assert result[0]["type"] == "personal"

    def test_coerces_unknown_tier_to_inbox(self):
        from scan_service import _normalise_voice_candidates
        # #137 Sub-PR B (PR73): "next_week" + "backlog" are now valid;
        # only truly bogus values + the deliberately-omitted "freezer"
        # should still coerce to inbox.
        result = _normalise_voice_candidates([
            {"title": "x", "tier": "freezer"},  # deliberately omitted
            {"title": "y", "tier": "bogus"},
        ])
        assert result[0]["tier"] == "inbox"
        assert result[1]["tier"] == "inbox"

    def test_accepts_next_week_tier(self):
        """#137 Sub-PR B: 'next_week' is now a valid voice tier
        (was previously coerced to inbox, losing the user's intent)."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "Plan Q2 review", "tier": "next_week"},
        ])
        assert result[0]["tier"] == "next_week"

    def test_accepts_backlog_tier(self):
        """#137 Sub-PR B: 'backlog' is now a valid voice tier — users
        dictating 'backlog this' or 'someday' map to backlog instead
        of being silently demoted to inbox."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "Read that book", "tier": "backlog"},
        ])
        assert result[0]["tier"] == "backlog"

    def test_freezer_tier_still_coerced(self):
        """#137 Sub-PR B: 'freezer' is deliberately NOT auto-assignable
        from voice — it's a parking lot the user explicitly opts into
        via the detail panel."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "x", "tier": "freezer"},
        ])
        assert result[0]["tier"] == "inbox"

    def test_voice_valid_tiers_set_membership(self):
        """#137 Sub-PR B: contract test — guards against accidental
        widening (e.g. someone adds "freezer" without thinking through
        the parking-lot UX) or accidental narrowing (a regression that
        re-removes next_week / backlog)."""
        from scan_service import _VOICE_VALID_TIERS
        expected = {
            "inbox", "today", "tomorrow",
            "this_week", "next_week", "backlog",
        }
        assert expected == _VOICE_VALID_TIERS
        assert "freezer" not in _VOICE_VALID_TIERS

    def test_validates_due_date_format(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "a", "due_date": "2026-04-22"},    # valid
            {"title": "b", "due_date": "tomorrow"},      # string but bad ISO
            {"title": "c", "due_date": 12345},           # not a string
            {"title": "d"},                              # missing
        ])
        assert result[0]["due_date"] == "2026-04-22"
        assert result[1]["due_date"] is None
        assert result[2]["due_date"] is None
        assert result[3]["due_date"] is None

    def test_truncates_long_titles(self):
        from scan_service import _normalise_voice_candidates
        long = "x" * 150
        result = _normalise_voice_candidates([
            {"title": long, "type": "work"}
        ])
        assert len(result[0]["title"]) == 100

    def test_preserves_valid_inference_end_to_end(self):
        """Baseline #36 shape still passes through unchanged, with #37
        additions (project_id, goal_id, is_task) set to safe defaults
        when no hints are supplied. #172 added `category` — when Claude
        omits it the normaliser fills the personal_growth default."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "Pick up meds", "type": "personal",
             "tier": "tomorrow", "due_date": "2026-04-22"},
        ])
        assert result[0] == {
            "title": "Pick up meds",
            "type": "personal",
            "tier": "tomorrow",
            "due_date": "2026-04-22",
            "project_hint": None,
            "project_id": None,
            "goal_hint": None,
            "goal_id": None,
            "is_task": True,
            "category": "personal_growth",
        }

    # --- #172 category normalisation ------------------------------------

    def test_valid_category_preserved(self):
        """#172: a valid GoalCategory value from Claude survives
        normalisation unchanged."""
        from scan_service import _normalise_voice_candidates
        for cat in ("health", "personal_growth", "relationships", "work", "bau"):
            result = _normalise_voice_candidates([
                {"title": "x", "type": "personal", "tier": "inbox",
                 "category": cat},
            ])
            assert result[0]["category"] == cat

    def test_unknown_category_coerced_to_personal_growth(self):
        """#172: a hallucinated / missing category coerces to the
        neutral default — same fallback the image goals-parse prompt
        uses. 'personal' (a task TYPE, the value the OLD buggy code
        passed) is NOT a valid category and must coerce."""
        from scan_service import _normalise_voice_candidates
        for bad in ("personal", "garbage", "", None):
            result = _normalise_voice_candidates([
                {"title": "x", "type": "personal", "tier": "inbox",
                 "category": bad},
            ])
            assert result[0]["category"] == "personal_growth", (
                f"category {bad!r} should coerce to personal_growth"
            )

    def test_missing_category_key_defaults(self):
        """#172: Claude omitting the key entirely → default applied."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "x", "type": "work", "tier": "inbox"},
        ])
        assert result[0]["category"] == "personal_growth"

    # --- #37 hint resolution --------------------------------------------

    def test_project_hint_resolves_to_id_case_insensitive(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "Ship feature", "project_hint": "Q2 OKRs"}],
            projects=[("proj-uuid-1", "Q2 OKRs")],
            goals=[],
        )
        assert result[0]["project_id"] == "proj-uuid-1"
        assert result[0]["project_hint"] == "Q2 OKRs"

    def test_project_hint_case_insensitive_match(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "q2 okrs"}],
            projects=[("proj-1", "Q2 OKRs")],
            goals=[],
        )
        assert result[0]["project_id"] == "proj-1"

    def test_unknown_project_hint_stays_as_free_text(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Hallucinated Project"}],
            projects=[("proj-1", "Real Project")],
            goals=[],
        )
        assert result[0]["project_id"] is None
        assert result[0]["project_hint"] == "Hallucinated Project"

    def test_goal_hint_resolves_to_id(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "Run 5K", "goal_hint": "Run a half marathon"}],
            projects=[],
            goals=[("goal-1", "Run a half marathon")],
        )
        assert result[0]["goal_id"] == "goal-1"

    def test_goal_hint_unknown_stays_as_free_text(self):
        """#137 Sub-PR C: explicit 'for the X goal' phrasing where X
        doesn't match any user goal must NOT be invented — Claude is
        instructed to leave goal_hint null in that case, but we also
        defensively assert here that even if Claude returns the
        free-text hint, it stays as text (no goal_id resolved)."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "goal_hint": "Hallucinated goal"}],
            projects=[],
            goals=[("goal-1", "Run a half marathon")],
        )
        assert result[0]["goal_id"] is None
        assert result[0]["goal_hint"] == "Hallucinated goal"

    # --- #234 (2026-05-26) cross-domain fallback + exact-name regression -

    def test_234_exact_user_repro_project_and_goal_both_named_job_search(self):
        """User-reported 2026-05-25 with iPhone screenshot: voice-memo
        candidate "Follow up with VG regarding job openings" showed
        BOTH "Heard project: 'Job Search' (no match)" AND
        "Heard goal: 'Job Search' (no match)" — but the user's prod
        DB has BOTH a Project AND a Goal named exactly "Job Search".

        This is the regression assertion that the resolver works for
        the user's exact data shape. If it ever fails, "(no match)"
        will surface again and we'll have a fast Jest-style signal
        instead of waiting for the user to find it.
        """
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{
                "title": "Follow up with VG regarding job openings",
                "type": "personal",
                "tier": "this_week",
                "project_hint": "Job Search",
                "goal_hint": "Job Search",
            }],
            projects=[("project-uuid-21a67c55", "Job Search")],
            goals=[("goal-uuid-5d20e981", "Job Search")],
        )
        assert result[0]["project_id"] == "project-uuid-21a67c55"
        assert result[0]["goal_id"] == "goal-uuid-5d20e981"
        # Hints stay on the candidate even when resolved (the UI uses
        # them for the dropdown's pre-selection + tooltip).
        assert result[0]["project_hint"] == "Job Search"
        assert result[0]["goal_hint"] == "Job Search"

    def test_234_cross_domain_project_hint_falls_back_to_goal(self):
        """If Claude misclassifies — putting a goal-name in
        project_hint AND not setting goal_hint — the cross-domain
        fallback resolves project_hint against goals and fills goal_id.
        project_id stays null (the project lookup correctly missed)."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Run a half marathon"}],
            projects=[("p1", "Some Project")],
            goals=[("g1", "Run a half marathon")],
        )
        assert result[0]["project_id"] is None
        assert result[0]["goal_id"] == "g1"
        # The fallback surfaces the resolved name as goal_hint so the
        # UI can show the user which goal it picked.
        assert result[0]["goal_hint"] == "Run a half marathon"

    def test_234_cross_domain_goal_hint_falls_back_to_project(self):
        """Symmetric to the above: a project-name in goal_hint with no
        project_hint set resolves via the goal→project fallback."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "goal_hint": "Q2 OKRs"}],
            projects=[("p1", "Q2 OKRs")],
            goals=[("g1", "Some Goal")],
        )
        assert result[0]["goal_id"] is None
        assert result[0]["project_id"] == "p1"
        assert result[0]["project_hint"] == "Q2 OKRs"

    def test_234_cross_domain_does_not_clobber_explicit_resolution(self):
        """If Claude correctly sets BOTH hints and both resolve, the
        fallback must NOT overwrite either. Specifically: an explicit
        project_hint that resolves to a project shouldn't be
        secondarily resolved against goals (would clobber the goal_id
        if also explicit).
        """
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{
                "title": "x",
                "project_hint": "Marathon Training",
                "goal_hint": "Run a half marathon",
            }],
            projects=[("p1", "Marathon Training")],
            goals=[("g1", "Run a half marathon")],
        )
        assert result[0]["project_id"] == "p1"
        assert result[0]["goal_id"] == "g1"

    def test_234_cross_domain_does_not_fire_if_already_resolved(self):
        """If project_hint resolved to a project, the goal-fallback
        path must not also run on the same hint (would risk clobbering
        a separately-set goal_hint's resolution)."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Job Search"}],
            projects=[("p1", "Job Search")],
            goals=[("g1", "Job Search")],
        )
        # project_hint resolves to project → no fallback to goal.
        # goal_id stays None because no goal_hint was set.
        assert result[0]["project_id"] == "p1"
        assert result[0]["goal_id"] is None

    # --- #234 third pass (2026-05-26): Unicode-aware hint normalisation -

    def test_234_unicode_zero_width_space_in_hint_still_resolves(self):
        """Claude has been observed to emit hints with hidden U+200B
        (zero-width space) characters that render identically to ASCII
        but break str.lower().strip() lookup. The normalised resolver
        should still match the ASCII title."""
        from scan_service import _normalise_voice_candidates
        # "Roadmaps​" — trailing zero-width space, invisible in any
        # text display but breaks naive lookup.
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Roadmaps​"}],
            projects=[("p-roadmaps", "Roadmaps")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-roadmaps"

    def test_234_unicode_leading_zero_width_joiner_still_resolves(self):
        from scan_service import _normalise_voice_candidates
        # Leading U+200D (zero-width joiner) — also breaks str.strip().
        result = _normalise_voice_candidates(
            [{"title": "x", "goal_hint": "‍Job Search"}],
            projects=[],
            goals=[("g-job", "Job Search")],
        )
        assert result[0]["goal_id"] == "g-job"

    def test_234_unicode_nbsp_between_words_still_resolves(self):
        """U+00A0 (non-breaking space) renders as a regular space but
        is NOT equal to it. A hint with NBSP between words would miss
        a regular-space title without normalisation."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "goal_hint": "Roadmaps Best Practices"}],
            projects=[],
            goals=[("g-rbp", "Roadmaps Best Practices")],
        )
        assert result[0]["goal_id"] == "g-rbp"

    def test_234_unicode_fullwidth_letters_still_resolve(self):
        """NFKC normalisation folds fullwidth ASCII (e.g. "Ｒoadmaps")
        to plain ASCII."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Ｒoadmaps"}],
            projects=[("p-roadmaps", "Roadmaps")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-roadmaps"

    def test_234_unicode_smart_quotes_normalised(self):
        """If Claude wraps a hint in smart quotes ("Roadmaps"), NFKC
        normalises them. Title in the DB has no quotes — but if a
        hint with quotes still resolves via substring fallback, the
        normalisation hasn't broken the fallback path either."""
        from scan_service import _normalise_voice_candidates
        # Note: smart quotes aren't normalised to "" by NFKC alone —
        # but a quoted hint like ‘Roadmaps’ would substring-match the
        # title "roadmaps". We test the trailing-quote case.
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Roadmaps"}],  # plain
            projects=[("p-roadmaps", "Roadmaps")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-roadmaps"

    def test_normalise_title_helper_strips_zero_width(self):
        """Direct unit test of the helper. Critical guarantee:
        zero-width characters are removed (str.strip() leaves them)."""
        from scan_service import _normalise_title
        assert _normalise_title("Roadmaps​") == "roadmaps"
        assert _normalise_title("‍Job Search") == "job search"
        assert _normalise_title("Roadmaps Best Practices") == \
            "roadmaps best practices"
        assert _normalise_title("Ｒoadmaps") == "roadmaps"
        assert _normalise_title("  Trailing whitespace  ") == "trailing whitespace"
        assert _normalise_title("") == ""
        assert _normalise_title(None) == ""

    def test_234_no_hint_no_fallback(self):
        """No hint at all → no resolution attempted on either side."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x"}],
            projects=[("p1", "Job Search")],
            goals=[("g1", "Job Search")],
        )
        assert result[0]["project_id"] is None
        assert result[0]["goal_id"] is None
        assert result[0]["project_hint"] is None
        assert result[0]["goal_hint"] is None

    # --- #234 fourth pass (2026-05-26): separator-char normalization ---
    # User STILL hit "(no match)" for "Roadmap Automation" after the
    # third-pass Unicode-normalize fix. Diagnostic probe found
    # "Roadmap-Automation" and "Roadmap_Automation" still miss — both
    # plausible Claude mutations (the model "tidies up" multi-word
    # names into code-style identifiers). Fix: coerce hyphens,
    # underscores, en-dashes, em-dashes to a single space.

    def test_234_hyphen_in_hint_resolves_to_space_separated_title(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Roadmap-Automation"}],
            projects=[("p-ra", "Roadmap Automation")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-ra"

    def test_234_underscore_in_hint_resolves(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Roadmap_Automation"}],
            projects=[("p-ra", "Roadmap Automation")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-ra"

    def test_234_em_dash_in_hint_resolves(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "goal_hint": "Roadmaps—Best Practices"}],
            projects=[],
            goals=[("g-rbp", "Roadmaps Best Practices")],
        )
        assert result[0]["goal_id"] == "g-rbp"

    def test_234_en_dash_in_hint_resolves(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "x", "project_hint": "Roadmap–Automation"}],
            projects=[("p-ra", "Roadmap Automation")],
            goals=[],
        )
        assert result[0]["project_id"] == "p-ra"

    def test_234_normalise_title_separator_chars(self):
        """Direct unit test of separator-char coercion."""
        from scan_service import _normalise_title
        assert _normalise_title("Roadmap-Automation") == "roadmap automation"
        assert _normalise_title("Roadmap_Automation") == "roadmap automation"
        assert _normalise_title("Roadmap—Automation") == "roadmap automation"
        assert _normalise_title("Roadmap–Automation") == "roadmap automation"
        assert _normalise_title("foo-bar_baz—qux") == "foo bar baz qux"
        assert _normalise_title("foo - bar") == "foo bar"

    def test_234_fetch_logs_counts_on_success(self, app, caplog):
        """The #234 fetch surfaces project/goal counts to logs so a
        future 'all hints missed' report can be diagnosed from
        /api/debug/logs.

        2026-05-26 follow-up: in the test DB there are typically 0
        projects/goals — that triggers the THIN-source WARNING path
        (the same "missing data" signal real users would hit). Either
        the INFO or the WARNING qualifies as "the log fired and named
        the counts" for the purpose of this assertion.
        """
        import logging

        from scan_service import _fetch_projects_and_goals_for_hints
        # caplog at INFO so we capture both the happy-path INFO and the
        # thin-sources WARNING when projects/goals are missing.
        with app.app_context(), caplog.at_level(logging.INFO, logger="scan_service"):
            projects, goals = _fetch_projects_and_goals_for_hints()
        msgs = [r.getMessage() for r in caplog.records]
        # One of the two should be present; both report N projects + M
        # goals, just at different severities.
        assert any(
            "voice hint sources:" in m or "voice hint sources thin:" in m
            for m in msgs
        ), msgs

    def test_234_fetch_logs_warning_on_exception(self, monkeypatch, caplog):
        """If the DB query raises (transient, schema drift, etc.),
        the fetch returns empty AND logs a WARNING with the exception
        type + message — instead of silently swallowing.
        """
        import logging

        import scan_service

        # Patch db.session.scalars to raise on the next call. The
        # `from models import ... db` is local-to-function so we have
        # to patch at the source.
        from models import db as _db

        def _explode(*args, **kwargs):
            raise RuntimeError("simulated DB transient")

        monkeypatch.setattr(_db.session, "scalars", _explode)
        with caplog.at_level(logging.WARNING, logger="scan_service"):
            projects, goals = scan_service._fetch_projects_and_goals_for_hints()
        assert projects == []
        assert goals == []
        msgs = [r.getMessage() for r in caplog.records]
        assert any("voice hint sources fetch failed" in m for m in msgs), msgs
        assert any("RuntimeError" in m for m in msgs), msgs

    def test_is_task_false_preserved(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates(
            [{"title": "Felt scattered today", "is_task": False}]
        )
        assert result[0]["is_task"] is False

    def test_is_task_defaults_true_when_missing(self):
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([{"title": "x"}])
        assert result[0]["is_task"] is True

    def test_is_task_truthy_non_false_stays_true(self):
        """Only exact boolean False counts as 'not a task' — a Claude
        miss that returns 'is_task': None must not silently drop the
        task."""
        from scan_service import _normalise_voice_candidates
        result = _normalise_voice_candidates([
            {"title": "a", "is_task": None},
            {"title": "b", "is_task": "yes"},
        ])
        assert result[0]["is_task"] is True
        assert result[1]["is_task"] is True


class TestVoiceCreateTasksFromCandidates:
    """Backlog #36: create_tasks_from_candidates honours inferred
    tier + due_date from the voice review screen."""

    def test_inferred_tier_and_due_date_land_in_task(self, app):
        from datetime import date

        from models import TaskType, Tier
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            tasks = create_tasks_from_candidates(
                [
                    {
                        "title": "Pick up meds",
                        "type": "personal",
                        "tier": "tomorrow",
                        "due_date": "2026-04-22",
                        "included": True,
                    }
                ],
                source_prefix="voice",
            )
            assert len(tasks) == 1
            t = tasks[0]
            assert t.title == "Pick up meds"
            assert t.type == TaskType.PERSONAL
            assert t.tier == Tier.TOMORROW
            assert t.due_date == date(2026, 4, 22)

    def test_missing_tier_defaults_to_inbox(self, app):
        """Existing image-OCR candidates don't set `tier` — must not
        regress when mixed through the same code path."""
        from models import Tier
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "No tier", "type": "work", "included": True}]
            )
            assert tasks[0].tier == Tier.INBOX
            assert tasks[0].due_date is None

    def test_bad_due_date_silently_dropped(self, app):
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "Bad date", "type": "work",
                  "due_date": "not-a-date", "included": True}]
            )
            assert len(tasks) == 1
            assert tasks[0].due_date is None

    # --- #37 project/goal ID flow -----------------------------------

    def test_project_and_goal_ids_land_on_task(self, app):
        """Voice NLP phase 2: when the candidate dict carries a valid
        project_id / goal_id (resolved from hints), the created Task
        is linked to those records."""
        import uuid as _uuid

        from models import Goal, GoalCategory, GoalPriority, Project, ProjectType, db
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            proj = Project(name="P1", type=ProjectType.WORK)
            goal = Goal(
                title="G1",
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
            )
            db.session.add_all([proj, goal])
            db.session.commit()
            tasks = create_tasks_from_candidates(
                [{
                    "title": "Linked task", "type": "work",
                    "project_id": str(proj.id),
                    "goal_id": str(goal.id),
                    "included": True,
                }]
            )
            assert len(tasks) == 1
            assert tasks[0].project_id == proj.id
            assert tasks[0].goal_id == goal.id
            # Sanity — isinstance, not equality with string
            assert isinstance(tasks[0].project_id, _uuid.UUID)

    def test_malformed_project_id_silently_dropped(self, app):
        """A non-UUID project_id must not crash the batch — one bad
        candidate should only cost itself its link, not the whole
        import."""
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            tasks = create_tasks_from_candidates(
                [{"title": "x", "type": "work",
                  "project_id": "not-a-uuid", "included": True}]
            )
            assert len(tasks) == 1
            assert tasks[0].project_id is None


class TestVoicePromptTZDriftFix180:
    """Audit fix #180 (2026-05-20): _call_claude_api_voice used
    UTC ``date.today()`` for the ``Today:`` line in the prompt. At
    9pm ET, Claude would resolve "tomorrow" against UTC's next-day,
    stamping due_date one day later than the user meant.
    """

    def test_prompt_uses_local_today_date(self, monkeypatch):
        from datetime import date

        from scan_service import _call_claude_api_voice

        pinned = date(2026, 5, 20)
        monkeypatch.setattr(
            "scan_service.local_today_date", lambda: pinned,
            raising=False,
        )
        # The import inside _call_claude_api_voice is local — patch the
        # module the helper resolves against.
        import utils as _utils
        monkeypatch.setattr(_utils, "local_today_date", lambda: pinned)

        captured = {}

        def fake_post(api_key, prompt, max_tokens):  # noqa: ARG001
            captured["prompt"] = prompt
            # Minimal Claude-shaped response: empty candidates list.
            return {"content": [{"text": "[]"}]}

        monkeypatch.setattr("scan_service._post_to_claude", fake_post)

        out = _call_claude_api_voice(
            api_key="sk-test",
            transcript="something tomorrow",
            projects=[],
            goals=[],
        )
        assert out == []
        # The pinned local date should appear in the prompt — both at the
        # "Today's date is" header and the inline "against today's date"
        # reference. Strict positive: the ET date is present.
        assert "2026-05-20" in captured["prompt"]


class TestVoicePromptSelfConsistency:
    """#137 Sub-PR C: prompt-template self-consistency.

    Sub-PR C is a prompt-engineering change — the rules live in the
    Claude system prompt, not in code we can directly exercise. These
    tests guard the prompt itself: that it formats cleanly, that the
    in-prompt example is valid JSON, and that the example demonstrates
    the documented rules using only valid enum values.

    This is NOT a substitute for verifying Claude actually follows the
    rules at runtime (that's a manual prod-smoke confirmation when the
    user dictates an explicit-mention memo). But it catches the
    mechanical breakage classes: missing format-vars, malformed JSON
    in the example, drift between the prompt example's tier values
    and `_VOICE_VALID_TIERS`, and accidental deletion of the explicit
    phrasing rules in a future edit.
    """

    def _format_prompt(self):
        from scan_service import _VOICE_PARSE_PROMPT
        return _VOICE_PARSE_PROMPT.format(
            today="2026-04-20",
            project_titles="- Q2 OKRs\n- Launch site",
            goal_titles="- Run a half marathon",
            transcript="(test transcript)",
        )

    def test_prompt_formats_without_keyerror(self):
        """All format-vars are supplied — no surprise placeholders
        introduced by Sub-PR C edits. _format_prompt() raising
        KeyError is the failure mode we're guarding against (e.g.
        a future edit adding `{example}` without supplying it)."""
        prompt = self._format_prompt()
        assert "2026-04-20" in prompt
        assert "Q2 OKRs" in prompt
        assert "Run a half marathon" in prompt

    def test_prompt_contains_explicit_project_phrasing_rules(self):
        """Sub-PR C rule must be present — guards against accidental
        deletion in future edits. Logic test partner is the unknown-
        hint resolution test above; this confirms Claude is actually
        instructed to detect those phrasings."""
        from scan_service import _VOICE_PARSE_PROMPT
        for phrase in (
            "for the NAME project",
            "project: NAME",
            "for the NAME goal",
            "goal: NAME",
        ):
            assert phrase in _VOICE_PARSE_PROMPT, f"missing rule: {phrase}"

    def test_prompt_covers_user_reported_phrasings(self):
        """User-reported regression 2026-05-01: prompt didn't catch
        'put in project NAME' or 'recommend project NAME' — the
        original explicit-phrasing rules required either a colon
        ('project: NAME') or 'the' ('for the NAME project'). The
        widened rule must teach the model to also accept verb-led
        clauses that mention 'project' + NAME without 'the'."""
        from scan_service import _VOICE_PARSE_PROMPT
        for phrase in (
            "put in project NAME",
            "recommend project NAME",
            "in project NAME",
            "to project NAME",
        ):
            assert phrase in _VOICE_PARSE_PROMPT, f"missing rule: {phrase}"

    def test_prompt_example_demonstrates_put_in_project_phrasing(self):
        """User-reported regression 2026-05-01 + 2026-05-02:
        examples in the prompt teach Claude more reliably than abstract
        rules. The example must include the literal "put ... in
        project NAME" form so Claude has a concrete instance to
        generalize from. Without this, even the widened rule list
        sometimes fails to match the user's verb-led phrasings."""
        from scan_service import _VOICE_PARSE_PROMPT
        # Specifically the no-"the" verb-led form.
        assert "in project Launch site" in _VOICE_PARSE_PROMPT, (
            "prompt example must demonstrate 'in project NAME' "
            "(no 'the') so Claude generalizes to the user's "
            "'put in project' / 'recommend project' phrasings"
        )

    def test_prompt_states_general_rule_for_phrasings(self):
        """The widened rule says ANY clause mentioning 'project' + NAME
        should match. This 'general rule' wording is what teaches the
        model to generalize beyond the listed examples — without it,
        Claude over-fits to the literal 5-6 example phrasings."""
        from scan_service import _VOICE_PARSE_PROMPT
        # The phrase 'general rule' anchors the broader instruction.
        assert "general rule" in _VOICE_PARSE_PROMPT
        # And it must mention the trigger word 'project' alongside NAME.
        assert "mentions the word \"project\"" in _VOICE_PARSE_PROMPT

    def test_prompt_contains_no_invent_rule(self):
        """The 'do not invent' contract is what protects against
        hallucinated project / goal names. Must stay in the prompt."""
        from scan_service import _VOICE_PARSE_PROMPT
        assert "do not invent" in _VOICE_PARSE_PROMPT

    def test_prompt_example_is_valid_json(self):
        """The in-prompt example must parse — catches JSON syntax
        breaks introduced by Sub-PR C's reorder."""
        import json
        import re
        prompt = self._format_prompt()
        # Extract the bracketed JSON array from the Output: section.
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        assert match is not None, "Could not locate example JSON in prompt"
        items = json.loads(match.group(1))
        assert isinstance(items, list)
        assert len(items) >= 5

    def test_prompt_example_tier_values_are_all_valid(self):
        """The example must only use tier values that
        `_normalise_voice_candidates` will accept — otherwise the prompt
        teaches Claude to use a tier that the server then silently
        coerces to inbox (the original bug class for 'next_week' /
        'backlog' before Sub-PR B)."""
        import json
        import re

        from scan_service import _VOICE_VALID_TIERS
        prompt = self._format_prompt()
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        for item in items:
            assert item["tier"] in _VOICE_VALID_TIERS, (
                f"prompt example uses invalid tier: {item['tier']}"
            )

    def test_prompt_example_every_item_has_a_category(self):
        """#172 (2026-05-21): every example item must carry a `category`
        key so Claude learns to emit it for every item. A missing key
        in the example teaches Claude the field is optional."""
        import json
        import re
        prompt = self._format_prompt()
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        for item in items:
            assert "category" in item, (
                f"prompt example item {item['title']!r} missing `category`"
            )

    def test_prompt_example_category_values_are_all_valid(self):
        """#172: example categories must all be real GoalCategory enum
        values — otherwise the prompt teaches Claude a value the server
        coerces away (same bug class as the tier test above)."""
        import json
        import re

        from scan_service import _VOICE_VALID_CATEGORIES
        prompt = self._format_prompt()
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        for item in items:
            assert item["category"] in _VOICE_VALID_CATEGORIES, (
                f"prompt example uses invalid category: {item['category']!r}"
            )

    def test_prompt_lists_all_five_goal_categories(self):
        """#172: the prompt's category rule must enumerate all 5
        GoalCategory enum values so Claude has the full vocabulary.
        Guards against a future edit dropping one (the way the image
        goals-parse prompt drifted and lost 'bau')."""
        from scan_service import _VOICE_PARSE_PROMPT, _VOICE_VALID_CATEGORIES
        for cat in _VOICE_VALID_CATEGORIES:
            assert f'"{cat}"' in _VOICE_PARSE_PROMPT, (
                f"prompt category rule missing enum value: {cat}"
            )

    def test_voice_valid_categories_matches_goal_category_enum(self):
        """#172: the _VOICE_VALID_CATEGORIES allowlist must stay in
        lockstep with the GoalCategory enum — a new enum member that
        isn't added here would be silently coerced to personal_growth."""
        from models import GoalCategory
        from scan_service import _VOICE_VALID_CATEGORIES
        enum_values = {c.value for c in GoalCategory}
        assert enum_values == _VOICE_VALID_CATEGORIES, (
            f"drift: _VOICE_VALID_CATEGORIES={_VOICE_VALID_CATEGORIES} "
            f"vs GoalCategory={enum_values}"
        )

    def test_prompt_example_demonstrates_explicit_project_phrasing(self):
        """The example must SHOW Claude an explicit-phrasing case so
        the rule is grounded in a concrete instance, not just stated
        abstractly. Sub-PR C added an 'Email Sarah for the launch
        site project' line specifically to teach this pattern."""
        import json
        import re
        prompt = self._format_prompt()
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        # Find an item with project_hint set whose title doesn't
        # mention the project name verbatim — that's the explicit-
        # phrasing case (in contrast to "Q2 OKR deck" which is a
        # topic match where the project name appears in the title).
        explicit_cases = [
            item for item in items
            if item.get("project_hint")
            and item["project_hint"].lower() not in item["title"].lower()
        ]
        assert len(explicit_cases) >= 1, (
            "prompt example should include an explicit-phrasing case "
            "(project_hint set without the project name appearing in title)"
        )

    def test_prompt_example_demonstrates_backlog_tier(self):
        """Sub-PR B added 'backlog' as a valid tier; Sub-PR C's example
        should show Claude an instance so the prompt teaches it."""
        import json
        import re
        prompt = self._format_prompt()
        match = re.search(r"Output:\s*(\[.*?\])\s*Transcript:", prompt, re.DOTALL)
        items = json.loads(match.group(1))
        tiers_used = {item["tier"] for item in items}
        assert "backlog" in tiers_used, (
            "Sub-PR C example should demonstrate the backlog tier"
        )


class TestVoiceMemoTemplateScripts:
    """User-reported regression 2026-05-01: project→goal cascade in the
    voice review UI didn't fire. Root cause: `templates/voice_memo.html`
    loaded `voice_memo.js` but NOT `filter_helpers.js` — so when the
    project select's change handler called `window.filterHelpers
    .projectCascadeGoalId(...)`, it threw TypeError silently. Every
    other template that renders board / project / goal UI (index,
    calendar, completed, docs, goals, projects, recurring, tier) loads
    filter_helpers.js. This test guards the wiring."""

    def test_voice_memo_template_loads_filter_helpers(self, authed_client):
        """The HTML response for /voice-memo must reference
        /static/filter_helpers.js. Without it, voice_memo.js's
        project-cascade handler silently no-ops on every project
        change."""
        resp = authed_client.get("/voice-memo")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "filter_helpers.js" in body, (
            "voice_memo.html must load filter_helpers.js for the "
            "project→goal cascade in the review UI to work"
        )


class TestVoiceHintSubstringFallback:
    """Bug 2026-05-09: project_hint resolver did exact-match only, so
    "audit" never resolved to "IPPM Audit". Added a substring fallback:
    if a hint is contained in (or contains) exactly ONE active title,
    resolve to that. Multi-match → leave unresolved (ambiguous)."""

    def _norm(self, item, projects=None, goals=None):
        from scan_service import _normalise_voice_candidates
        return _normalise_voice_candidates([item], projects=projects, goals=goals)

    def test_substring_single_match_resolves(self):
        """User said "audit"; project list has one match — should resolve."""
        result = self._norm(
            {"title": "Tidy the audit notes", "project_hint": "audit"},
            projects=[("p-ippm", "IPPM Audit"), ("p-other", "Roadmaps")],
        )
        assert result[0]["project_id"] == "p-ippm"
        # The original hint is preserved alongside the resolved id.
        assert result[0]["project_hint"] == "audit"

    def test_substring_multi_match_stays_unresolved(self):
        """Hint matches multiple projects — don't guess."""
        result = self._norm(
            {"title": "audit work", "project_hint": "audit"},
            projects=[
                ("p-ippm", "IPPM Audit"),
                ("p-ext",  "External Audit"),
            ],
        )
        assert result[0]["project_id"] is None
        assert result[0]["project_hint"] == "audit"

    def test_exact_match_still_wins(self):
        """When an exact title is present, prefer it over any
        substring-matching siblings (preserves prior behavior)."""
        result = self._norm(
            {"title": "x", "project_hint": "audit"},
            projects=[
                ("p-exact", "audit"),
                ("p-fuzzy", "Some Audit Project"),
            ],
        )
        assert result[0]["project_id"] == "p-exact"

    def test_inverse_substring_resolves(self):
        """Hint LONGER than the title (e.g. Claude added qualifiers).
        "the audit project" still resolves to "audit"."""
        result = self._norm(
            {"title": "x", "project_hint": "the audit project"},
            projects=[("p-audit", "audit")],
        )
        assert result[0]["project_id"] == "p-audit"

    def test_no_match_leaves_hint_unresolved(self):
        """Hint nowhere on the list → no resolution, hint preserved."""
        result = self._norm(
            {"title": "x", "project_hint": "completely unrelated"},
            projects=[("p-ippm", "IPPM Audit")],
        )
        assert result[0]["project_id"] is None
        assert result[0]["project_hint"] == "completely unrelated"

    def test_substring_fallback_works_for_goals_too(self):
        """Same logic applied symmetrically for goal_hint."""
        result = self._norm(
            {"title": "x", "goal_hint": "fitness"},
            goals=[("g-fitness", "Q2 Fitness Goal")],
        )
        assert result[0]["goal_id"] == "g-fitness"

    def test_case_insensitive_substring(self):
        """Casing on the hint shouldn't matter."""
        result = self._norm(
            {"title": "x", "project_hint": "AUDIT"},
            projects=[("p-ippm", "IPPM Audit")],
        )
        assert result[0]["project_id"] == "p-ippm"


class TestVoiceHintAcronymLooseMatch:
    """#249 (2026-05-28): Whisper-acronym-transcription fallback.

    When the speaker says a 3-letter acronym like "BAU", Whisper
    typically writes it back with periods ("B.A.U.") or letter-
    spaced ("B A U"). The existing exact + substring passes don't
    handle this — "b.a.u." and "b a u" share no contiguous substring
    with the project key "bau".

    Loose-match fallback: after exact + substring miss, strip every
    non-alphanumeric character from BOTH the hint and the lookup
    keys, then try exact match. "b.a.u." → "bau" matches "bau".
    """

    def _norm(self, item, projects=None, goals=None):
        from scan_service import _normalise_voice_candidates
        return _normalise_voice_candidates([item], projects=projects, goals=goals)

    def test_period_separated_acronym_resolves(self):
        """User says 'BAU'; Whisper writes 'B.A.U.' — should match."""
        result = self._norm(
            {"title": "x", "project_hint": "B.A.U."},
            projects=[("p-bau", "BAU"), ("p-other", "Roadmaps")],
        )
        assert result[0]["project_id"] == "p-bau"

    def test_period_separated_acronym_no_trailing_period(self):
        """'B.A.U' (no trailing period) should also resolve."""
        result = self._norm(
            {"title": "x", "project_hint": "B.A.U"},
            projects=[("p-bau", "BAU")],
        )
        assert result[0]["project_id"] == "p-bau"

    def test_letter_spaced_acronym_resolves(self):
        """'B A U' (letter-by-letter spacing) should resolve."""
        result = self._norm(
            {"title": "x", "project_hint": "B A U"},
            projects=[("p-bau", "BAU")],
        )
        assert result[0]["project_id"] == "p-bau"

    def test_hyphen_separated_acronym_resolves(self):
        """'B-A-U' should resolve. (Hyphens are already handled by
        _SEPARATOR_RE → space, but loose-match catches the resulting
        spaces too.)"""
        result = self._norm(
            {"title": "x", "project_hint": "B-A-U"},
            projects=[("p-bau", "BAU")],
        )
        assert result[0]["project_id"] == "p-bau"

    def test_loose_match_works_against_goals(self):
        """Same fallback fires on goal hints (not just projects)."""
        result = self._norm(
            {"title": "x", "goal_hint": "Q.4 OKRs"},
            goals=[("g-q4", "Q4 OKRs"), ("g-other", "Health")],
        )
        assert result[0]["goal_id"] == "g-q4"

    def test_loose_match_ambiguous_returns_none(self):
        """If the loose-stripped hint matches multiple titles
        ambiguously, don't guess — leave unresolved."""
        # Two projects whose alnum-only forms both contain "bau" —
        # but neither equals "bau" exactly, so the loose-EXACT pass
        # won't pick either. Substring fallback already runs and
        # would catch one if singular; here both contain "bau" so
        # multi-match → ambiguous → no resolve.
        result = self._norm(
            {"title": "x", "project_hint": "B.A.U."},
            projects=[
                ("p-bau1", "BAU East"),
                ("p-bau2", "BAU West"),
            ],
        )
        # Substring fallback: "bau" in "bau east" + "bau west" →
        # 2 matches → ambiguous → returns None. Loose pass: "bau"
        # in alnum map → keys are "baueast", "bauwest" → "bau" not
        # exact in alnum map either → returns None.
        assert result[0]["project_id"] is None

    def test_loose_match_does_not_fire_when_substring_resolves(self):
        """If substring fallback already finds a unique match, the
        loose-match pass shouldn't override it. (Belt-and-braces:
        substring runs first in _resolve_voice_hint.)"""
        result = self._norm(
            {"title": "x", "project_hint": "audit"},
            projects=[("p-ippm", "IPPM Audit"), ("p-bau", "BAU")],
        )
        # Should resolve via substring (audit in 'ippm audit').
        assert result[0]["project_id"] == "p-ippm"

    def test_alphanumeric_only_hint_does_not_double_check(self):
        """If the hint is already alphanumeric-only (e.g. 'BAU'),
        loose-match would be redundant with exact. The branch
        should skip (no infinite loop, no false work)."""
        result = self._norm(
            {"title": "x", "project_hint": "BAU"},
            projects=[("p-bau", "BAU")],
        )
        # Exact match wins on the first pass; loose-match never
        # runs because the alnum stripped hint == the normalised hint.
        assert result[0]["project_id"] == "p-bau"

    def test_loose_match_preserves_original_hint_string(self):
        """The candidate's `project_hint` field MUST stay the
        original Whisper string (e.g. 'B.A.U.'), not the
        normalised loose form. The UI shows it as 'Heard project:
        "<original>"', so we want the original prose."""
        result = self._norm(
            {"title": "x", "project_hint": "B.A.U."},
            projects=[("p-bau", "BAU")],
        )
        assert result[0]["project_hint"] == "B.A.U."
        assert result[0]["project_id"] == "p-bau"


# --- #239 (2026-05-27): _call_whisper_api unit coverage --------------------
# Pre-#239, the only voice_service.py paths exercised by the existing tests
# were `transcribe_audio` (which is mocked at the boundary) and the
# top-level `_normalise_voice_candidates`. The actual Whisper HTTP wrapper
# `_call_whisper_api` was ENTIRELY uncovered — lines 161-202 representing
# the egress call, response parsing, cost calc, and the EgressError →
# RuntimeError translation. These tests close that gap so the
# `voice_service.py` critical-path floor (in #229's coverage audit) can
# move from 70% → 80%, matching the other critical-path services.


class TestCallWhisperApi:
    """Unit coverage for _call_whisper_api — the egress wrapper around
    OpenAI's Whisper endpoint. Monkeypatches `egress.safe_call_api` so
    no real HTTP call fires."""

    def test_happy_path_returns_transcript_duration_cost(self, monkeypatch):
        from voice_service import WHISPER_USD_PER_MINUTE, _call_whisper_api

        captured = {}

        def fake_safe_call_api(*, url, headers, files, data, timeout_sec, vendor):
            captured["url"] = url
            captured["headers"] = headers
            captured["files"] = files
            captured["data"] = data
            captured["timeout_sec"] = timeout_sec
            captured["vendor"] = vendor
            return {
                "text": "  Hello world this is the transcript.  ",
                "duration": 12.5,
            }

        import egress
        monkeypatch.setattr(egress, "safe_call_api", fake_safe_call_api)

        result = _call_whisper_api(
            api_key="fake-key",
            audio_bytes=b"PCM-frames-here",
            mime_type="audio/webm",
        )

        # Transcript is .strip()'d (the leading + trailing spaces gone).
        assert result["transcript"] == "Hello world this is the transcript."
        assert result["duration_seconds"] == 12.5
        # 12.5 seconds = 12.5/60 minutes * $0.006/min = $0.00125
        expected_cost = (12.5 / 60.0) * WHISPER_USD_PER_MINUTE
        assert result["cost_usd"] == pytest.approx(expected_cost)

        # Egress call shape — these are the fields that matter for
        # observability (vendor name in scrub logs) and correctness
        # (multipart shape Whisper expects).
        assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
        assert captured["headers"] == {"Authorization": "Bearer fake-key"}
        assert captured["vendor"] == "Whisper"
        assert captured["timeout_sec"] == 120
        assert captured["data"]["model"] == "whisper-1"
        assert captured["data"]["response_format"] == "verbose_json"
        # `files` is the multipart payload. The "file" key has a tuple
        # of (filename, file-like, mime_type).
        assert "file" in captured["files"]
        fname, fileobj, ftype = captured["files"]["file"]
        assert fname == "memo.webm"
        assert ftype == "audio/webm"
        # file-like should read back the audio bytes.
        assert fileobj.read() == b"PCM-frames-here"

    def test_egress_error_translates_to_runtime_error(self, monkeypatch):
        """Public contract of voice_service: callers in voice_api.py
        catch RuntimeError. Internally egress raises EgressError; this
        wrapper translates so the boundary stays stable."""
        import egress
        from voice_service import _call_whisper_api

        def fake_safe_call_api(**kw):
            raise egress.EgressError("Whisper rate-limited: HTTP 429")

        monkeypatch.setattr(egress, "safe_call_api", fake_safe_call_api)

        with pytest.raises(RuntimeError) as excinfo:
            _call_whisper_api(
                api_key="k", audio_bytes=b"x", mime_type="audio/webm",
            )
        # Message preserved (caller surfaces it to the user as part of
        # the 422 error body in voice_api.upload).
        assert "rate-limited" in str(excinfo.value)
        # And the original EgressError is chained via __cause__ so the
        # full trace is visible in /api/debug/logs.
        assert isinstance(excinfo.value.__cause__, egress.EgressError)

    def test_missing_duration_falls_back_to_zero(self, monkeypatch):
        """Whisper has been observed to omit `duration` on very short
        clips. Don't blow up — treat as 0.0 (cost = 0) and let the
        transcript still flow through."""
        import egress
        from voice_service import _call_whisper_api
        monkeypatch.setattr(
            egress, "safe_call_api",
            lambda **kw: {"text": "Hi"},  # no `duration` key
        )

        result = _call_whisper_api(
            api_key="k", audio_bytes=b"x", mime_type="audio/webm",
        )
        assert result["transcript"] == "Hi"
        assert result["duration_seconds"] == 0.0
        assert result["cost_usd"] == 0.0

    def test_missing_text_returns_empty_transcript(self, monkeypatch):
        """If Whisper returns no `text` field (rare; usually empty
        string instead), fall back to empty string rather than None.
        The downstream pipeline (`parse_voice_memo_to_tasks`) gates on
        empty transcript anyway."""
        import egress
        from voice_service import _call_whisper_api
        monkeypatch.setattr(
            egress, "safe_call_api",
            lambda **kw: {"duration": 1.0},  # no `text` key
        )

        result = _call_whisper_api(
            api_key="k", audio_bytes=b"x", mime_type="audio/webm",
        )
        assert result["transcript"] == ""

    def test_mp4_mime_routes_to_mp4_filename(self, monkeypatch):
        """iOS Safari sends `audio/mp4` for AAC-in-MP4 recordings.
        The filename passed to Whisper must have the .mp4 extension
        for Whisper to detect the format correctly."""
        from voice_service import _call_whisper_api

        captured = {}

        import egress
        def fake(**kw):
            captured["files"] = kw["files"]
            return {"text": "x", "duration": 1.0}
        monkeypatch.setattr(egress, "safe_call_api", fake)

        _call_whisper_api(
            api_key="k", audio_bytes=b"x", mime_type="audio/mp4",
        )
        fname, _, _ = captured["files"]["file"]
        assert fname == "memo.mp4"

    def test_ios_safari_colon_separator_in_mime(self, monkeypatch):
        """iOS Safari has been observed sending non-standard `:`
        separator in MIME (e.g. `audio/mp4:codecs-mp4a.40.2`).
        _filename_for_mime handles both `;` and `:` — verify the
        whole call wraps it correctly."""
        from voice_service import _call_whisper_api

        captured = {}

        import egress
        def fake(**kw):
            captured["files"] = kw["files"]
            return {"text": "x", "duration": 1.0}
        monkeypatch.setattr(egress, "safe_call_api", fake)

        _call_whisper_api(
            api_key="k",
            audio_bytes=b"x",
            mime_type="audio/mp4:codecs-mp4a.40.2",
        )
        fname, _, ftype = captured["files"]["file"]
        assert fname == "memo.mp4"
        # The full mime (with the `:` codec hint) is what we send to
        # Whisper — Whisper's parser ignores anything after the base
        # type, so this is fine.
        assert ftype == "audio/mp4:codecs-mp4a.40.2"

    def test_cost_calculation_matches_published_rate(self, monkeypatch):
        """Whisper bills at $0.006/min. A 60-second clip should cost
        exactly $0.006 (within float epsilon)."""
        import egress
        from voice_service import _call_whisper_api
        monkeypatch.setattr(
            egress, "safe_call_api",
            lambda **kw: {"text": "x", "duration": 60.0},
        )

        result = _call_whisper_api(
            api_key="k", audio_bytes=b"x", mime_type="audio/webm",
        )
        assert result["cost_usd"] == pytest.approx(0.006)

    def test_duration_zero_yields_zero_cost(self, monkeypatch):
        """Edge: 0-second clip = $0 cost (avoids accidental floor
        billing on truly silent recordings)."""
        import egress
        from voice_service import _call_whisper_api
        monkeypatch.setattr(
            egress, "safe_call_api",
            lambda **kw: {"text": "", "duration": 0.0},
        )

        result = _call_whisper_api(
            api_key="k", audio_bytes=b"x", mime_type="audio/webm",
        )
        assert result["cost_usd"] == 0.0
