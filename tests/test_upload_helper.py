"""Direct unit tests for utils.validate_upload — the shared multipart
upload validator used by voice_api.py and scan_api.py.

Behavior is exercised transitively by the route-level tests in
test_voice_memo.py and test_scan_api.py. This file covers the helper
in isolation so a future caller (file-import, image attach, etc.)
can rely on the documented contract without depending on the
specifics of the route that drives the test.

Cross-reference ADR-025 for the boundary design.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

from werkzeug.datastructures import FileStorage

from utils import _normalize_mime, validate_upload


def _make_request(file: FileStorage | None, field: str = "audio"):
    """Build a minimal stand-in for `flask.request` — just `request.files[field_name]`
    is what validate_upload touches. Avoids spinning up a full Flask app
    context for a pure-function test."""
    files = {field: file} if file is not None else {}
    return SimpleNamespace(files=files)


def _file(content: bytes, filename: str, content_type: str) -> FileStorage:
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )


# --- _normalize_mime --------------------------------------------------------


class TestNormalizeMime:
    """The browser-quirk surface: every weird Content-Type header shape
    we've seen in the wild gets canonicalized to `type/subtype`."""

    def test_strips_rfc_7231_codec_params(self):
        assert _normalize_mime("audio/mp4;codecs=mp4a.40.2") == "audio/mp4"

    def test_strips_ios_safari_colon_separator(self):
        # Non-standard but observed in iOS Safari builds — see the docstring
        assert _normalize_mime("audio/mp4:codecs-mp4a.40.2") == "audio/mp4"

    def test_passes_through_clean_mime(self):
        assert _normalize_mime("audio/webm") == "audio/webm"
        assert _normalize_mime("image/png") == "image/png"

    def test_lowercases(self):
        assert _normalize_mime("Audio/MP4") == "audio/mp4"

    def test_strips_surrounding_whitespace(self):
        assert _normalize_mime("  audio/webm  ") == "audio/webm"

    def test_empty_input_returns_empty(self):
        assert _normalize_mime("") == ""

    def test_charset_param_stripped(self):
        # Doesn't apply to our uploads (charset is a text/* concept) but
        # the regex is generic — verify it handles charset shape too.
        assert _normalize_mime("text/html;charset=utf-8") == "text/html"


# --- validate_upload: missing-field path ------------------------------------


class TestValidateUploadMissingField:

    def test_missing_field_returns_400(self):
        req = _make_request(None)
        body, ctype, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=1024,
        )
        assert body is None and ctype is None
        assert err is not None
        response, status = err
        assert status == 400
        assert "audio" in response["error"].lower()

    def test_empty_filename_returns_400(self):
        # FileStorage with filename="" — Flask hands us this when the user
        # submits a multipart form without selecting a file
        req = _make_request(_file(b"data", filename="", content_type="audio/webm"))
        body, ctype, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=1024,
        )
        assert body is None
        response, status = err
        assert status == 400
        assert "filename" in response["error"].lower()


# --- validate_upload: MIME enforcement --------------------------------------


class TestValidateUploadMimeEnforcement:

    def test_disallowed_mime_returns_422_with_allowed_list(self):
        req = _make_request(
            _file(b"x", "evil.exe", "application/octet-stream"),
        )
        body, ctype, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=1024,
        )
        assert body is None
        response, status = err
        # 422 (Unprocessable Entity) — the request is well-formed but
        # we won't process this content type
        assert status == 422
        assert "Unsupported" in response["error"]
        # Allowed list surfaced so the client can self-correct
        assert response["allowed"] == ["audio/webm"]
        # The actual offending raw type is reported (un-normalized) so
        # the user sees what they actually sent
        assert "application/octet-stream" in response["error"]

    def test_allowed_mime_match_after_codec_strip(self):
        # iOS Safari sends audio/mp4 WITH a ;codecs=... suffix; the
        # allowed-set never includes the codec, so normalization is the
        # only thing that lets this through.
        req = _make_request(
            _file(b"audio bytes", "voice.m4a", "audio/mp4;codecs=mp4a.40.2"),
        )
        body, ctype, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/mp4"}, max_bytes=1024,
        )
        assert err is None
        assert body == b"audio bytes"
        # Caller gets the RAW content_type, NOT the normalized one — Whisper
        # and other downstream callers may need the codec parameter
        assert ctype == "audio/mp4;codecs=mp4a.40.2"

    def test_missing_content_type_treated_as_disallowed(self):
        # Some clients omit Content-Type entirely; FileStorage exposes None
        req = _make_request(
            _file(b"data", "voice.webm", content_type=None),  # type: ignore[arg-type]
        )
        body, _, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=1024,
        )
        assert body is None
        response, status = err
        assert status == 422


# --- validate_upload: size enforcement --------------------------------------


class TestValidateUploadSize:

    def test_oversize_returns_413(self):
        # 100 bytes file vs 50-byte cap
        req = _make_request(
            _file(b"X" * 100, "big.webm", "audio/webm"),
        )
        body, _, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=50,
        )
        assert body is None
        response, status = err
        # 413 Payload Too Large — the standard for body-size rejection
        assert status == 413
        assert "too large" in response["error"].lower()

    def test_oversize_message_reports_mb(self):
        # 5 MB file, 1 MB cap — message should say "5 MB; max 1 MB"
        req = _make_request(
            _file(b"X" * (5 * 1024 * 1024), "big.webm", "audio/webm"),
        )
        body, _, err = validate_upload(
            req,
            field_name="audio",
            allowed_mime={"audio/webm"},
            max_bytes=1 * 1024 * 1024,
        )
        response, _ = err
        assert "5 MB" in response["error"]
        assert "1 MB" in response["error"]

    def test_at_exact_cap_passes(self):
        # Boundary case — 100 bytes exactly = max_bytes 100; should pass
        req = _make_request(
            _file(b"X" * 100, "ok.webm", "audio/webm"),
        )
        body, _, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=100,
        )
        assert err is None
        assert body == b"X" * 100


# --- validate_upload: empty-file guard --------------------------------------


class TestValidateUploadEmpty:

    def test_empty_file_returns_400(self):
        # File present, MIME OK, fits in size — but body is 0 bytes.
        # This catches the "user pressed record but never spoke" case
        # before we burn a Whisper call on it.
        req = _make_request(_file(b"", "silence.webm", "audio/webm"))
        body, _, err = validate_upload(
            req, field_name="audio", allowed_mime={"audio/webm"}, max_bytes=1024,
        )
        assert body is None
        response, status = err
        assert status == 400
        assert "Empty" in response["error"]


# --- validate_upload: success-path return shape -----------------------------


class TestValidateUploadSuccessShape:

    def test_returns_bytes_and_raw_content_type(self):
        req = _make_request(
            _file(b"hello bytes", "img.png", "image/png"),
            field="image",
        )
        body, ctype, err = validate_upload(
            req,
            field_name="image",
            allowed_mime={"image/png", "image/jpeg"},
            max_bytes=1024,
        )
        assert err is None
        assert body == b"hello bytes"
        assert ctype == "image/png"

    def test_field_name_appears_in_missing_error(self):
        # Same helper used for both audio and image — make sure the
        # error message reflects the actual field name the caller passed
        req = _make_request(None)
        _, _, err = validate_upload(
            req, field_name="image", allowed_mime={"image/png"}, max_bytes=1024,
        )
        response, _ = err
        assert "image" in response["error"].lower()
