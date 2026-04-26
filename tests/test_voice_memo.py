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
        result = _normalise_voice_candidates([
            {"title": "x", "tier": "next_week"},  # valid enum but not in _VOICE_VALID_TIERS
            {"title": "y", "tier": "bogus"},
        ])
        assert result[0]["tier"] == "inbox"
        assert result[1]["tier"] == "inbox"

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
        when no hints are supplied."""
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
        }

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
