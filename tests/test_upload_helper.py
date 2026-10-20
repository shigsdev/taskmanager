"""Direct unit tests for utils.validate_upload — the shared multipart
upload validator (ADR-025).

Callers: voice_api.py and reflection_api.py (audio) and scan_api.py
(image) use MIME mode; import_api.py (Excel / .docx / transcript) and
reflection_api.py's context documents use extension mode (#194),
because browsers send unreliable Content-Types for documents. The
route tests exercise each caller; this file pins the helper's own
contract for both modes.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
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


# --- validate_upload: extension mode (#194) ---------------------------------


class TestValidateUploadExtensionMode:
    """Document imports match the filename, not the browser's
    Content-Type — a .docx often arrives as application/octet-stream."""

    DOCS = frozenset({".xlsx", ".docx"})

    def _check(self, filename, content_type="application/octet-stream",
               content=b"PK\x03\x04 zip bytes"):
        req = _make_request(_file(content, filename, content_type), field="file")
        return validate_upload(
            req, field_name="file", allowed_extensions=self.DOCS, max_bytes=1024,
        )

    def test_matching_extension_passes_whatever_the_content_type(self):
        body, ctype, err = self._check("plan.xlsx", "application/octet-stream")
        assert err is None
        assert body == b"PK\x03\x04 zip bytes"
        # The raw type still comes back for the caller.
        assert ctype == "application/octet-stream"

    def test_missing_content_type_is_fine_in_extension_mode(self):
        _, _, err = self._check("notes.docx", content_type=None)  # type: ignore[arg-type]
        assert err is None

    def test_extension_match_ignores_case(self):
        _, _, err = self._check("PLAN.XLSX")
        assert err is None

    @pytest.mark.parametrize("filename", [
        "plan.csv", "plan.xlsx.exe", "xlsx", "plan.xls",
    ])
    def test_other_extensions_return_422_with_sorted_allowed_list(self, filename):
        body, _, err = self._check(filename)
        assert body is None
        response, status = err
        assert status == 422
        # The filename, not the Content-Type, is what the user is told.
        assert response["error"] == f"Unsupported file type: {filename}"
        assert response["allowed"] == [".docx", ".xlsx"]

    def test_size_and_empty_guards_still_apply(self):
        req = _make_request(_file(b"X" * 2048, "big.xlsx", ""), field="file")
        _, _, err = validate_upload(
            req, field_name="file", allowed_extensions=self.DOCS, max_bytes=1024,
        )
        assert err[1] == 413
        _, _, err = self._check("empty.docx", content=b"")
        assert err == ({"error": "Empty file"}, 400)


class TestValidateUploadNeedsAMode:

    def test_both_modes_is_a_programming_error(self):
        """#511: the docstring says pass exactly one; extension mode used to
        win silently and the MIME list was ignored."""
        req = _make_request(_file(b"x", "a.xlsx", "application/octet-stream"))
        with pytest.raises(ValueError, match="not both"):
            validate_upload(req, field_name="audio", max_bytes=1024,
                            allowed_mime={"audio/webm"}, allowed_extensions={".xlsx"})

    def test_neither_mode_is_a_programming_error(self):
        """A caller that names no type rule must fail loudly at once,
        never accept every file."""
        req = _make_request(_file(b"x", "a.bin", "application/octet-stream"))
        with pytest.raises(ValueError, match="allowed_mime or allowed_extensions"):
            validate_upload(req, field_name="audio", max_bytes=1024)
