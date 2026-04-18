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
    import requests

    # API key in header (X-Goog-Api-Key) instead of URL query param.
    # URL query params show up in proxy/CDN/Railway egress logs;
    # headers don't. See docs/adr/007-api-key-in-header.md.
    url = "https://vision.googleapis.com/v1/images:annotate"
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        # Network error, DNS, timeout, etc.
        raise RuntimeError(f"Vision API network error: {type(e).__name__}") from e

    if not resp.ok:
        # Try to pull Google's own error message out of the body.
        detail = ""
        try:
            body = resp.json()
            detail = (
                body.get("error", {}).get("message")
                or body.get("error", {}).get("status")
                or ""
            )
        except ValueError:
            detail = resp.text[:200]
        raise RuntimeError(
            f"Vision API returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else "")
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError("Vision API returned invalid JSON") from e

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

    Wraps failure modes in RuntimeError with a safe, descriptive
    message — the API key is never included.
    """
    import requests

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": _PARSE_PROMPT.format(ocr_text=ocr_text),
            }
        ],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"Claude API network error: {type(e).__name__}") from e

    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") or ""
        except ValueError:
            detail = resp.text[:200]
        raise RuntimeError(
            f"Claude API returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else "")
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError("Claude API returned invalid JSON") from e

    content = data.get("content", [{}])[0].get("text", "")
    return _extract_json_array(content)


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
    """Make the Claude API call for goal extraction. Separated for testability."""
    import requests

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": _GOAL_PARSE_PROMPT.format(ocr_text=ocr_text),
            }
        ],
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(
            f"Claude API network error: {type(e).__name__}"
        ) from e

    if not resp.ok:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") or ""
        except ValueError:
            detail = resp.text[:200]
        raise RuntimeError(
            f"Claude API returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else "")
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError("Claude API returned invalid JSON") from e

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


# --- Create tasks from confirmed candidates ----------------------------------


def create_tasks_from_candidates(
    candidates: list[dict[str, Any]],
    source_prefix: str = "scan",
) -> list[Task]:
    """Create Task records from confirmed candidates.

    Each candidate is a dict with:
    - title (str): the task text (required)
    - type (str): "work" or "personal" (default: "work")
    - included (bool): whether the user confirmed this candidate

    Only candidates with included=True are created.
    All created tasks land in the Inbox tier.

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

        task = Task(
            title=title,
            type=task_type,
            tier=Tier.INBOX,
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
