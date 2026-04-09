"""Shared utilities used across service and API layers.

Centralizes common helpers to avoid duplication (per CLAUDE.md).
"""
from __future__ import annotations

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
