"""Shared utilities used across service and API layers.

Centralizes common helpers to avoid duplication (per CLAUDE.md).
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from flask import jsonify


class ValidationError(Exception):
    """Raised when user input fails validation. Routes map this to HTTP 422."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


# --- API-layer helpers -------------------------------------------------------


def enum_or_400(enum_cls, value):
    """Parse a query-string value into an enum member, or return a 400 response.

    Returns:
        (enum_member, None) on success, or (None, response_tuple) on failure.
    """
    if value is None:
        return None, None
    try:
        return enum_cls(value), None
    except ValueError:
        return None, (jsonify({"error": f"invalid filter value: {value}"}), 400)


# --- Service-layer coercion helpers ------------------------------------------


def parse_enum(enum_cls, value: Any, field: str):
    """Parse a value into an enum member, or raise ValidationError."""
    if value is None:
        return None
    try:
        return enum_cls(str(value))
    except ValueError as e:
        raise ValidationError(f"invalid {field}: {value!r}", field) from e


def parse_uuid(value: Any, field: str) -> uuid.UUID | None:
    """Parse a value into a UUID, or raise ValidationError."""
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise ValidationError(f"invalid {field}", field) from e


def parse_int(value: Any, field: str, *, allow_none: bool = False) -> int | None:
    """Parse a value into an int, or raise ValidationError.

    Args:
        allow_none: If True, return None when value is None.
                    If False (default), None raises ValidationError.
    """
    if value is None:
        if allow_none:
            return None
        raise ValidationError(f"{field} is required", field)
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValidationError(f"invalid {field}: must be an integer", field) from e


# --- File upload validation --------------------------------------------------


def validate_upload(
    request,
    *,
    field_name: str,
    allowed_mime: frozenset[str] | set[str],
    max_bytes: int,
):
    """Common upload validation for multipart/form-data file fields.

    Used by ``voice_api`` and ``scan_api`` (and any future upload route)
    to enforce the same checks consistently — see CLAUDE.md Cascade
    check, "A new file-upload endpoint" row.

    Performs in order:
      1. Field is present in ``request.files``
      2. Filename is non-empty
      3. Content-Type matches an allowed MIME (after stripping codec
         parameters; iOS Safari sends ``audio/mp4;codecs=mp4a.40.2``)
      4. Body fits inside ``max_bytes``
      5. Body is non-empty

    Args:
        request: Flask ``flask.request`` proxy (passed in for testability).
        field_name: e.g. ``"audio"`` or ``"image"``.
        allowed_mime: Set of base MIME types (no codec params); incoming
            content type is normalized via :func:`_normalize_mime` before
            matching.
        max_bytes: Hard cap on body size in bytes.

    Returns:
        ``(audio_bytes, content_type, None)`` on success — caller uses
        the bytes and the (raw) content_type for downstream calls
        (Whisper looks at filename extension, so callers may want to
        derive an extension from the normalized type).

        ``(None, None, (response_dict, status_code))`` on failure — the
        caller does ``return jsonify(response_dict), status_code``.

    The tuple-of-error-or-success pattern matches the existing
    ``enum_or_400`` helper above, keeping route code straight-line.
    """
    if field_name not in request.files:
        return None, None, ({"error": f"No {field_name} file provided"}, 400)

    file = request.files[field_name]
    if not file.filename:
        return None, None, ({"error": "No filename"}, 400)

    raw_content_type = file.content_type or ""
    base_type = _normalize_mime(raw_content_type)
    if base_type not in allowed_mime:
        return None, None, (
            {
                "error": f"Unsupported {field_name} type: {raw_content_type}",
                "allowed": sorted(allowed_mime),
            },
            422,
        )

    body = file.read()
    if len(body) > max_bytes:
        mb = max_bytes // 1024 // 1024
        actual_mb = len(body) // 1024 // 1024
        return None, None, (
            {"error": f"{field_name.capitalize()} file too large ({actual_mb} MB; max {mb} MB)"},
            413,
        )

    if not body:
        return None, None, ({"error": "Empty file"}, 400)

    return body, raw_content_type, None


def _normalize_mime(content_type: str) -> str:
    """Strip parameters from an HTTP Content-Type header.

    Browsers append codec / charset / boundary parameters that vary by
    device. We match against base ``type/subtype`` only.

    Accepts both ``;`` (RFC 7231 standard) and ``:`` (non-standard but
    observed in iOS Safari versions for audio/mp4) as separators.

      audio/mp4;codecs=mp4a.40.2  -> audio/mp4
      audio/mp4:codecs-mp4a.40.2  -> audio/mp4
      audio/webm                  -> audio/webm
      ""                          -> ""
    """
    if not content_type:
        return ""
    return re.split(r"[;:]", content_type, maxsplit=1)[0].strip().lower()
