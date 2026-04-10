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

from models import ImportLog, Task, TaskType, Tier, db

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

    url = (
        "https://vision.googleapis.com/v1/images:annotate"
        f"?key={api_key}"
    )
    payload = {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode()},
                "features": [{"type": "TEXT_DETECTION"}],
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        # Network error, DNS, timeout, etc. Don't leak the full URL
        # (which contains the API key) into the error message.
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


# --- Create tasks from confirmed candidates ----------------------------------


def create_tasks_from_candidates(
    candidates: list[dict[str, Any]],
) -> list[Task]:
    """Create Task records from confirmed scan candidates.

    Each candidate is a dict with:
    - title (str): the task text (required)
    - type (str): "work" or "personal" (default: "work")
    - included (bool): whether the user confirmed this candidate

    Only candidates with included=True are created.
    All created tasks land in the Inbox tier.

    Stamps a shared ``batch_id`` on every created Task and writes an
    ``ImportLog`` entry so the scan can be undone as a group via the
    recycle bin flow.

    Args:
        candidates: List of candidate dicts from the review screen.

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
        source = "scan_" + datetime.now(UTC).strftime("%Y_%m_%d_%H%M%S")
        log = ImportLog(
            source=source, task_count=len(created), batch_id=batch_id
        )
        db.session.add(log)
        db.session.commit()
    return created
