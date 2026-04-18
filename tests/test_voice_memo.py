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
        _bypass_auth(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

        with (
            patch(
                "voice_api.transcribe_audio",
                return_value={
                    "transcript": "Buy milk. Call the dentist.",
                    "duration_seconds": 12.5,
                    "cost_usd": 0.00125,
                },
            ),
            patch(
                "voice_api.parse_tasks_from_text",
                return_value=["Buy milk", "Call the dentist"],
            ),
        ):
            resp = client.post(
                "/api/voice-memo",
                data={"audio": (io.BytesIO(b"fake audio bytes"), "memo.webm", "audio/webm")},
                content_type="multipart/form-data",
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["transcript"] == "Buy milk. Call the dentist."
        assert body["duration_seconds"] == 12.5
        assert body["cost_usd"] == pytest.approx(0.00125)
        titles = [c["title"] for c in body["candidates"]]
        assert titles == ["Buy milk", "Call the dentist"]
        # All candidates default to "work" type and included=True
        assert all(c["type"] == "work" for c in body["candidates"])
        assert all(c["included"] is True for c in body["candidates"])

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
                "voice_api.parse_tasks_from_text",
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
