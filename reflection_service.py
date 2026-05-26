"""Weekly Reflection — transcript → AI-proposed entity changes.

Pipeline (user-requested 2026-05-16):

1. Reflection text reaches the server either typed directly or as audio
   that ``voice_service.transcribe_audio`` (Whisper) turned into text.
2. ``analyze_reflection`` sends the transcript to Claude alongside a
   compact snapshot of the user's active projects / goals / tasks and
   asks for a JSON object of proposed create / update / delete actions,
   split into an "explicit" bucket (things the user actually said) and a
   "suggested" bucket (proactive cleanup the user opted into).
3. ``normalize_actions`` validates + shapes each action against the
   current data so the review UI can render a safe diff.
4. The user reviews + confirms; ``apply_selected_actions`` writes only
   the confirmed actions through the existing service layer. Created
   rows are grouped under a shared ``ImportLog`` batch so the whole
   reflection's creations can be undone in one click from the recycle
   bin. Deletes are soft (recycle bin) — never hard.

Security (per CLAUDE.md):
- Audio is handled by voice_service in memory only; this module never
  touches audio bytes, only the transcript string.
- The Claude call goes through ``scan_service._post_to_claude`` →
  ``egress.safe_call_api`` (ADR-006/007) — key in a header, never a
  query string, errors scrubbed.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from models import (
    Goal,
    Project,
    Reflection,
    ReflectionInputMode,
    Task,
    TaskStatus,
    db,
)

logger = logging.getLogger(__name__)

# Approximate Claude Sonnet 4.x pricing as of 2026-05 ($ per 1M tokens).
# Kept in code (not a DB table) for the same reason as Whisper pricing in
# voice_service: it changes only when Anthropic updates pricing, at which
# point we want a code review + deploy. Used only for the internal
# audit cost log — never shown to the user, so an approximate figure is
# acceptable.
_CLAUDE_USD_PER_MTOK_INPUT = 3.0
_CLAUDE_USD_PER_MTOK_OUTPUT = 15.0

# Cap the number of tasks fed into the snapshot so the prompt stays
# bounded on a busy board. Active tasks only; ordered most-recent first.
_MAX_SNAPSHOT_TASKS = 250

_VALID_OPS = {"create", "update", "delete"}
_VALID_ENTITIES = {"task", "goal", "project"}
_VALID_BUCKETS = {"explicit", "suggested"}

# Fields the AI is allowed to set per (op, entity). Anything else is
# dropped during normalisation so a hallucinated key can't reach the
# service layer (goal/project update_* raise on unknown keys).
_TASK_CREATE_FIELDS = {"title", "type", "tier", "due_date", "notes",
                       "project_hint", "goal_hint"}
_TASK_UPDATE_FIELDS = {"title", "type", "tier", "status", "due_date",
                       "notes", "project_hint", "goal_hint"}
_GOAL_CREATE_FIELDS = {"title", "category", "priority", "status",
                       "target_quarter", "actions", "notes"}
_GOAL_UPDATE_FIELDS = {"title", "category", "priority", "status",
                       "target_quarter", "actions", "notes",
                       "priority_rank"}
_PROJECT_CREATE_FIELDS = {"name", "type", "status", "target_quarter",
                          "actions", "notes", "goal_hint"}
_PROJECT_UPDATE_FIELDS = {"name", "type", "status", "target_quarter",
                          "actions", "notes"}


def current_iso_week(today: date | None = None) -> str:
    """Return the ISO week label, e.g. ``2026-W20``."""
    d = today or datetime.now(UTC).date()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# --- State snapshot ----------------------------------------------------------


def build_state_snapshot() -> dict[str, Any]:
    """Compact view of the user's active projects/goals/tasks for Claude.

    Only active entities are included (soft-deleted rows are out of
    scope for a reflection). Each row carries its UUID so the AI can
    target it for update/delete; new entities are referenced by
    name/title hint instead.
    """
    projects = list(
        db.session.scalars(
            select(Project).where(Project.is_active.is_(True))
        )
    )
    goals = list(
        db.session.scalars(
            select(Goal).where(Goal.is_active.is_(True))
        )
    )
    tasks = list(
        db.session.scalars(
            select(Task)
            .where(Task.status == TaskStatus.ACTIVE)
            .order_by(Task.updated_at.desc())
            .limit(_MAX_SNAPSHOT_TASKS)
        )
    )

    proj_by_id = {p.id: p for p in projects}
    goal_by_id = {g.id: g for g in goals}

    return {
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "type": p.type.value,
                "status": p.status.value,
                "priority": p.priority.value if p.priority else None,
            }
            for p in projects
        ],
        "goals": [
            {
                "id": str(g.id),
                "title": g.title,
                "category": g.category.value,
                "priority": g.priority.value,
                "status": g.status.value,
            }
            for g in goals
        ],
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "tier": t.tier.value,
                "type": t.type.value,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "project": (
                    proj_by_id[t.project_id].name
                    if t.project_id in proj_by_id
                    else None
                ),
                "goal": (
                    goal_by_id[t.goal_id].title
                    if t.goal_id in goal_by_id
                    else None
                ),
            }
            for t in tasks
        ],
    }


# --- Claude prompt + call ----------------------------------------------------


_REFLECT_PROMPT = """\
You are a planning assistant embedded in a personal task manager. The \
user just wrote (or spoke) a weekly reflection. Read it and propose \
concrete changes to their projects, goals, and tasks.

Today's date is {today} (ISO week {iso_week}).

The user's CURRENT state (only act on these — never invent IDs):

PROJECTS (id | name | type | status | priority):
{projects}

GOALS (id | title | category | priority | status):
{goals}

ACTIVE TASKS (id | title | tier | type | due | project | goal):
{tasks}

Allowed enum values:
- task.type: work, personal
- task.tier: today, tomorrow, this_week, next_week, backlog, freezer, inbox
- task.status: active, archived (= done/completed), cancelled (= consciously dropped)
- goal.category: health, personal_growth, relationships, work, bau
- goal.priority: must, should, could, need_more_info
- goal.status / project.status: not_started, in_progress, done, on_hold
- project.type: work, personal

Return ONLY a JSON object (no prose, no markdown fence) with exactly two
keys, "explicit" and "suggested", each an array of action objects:

- "explicit": changes the user DIRECTLY asked for or that follow
  unambiguously from what they said.
- "suggested": OPTIONAL proactive ideas based on the overall state
  (e.g. a goal with no active tasks, a stale task, an obviously
  finished project). The user opted in to these but they default to
  unchecked, so only include genuinely useful ones.

Each action object:
{{
  "op": "create" | "update" | "delete",
  "entity": "task" | "goal" | "project",
  "id": "<existing uuid>"          // REQUIRED for update/delete, omit for create
  "fields": {{ ... }},             // see below
  "reason": "one short sentence explaining why"
}}

fields by case:
- create task: title (required), type, tier, due_date ("YYYY-MM-DD" or null),
  notes, project_hint (verbatim project name from the list or null),
  goal_hint (verbatim goal title from the list or null)
- create goal: title (required), category, priority, status,
  target_quarter, actions, notes
- create project: name (required), type, status, target_quarter,
  actions, notes, goal_hint
- update <entity>: ONLY the fields that change (same field names as
  create; for update task you may also set status to archived/cancelled;
  for goal/project you may set status to done/on_hold to "finish" or
  "pause" it). Use project_hint / goal_hint to re-link a task.
- delete <entity>: no fields needed — soft-delete (recycle bin),
  reversible. Use this for "drop / remove / get rid of / kill".

Rules:
- "mark X done / finished / completed" → for a task: update status to
  archived. For a goal/project: update status to done.
- "park / pause / put X on hold / not now" → goal/project status
  on_hold; task tier freezer.
- Only reference ids that appear above. To attach a task to a project
  or goal you are CREATING in the same reflection, use the hint with
  the exact name/title you used in that create action.
- If the reflection contains no actionable changes, return
  {{"explicit": [], "suggested": []}}.

Reflection:
{transcript}
"""


def _call_claude(api_key: str, prompt: str) -> dict[str, Any]:
    """Make the Claude call. Separated for testability (tests patch this).

    Reuses ``scan_service._post_to_claude`` so the HTTP mechanics +
    egress wrapper are identical to the scan / voice pipelines.
    """
    from scan_service import _post_to_claude

    return _post_to_claude(api_key=api_key, prompt=prompt, max_tokens=4096)


def _claude_cost_usd(usage: dict[str, Any] | None) -> float | None:
    if not isinstance(usage, dict):
        return None
    in_tok = usage.get("input_tokens")
    out_tok = usage.get("output_tokens")
    if not isinstance(in_tok, int) or not isinstance(out_tok, int):
        return None
    return (
        in_tok / 1_000_000 * _CLAUDE_USD_PER_MTOK_INPUT
        + out_tok / 1_000_000 * _CLAUDE_USD_PER_MTOK_OUTPUT
    )


def _extract_action_object(text: str) -> dict[str, Any]:
    """Pull the ``{"explicit": [...], "suggested": [...]}`` object out of
    Claude's reply. Mirrors scan_service's tolerant parsing — direct
    parse, then markdown fence, then brace-bound fallback. Returns
    empty buckets on any failure rather than raising (a format blip
    becomes "no proposals", not a 500).
    """
    text = (text or "").strip()

    def _coerce(obj: Any) -> dict[str, Any] | None:
        if not isinstance(obj, dict):
            return None
        exp = obj.get("explicit")
        sug = obj.get("suggested")
        return {
            "explicit": exp if isinstance(exp, list) else [],
            "suggested": sug if isinstance(sug, list) else [],
        }

    try:
        got = _coerce(json.loads(text))
        if got is not None:
            return got
    except json.JSONDecodeError:
        pass

    if "```" in text:
        for part in text.split("```"):
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            try:
                got = _coerce(json.loads(cleaned))
                if got is not None:
                    return got
            except json.JSONDecodeError:
                continue

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            got = _coerce(json.loads(text[start : end + 1]))
            if got is not None:
                return got
        except json.JSONDecodeError:
            pass

    return {"explicit": [], "suggested": []}


def analyze_reflection(transcript: str) -> dict[str, Any]:
    """Send a reflection transcript to Claude and return proposed actions.

    Returns ``{"explicit": [...], "suggested": [...], "ai_cost_usd":
    float | None, "snapshot": {...}}`` where the action lists are
    normalised + validated against the current state.

    Raises:
        RuntimeError: if ANTHROPIC_API_KEY is missing or the call fails.
    """
    import os

    if not transcript or not transcript.strip():
        return {"explicit": [], "suggested": [], "ai_cost_usd": None,
                "snapshot": build_state_snapshot()}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    snapshot = build_state_snapshot()
    prompt = _REFLECT_PROMPT.format(
        today=datetime.now(UTC).date().isoformat(),
        iso_week=current_iso_week(),
        projects=_fmt_rows(
            snapshot["projects"],
            ("id", "name", "type", "status", "priority"),
        ),
        goals=_fmt_rows(
            snapshot["goals"],
            ("id", "title", "category", "priority", "status"),
        ),
        tasks=_fmt_rows(
            snapshot["tasks"],
            ("id", "title", "tier", "type", "due_date", "project", "goal"),
        ),
        transcript=transcript.strip(),
    )

    data = _call_claude(api_key, prompt)
    content = data.get("content", [{}])[0].get("text", "")
    raw = _extract_action_object(content)
    cost = _claude_cost_usd(data.get("usage"))

    return {
        "explicit": normalize_actions(raw.get("explicit", []),
                                      snapshot, "explicit"),
        "suggested": normalize_actions(raw.get("suggested", []),
                                       snapshot, "suggested"),
        "ai_cost_usd": cost,
        "snapshot": snapshot,
    }


def _fmt_rows(rows: list[dict[str, Any]], cols: tuple[str, ...]) -> str:
    if not rows:
        return "(none)"
    return "\n".join(
        " | ".join(str(r.get(c, "") if r.get(c) is not None else "")
                   for c in cols)
        for r in rows
    )


# --- Normalisation -----------------------------------------------------------


def _index(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build id + name lookup maps from a snapshot."""
    return {
        "task_ids": {t["id"] for t in snapshot.get("tasks", [])},
        "goal_ids": {g["id"] for g in snapshot.get("goals", [])},
        "project_ids": {p["id"] for p in snapshot.get("projects", [])},
        "task_label": {t["id"]: t["title"] for t in snapshot.get("tasks", [])},
        "goal_label": {g["id"]: g["title"] for g in snapshot.get("goals", [])},
        "project_label": {
            p["id"]: p["name"] for p in snapshot.get("projects", [])
        },
        "task_by_id": {t["id"]: t for t in snapshot.get("tasks", [])},
        "goal_by_id": {g["id"]: g for g in snapshot.get("goals", [])},
        "project_by_id": {
            p["id"]: p for p in snapshot.get("projects", [])
        },
    }


def normalize_actions(
    raw: list[Any], snapshot: dict[str, Any], bucket: str
) -> list[dict[str, Any]]:
    """Validate + shape raw AI actions for the review UI.

    Drops anything malformed (bad op/entity, update/delete with an id
    that isn't in the snapshot, create with no title). Restricts
    ``fields`` to the allowed set per (op, entity) so a hallucinated
    key never reaches the service layer.
    """
    idx = _index(snapshot)
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out

    for item in raw:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op", "")).strip().lower()
        entity = str(item.get("entity", "")).strip().lower()
        if op not in _VALID_OPS or entity not in _VALID_ENTITIES:
            continue

        reason = str(item.get("reason", "") or "").strip()
        fields = item.get("fields")
        if not isinstance(fields, dict):
            fields = {}

        if op in ("update", "delete"):
            rid = str(item.get("id", "") or "").strip()
            id_set = idx[f"{entity}_ids"]
            if rid not in id_set:
                continue
            label = idx[f"{entity}_label"].get(rid, rid)
            if op == "delete":
                out.append({
                    "op": "delete", "entity": entity, "bucket": bucket,
                    "id": rid, "target": label, "reason": reason,
                    "changes": [], "fields": {}, "payload": {},
                })
                continue
            allowed = (
                _TASK_UPDATE_FIELDS if entity == "task"
                else _GOAL_UPDATE_FIELDS if entity == "goal"
                else _PROJECT_UPDATE_FIELDS
            )
            clean = {k: v for k, v in fields.items() if k in allowed}
            if not clean:
                continue
            current = idx[f"{entity}_by_id"].get(rid, {})
            changes = _diff(entity, current, clean)
            out.append({
                "op": "update", "entity": entity, "bucket": bucket,
                "id": rid, "target": label, "reason": reason,
                "changes": changes, "fields": clean, "payload": clean,
            })
            continue

        # op == create
        allowed = (
            _TASK_CREATE_FIELDS if entity == "task"
            else _GOAL_CREATE_FIELDS if entity == "goal"
            else _PROJECT_CREATE_FIELDS
        )
        clean = {k: v for k, v in fields.items() if k in allowed}
        name_key = "name" if entity == "project" else "title"
        label = str(clean.get(name_key, "") or "").strip()
        if not label:
            continue
        out.append({
            "op": "create", "entity": entity, "bucket": bucket,
            "id": None, "target": label, "reason": reason,
            "changes": [], "fields": clean, "payload": clean,
        })

    return out


def _diff(
    entity: str, current: dict[str, Any], proposed: dict[str, Any]
) -> list[dict[str, Any]]:
    """Human-readable old→new pairs for the review UI (display only)."""
    # Map proposed field names onto the snapshot's field names so the
    # "from" side resolves. project_hint/goal_hint show against the
    # snapshot's project/goal label.
    alias = {"project_hint": "project", "goal_hint": "goal"}
    changes: list[dict[str, Any]] = []
    for field, to_val in proposed.items():
        src = alias.get(field, field)
        from_val = current.get(src)
        if str(from_val or "") == str(to_val or ""):
            continue
        changes.append({
            "field": field,
            "from": from_val,
            "to": to_val,
        })
    return changes


# --- Persistence + apply -----------------------------------------------------


def save_reflection(
    *,
    transcript: str,
    input_mode: ReflectionInputMode,
    proposed: dict[str, Any],
    audio_duration_seconds: float | None = None,
    audio_cost_usd: float | None = None,
    ai_cost_usd: float | None = None,
    raw_segments: list[dict[str, Any]] | None = None,
) -> Reflection:
    """Persist a reflection + its proposed actions. Transcript is kept
    forever for future reference (the explicit user requirement).

    #237 (2026-05-26): ``raw_segments`` is the list of per-segment
    Whisper transcripts from the #232 pause/resume flow. Each entry
    is a dict ``{text, duration_seconds, cost_usd, recorded_at}``.
    Defaults to ``[]`` (typed reflections + voice reflections that
    pre-date #237).
    """
    reflection = Reflection(
        iso_week=current_iso_week(),
        input_mode=input_mode,
        transcript=transcript.strip(),
        audio_duration_seconds=audio_duration_seconds,
        audio_cost_usd=audio_cost_usd,
        ai_cost_usd=ai_cost_usd,
        raw_segments=_normalise_raw_segments(raw_segments),
        proposed_actions={
            "explicit": proposed.get("explicit", []),
            "suggested": proposed.get("suggested", []),
        },
    )
    db.session.add(reflection)
    db.session.commit()
    return reflection


def _normalise_raw_segments(
    raw_segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """#237: coerce client-supplied raw_segments to the persisted shape.

    Drops non-dict entries, coerces field types, caps text length to
    20000 chars per segment (same as the textarea maxlength), drops
    segments with empty text. Returns ``[]`` if the input is None or
    everything got dropped.
    """
    if not isinstance(raw_segments, list):
        return []
    out: list[dict[str, Any]] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        text = seg.get("text")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue
        # Length cap (defense against an unbounded client send). The
        # textarea maxlength is 20000; one segment is a subset.
        if len(text) > 20000:
            text = text[:20000]

        # Optional telemetry fields — coerce to float, drop if invalid.
        duration = seg.get("duration_seconds")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        cost = seg.get("cost_usd")
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None

        # recorded_at is a client-supplied ISO timestamp. Validate the
        # shape — anything that doesn't parse becomes None rather than
        # raising (we never want a stray client field to discard the
        # transcript text).
        recorded_at = seg.get("recorded_at")
        if isinstance(recorded_at, str):
            recorded_at = recorded_at.strip() or None
            # Cap to a reasonable timestamp length to avoid an
            # unbounded send.
            if recorded_at and len(recorded_at) > 64:
                recorded_at = None
        else:
            recorded_at = None

        out.append({
            "text": text,
            "duration_seconds": duration,
            "cost_usd": cost,
            "recorded_at": recorded_at,
        })
    return out


def attach_analysis(
    reflection: Reflection,
    *,
    proposed: dict[str, Any],
    ai_cost_usd: float | None = None,
) -> Reflection:
    """Attach Claude's proposed actions to an already-persisted
    reflection.

    Split out from save_reflection so the transcript can be committed
    BEFORE the (failure-prone, paid) Claude call — a transient Claude
    outage must never discard a reflection the user already typed or
    a voice memo that already cost a Whisper transcription. The #165
    spec requires "every transcript persisted forever"; persisting
    only on analysis success violated that. The endpoint now does
    save_reflection() → analyze_reflection() → attach_analysis(), so
    a Claude failure leaves a saved (analysable-later) reflection
    rather than losing it.
    """
    reflection.proposed_actions = {
        "explicit": proposed.get("explicit", []),
        "suggested": proposed.get("suggested", []),
    }
    if ai_cost_usd is not None:
        reflection.ai_cost_usd = ai_cost_usd
    db.session.commit()
    return reflection


def get_reflection(reflection_id: uuid.UUID) -> Reflection | None:
    return db.session.get(Reflection, reflection_id)


def list_reflections(
    limit: int = 100,
    *,
    include_archived: bool = False,
    include_deleted: bool = False,
) -> list[Reflection]:
    """List reflections, newest first.

    #238 (2026-05-26):
      - ``include_archived=False`` (default) hides rows where
        ``is_archived=True``. UI passes ``True`` when the "Show
        archived" toggle is on.
      - ``include_deleted=False`` (default) hides rows where
        ``is_active=False`` (soft-deleted). UI passes ``True`` only
        for the Recently-deleted section so the user can restore.
    """
    stmt = select(Reflection)
    if not include_archived:
        stmt = stmt.where(Reflection.is_archived.is_(False))
    if not include_deleted:
        stmt = stmt.where(Reflection.is_active.is_(True))
    stmt = stmt.order_by(Reflection.created_at.desc()).limit(limit)
    return list(db.session.scalars(stmt))


def set_reflection_archived(
    reflection_id: uuid.UUID, archived: bool,
) -> Reflection | None:
    """Toggle a reflection's archived flag. Returns the updated
    Reflection or None if not found.

    Idempotent: setting archived=True on an already-archived row is
    a no-op (no error). Soft-deleted rows can still be archived/
    unarchived — the two flags are independent (deleted+archived is
    a valid state; restore handles the active flag, unarchive handles
    the archived flag).
    """
    r = get_reflection(reflection_id)
    if r is None:
        return None
    if r.is_archived != bool(archived):
        r.is_archived = bool(archived)
        db.session.commit()
    return r


def soft_delete_reflection(reflection_id: uuid.UUID) -> Reflection | None:
    """Mark a reflection inactive (soft-delete). Idempotent."""
    r = get_reflection(reflection_id)
    if r is None:
        return None
    if r.is_active:
        r.is_active = False
        db.session.commit()
    return r


def restore_reflection(reflection_id: uuid.UUID) -> Reflection | None:
    """Restore a soft-deleted reflection. Idempotent."""
    r = get_reflection(reflection_id)
    if r is None:
        return None
    if not r.is_active:
        r.is_active = True
        db.session.commit()
    return r


def _resolve_ref(hint: Any, index: dict[str, uuid.UUID]) -> str | None:
    """Resolve a case-insensitive name/title hint to a UUID string."""
    if not hint or not isinstance(hint, str):
        return None
    found = index.get(hint.strip().lower())
    return str(found) if found else None


def apply_selected_actions(
    reflection: Reflection, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply the user-confirmed actions through the existing service layer.

    Created rows are grouped under shared ``ImportLog`` batches (one per
    entity kind) via the import_service / scan_service creators so the
    whole reflection's creations are undoable from the recycle bin.
    Updates/deletes go through the canonical ``*_service`` functions;
    deletes are soft. Order: create projects → goals → tasks → updates →
    deletes, so a task can link to a project/goal created in the same
    reflection.

    Returns a summary dict and records it (plus the confirmed actions)
    on the Reflection row as the audit trail.
    """
    from import_service import (
        create_goals_from_import,
        create_projects_from_import,
    )
    from scan_service import create_tasks_from_candidates

    summary: dict[str, Any] = {
        "created": {"task": 0, "goal": 0, "project": 0},
        "updated": {"task": 0, "goal": 0, "project": 0},
        "deleted": {"task": 0, "goal": 0, "project": 0},
        "errors": [],
    }

    creates = {"task": [], "goal": [], "project": []}
    updates: list[dict[str, Any]] = []
    deletes: list[dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        op = a.get("op")
        entity = a.get("entity")
        if op not in _VALID_OPS or entity not in _VALID_ENTITIES:
            continue
        if op == "create":
            creates[entity].append(a)
        elif op == "update":
            updates.append(a)
        else:
            deletes.append(a)

    # 1. Create projects + goals first so tasks can link to them.
    #
    # #174 (2026-05-21): each create step is wrapped in its own
    # try/except — mirroring the update/delete loops below. Before this,
    # a failure inside any import creator bubbled straight out of
    # apply_selected_actions; the route's catch-all then returned an
    # opaque 500 and the partial `summary` (what DID land) was lost.
    # Now a create-step failure is captured in summary["errors"], the
    # session is rolled back, and the remaining steps still run.
    try:
        proj_objs = create_projects_from_import(
            [_project_candidate(a) for a in creates["project"]],
            source="reflection_project",
        )
        summary["created"]["project"] = len(proj_objs)
    except Exception as e:  # noqa: BLE001 — surface, don't crash batch
        db.session.rollback()
        summary["errors"].append(
            f"create projects: {type(e).__name__}: {e}"
        )

    try:
        goal_objs = create_goals_from_import(
            [_goal_candidate(a) for a in creates["goal"]],
            source="reflection_goal",
        )
        summary["created"]["goal"] = len(goal_objs)
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        summary["errors"].append(
            f"create goals: {type(e).__name__}: {e}"
        )

    # Build name→id maps INCLUDING rows just created so a task's
    # project_hint / goal_hint can resolve to brand-new entities too.
    project_index: dict[str, uuid.UUID] = {}
    for p in db.session.scalars(
        select(Project).where(Project.is_active.is_(True))
    ):
        project_index[p.name.strip().lower()] = p.id
    goal_index: dict[str, uuid.UUID] = {}
    for g in db.session.scalars(
        select(Goal).where(Goal.is_active.is_(True))
    ):
        goal_index[g.title.strip().lower()] = g.id

    # 2. Create tasks.
    task_candidates = []
    for a in creates["task"]:
        f = a.get("payload") or a.get("fields") or {}
        task_candidates.append({
            "title": (f.get("title") or "").strip(),
            "type": f.get("type") or "work",
            "tier": f.get("tier") or "inbox",
            "due_date": f.get("due_date") or "",
            "project_id": _resolve_ref(f.get("project_hint"), project_index)
            or "",
            "goal_id": _resolve_ref(f.get("goal_hint"), goal_index) or "",
            "included": True,
        })
    try:
        task_objs = create_tasks_from_candidates(
            task_candidates, source_prefix="reflection"
        )
        summary["created"]["task"] = len(task_objs)
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        summary["errors"].append(
            f"create tasks: {type(e).__name__}: {e}"
        )

    # 3. Updates.
    for a in updates:
        entity = a["entity"]
        rid = _parse_uuid(a.get("id"))
        if rid is None:
            summary["errors"].append(f"update {entity}: bad id")
            continue
        payload = dict(a.get("payload") or a.get("fields") or {})
        try:
            if entity == "task":
                _apply_task_link_hints(
                    payload, project_index, goal_index, summary
                )
                from task_service import update_task
                ok = update_task(rid, payload) is not None
            elif entity == "goal":
                from goal_service import update_goal
                ok = update_goal(rid, payload) is not None
            else:
                from project_service import update_project
                ok = update_project(rid, payload) is not None
        except Exception as e:  # noqa: BLE001 — surface, don't crash batch
            db.session.rollback()
            summary["errors"].append(
                f"update {entity} {rid}: {type(e).__name__}: {e}"
            )
            continue
        if ok:
            summary["updated"][entity] += 1
        else:
            summary["errors"].append(f"update {entity} {rid}: not found")

    # 4. Deletes (soft — recycle bin).
    for a in deletes:
        entity = a["entity"]
        rid = _parse_uuid(a.get("id"))
        if rid is None:
            summary["errors"].append(f"delete {entity}: bad id")
            continue
        try:
            if entity == "task":
                from task_service import delete_task
                ok = delete_task(rid)
            elif entity == "goal":
                from goal_service import delete_goal
                ok = delete_goal(rid)
            else:
                from project_service import delete_project
                ok = delete_project(rid)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            summary["errors"].append(
                f"delete {entity} {rid}: {type(e).__name__}: {e}"
            )
            continue
        if ok:
            summary["deleted"][entity] += 1
        else:
            summary["errors"].append(f"delete {entity} {rid}: not found")

    # Persist the audit record. #174: wrap so a failure here also lands
    # in summary["errors"] instead of bubbling to an opaque 500 —
    # apply_selected_actions never raises, so the route always has a
    # summary to return. On failure `applied_at` stays None; the route
    # guards the .isoformat() access accordingly.
    try:
        reflection.applied_actions = {"actions": actions, "summary": summary}
        reflection.applied_at = datetime.now(UTC)
        db.session.commit()
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        reflection.applied_at = None
        summary["errors"].append(
            f"failed to persist reflection audit record: "
            f"{type(e).__name__}: {e}"
        )
    return summary


def _apply_task_link_hints(
    payload: dict[str, Any],
    project_index: dict[str, uuid.UUID],
    goal_index: dict[str, uuid.UUID],
    summary: dict[str, Any],
) -> None:
    """Translate project_hint/goal_hint in an update payload into the
    project_id/goal_id keys update_task understands.

    #181 (2026-05-21): when a hint does NOT resolve — Claude proposed a
    stale or hallucinated project/goal name — the old code set
    ``payload["project_id"] = None``. ``update_task`` treats an
    explicit ``None`` as "clear this field", so an unresolved hint
    SILENTLY wiped the task's existing project/goal link (same
    silent-payload-drop class as #57, but originating server-side from
    the AI rather than the client). Now: a hint that resolves sets the
    id; a hint that does NOT resolve has its key popped entirely —
    ``update_task``'s "absent key = no change" semantics then preserves
    the original link — and a non-empty unresolved hint is surfaced in
    ``summary["errors"]`` so the user sees what happened.
    """
    if "project_hint" in payload:
        hint = payload.pop("project_hint")
        resolved = _resolve_ref(hint, project_index)
        if resolved is not None:
            payload["project_id"] = resolved
        elif isinstance(hint, str) and hint.strip():
            # Non-empty hint that matched nothing — a real miss worth
            # telling the user about. (An empty/None hint just means
            # "no project hint" — pop silently, no warning.)
            summary["errors"].append(
                f"project_hint {hint.strip()!r} not found — "
                f"kept the task's existing project"
            )
    if "goal_hint" in payload:
        hint = payload.pop("goal_hint")
        resolved = _resolve_ref(hint, goal_index)
        if resolved is not None:
            payload["goal_id"] = resolved
        elif isinstance(hint, str) and hint.strip():
            summary["errors"].append(
                f"goal_hint {hint.strip()!r} not found — "
                f"kept the task's existing goal"
            )


def _project_candidate(a: dict[str, Any]) -> dict[str, Any]:
    f = a.get("payload") or a.get("fields") or {}
    return {
        "name": (f.get("name") or "").strip(),
        "type": f.get("type") or "work",
        "status": f.get("status") or "not_started",
        "target_quarter": f.get("target_quarter") or "",
        "actions": f.get("actions") or "",
        "notes": f.get("notes") or "",
        "linked_goal": f.get("goal_hint") or "",
        "included": True,
    }


def _goal_candidate(a: dict[str, Any]) -> dict[str, Any]:
    f = a.get("payload") or a.get("fields") or {}
    return {
        "title": (f.get("title") or "").strip(),
        "category": f.get("category") or "work",
        "priority": f.get("priority") or "should",
        "status": f.get("status") or "not_started",
        "target_quarter": f.get("target_quarter") or "",
        "actions": f.get("actions") or "",
        "notes": f.get("notes") or "",
        "included": True,
    }


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None
