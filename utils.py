"""Shared utilities used across service and API layers.

Centralizes common helpers to avoid duplication (per CLAUDE.md).
"""
from __future__ import annotations

from flask import jsonify


class ValidationError(Exception):
    """Raised when user input fails validation. Routes map this to HTTP 422."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


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
