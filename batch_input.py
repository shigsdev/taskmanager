"""Shape checks for the rows a batch confirm endpoint receives (#484).

The import / scan / voice review pages send a list of ``candidates`` rows.
The pages always send well-formed rows, but the API is reachable by a
hand-built request, an older client or a Shortcut too, and the creators
used to trust each row: a row that isn't an object, or a number where text
belongs (``.strip()`` on it), failed the WHOLE batch with a 500, and
``included: "false"`` counted as included.

``clean_rows`` runs first in each confirm endpoint: a row that isn't an
object is skipped (and counted, so the answer can say so); a text field
holding a number becomes its digits; any other shape in a text field is
dropped as if missing; ``included`` becomes a real boolean. Pure — no app
imports.
"""
from __future__ import annotations

# Fields the creators read as text (``(row.get(k) or "").strip()`` and
# friends) across import_service / scan_service / voice_api.
TEXT_FIELDS = (
    "title", "name", "type", "tier", "due_date", "project_id", "goal_id",
    "linked_goal", "linked_project", "notes", "url", "category", "priority",
    "status", "actions", "target_quarter", "color",
)

_FALSE_WORDS = {"false", "no", "0", ""}


def row_included(row: dict) -> bool:
    """True unless the row says to leave it out.

    Missing / ``true`` → included. ``false``, ``0`` and the strings
    ``"false"``, ``"no"``, ``"0"``, ``""`` (any case, any spaces) → left out.
    """
    value = row.get("included", True)
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_WORDS
    return bool(value)


def clean_row(row: object) -> dict | None:
    """A copy of ``row`` the creators can read safely, or None if it isn't one."""
    if not isinstance(row, dict):
        return None
    out = dict(row)
    for key in TEXT_FIELDS:
        if key not in out or out[key] is None or isinstance(out[key], str):
            continue
        value = out[key]
        # bool is an int subclass — True is not a title.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = str(value)
        else:
            del out[key]
    out["included"] = row_included(row)
    return out


def clean_rows(candidates: list) -> tuple[list[dict], int]:
    """(the readable rows, cleaned; how many were skipped)."""
    rows: list[dict] = []
    skipped = 0
    for candidate in candidates:
        row = clean_row(candidate)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return rows, skipped


def skipped_warning(skipped: int) -> str | None:
    """The sentence a confirm answer adds when it skipped rows, or None."""
    if skipped <= 0:
        return None
    if skipped == 1:
        return "1 row couldn't be read and was skipped."
    return f"{skipped} rows couldn't be read and were skipped."


def join_warnings(*parts: str | None) -> str | None:
    """The non-empty sentences joined with a space, or None if there are none."""
    text = " ".join(p for p in parts if p)
    return text or None
