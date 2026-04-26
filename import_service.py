"""Import service — OneNote text parsing + Excel goals parsing.

Two import flows:
1. OneNote tasks: user pastes plain text → parser extracts task lines →
   preview → confirmed tasks land in Inbox
2. Excel goals: user uploads .xlsx → parser reads rows into goal
   candidates → preview → confirmed goals created

Both flows log the operation to ImportLog for audit trail.
Duplicate detection prevents re-importing the same items.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ImportLog,
    Project,
    ProjectStatus,
    ProjectType,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)

logger = logging.getLogger(__name__)


# --- OneNote text parsing ----------------------------------------------------


def parse_onenote_text(text: str) -> list[dict[str, Any]]:
    """Parse pasted OneNote text into task candidates.

    OneNote exports tasks as plain text with various bullet styles:
    - Bullet points (-, *, •)
    - Numbered lists (1., 2., etc.)
    - Checkbox items (☐, [], [ ])
    - Plain lines (non-empty, non-header)

    Lines that look like headers (ALL CAPS, very short, or date-only)
    are skipped. Empty lines are skipped.

    Args:
        text: Raw pasted text from OneNote.

    Returns:
        List of candidate dicts with title, type, included fields.
    """
    if not text or not text.strip():
        return []

    candidates = []
    seen_titles: set[str] = set()

    for line in text.splitlines():
        title = _clean_task_line(line)
        if not title:
            continue

        if _is_header_line(title):
            continue

        # Deduplicate within the same paste
        normalized = title.lower().strip()
        if normalized in seen_titles:
            continue
        seen_titles.add(normalized)

        candidates.append({
            "title": title,
            "type": "work",
            "included": True,
        })

    return candidates


def _clean_task_line(line: str) -> str:
    """Strip bullet markers, checkboxes, numbering from a line."""
    line = line.strip()
    if not line:
        return ""

    # Remove checkbox markers: ☐, ☑, ✓, [x], [ ], []
    line = re.sub(r"^[\u2610\u2611\u2713]\s*", "", line)
    line = re.sub(r"^\[[ xX]?\]\s*", "", line)

    # Remove bullet markers: -, *, •, ‣, ▪
    line = re.sub(r"^[-*\u2022\u2023\u25AA]\s+", "", line)

    # Remove numbered list: 1., 2), etc.
    line = re.sub(r"^\d+[.)]\s+", "", line)

    # Remove leading/trailing whitespace and control chars
    line = line.strip()

    # Skip very short lines (likely artifacts)
    if len(line) < 2:
        return ""

    return line


def _is_header_line(text: str) -> bool:
    """Detect header-like lines that aren't real tasks."""
    # All caps lines (any length, up to 40 chars) are likely section headers
    words = text.split()
    if (
        len(words) >= 1
        and len(text) <= 40
        and text == text.upper()
        and not any(c.isdigit() for c in text)
    ):
        return True

    # Date-only lines (e.g., "April 5, 2026", "2026-04-05")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return True
    return bool(re.match(
        r"^(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*\d{4}$",
        text,
        re.IGNORECASE,
    ))


# --- OneNote .docx file parsing ----------------------------------------------


def parse_onenote_docx(file_bytes: bytes) -> list[dict[str, Any]]:
    """Parse a OneNote-exported .docx file into task candidates.

    OneNote can export pages as Word documents via File → Export → Word.
    The exported file contains paragraphs with the same bullet/checkbox
    formatting as the pasted text. We extract each paragraph's text and
    run it through the same cleaning pipeline as parse_onenote_text.

    Args:
        file_bytes: Raw bytes of the .docx file.

    Returns:
        List of candidate dicts with title, type, included fields.
    """
    import docx

    try:
        doc = docx.Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"Cannot read Word document: {e}") from e

    # Extract all paragraph text, one per line
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)

    # Also extract text from tables (OneNote sometimes uses tables)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    lines.append(text)

    if not lines:
        return []

    # Reuse the same text parser
    combined = "\n".join(lines)
    return parse_onenote_text(combined)


# --- Excel goals parsing ----------------------------------------------------


def parse_excel_goals(file_bytes: bytes) -> list[dict[str, Any]]:
    """Parse an Excel (.xlsx) file into goal candidates.

    Expected columns (case-insensitive, matched by header row):
    - title (required)
    - category: health, personal_growth, relationships, work
    - priority: must, should, could, need_more_info
    - actions: free text
    - target_quarter: e.g. "Q2 2026"
    - status: not_started, in_progress, done, on_hold
    - notes: free text

    The first row is treated as the header. Rows with no title are skipped.

    Args:
        file_bytes: Raw bytes of the .xlsx file.

    Returns:
        List of goal candidate dicts.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    except Exception as e:
        raise ValueError(f"Cannot read Excel file: {e}") from e

    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no active worksheet")

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Map header names to column indices
    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_map = {name: idx for idx, name in enumerate(headers) if name}

    if "title" not in col_map:
        raise ValueError(
            "Excel file must have a 'title' column in the first row. "
            f"Found columns: {[h for h in headers if h]}"
        )

    candidates = []
    seen_titles: set[str] = set()

    for row in rows[1:]:
        title = _cell_str(row, col_map.get("title"))
        if not title:
            continue

        # Deduplicate within file
        normalized = title.lower()
        if normalized in seen_titles:
            continue
        seen_titles.add(normalized)

        category = _cell_str(row, col_map.get("category")) or "work"
        priority = _cell_str(row, col_map.get("priority")) or "should"

        # Validate enum values, fall back to defaults
        if not _valid_enum(GoalCategory, category):
            category = "work"
        if not _valid_enum(GoalPriority, priority):
            priority = "should"

        status = _cell_str(row, col_map.get("status")) or "not_started"
        if not _valid_enum(GoalStatus, status):
            status = "not_started"

        candidates.append({
            "title": title,
            "category": category,
            "priority": priority,
            "actions": _cell_str(row, col_map.get("actions")) or "",
            "target_quarter": _cell_str(row, col_map.get("target_quarter")) or "",
            "status": status,
            "notes": _cell_str(row, col_map.get("notes")) or "",
            "included": True,
        })

    return candidates


def _cell_str(row: tuple, idx: int | None) -> str:
    """Safely extract a string from a row tuple by index."""
    if idx is None or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


def _valid_enum(enum_cls, value: str) -> bool:
    """Check if a string is a valid member of an enum."""
    try:
        enum_cls(value)
        return True
    except ValueError:
        return False


# --- Duplicate detection -----------------------------------------------------


def find_duplicate_tasks(titles: list[str]) -> list[str]:
    """Return titles that already exist as active tasks (case-insensitive)."""
    if not titles:
        return []

    from sqlalchemy import func

    lower_titles = [t.lower() for t in titles]
    existing = db.session.scalars(
        select(Task.title).where(
            Task.status != TaskStatus.DELETED,
            func.lower(Task.title).in_(lower_titles),
        )
    ).all()
    existing_lower = {t.lower() for t in existing}

    return [t for t in titles if t.lower() in existing_lower]


def parse_project_names_text(text: str) -> list[dict[str, Any]]:
    """#80 (2026-04-26): parse one project name per line from raw text.

    Strips bullet/numbered list markers (- *, 1., etc.) so a copy-pasted
    list works without manual cleanup. Skips empty lines and obvious
    headers. Returns the same candidate shape the UI consumes.
    """
    if not text or not text.strip():
        return []

    candidates: list[dict[str, Any]] = []
    seen_lower: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip bullet / numbered prefixes (mirrors parse_onenote_text logic).
        cleaned = _clean_task_line(line)
        if not cleaned:
            continue
        if _is_header_line(cleaned):
            continue
        if len(cleaned) < 2:
            continue
        lo = cleaned.lower()
        if lo in seen_lower:
            continue
        seen_lower.add(lo)
        candidates.append({
            "name": cleaned,
            "type": "work",
            "included": True,
        })
    return candidates


def parse_excel_tasks(file_bytes: bytes) -> list[dict[str, Any]]:
    """#89 (2026-04-26): parse a .xlsx of task rows.

    Expected header row (case-insensitive):
      - title (required)
      - type: work, personal — default work
      - tier: inbox, today, tomorrow, this_week, next_week, backlog,
        freezer — default inbox
      - due_date: ISO YYYY-MM-DD; openpyxl returns datetime which gets
        normalised to YYYY-MM-DD string
      - linked_goal: free-text goal title; matched case-insensitive at
        create time. No exact-id requirement.
      - linked_project: free-text project name; same matching.
      - notes: free text
      - url: free text

    Rows with no title are skipped. Returns the candidate shape the
    review UI consumes (the field mapping mirrors what
    `create_tasks_from_import` already accepts).
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    except Exception as e:
        raise ValueError(f"Cannot read Excel file: {e}") from e

    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no active worksheet")

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_map = {name: idx for idx, name in enumerate(headers) if name}

    candidates: list[dict[str, Any]] = []
    for row in rows[1:]:
        title = _cell_str(row, col_map.get("title"))
        if not title:
            continue
        type_str = _cell_str(row, col_map.get("type")).lower()
        if not _valid_enum(TaskType, type_str):
            type_str = "work"
        tier_str = _cell_str(row, col_map.get("tier")).lower()
        if not _valid_enum(Tier, tier_str):
            tier_str = "inbox"
        # due_date may come back from openpyxl as a date / datetime —
        # normalise to YYYY-MM-DD string. Plain strings pass through.
        due_idx = col_map.get("due_date")
        due_raw = row[due_idx] if (due_idx is not None and due_idx < len(row)) else None
        if hasattr(due_raw, "strftime"):
            due_str = due_raw.strftime("%Y-%m-%d")
        else:
            due_str = _cell_str(row, due_idx)
        candidates.append({
            "title": title,
            "type": type_str,
            "tier": tier_str,
            "due_date": due_str,
            "linked_goal": _cell_str(row, col_map.get("linked_goal")),
            "linked_project": _cell_str(row, col_map.get("linked_project")),
            "notes": _cell_str(row, col_map.get("notes")),
            "url": _cell_str(row, col_map.get("url")),
            "included": True,
        })
    return candidates


def parse_excel_projects(file_bytes: bytes) -> list[dict[str, Any]]:
    """#80 (2026-04-26): parse a .xlsx of project rows.

    Expected columns (case-insensitive header row):
      - name (required)
      - type: work, personal
      - target_quarter: free string e.g. "2026-Q4"
      - status: not_started, in_progress, done, on_hold
      - color: hex e.g. "#2563eb" — if absent, per-type default fills (#66)
      - actions, notes: free text
      - linked_goal: free-text title; matched case-insensitively against
        existing goals at create time. No exact-id requirement.

    Rows with no name are skipped.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    except Exception as e:
        raise ValueError(f"Cannot read Excel file: {e}") from e

    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no active worksheet")

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    col_map = {name: idx for idx, name in enumerate(headers) if name}

    candidates: list[dict[str, Any]] = []
    for row in rows[1:]:
        name = _cell_str(row, col_map.get("name"))
        if not name:
            continue
        type_str = _cell_str(row, col_map.get("type")).lower()
        if not _valid_enum(ProjectType, type_str):
            type_str = "work"
        status_str = _cell_str(row, col_map.get("status")).lower()
        if not _valid_enum(ProjectStatus, status_str):
            status_str = "not_started"
        candidates.append({
            "name": name,
            "type": type_str,
            "target_quarter": _cell_str(row, col_map.get("target_quarter")),
            "status": status_str,
            "color": _cell_str(row, col_map.get("color")),
            "actions": _cell_str(row, col_map.get("actions")),
            "notes": _cell_str(row, col_map.get("notes")),
            "linked_goal": _cell_str(row, col_map.get("linked_goal")),
            "included": True,
        })
    return candidates


def find_duplicate_projects(names: list[str]) -> list[str]:
    """#80: return project names that already exist (case-insensitive)."""
    if not names:
        return []
    existing = db.session.scalars(
        select(Project.name).where(Project.is_active.is_(True))
    ).all()
    existing_lower = {n.lower() for n in existing}
    return [n for n in names if n.lower() in existing_lower]


def find_duplicate_goals(titles: list[str]) -> list[str]:
    """Return titles that already exist as active goals (case-insensitive)."""
    if not titles:
        return []

    existing = db.session.scalars(
        select(Goal.title).where(Goal.is_active.is_(True))
    ).all()
    existing_lower = {t.lower() for t in existing}

    return [t for t in titles if t.lower() in existing_lower]


# --- Create records from confirmed candidates --------------------------------


def create_tasks_from_import(
    candidates: list[dict[str, Any]],
    source: str,
) -> list[Task]:
    """Create Task records from confirmed import candidates.

    Only candidates with included=True are created.
    All imported tasks land in the Inbox tier.
    Logs the import to ImportLog and stamps a shared ``batch_id`` on
    every created Task so the whole import can be undone as a group
    via the recycle bin flow.

    Args:
        candidates: List of candidate dicts from the preview.
        source: Import source identifier for the log.

    Returns:
        List of newly created Task records.
    """
    # #89 (2026-04-26): pre-load goal + project lookups once so any
    # candidate carrying `linked_goal` or `linked_project` (Excel paths)
    # resolves O(1) instead of N queries. Lower-cased title/name is the
    # match key (matches the project import behavior in #80).
    goal_index: dict[str, Any] = {}
    for g in db.session.scalars(
        select(Goal).where(Goal.is_active.is_(True))
    ):
        goal_index[g.title.strip().lower()] = g.id
    project_index: dict[str, Any] = {}
    for p in db.session.scalars(
        select(Project).where(Project.is_active.is_(True))
    ):
        project_index[p.name.strip().lower()] = p.id

    batch_id = uuid.uuid4()
    created = []
    for candidate in candidates:
        if not candidate.get("included", True):
            continue

        title = (candidate.get("title") or "").strip()
        if not title:
            continue

        task_type_str = candidate.get("type", "work")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            task_type = TaskType.WORK

        # #76 (2026-04-25): preview row now exposes more fields. Default
        # tier remains Inbox; everything else is optional. Bad values are
        # silently coerced to defaults rather than aborting the whole
        # import — the user just edited each row, so we trust them.
        tier_str = candidate.get("tier") or "inbox"
        try:
            tier = Tier(tier_str)
        except ValueError:
            tier = Tier.INBOX

        due_date_val: date | None = None
        due_raw = (candidate.get("due_date") or "").strip()
        if due_raw:
            try:
                due_date_val = date.fromisoformat(due_raw)
            except ValueError:
                due_date_val = None

        # goal_id can be a UUID string OR fall through to a free-text
        # `linked_goal` lookup (#89 Excel path).
        goal_id_val: uuid.UUID | None = None
        goal_raw = (candidate.get("goal_id") or "").strip()
        if goal_raw:
            try:
                goal_id_val = uuid.UUID(goal_raw)
            except ValueError:
                goal_id_val = None
        if goal_id_val is None:
            linked_goal_raw = (candidate.get("linked_goal") or "").strip()
            if linked_goal_raw:
                goal_id_val = goal_index.get(linked_goal_raw.lower())

        project_id_val: uuid.UUID | None = None
        project_raw = (candidate.get("project_id") or "").strip()
        if project_raw:
            try:
                project_id_val = uuid.UUID(project_raw)
            except ValueError:
                project_id_val = None
        if project_id_val is None:
            linked_project_raw = (candidate.get("linked_project") or "").strip()
            if linked_project_raw:
                project_id_val = project_index.get(linked_project_raw.lower())

        notes = (candidate.get("notes") or "").strip() or None
        url = (candidate.get("url") or "").strip() or None

        task = Task(
            title=title,
            type=task_type,
            tier=tier,
            due_date=due_date_val,
            goal_id=goal_id_val,
            project_id=project_id_val,
            notes=notes,
            url=url,
            batch_id=batch_id,
        )
        db.session.add(task)
        created.append(task)

    if created:
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()

    return created


def create_goals_from_import(
    candidates: list[dict[str, Any]],
    source: str,
) -> list[Goal]:
    """Create Goal records from confirmed import candidates.

    Only candidates with included=True are created.
    Logs the import to ImportLog and stamps a shared ``batch_id`` on
    every created Goal so the whole import can be undone as a group
    via the recycle bin flow.

    Args:
        candidates: List of goal candidate dicts from the preview.
        source: Import source identifier for the log.

    Returns:
        List of newly created Goal records.
    """
    batch_id = uuid.uuid4()
    created = []
    for candidate in candidates:
        if not candidate.get("included", True):
            continue

        title = (candidate.get("title") or "").strip()
        if not title:
            continue

        try:
            category = GoalCategory(candidate.get("category", "work"))
        except ValueError:
            category = GoalCategory.WORK

        try:
            priority = GoalPriority(candidate.get("priority", "should"))
        except ValueError:
            priority = GoalPriority.SHOULD

        try:
            status = GoalStatus(candidate.get("status", "not_started"))
        except ValueError:
            status = GoalStatus.NOT_STARTED

        goal = Goal(
            title=title,
            category=category,
            priority=priority,
            actions=candidate.get("actions") or None,
            target_quarter=candidate.get("target_quarter") or None,
            status=status,
            notes=candidate.get("notes") or None,
            batch_id=batch_id,
        )
        db.session.add(goal)
        created.append(goal)

    if created:
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()

    return created


def create_projects_from_import(
    candidates: list[dict[str, Any]],
    source: str,
) -> list[Project]:
    """#80 (2026-04-26): create Project records from confirmed candidates.

    Mirrors create_goals_from_import: only included candidates create
    rows, batch_id stamps every row for recycle-bin batch undo, ImportLog
    captures the import. linked_goal is matched case-insensitively to an
    existing active goal title; misses are silently skipped (project
    still created with goal_id=None).
    """
    from project_service import _default_color_for_type

    if not candidates:
        return []

    # Pre-load active goals into a case-insensitive title -> id lookup
    # so per-row linked_goal resolution is O(1) instead of N queries.
    goal_index: dict[str, Any] = {}
    for g in db.session.scalars(
        select(Goal).where(Goal.is_active.is_(True))
    ):
        goal_index[g.title.strip().lower()] = g.id

    batch_id = uuid.uuid4()
    created: list[Project] = []
    for candidate in candidates:
        if not candidate.get("included", True):
            continue
        name = (candidate.get("name") or "").strip()
        if not name:
            continue

        type_str = candidate.get("type", "work")
        try:
            project_type = ProjectType(type_str)
        except ValueError:
            project_type = ProjectType.WORK

        status_str = candidate.get("status", "not_started")
        try:
            status = ProjectStatus(status_str)
        except ValueError:
            status = ProjectStatus.NOT_STARTED

        color = (candidate.get("color") or "").strip()
        if not color:
            color = _default_color_for_type(project_type)

        goal_id = None
        linked_raw = (candidate.get("linked_goal") or "").strip()
        if linked_raw:
            goal_id = goal_index.get(linked_raw.lower())

        project = Project(
            name=name,
            type=project_type,
            color=color,
            target_quarter=(candidate.get("target_quarter") or "").strip() or None,
            actions=(candidate.get("actions") or "").strip() or None,
            notes=(candidate.get("notes") or "").strip() or None,
            status=status,
            goal_id=goal_id,
        )
        db.session.add(project)
        created.append(project)

    if created:
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()

    return created
