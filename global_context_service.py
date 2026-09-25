"""Reference documents attached to EVERY reflection (#336).

WHY THIS EXISTS
---------------
#328 attaches a document to the open DRAFT, so it follows one reflection
and retires with it. Reflecting toward a fixed date across many sittings
then means re-uploading the same job description and the same 90-day
plan every time — and those are exactly the documents that never change.

A row in ``global_context_files`` rides along with every analysis
automatically. Per-session attachments are untouched and still live on
``Reflection.context_files``.

ONE BUDGET, NOT TWO
-------------------
Globals and session attachments are merged at prompt-build time and
share the #328 caps (``MAX_FILES``, ``MAX_TOTAL_CHARS``). Marking a
document global must not quietly buy extra room in the prompt — the
budget exists because the prompt has a real ceiling, and where a
document is filed does not change that.

WHAT IS NOT STORED PER REFLECTION
---------------------------------
A global document is **not** copied onto each reflection row. This table
is the record of what was riding along. Copying would duplicate tens of
thousands of characters per sitting, which is the cost this feature
exists to remove — the trade being that a reflection's stored
``context_files`` shows only what was attached to it specifically.

SECURITY
--------
Unchanged from #328 / ADR-037. The uploaded FILE is decoded in memory by
``reflection_context_service`` and its bytes dropped; only the extracted
text is stored. That text is untrusted input on a prompt path that can
propose deletes, so it stays fenced, labelled data-not-instructions, and
subject to the same human confirm step.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from models import GlobalContextFile, db
from reflection_context_service import normalise_context_files, safe_filename

logger = logging.getLogger(__name__)


def _as_record(row: GlobalContextFile) -> dict[str, Any]:
    """A row in the SAME dict shape #328 uses for a session attachment.

    Converting at this boundary means every downstream helper —
    ``check_capacity``, ``public_view``, ``total_chars``,
    ``context_files_block`` — works on globals unchanged, rather than
    growing a second code path that could drift from the first.

    ``scope`` is the one addition: the UI has to show which documents
    ride along with everything and which belong to this sitting, and the
    caller would otherwise have to track that positionally.
    """
    return {
        "id": str(row.id),
        "filename": row.filename,
        "kind": row.kind,
        "chars": int(row.chars or 0),
        "source_chars": int(row.source_chars or row.chars or 0),
        "truncated": bool(row.truncated),
        "text": row.text or "",
        "added_at": row.created_at.isoformat() if row.created_at else "",
        "scope": "global",
    }


def list_global_files() -> list[dict[str, Any]]:
    """Every always-attached document, oldest first."""
    rows = db.session.scalars(
        select(GlobalContextFile).order_by(GlobalContextFile.created_at.asc())
    )
    return [_as_record(r) for r in rows]


def add_global_file(attachment: dict[str, Any]) -> dict[str, Any]:
    """Store an extracted document as always-attached.

    Takes the dict ``reflection_context_service.build_attachment``
    returns, so the extraction, truncation and naming rules are shared
    with the per-session path rather than reimplemented.
    """
    row = GlobalContextFile(
        filename=safe_filename(str(attachment.get("filename") or "")),
        kind=str(attachment.get("kind") or "file"),
        text=str(attachment.get("text") or ""),
        chars=int(attachment.get("chars") or 0),
        source_chars=int(
            attachment.get("source_chars") or attachment.get("chars") or 0
        ),
        truncated=bool(attachment.get("truncated")),
    )
    db.session.add(row)
    db.session.commit()
    return _as_record(row)


def remove_global_file(file_id) -> bool:
    """Delete one always-attached document. False if it wasn't there.

    A hard delete, unlike the soft-delete used for reflections: this is
    reference material the user is explicitly curating, and a
    recently-deleted list of documents they meant to remove would be
    clutter, not history. The reflections it informed are unaffected —
    they keep their own transcripts and their own attachments.
    """
    try:
        key = uuid.UUID(str(file_id))
    except (TypeError, ValueError):
        return False
    row = db.session.get(GlobalContextFile, key)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def merged_context_files(session_files) -> list[dict[str, Any]]:
    """Globals + this reflection's own attachments, de-duplicated.

    Globals come FIRST: they are the standing reference the sitting is
    being read against, and a model that meets the job description before
    the week's notes has the frame to read the notes in.

    De-duplicated on filename + text length rather than id, because the
    two stores mint ids independently — the same document attached to
    this sitting AND marked global is two different ids for one file, and
    sending it twice would charge the shared budget twice for nothing.
    The SESSION copy loses, so the surviving record is the global one;
    either is byte-identical text, so only the metadata differs.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rec in [*list_global_files(), *normalise_context_files(session_files)]:
        key = f"{rec.get('filename')}:{len(rec.get('text') or '')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out
