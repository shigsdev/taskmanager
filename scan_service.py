"""Image scan to tasks — OCR + AI parsing pipeline.

Pipeline:
1. Image bytes → Google Vision API → raw OCR text
2. Raw OCR text → Claude API (claude-sonnet) → JSON array of task candidates
3. User reviews candidates → confirmed tasks created in Inbox

Security (per CLAUDE.md):
- Images processed in memory only — never written to disk or DB
- Google Vision and Claude API calls are server-side only
- No image metadata stored
"""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    GoalStatus,
    ImportLog,
    Task,
    TaskType,
    Tier,
    db,
)

logger = logging.getLogger(__name__)


# --- OCR via Google Vision API ------------------------------------------------


def extract_text_from_image(image_bytes: bytes) -> str:
    """Send image bytes to Google Vision API for OCR text extraction.

    The image is base64-encoded and sent as a JSON payload to the
    Vision API's TEXT_DETECTION feature. The API returns detected text
    blocks, which we concatenate into a single string.

    Args:
        image_bytes: Raw image file bytes (jpg, png, webp).

    Returns:
        The extracted text as a string. Empty string if no text found.

    Raises:
        RuntimeError: If the API call fails or key is missing.
    """
    api_key = os.environ.get("GOOGLE_VISION_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_VISION_API_KEY not configured")

    return _call_vision_api(api_key, image_bytes)


def _call_vision_api(api_key: str, image_bytes: bytes) -> str:
    """Make the actual Google Vision API call. Separated for testability.

    Wraps all failure modes (network, HTTP error, bad JSON, per-request
    API error) in RuntimeError with a useful message that's safe to
    surface to the user — the API key is never included.
    """
    from egress import EgressError, safe_call_api

    # API key in header (X-Goog-Api-Key) instead of URL query param —
    # see docs/adr/007. HTTP mechanics (timeout, error wrapping) live
    # in egress.safe_call_api — see docs/adr/006.
    payload = {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }

    try:
        data = safe_call_api(
            url="https://vision.googleapis.com/v1/images:annotate",
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout_sec=30,
            vendor="Vision",
        )
    except EgressError as e:
        raise RuntimeError(str(e)) from e

    # Per-request error (Vision wraps errors inside responses[0].error)
    responses = data.get("responses") or [{}]
    first = responses[0] if responses else {}
    if "error" in first and first["error"]:
        msg = first["error"].get("message") or first["error"].get("status") or "unknown"
        raise RuntimeError(f"Vision API request error: {msg}")

    annotations = first.get("textAnnotations", [])
    if not annotations:
        return ""
    # First annotation is the full text block
    return annotations[0].get("description", "").strip()


# --- Task parsing via Claude API ----------------------------------------------


_PARSE_PROMPT = """\
You are a task extraction assistant. Given raw OCR text from an image \
(which may contain handwritten notes, bullet lists, meeting agendas, \
or mixed content), extract discrete actionable task items.

Rules:
- Each task should be a short, clear action item (under 100 characters)
- Ignore headers, page numbers, decorative text, dates used as headers
- Consolidate fragmented lines that belong to the same task
- Handle bullet points, numbered lists, dashes, and plain text
- If a line is not an actionable task, skip it
- Return ONLY a JSON array of strings, no other text

Example output:
["Buy groceries", "Schedule dentist appointment", "Review Q2 report"]

OCR text:
{ocr_text}
"""


def parse_tasks_from_text(ocr_text: str) -> list[str]:
    """Send OCR text to Claude API to parse into task candidates.

    Uses Claude claude-sonnet-4-6 to intelligently parse raw OCR output into
    clean, discrete task items. The AI handles messy formatting,
    handwriting artifacts, and mixed content types.

    Args:
        ocr_text: Raw text from Google Vision OCR.

    Returns:
        List of task candidate strings.

    Raises:
        RuntimeError: If the API call fails or key is missing.
    """
    if not ocr_text.strip():
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    return _call_claude_api(api_key, ocr_text)


def _call_claude_api(api_key: str, ocr_text: str) -> list[str]:
    """Make the actual Claude API call. Separated for testability.

    Delegates HTTP mechanics to ``egress.safe_call_api``.
    """
    data = _post_to_claude(
        api_key=api_key,
        prompt=_PARSE_PROMPT.format(ocr_text=ocr_text),
        max_tokens=1024,
    )
    content = data.get("content", [{}])[0].get("text", "")
    return _extract_json_array(content)


def _post_to_claude(*, api_key: str, prompt: str, max_tokens: int) -> dict[str, Any]:
    """Shared Claude API caller — used by both task and goal extraction."""
    from egress import EgressError, safe_call_api

    try:
        return safe_call_api(
            url="https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout_sec=60,
            vendor="Claude",
        )
    except EgressError as e:
        raise RuntimeError(str(e)) from e


def _extract_json_array(text: str) -> list[str]:
    """Extract a JSON array from Claude's response text.

    Claude might wrap the JSON in markdown code blocks or include
    extra text. This function finds and parses the JSON array.
    """
    # Try direct parse first
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(item) for item in result if item]
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                result = json.loads(cleaned)
                if isinstance(result, list):
                    return [str(item) for item in result if item]
            except json.JSONDecodeError:
                continue

    # Try finding array brackets
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list):
                return [str(item) for item in result if item]
        except json.JSONDecodeError:
            pass

    return []


# --- Goal parsing via Claude API ---------------------------------------------


_GOAL_PARSE_PROMPT = """\
You are a goal extraction assistant. Given raw OCR text from an image \
(which may contain handwritten notes, brainstorming pages, annual planning \
documents, or meeting notes), extract discrete personal or professional \
GOALS — larger-scope objectives, not daily to-do items.

Each goal must be a JSON object with these keys:
- title: short goal statement (under 200 characters, required)
- category: one of "health", "personal_growth", "relationships", "work"
- priority: one of "must", "should", "could", "need_more_info"
- target_quarter: optional free-text like "Q2 2026", or null
- actions: optional short string of concrete steps, or null

Rules:
- Focus on aspirational or multi-step objectives, not simple tasks
- If category is unclear, use "personal_growth"
- If priority is unclear, use "need_more_info"
- Consolidate related bullet points into a single goal
- Return ONLY a JSON array of objects, no other text

Example output:
[
  {{"title": "Lose 10 pounds by summer", "category": "health",
    "priority": "should", "target_quarter": "Q2 2026",
    "actions": "Gym 3x/week, meal prep Sundays"}},
  {{"title": "Ship v2 launch", "category": "work",
    "priority": "must", "target_quarter": null, "actions": null}}
]

OCR text:
{ocr_text}
"""


# #86 (2026-04-26): scan-to-projects prompt. Mirrors the goal/task
# prompts but produces project candidates (name + type + optional
# target quarter).
_PROJECT_PARSE_PROMPT = """\
You are a project extraction assistant. Given raw OCR text from an \
image (which may contain handwritten notes, planning whiteboards, or \
meeting agendas), extract discrete PROJECTS — areas of focus that \
group multiple related tasks (e.g. "Q3 Planning", "Portal Redesign", \
"Home Renovation").

Each project must be a JSON object with these keys:
- name: short project name (under 200 characters, required)
- type: one of "work", "personal"
- target_quarter: optional free-text like "2026-Q4", or null

Rules:
- Focus on multi-task initiatives, not individual tasks or aspirational goals
- If type is unclear, use "work"
- Consolidate related bullets into a single project
- Return ONLY a JSON array of objects, no other text

Example output:
[
  {{"name": "Portal redesign", "type": "work", "target_quarter": "2026-Q3"}},
  {{"name": "Garden cleanup", "type": "personal", "target_quarter": null}}
]

OCR text:
{ocr_text}
"""


def parse_projects_from_text(ocr_text: str) -> list[dict[str, Any]]:
    """#86: extract project candidates from OCR text via Claude."""
    if not ocr_text.strip():
        return []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    data = _post_to_claude(
        api_key=api_key,
        prompt=_PROJECT_PARSE_PROMPT.format(ocr_text=ocr_text),
        max_tokens=2048,
    )
    content = data.get("content", [{}])[0].get("text", "")
    return _extract_json_object_list(content)


def parse_goals_from_text(ocr_text: str) -> list[dict[str, Any]]:
    """Send OCR text to Claude API to parse into goal candidates.

    Returns a list of dicts with keys: title, category, priority,
    target_quarter, actions. Invalid category/priority values are left
    as-is here — the ``create_goals_from_candidates`` path coerces them
    to valid enum values with sensible fallbacks.

    Raises:
        RuntimeError: If the API call fails or the key is missing.
    """
    if not ocr_text.strip():
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    return _call_claude_api_goals(api_key, ocr_text)


def _call_claude_api_goals(
    api_key: str, ocr_text: str
) -> list[dict[str, Any]]:
    """Make the Claude API call for goal extraction. Separated for testability.

    Reuses ``_post_to_claude`` so the only difference between task and
    goal extraction is the prompt + max_tokens + JSON parser.
    """
    data = _post_to_claude(
        api_key=api_key,
        prompt=_GOAL_PARSE_PROMPT.format(ocr_text=ocr_text),
        max_tokens=2048,
    )
    content = data.get("content", [{}])[0].get("text", "")
    return _extract_json_object_list(content)


def _extract_json_object_list(text: str) -> list[dict[str, Any]]:
    """Extract a JSON array of objects from Claude's response text.

    Mirrors ``_extract_json_array`` but returns dicts instead of strings.
    Items that aren't dicts are dropped so a stray string can't sneak
    through and cause a KeyError downstream.
    """
    text = text.strip()
    candidates: list[Any] | None = None

    # Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            candidates = parsed
    except json.JSONDecodeError:
        pass

    # Try markdown code block
    if candidates is None and "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    candidates = parsed
                    break
            except json.JSONDecodeError:
                continue

    # Try array brackets
    if candidates is None:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, list):
                    candidates = parsed
            except json.JSONDecodeError:
                pass

    if not candidates:
        return []

    return [item for item in candidates if isinstance(item, dict)]


# --- Voice-memo structured task parsing (#36) --------------------------------

_VOICE_PARSE_PROMPT = """\
You are a task extraction assistant. Given a transcript of a spoken \
voice memo, extract items AND infer metadata (type, tier, due_date, \
project_hint, goal_hint, is_task) from the speaker's context.

Today's date is {today}.

The user's existing projects (exact titles — cite these verbatim if
a task clearly relates to one; do NOT invent new project names):
{project_titles}

The user's existing goals (exact titles — same rule):
{goal_titles}

Each item must be a JSON object with these keys:
- title: short clear phrasing (under 100 characters, required)
- type: "work" or "personal". Infer from context: work keywords
  (meeting, project, deadline, standup, PR, report, client) → "work";
  personal keywords (family, groceries, dentist, workout, bills,
  chores) → "personal". Default to "personal" if unclear.
- tier: one of "inbox", "today", "tomorrow", "this_week".
  * "today" if the speaker says today / now / ASAP / urgent
  * "tomorrow" if they say tomorrow / next day
  * "this_week" if they mention a specific weekday within the next
    6 days (e.g. "by Friday", "on Thursday") OR say "this week"
  * "inbox" (default) for everything else — no urgency specified
- due_date: ISO date string "YYYY-MM-DD" if the speaker mentioned a
  specific calendar date, OR null. Resolve relative references
  ("tomorrow", "Friday", "next Tuesday", "the 15th") against today's
  date {today}. Return null if no date was mentioned.
- project_hint: exact title (verbatim) of a user project this task
  clearly belongs to, OR null. Only cite a project from the list
  above — do not invent. If nothing on the list fits, null.
- goal_hint: exact title (verbatim) of a user goal this task
  clearly supports, OR null. Same rule — only cite from the list.
- is_task: true if this is an actionable task, false if it is pure
  reflection / journaling / venting / status observation without a
  next action. Reflective non-tasks still need a title (summarise
  the thought) so the user can review and decide.

Rules:
- Split independent tasks into separate items; consolidate fragments
  that describe the same task.
- Keep filler words / "um" / "like" out of titles.
- Return ONLY a JSON array of objects, no other text.

Example (if today is 2026-04-20, a Monday; projects = ["Q2 OKRs"];
goals = ["Run a half marathon"]):
Input: "Okay so tomorrow I need to pick up prescriptions, and by \
Friday I have to finish the Q2 OKR deck. Also email Sarah about \
the meeting. And I should do a 5K run this weekend. I'm feeling \
scattered today."
Output:
[
  {{"title": "Pick up prescriptions", "type": "personal",
    "tier": "tomorrow", "due_date": "2026-04-21",
    "project_hint": null, "goal_hint": null, "is_task": true}},
  {{"title": "Finish Q2 OKR deck", "type": "work",
    "tier": "this_week", "due_date": "2026-04-24",
    "project_hint": "Q2 OKRs", "goal_hint": null,
    "is_task": true}},
  {{"title": "Email Sarah about the meeting", "type": "work",
    "tier": "inbox", "due_date": null,
    "project_hint": null, "goal_hint": null, "is_task": true}},
  {{"title": "5K run this weekend", "type": "personal",
    "tier": "this_week", "due_date": null,
    "project_hint": null, "goal_hint": "Run a half marathon",
    "is_task": true}},
  {{"title": "Feeling scattered today", "type": "personal",
    "tier": "inbox", "due_date": null,
    "project_hint": null, "goal_hint": null, "is_task": false}}
]

Transcript:
{transcript}
"""


def parse_voice_memo_to_tasks(transcript: str) -> list[dict[str, Any]]:
    """Send a voice-memo transcript to Claude for structured extraction.

    Phase 2 (#37) response shape — one dict per item:
        {
            title: str,
            type: "work" | "personal",
            tier: "inbox" | "today" | "tomorrow" | "this_week",
            due_date: str | None,       # ISO YYYY-MM-DD
            project_id: str | None,     # resolved from project_hint
            goal_id: str | None,        # resolved from goal_hint
            is_task: bool,
        }

    Hints returned by Claude are resolved to real `project_id` /
    `goal_id` UUIDs here (case-insensitive exact title match against
    the user's ACTIVE projects/goals). No match → ID stays None;
    callers can still show the hint on the review screen for manual
    linking.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is missing.
    """
    if not transcript.strip():
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    # Fetch the user's active projects + goals so the prompt can cite
    # exact titles AND the normaliser can resolve hints → UUIDs.
    # Kept inside the parsing function (rather than passed in) so
    # callers don't have to know about this coupling.
    projects, goals = _fetch_projects_and_goals_for_hints()

    return _call_claude_api_voice(api_key, transcript, projects, goals)


def _fetch_projects_and_goals_for_hints() -> tuple[
    list[tuple[str, str]], list[tuple[str, str]]
]:
    """Return `([(project_id, title), ...], [(goal_id, title), ...])`
    of ACTIVE entries for voice-NLP hint resolution.

    Returns empty lists on any error (DB unavailable, etc.) — the
    rest of the voice flow still works without hints.
    """
    try:
        from sqlalchemy import select

        from models import Goal, Project, db
        projects = [
            (str(p.id), p.name)
            for p in db.session.scalars(
                select(Project).where(Project.is_active.is_(True))
            )
        ]
        goals = [
            (str(g.id), g.title)
            for g in db.session.scalars(
                select(Goal).where(Goal.is_active.is_(True))
            )
        ]
        return projects, goals
    except Exception:  # noqa: BLE001 — hints are optional; never crash the flow
        return [], []


def _call_claude_api_voice(
    api_key: str,
    transcript: str,
    projects: list[tuple[str, str]],
    goals: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Make the Claude API call for voice-memo parsing. Separated for
    testability — tests can patch this instead of the HTTP layer."""
    from datetime import date as _date
    today_iso = _date.today().isoformat()

    # Render the titles as a comma-separated list for the prompt. If
    # empty, use the explicit word "(none)" so Claude doesn't get
    # confused by an empty field.
    project_titles = ", ".join(
        repr(title) for _, title in projects
    ) or "(none)"
    goal_titles = ", ".join(
        repr(title) for _, title in goals
    ) or "(none)"

    data = _post_to_claude(
        api_key=api_key,
        prompt=_VOICE_PARSE_PROMPT.format(
            today=today_iso,
            transcript=transcript,
            project_titles=project_titles,
            goal_titles=goal_titles,
        ),
        max_tokens=2048,
    )
    content = data.get("content", [{}])[0].get("text", "")
    return _normalise_voice_candidates(
        _extract_json_object_list(content),
        projects=projects,
        goals=goals,
    )


# Allowed values for structured voice output. Anything outside these
# lists gets coerced to the default — guards against hallucinated
# tier/type values without crashing the UI downstream.
_VOICE_VALID_TYPES = {"work", "personal"}
_VOICE_VALID_TIERS = {"inbox", "today", "tomorrow", "this_week"}


def _normalise_voice_candidates(
    raw: list[dict[str, Any]],
    *,
    projects: list[tuple[str, str]] | None = None,
    goals: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Clean + coerce Claude's voice output to a predictable shape.

    - Drops items with no title (or non-string title).
    - Truncates over-long titles to 100 chars.
    - Coerces unknown type values to "personal".
    - Coerces unknown tier values to "inbox".
    - Validates due_date as ISO YYYY-MM-DD; drops (→ None) otherwise.
    - Resolves project_hint / goal_hint to UUIDs via case-insensitive
      exact title match against the supplied projects/goals lists
      (#37). Unresolved hints stay in `project_hint` / `goal_hint`
      on the candidate so the UI can surface them as free text.
    - Defaults `is_task` to True (safer assumption — user unchecks
      on the review screen if they want it dropped).
    """
    from datetime import date as _date

    # Build case-insensitive title → id lookup maps. Skip if no
    # projects/goals supplied (test case or empty-db case).
    proj_by_title_lc = {
        title.lower().strip(): pid
        for pid, title in (projects or [])
        if isinstance(title, str) and title.strip()
    }
    goal_by_title_lc = {
        title.lower().strip(): gid
        for gid, title in (goals or [])
        if isinstance(title, str) and title.strip()
    }

    out: list[dict[str, Any]] = []
    for item in raw:
        title = item.get("title")
        if not isinstance(title, str):
            continue
        title = title.strip()
        if not title:
            continue
        if len(title) > 100:
            title = title[:100]

        type_val = item.get("type")
        if type_val not in _VOICE_VALID_TYPES:
            type_val = "personal"

        tier_val = item.get("tier")
        if tier_val not in _VOICE_VALID_TIERS:
            tier_val = "inbox"

        due_date: str | None = None
        raw_due = item.get("due_date")
        if isinstance(raw_due, str):
            try:
                _date.fromisoformat(raw_due)
                due_date = raw_due
            except ValueError:
                due_date = None

        # Resolve project_hint + goal_hint to UUIDs (#37). Hint
        # string stays on the candidate regardless so the UI can
        # show "Claude suggested X" even when X doesn't match.
        project_hint = item.get("project_hint")
        project_id: str | None = None
        if isinstance(project_hint, str) and project_hint.strip():
            project_id = proj_by_title_lc.get(
                project_hint.strip().lower()
            )

        goal_hint = item.get("goal_hint")
        goal_id: str | None = None
        if isinstance(goal_hint, str) and goal_hint.strip():
            goal_id = goal_by_title_lc.get(goal_hint.strip().lower())

        # Default is_task=True so that a Claude miss (forgot to emit
        # the field) still treats the item as a task. `is not False`
        # preserves the "only literal False flips it off" semantic
        # (None / missing / non-bool truthy all stay True).
        is_task = item.get("is_task") is not False

        out.append({
            "title": title,
            "type": type_val,
            "tier": tier_val,
            "due_date": due_date,
            "project_hint": project_hint if isinstance(project_hint, str) else None,
            "project_id": project_id,
            "goal_hint": goal_hint if isinstance(goal_hint, str) else None,
            "goal_id": goal_id,
            "is_task": is_task,
        })
    return out


# --- Create tasks from confirmed candidates ----------------------------------


def create_tasks_from_candidates(
    candidates: list[dict[str, Any]],
    source_prefix: str = "scan",
) -> list[Task]:
    """Create Task records from confirmed candidates.

    Each candidate is a dict with:
    - title (str): the task text (required)
    - type (str): "work" or "personal" (default: "work")
    - tier (str, optional): Tier enum value. Default: Inbox. Used by
      the voice-memo NLP path (#36) to preserve inferred tier.
    - due_date (str, optional): ISO YYYY-MM-DD. Default: None. Used by
      the voice-memo NLP path (#36).
    - included (bool): whether the user confirmed this candidate

    Only candidates with included=True are created.

    Stamps a shared ``batch_id`` on every created Task and writes an
    ``ImportLog`` entry so the batch can be undone as a group via the
    recycle bin flow.

    Args:
        candidates: List of candidate dicts from the review screen.
        source_prefix: Audit-log prefix recorded in ``ImportLog.source``
            (e.g. "scan", "voice"). Lets the recycle bin distinguish
            where a batch came from. Suffixed with a timestamp.

    Returns:
        List of newly created Task records.
    """
    from datetime import date as _date
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

        # #36: honor inferred tier (defaults to Inbox if missing or
        # invalid — same as the pre-NLP behavior).
        import contextlib
        tier_str = candidate.get("tier")
        tier = Tier.INBOX
        if tier_str:
            with contextlib.suppress(ValueError):
                tier = Tier(tier_str)

        # #36: honor inferred due_date. Validates ISO format; silently
        # drops bad values so one malformed candidate doesn't fail
        # the whole batch.
        due_date = None
        due_raw = candidate.get("due_date")
        if isinstance(due_raw, str) and due_raw:
            try:
                due_date = _date.fromisoformat(due_raw)
            except ValueError:
                due_date = None

        # #37: honor inferred project_id + goal_id. Already resolved
        # to UUIDs by _normalise_voice_candidates; validated here
        # to prevent a spoofed or stale ID from blowing up the task
        # INSERT. Unknown ID → silently None (user links manually).
        project_id = None
        raw_project_id = candidate.get("project_id")
        if isinstance(raw_project_id, str) and raw_project_id:
            with contextlib.suppress(ValueError):
                project_id = uuid.UUID(raw_project_id)

        goal_id = None
        raw_goal_id = candidate.get("goal_id")
        if isinstance(raw_goal_id, str) and raw_goal_id:
            with contextlib.suppress(ValueError):
                goal_id = uuid.UUID(raw_goal_id)

        task = Task(
            title=title,
            type=task_type,
            tier=tier,
            due_date=due_date,
            project_id=project_id,
            goal_id=goal_id,
            batch_id=batch_id,
        )
        db.session.add(task)
        created.append(task)

    if created:
        source = f"{source_prefix}_" + datetime.now(UTC).strftime("%Y_%m_%d_%H%M%S")
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()
    return created


def create_goals_from_candidates(
    candidates: list[dict[str, Any]],
) -> list[Goal]:
    """Create Goal records from confirmed scan candidates.

    Each candidate is a dict with:
    - title (str, required)
    - category (str): GoalCategory value, defaults to "personal_growth"
    - priority (str): GoalPriority value, defaults to "need_more_info"
    - target_quarter (str | None): optional free text
    - actions (str | None): optional
    - included (bool): whether the user confirmed this candidate

    Stamps a shared ``batch_id`` on every Goal created and writes an
    ``ImportLog`` entry with a ``scan_...`` source so the whole scan can
    be undone as a group via the recycle bin flow (same pattern as
    ``create_tasks_from_candidates``).
    """
    batch_id = uuid.uuid4()
    created: list[Goal] = []
    for candidate in candidates:
        if not candidate.get("included", True):
            continue

        title = (candidate.get("title") or "").strip()
        if not title:
            continue

        try:
            category = GoalCategory(
                candidate.get("category", "personal_growth")
            )
        except ValueError:
            category = GoalCategory.PERSONAL_GROWTH

        try:
            priority = GoalPriority(
                candidate.get("priority", "need_more_info")
            )
        except ValueError:
            priority = GoalPriority.NEED_MORE_INFO

        target_quarter = candidate.get("target_quarter") or None
        if target_quarter is not None:
            target_quarter = str(target_quarter).strip()[:20] or None

        actions = candidate.get("actions") or None
        if actions is not None:
            actions = str(actions).strip() or None

        goal = Goal(
            title=title[:500],
            category=category,
            priority=priority,
            target_quarter=target_quarter,
            actions=actions,
            status=GoalStatus.NOT_STARTED,
            batch_id=batch_id,
        )
        db.session.add(goal)
        created.append(goal)

    if created:
        source = "scan_" + datetime.now(UTC).strftime("%Y_%m_%d_%H%M%S")
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()
    return created
