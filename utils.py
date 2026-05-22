"""Shared utilities used across service and API layers.

Centralizes common helpers to avoid duplication (per CLAUDE.md).
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime
from functools import wraps
from typing import Any

from flask import g, jsonify, request


def local_today_date() -> date:
    """Return "today" in the user's configured timezone.

    PR63 audit fix #128: Railway runs UTC, but "today" from the user's
    POV follows ``DIGEST_TZ`` (default America/New_York). Using server
    UTC would make late-evening (8pm+ ET) HTTP requests resolve "today"
    as tomorrow's date, drifting recurring spawn previews, the review
    queue stale-cutoff, and the ad-hoc digest preview. Same TZ
    convention as the Tomorrow auto-roll cron (#27).

    Originally lived as a private ``_local_today_date`` in task_service;
    extracted here so the recurring / review / digest services can
    share it without an inter-service circular import. task_service
    still re-exports the old name as a thin alias for callers that
    imported it directly.
    """
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("DIGEST_TZ", "America/New_York")
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001
        # ZoneInfo / tzdata unavailable → fall back to server local date.
        # Not ideal on Railway-UTC, but better than crashing.
        return date.today()


def local_date_from_dt(dt: datetime | None) -> date | None:
    """Return the ``DIGEST_TZ`` date for a tz-aware datetime.

    Audit fix #178 (2026-05-20): ``dt.date()`` returns the UTC date when
    ``dt`` is stored as UTC by SQLAlchemy (default for
    ``db.DateTime(timezone=True)`` on Postgres). Same drift class as
    ``date.today()`` — at 11pm ET, ``dt.date()`` returns next day, which
    breaks any "what local date did this happen on" calculation
    (triage staleness, calendar bucketing, etc.).

    Mirrors the inline ZoneInfo conversion already used in
    ``recurring_service.spawn_today_tasks`` (~line 443-459) — extracted
    here so both call sites share one helper.

    Returns ``None`` when ``dt`` is ``None``.
    """
    if dt is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("DIGEST_TZ", "America/New_York")
        # Tz-naive timestamps (shouldn't happen with timezone=True columns
        # but defend anyway) are assumed UTC before conversion.
        if dt.tzinfo is None:
            from datetime import UTC
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001
        # ZoneInfo / tzdata unavailable → fall back to server local date.
        return dt.date()


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


def validate_json_body(fn):
    """Decorator: require a JSON *object* request body, stash it on g.

    Wraps a route so it can assume the request carried a JSON object.
    On a missing / non-object body it short-circuits with
    ``{"error": "JSON body required"}, 400`` — the standard shape the
    28 strict routes previously open-coded. The route reads the parsed
    body via ``flask.g.json_body``.

    #196. Use ONLY on routes that genuinely require a body. Routes that
    accept an optional/empty body (``request.get_json(silent=True) or
    {}``) must NOT use this.
    """

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON body required"}), 400
        g.json_body = data
        return fn(*args, **kwargs)

    return _wrapped


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
    max_bytes: int,
    allowed_mime: frozenset[str] | set[str] | None = None,
    allowed_extensions: frozenset[str] | set[str] | None = None,
):
    """Common upload validation for multipart/form-data file fields.

    Used by ``voice_api``, ``scan_api``, ``import_api`` (and any future
    upload route) to enforce the same checks consistently — see
    CLAUDE.md Cascade check, "A new file-upload endpoint" row.

    Performs in order:
      1. Field is present in ``request.files``
      2. Filename is non-empty
      3. File TYPE matches — by Content-Type MIME (``allowed_mime``) OR
         by filename extension (``allowed_extensions``); see below
      4. Body fits inside ``max_bytes``
      5. Body is non-empty

    Type validation has two modes — pass exactly one:

    * ``allowed_mime`` — match the Content-Type header (after stripping
      codec params; iOS Safari sends ``audio/mp4;codecs=mp4a.40.2``).
      Right for media uploads (audio, image) where the browser sets a
      reliable Content-Type.
    * ``allowed_extensions`` — match the filename extension (#194).
      Right for document imports (``.docx`` / ``.xlsx`` / ``.md`` /
      ``.txt``) where the browser's Content-Type is unreliable.

    Args:
        request: Flask ``flask.request`` proxy (passed in for testability).
        field_name: e.g. ``"audio"``, ``"image"``, ``"file"``.
        max_bytes: Hard cap on body size in bytes.
        allowed_mime: Set of base MIME types (no codec params); incoming
            content type is normalized via :func:`_normalize_mime` before
            matching.
        allowed_extensions: Set of lowercased file extensions including
            the leading dot, e.g. ``{".xlsx", ".docx"}``.

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
    if allowed_mime is None and allowed_extensions is None:
        raise ValueError(
            "validate_upload: pass allowed_mime or allowed_extensions"
        )

    if field_name not in request.files:
        return None, None, ({"error": f"No {field_name} provided"}, 400)

    file = request.files[field_name]
    if not file.filename:
        return None, None, ({"error": "No filename"}, 400)

    raw_content_type = file.content_type or ""
    if allowed_extensions is not None:
        # Extension mode (#194) — document imports. The browser's
        # Content-Type for .md/.txt/.docx/.xlsx is unreliable, so match
        # the filename extension instead.
        name_lc = file.filename.lower()
        if not any(name_lc.endswith(ext) for ext in allowed_extensions):
            return None, None, (
                {
                    "error": f"Unsupported {field_name} type: {file.filename}",
                    "allowed": sorted(allowed_extensions),
                },
                422,
            )
    else:
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
            {"error": f"{field_name.capitalize()} too large ({actual_mb} MB; max {mb} MB)"},
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
