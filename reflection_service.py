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
  touches audio bytes, only the transcript string. Server-side audio
  never reaches disk or the DB. (#327 added a transient DEVICE-local
  buffer in the browser — see static/audio_buffer.js; nothing about the
  server side changed.)
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
from reflection_context_service import (
    context_files_block,
    normalise_context_files,
)
from utils import local_datetime_from_dt

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
{milestone}
{continuation}
{synthesis}
{recent_reflections}
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
{context_files}
Reflection:
{transcript}
"""


# #337: reflection analysis is a LONG call and must not run on the 60s
# client default. `weekly_planner_service` already learned this ("large
# max_tokens outputs genuinely take 60-150s end to end") and uses 180s;
# reflection issues the same 4096-token request and, since #328, may ship
# up to MAX_TOTAL_CHARS (60_000) of attached-document text on top of an
# arbitrarily long transcript. A real user hit ReadTimeout on 2026-09-24
# with ~44k chars of documents attached to a multi-hour reflection.
_ANALYSIS_TIMEOUT_SEC = 180


def _call_claude(api_key: str, prompt: str) -> dict[str, Any]:
    """Make the Claude call. Separated for testability (tests patch this).

    Calls ``claude_client.call_claude`` directly rather than going via
    ``scan_service._post_to_claude``: that delegator takes no timeout, so
    routing through it silently pinned this path to the 60s default (#337).
    Same model and egress wrapper as the scan / voice pipelines.
    """
    from claude_client import SONNET, call_claude

    return call_claude(
        api_key=api_key,
        prompt=prompt,
        max_tokens=4096,
        model=SONNET,
        timeout_sec=_ANALYSIS_TIMEOUT_SEC,
    )


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


# #325: how many past reflections Claude sees, and how much of each.
# Three is enough to establish "what I said I'd do and whether it
# happened" without turning every analysis into a re-read of the whole
# history (tokens, and older context crowds out this week's words).
_RECENT_REFLECTION_COUNT = 3
_RECENT_REFLECTION_CHARS = 1200

# --- Combined analysis budgets (#335) ---------------------------------------
# A synthesis feeds FULL transcripts, not the 1200-char continuity snippet --
# seeing a snippet of each sitting is exactly the limitation this feature
# exists to remove. That makes the input genuinely large, so it needs its own
# ceilings.
#
# MAX_COMBINED: more than ten sittings at once stops being a look-back and
# starts being the whole archive; the response is still capped at
# `max_tokens=4096` however much goes in, so a hundred-sitting request would
# just produce a thinner answer at a higher price.
MAX_COMBINED = 10
# ~30k tokens of transcript, which leaves comfortable room alongside the 60k
# characters of attached documents #328 already allows and the state snapshot.
MAX_COMBINED_CHARS = 120_000


def _milestone_block() -> str:
    """The runway line, wrapped for the prompt. Empty when unset."""
    try:
        from milestone_service import milestone_prompt_line
        line = milestone_prompt_line()
    except Exception:  # noqa: BLE001 — context is a bonus, never a blocker
        logger.exception("milestone prompt line failed; continuing without it")
        return ""
    return f"\n{line}\n" if line else ""


def recent_reflections_block(exclude_id=None, exclude_ids=None) -> str:
    """Prior reflections, newest first, as prompt context (#325).

    Turns a series of isolated check-ins into a thread: Claude can see
    what the user committed to last time and whether this week's words
    follow through. Truncated per-reflection so a long transcript can't
    crowd out the one being analysed. Best-effort — an error here must
    never block the analysis.

    ``exclude_ids`` (#334) drops additional rows. The continuation path
    uses it for the PARENT reflection: its words are already in the
    transcript verbatim and in full, so also listing it here would hand
    Claude the same text twice — once complete, once truncated to
    ``_RECENT_REFLECTION_CHARS`` — and invite it to read the user's own
    sentences as a previous week's commitment.
    """
    skip = set()
    if exclude_id is not None:
        skip.add(exclude_id)
    if exclude_ids:
        skip.update(i for i in exclude_ids if i is not None)
    try:
        # Over-fetch: skipped ids and #335 synthesis rows both drop out
        # below, and stopping at exactly three rows would let a couple of
        # look-backs push every real sitting out of the continuity block.
        rows = list_reflections(
            limit=_RECENT_REFLECTION_COUNT * 4 + len(skip)
        )
    except Exception:  # noqa: BLE001
        logger.exception("recent reflections lookup failed; continuing")
        return ""
    lines = []
    for r in rows:
        if r.id in skip:
            continue
        # #335: a synthesis row's transcript is a one-line header naming
        # the sittings it read. As continuity that is noise -- it carries
        # none of the thinking, and it would displace a real reflection.
        if r.synthesis_of:
            continue
        if len(lines) >= _RECENT_REFLECTION_COUNT:
            break
        text = (r.transcript or "").strip()
        if not text:
            continue
        if len(text) > _RECENT_REFLECTION_CHARS:
            text = text[:_RECENT_REFLECTION_CHARS].rstrip() + "…"
        # #339: if the user named the sitting, carry the name into the
        # prompt -- it is their own words for what that session was
        # about, far better continuity signal than a date alone.
        # #340: via reflection_label rather than open-coded, so this
        # block gets the user's LOCAL day and time like everywhere else.
        # It had its own copy of the rule, and so its own copy of the
        # UTC-date drift.
        lines.append(f"[{reflection_label(r)}] {text}")
    if not lines:
        return ""
    body = "\n\n".join(lines)
    return (
        "\nThe user's PREVIOUS reflections (newest first) — use these for "
        "continuity: notice what they committed to before, what recurs, and "
        "what has quietly stalled. Do NOT re-propose something already "
        "acted on.\n"
        f"{body}\n"
    )


def _applied_action_lines(reflection: Reflection) -> list[str]:
    """One short line per action the user actually APPLIED from a
    reflection, for the #334 continuation block.

    Reads the ``applied_actions`` audit record written by
    ``apply_selected_actions`` — shape ``{"actions": [...], "summary":
    {...}}``. Only the confirmed actions are listed: a PROPOSED action
    the user declined is not something to warn Claude off, it is
    something they chose not to do.
    """
    audit = reflection.applied_actions or {}
    actions = audit.get("actions") if isinstance(audit, dict) else None
    if not isinstance(actions, list):
        return []
    lines = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        op = str(a.get("op") or "?")
        entity = str(a.get("entity") or "?")
        fields = a.get("fields") if isinstance(a.get("fields"), dict) else {}
        name = fields.get("title") or fields.get("name") or a.get("id") or ""
        name = str(name).strip()
        # Keep the prompt tight — this is a reminder, not a record.
        if len(name) > 120:
            name = name[:120].rstrip() + "…"
        lines.append(f"- {op} {entity}: {name}" if name else f"- {op} {entity}")
        if len(lines) >= 40:
            break
    return lines


def continuation_block(parent: Reflection | None) -> str:
    """#334: tell Claude this reflection continues an earlier sitting.

    Two things it must know, neither of which is inferable from the
    transcript alone:

    1. The leading text is carried over, not written today. Without this
       the model reads a month-old paragraph as "what the user just
       said" and dates its proposals wrongly.
    2. Some of the earlier sitting's actions were already APPLIED. The
       tasks and goals they created are in the state snapshot below, so
       re-proposing them would read as a duplicate suggestion.

    This is prompt-level guidance, not a mechanical guarantee — the same
    honest caveat as the #333 checkpoint flow. The human confirm step
    remains the real control over what actually gets written.
    """
    if parent is None:
        return ""
    # #340: the third open-coded copy of the label rule, and the third
    # with the UTC-date drift. All three now go through reflection_label,
    # which also means a continuation banner and a synthesis header name
    # the same sitting the same way.
    label = reflection_label(parent)
    out = [
        # A leading empty element renders as the blank line that separates
        # this block from the milestone line above it.
        "",
        f"THIS REFLECTION CONTINUES AN EARLIER SITTING — {label}.",
        "That sitting's words open the reflection below verbatim; the new "
        "thinking follows them. Read the whole thing as ONE train of "
        "thought and date it to today, not to when the earlier part was "
        "written.",
    ]
    applied = _applied_action_lines(parent)
    if applied:
        out.append(
            "These changes from that sitting were ALREADY APPLIED — they "
            "exist in the state below, so do NOT propose them again:"
        )
        out.extend(applied)
    else:
        out.append(
            "Nothing from that sitting was applied, so its proposals are "
            "still open."
        )
    out.append("")
    return "\n".join(out)


def reflection_label(r: Reflection) -> str:
    """How one sitting is named in prompt text and in a synthesis header.

    Mirrors the client's ``reflectionLabel``: the user's own name when
    there is one, otherwise when it happened. A name is far better signal
    than a timestamp -- it is the user's summary of what that sitting was
    for.

    #340 (2026-09-25) -- the TIME, and the user's timezone. Two things
    were wrong with naming a sitting by ``created_at.date()``:

    1. Two untitled sittings on one day produced byte-identical labels,
       so a synthesis header listed ``- 2026-05-17`` twice and the prompt
       fences could not be told apart. #339 fixed exactly this for the
       history list by adding a time.
    2. ``created_at.date()`` is the UTC date. A 9pm ET reflection is
       01:00 UTC the NEXT day, so the label already named the wrong day
       and already disagreed with the history row -- no collision needed.

    Both are one fix: render the instant in the user's zone. That is not
    a new convention -- ``utils.local_today_date`` has answered "what
    time zone is the user in?" with ``DIGEST_TZ`` (default
    America/New_York) since audit fix #128, and this uses the same
    answer. It is also what makes this label AGREE with the history row,
    which renders the same instant in the browser's zone.

    The remaining asymmetry with the client is deliberate:
    ``reflectionLabel`` also appends the capture mode, because a history
    row must never render blank. A prompt fence has no such need, and
    "typed" tells Claude nothing.
    """
    local = local_datetime_from_dt(r.created_at)
    when = local.strftime("%Y-%m-%d %H:%M") if local else r.iso_week
    name = (r.title or "").strip()
    return f"{when} · {name}" if name else when


def combined_transcript(sources: list[Reflection]) -> tuple[str, list[str]]:
    """Concatenate several sittings into one prompt body, newest LAST.

    Chronological order matters: the model is being asked what changed
    and what went quiet, and that only reads correctly forwards.

    Returns ``(text, shortened_labels)``. Each sitting is fenced with its
    own dated header so the model can attribute a thought to a date --
    without that a synthesis is one undifferentiated wall of text and
    "you said this three weeks ago and again last week" becomes
    unsayable.

    The whole point of this feature is that transcripts arrive in FULL
    rather than as the 1200-char continuity snippet, so truncation here
    is a last resort against ``MAX_COMBINED_CHARS``. When it does happen
    the affected sittings are named in the returned list and reported to
    the user -- silently handing Claude half a reflection and presenting
    the result as a complete look-back would be the worst outcome.
    """
    ordered = sorted(sources, key=lambda r: (r.created_at or datetime.min))
    budget = MAX_COMBINED_CHARS
    per = max(1, budget // max(1, len(ordered)))
    parts: list[str] = []
    shortened: list[str] = []
    for i, r in enumerate(ordered, start=1):
        text = (r.transcript or "").strip()
        if not text:
            continue
        # An equal share each, so one enormous sitting cannot starve the
        # rest. Anything unspent by a short sitting is handed on below.
        allowance = max(per, budget - (len(ordered) - i) * per)
        if len(text) > allowance:
            text = text[:allowance].rstrip() + "…"
            shortened.append(reflection_label(r))
        budget -= len(text)
        parts.append(
            f"=== Sitting {i} of {len(ordered)} — {reflection_label(r)} ===\n"
            f"{text}"
        )
    return "\n\n".join(parts), shortened


def synthesis_block(
    sources: list[Reflection], shortened: list[str] | None = None,
) -> str:
    """#335: tell Claude it is reading several sittings at once.

    Without this the combined text reads as one very long weekly
    reflection, and the model answers the wrong question -- it proposes
    an action per paragraph instead of naming what recurs and what
    quietly stalled, which is the only reason to read them together.

    Actions already APPLIED across the selected sittings are listed for
    the same reason as in ``continuation_block``: they exist in the state
    snapshot below, so re-proposing them reads as a duplicate.
    """
    if not sources:
        return ""
    ordered = sorted(sources, key=lambda r: (r.created_at or datetime.min))
    first = reflection_label(ordered[0])
    last = reflection_label(ordered[-1])
    span = first if len(ordered) == 1 else f"{first} to {last}"
    out = [
        "",
        f"THIS IS A LOOK BACK ACROSS {len(ordered)} REFLECTIONS — {span}.",
        "They are separate sittings, each fenced and dated below, read "
        "together on purpose. This is NOT a new weekly reflection: answer "
        "the question the user is really asking by selecting them, which "
        "is what has been building up across these sittings.",
        "So: name what RECURS, what they committed to and then stopped "
        "mentioning, and where they have drifted from what they said they "
        "would do. Prefer a few well-grounded proposals over one per "
        "sitting, and ground each in the dates it came from.",
    ]
    applied: list[str] = []
    for r in ordered:
        applied.extend(_applied_action_lines(r))
    if applied:
        out.append(
            "These changes were ALREADY APPLIED from these sittings — "
            "they exist in the state below, so do NOT propose them again:"
        )
        out.extend(applied[:60])
    if shortened:
        out.append(
            "NOTE: these sittings were too long to include in full and are "
            "cut short: " + ", ".join(shortened) + ". Do not treat their "
            "endings as the user's final word."
        )
    out.append("")
    return "\n".join(out)


def analyze_reflection(
    transcript: str, exclude_id=None, context_files=None,
    continued_from=None, synthesis_sources=None, shortened=None,
) -> dict[str, Any]:
    """Send a reflection transcript to Claude and return proposed actions.

    Returns ``{"explicit": [...], "suggested": [...], "ai_cost_usd":
    float | None, "snapshot": {...}}`` where the action lists are
    normalised + validated against the current state.

    ``exclude_id`` (#325) is the id of the reflection being analysed.
    The API persists the transcript BEFORE calling this, so without it
    the reflection would appear in its own "previous reflections"
    context — handing Claude the same words twice and inviting it to
    treat this week's thoughts as last week's commitments.

    ``context_files`` (#328) are the attached documents' extracted text.
    They are rendered into a fenced, explicitly-untrusted block — see
    ``reflection_context_service`` and ADR-037 for why a document's
    contents must never be read as instructions.

    ``synthesis_sources`` (#335) are the reflections a COMBINED analysis
    is reading together. They reframe the prompt (look back across, don't
    react to) and drop out of the continuity list, where their text would
    otherwise appear a second time in truncated form. ``shortened`` names
    any whose transcript had to be cut to fit the budget.

    ``continued_from`` (#334) is the Reflection this one forked from, if
    any. It does two things: names the carry-over in the prompt so the
    older paragraphs aren't read as today's words, and drops that
    reflection from the "previous reflections" list, where it would
    otherwise appear a second time in truncated form.

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
        # #325: runway + continuity. Without these every reflection is
        # analysed cold — week 4 has no idea what week 1 committed to,
        # and no idea a deadline exists.
        milestone=_milestone_block(),
        # #334: names the forked-from sitting and what was already applied
        # from it. Collapses to "" for an ordinary reflection.
        continuation=continuation_block(continued_from),
        # #335: reframes the task when several sittings are read at once.
        # Collapses to "" for a single reflection.
        synthesis=synthesis_block(synthesis_sources or [], shortened),
        recent_reflections=recent_reflections_block(
            exclude_id=exclude_id,
            # #334/#335: these rows' full text is already in the
            # transcript, so listing them again truncated would hand
            # Claude the same words twice.
            exclude_ids=(
                ([continued_from.id] if continued_from is not None else [])
                + [r.id for r in (synthesis_sources or [])]
            ),
        ),
        # #328: attached documents, fenced and marked as data-not-
        # instructions. Collapses to "" when nothing is attached, so a
        # reflection without files gets byte-identical prompt to before.
        context_files=context_files_block(context_files),
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
    context_files: list[dict[str, Any]] | None = None,
    continued_from_id: uuid.UUID | None = None,
) -> Reflection:
    """Persist a reflection + its proposed actions. Transcript is kept
    forever for future reference (the explicit user requirement).

    #237 (2026-05-26): ``raw_segments`` is the list of per-segment
    Whisper transcripts from the #232 pause/resume flow. Each entry
    is a dict ``{text, duration_seconds, cost_usd, recorded_at}``.
    Defaults to ``[]`` (typed reflections + voice reflections that
    pre-date #237).

    #328 (2026-09-23): ``context_files`` carries the EXTRACTED TEXT of
    any documents the user attached (never the files themselves). Kept
    with the reflection so a retrospective can see what informed it.

    #334 (2026-09-24): ``continued_from_id`` records that this sitting
    was forked from an earlier one. The parent row is not touched — that
    is the whole point of forking rather than re-opening.
    """
    reflection = Reflection(
        iso_week=current_iso_week(),
        input_mode=input_mode,
        transcript=transcript.strip(),
        audio_duration_seconds=audio_duration_seconds,
        audio_cost_usd=audio_cost_usd,
        ai_cost_usd=ai_cost_usd,
        raw_segments=_normalise_raw_segments(raw_segments),
        context_files=normalise_context_files(context_files),
        continued_from_id=continued_from_id,
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


def reset_applied_state(reflection: Reflection) -> Reflection:
    """Clear the applied audit fields so this row can be applied again.

    Used by the #333 interim-analysis path. `confirm` refuses a second
    apply with 409 once `applied_at` is set, which is right for a
    finished reflection (applying twice would duplicate everything) but
    wrong for a draft being analysed repeatedly through a long session:
    each pass is a NEW set of proposals over more text.

    Only ever called on a draft. A submitted reflection keeps its
    one-shot guarantee.
    """
    reflection.applied_actions = None
    reflection.applied_at = None
    db.session.commit()
    return reflection


def set_reflection_title(reflection_id, title: str | None) -> Reflection | None:
    """Name (or un-name) a reflection sitting (#339).

    An empty or whitespace-only title stores NULL rather than "", so
    "unnamed" is a single state: the UI's fallback label then applies,
    and a stray space can never render as a blank name. Titles are
    trimmed and length-capped to the column width.

    Returns None when the id does not exist, so the route can 404.
    """
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return None
    clean = (title or "").strip()
    reflection.title = clean[:200] if clean else None
    db.session.commit()
    return reflection


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
    # #324: an unsubmitted draft is not history — it has no analysis and
    # is still being written. It surfaces only via get_open_draft().
    stmt = select(Reflection).where(Reflection.is_draft.is_(False))
    if not include_archived:
        stmt = stmt.where(Reflection.is_archived.is_(False))
    if not include_deleted:
        stmt = stmt.where(Reflection.is_active.is_(True))
    stmt = stmt.order_by(Reflection.created_at.desc()).limit(limit)
    return list(db.session.scalars(stmt))


# --- Drafts: reflecting across several sittings (#324) -----------------------
# The in-progress transcript lives server-side so it survives a reload, a
# closed tab, an evicted PWA, and a move between phone and laptop. Free:
# no Whisper/Claude call happens until the reflection is submitted.


def get_open_draft() -> Reflection | None:
    """The single open draft, or None. Newest wins if somehow several
    exist (belt-and-braces — save_draft keeps it to one)."""
    stmt = (
        select(Reflection)
        .where(
            Reflection.is_draft.is_(True),
            Reflection.is_active.is_(True),
        )
        .order_by(Reflection.updated_at.desc())
        .limit(1)
    )
    return db.session.scalars(stmt).first()


def save_draft(
    *,
    transcript: str,
    raw_segments: list[dict[str, Any]] | None = None,
    context_files: list[dict[str, Any]] | None = None,
) -> Reflection:
    """Upsert THE open draft with the current in-progress text.

    Deliberately upsert-one rather than append-a-row: the client sends
    the whole textarea on each autosave, so a new row per keystroke-burst
    would be noise. ``updated_at`` (onupdate) is what the UI shows as
    "last saved".

    Unlike ``save_reflection`` the transcript is NOT required to be
    non-empty — an empty draft is a legitimate "user cleared the box"
    state, and refusing it would strand the client mid-autosave.

    ``context_files`` is UNSET-means-UNCHANGED (#328), not
    unset-means-empty. The text autosave fires on every keystroke burst
    and sends only the textarea; treating its silence as "no
    attachments" would delete a document the user attached minutes
    earlier. Pass ``[]`` explicitly to clear them.

    ``raw_segments`` is UNSET-means-UNCHANGED for exactly the same reason
    (#330, 2026-09-25). It used to be assigned unconditionally, so any
    text-only autosave ERASED the per-segment Whisper audit trail. That
    is reachable, not theoretical: resume a dictated draft on a second
    device while something is already in the textarea and the client's
    restore bails out (it refuses to clobber what you were typing), so
    its segment buffer stays empty — then the first keystroke's PUT sends
    text alone and the segments recorded on the first device are gone.
    Same shape on one device via Try Again after a failed interim
    analysis, which empties the buffer while the draft stays live. Pass
    ``[]`` explicitly to clear them.
    """
    draft = get_open_draft()
    text = (transcript or "").strip()
    segments = (
        None if raw_segments is None
        else _normalise_raw_segments(raw_segments)
    )
    if draft is None:
        draft = Reflection(
            iso_week=current_iso_week(),
            input_mode=(
                ReflectionInputMode.VOICE if segments
                else ReflectionInputMode.TYPED
            ),
            transcript=text,
            raw_segments=(segments or []),
            context_files=normalise_context_files(context_files),
            proposed_actions={"explicit": [], "suggested": []},
            is_draft=True,
        )
        db.session.add(draft)
    else:
        draft.transcript = text
        if segments is not None:
            draft.raw_segments = segments
        if context_files is not None:
            draft.context_files = normalise_context_files(context_files)
        if segments:
            draft.input_mode = ReflectionInputMode.VOICE
    db.session.commit()
    return draft


def discard_draft() -> bool:
    """Delete the open draft outright. Returns False if there wasn't one.

    A hard delete, not the soft ``is_active=False`` used for submitted
    reflections: an abandoned draft was never a reflection, so keeping it
    in the Recently-deleted list would be clutter rather than history.
    The "keep every transcript forever" promise in #165 is about
    SUBMITTED reflections.
    """
    draft = get_open_draft()
    if draft is None:
        return False
    db.session.delete(draft)
    db.session.commit()
    return True


# --- Continuing a past reflection (#334) -------------------------------------
# Reflecting toward a date weeks out is not one sitting. Before this, every
# submit was terminal: the next sitting opened an empty box and the earlier
# thinking survived only as a 1200-char snippet in the continuity block.
#
# Continuing FORKS. The saved reflection is read, never written: its text,
# voice segments and attachments seed a NEW draft that points back at it via
# `continued_from_id`. Re-opening the saved row instead would have been less
# code and more honest-looking, but it would rewrite history — the record of
# what the user thought on the 21st would silently become what they thought
# on the 28th, and both /reflection and the Help page promise that every
# reflection is kept forever.


class DraftAlreadyOpen(RuntimeError):
    """Raised when continuing would overwrite unsaved work.

    Refusing is the only safe answer. The user's sittings run for hours,
    so clobbering an open draft could destroy a great deal of thinking,
    and there is no undo for a draft (they are hard-deleted, by design).
    Merging the two silently would be worse still: nobody asked for their
    Tuesday notes to be spliced into a month-old reflection.
    """


def draft_has_content(draft: Reflection | None) -> bool:
    """Is there anything in this draft worth protecting?

    Text, voice segments or attachments each count. An empty draft is
    just the autosave loop's footprint — safe to reuse for a fork.
    """
    if draft is None:
        return False
    return bool(
        (draft.transcript or "").strip()
        or (draft.raw_segments or [])
        or (draft.context_files or [])
    )


def continue_reflection(parent_id: uuid.UUID) -> Reflection | None:
    """Fork ``parent_id`` into a fresh open draft. Parent is untouched.

    Returns the new draft, or None when there is no continuable
    reflection with that id (drafts are not continuable — they are
    already open — and neither are soft-deleted rows).

    Raises:
        DraftAlreadyOpen: if a draft with content is already open.
    """
    parent = get_reflection(parent_id)
    if parent is None or parent.is_draft or not parent.is_active:
        return None

    existing = get_open_draft()
    if draft_has_content(existing):
        raise DraftAlreadyOpen(
            "You already have a reflection in progress. Finish or discard "
            "it before continuing a past one."
        )
    if existing is not None:
        # Empty shell left by the autosave loop — reuse the row rather
        # than leaving a second draft behind for get_open_draft to
        # arbitrate between.
        db.session.delete(existing)
        db.session.flush()

    draft = Reflection(
        # The fork belongs to the week it is being written in, not the
        # parent's week: it is this sitting's reflection.
        iso_week=current_iso_week(),
        input_mode=parent.input_mode,
        transcript=(parent.transcript or "").strip(),
        # #328: attachments MUST come along. They are the job description
        # and the 90-day plan the reflection is arguing with; dropping
        # them would silently shrink the next analysis without saying so.
        context_files=normalise_context_files(parent.context_files),
        raw_segments=_carry_over_segments(parent.raw_segments),
        proposed_actions={"explicit": [], "suggested": []},
        is_draft=True,
        continued_from_id=parent.id,
    )
    db.session.add(draft)
    db.session.commit()
    return draft


def _carry_over_segments(
    segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Copy a parent's #237 raw voice segments onto a fork, minus cost.

    The text and timings are the audit value — they are the original
    spoken words behind the transcript the fork starts from, and without
    them the fork's transcript would have no provenance at all.

    ``cost_usd`` is deliberately dropped: that Whisper spend is already
    recorded against the parent row, and carrying the number onto the
    fork too would double-count it for anyone (or any future feature)
    totalling what a reflection cost.
    """
    out = []
    for seg in _normalise_raw_segments(segments):
        out.append({**seg, "cost_usd": None})
    return out


# --- Reading several reflections together (#335) -----------------------------
# One sitting can say what happened this week. It cannot say "you have now
# mentioned the settlement handover three weeks running and still have no
# task for it" -- that question only has an answer across sittings, and it is
# the question a five-week run-up to a start date actually needs answered.
#
# The continuity block (#325) already carries the previous three
# reflections, but truncated to `_RECENT_REFLECTION_CHARS` each, which is
# background, not material to reason over. A combined analysis passes the
# selected transcripts in FULL.
#
# Like #334 this creates a NEW row and touches none of the sources. The row
# is a record that on some day the user looked back across those sittings;
# its own `transcript` is a short header naming them, because the words
# themselves already live on the rows it points at.


class CombinedSelectionError(ValueError):
    """The chosen set cannot be analysed together, with a reason to show.

    Carries user-facing text: every one of these is something the person
    can fix by changing their selection, so the message is the whole
    remedy.
    """


def resolve_combined_sources(ids) -> list[Reflection]:
    """Turn a list of ids into the reflections to read together.

    Raises:
        CombinedSelectionError: too few, too many, or not analysable.
    """
    if not isinstance(ids, list):
        raise CombinedSelectionError("Pick the reflections to analyze together.")
    # De-duplicate while keeping the caller's order stable for the error
    # message; a repeated id is a client bug, not a user's intent to
    # weight one sitting twice.
    seen: set[uuid.UUID] = set()
    parsed: list[uuid.UUID] = []
    for raw in ids:
        rid = _parse_uuid(raw)
        if rid is None:
            raise CombinedSelectionError("That isn't a reflection I can read.")
        if rid not in seen:
            seen.add(rid)
            parsed.append(rid)

    if len(parsed) < 2:
        raise CombinedSelectionError(
            "Pick at least two reflections. Analyzing one on its own is "
            "what the Analyze button on that row already does."
        )
    if len(parsed) > MAX_COMBINED:
        raise CombinedSelectionError(
            f"That's {len(parsed)} reflections — {MAX_COMBINED} is the most "
            "that can be read together. The answer gets thinner, not "
            "richer, past that: the reply length is capped however much "
            "goes in."
        )

    sources = []
    for rid in parsed:
        r = get_reflection(rid)
        # A draft is still being written and a soft-deleted row is in the
        # recycle bin; neither is something to read back.
        if r is None or r.is_draft or not r.is_active:
            raise CombinedSelectionError(
                "One of those reflections is no longer available. Refresh "
                "the page and pick again."
            )
        sources.append(r)

    if not any((r.transcript or "").strip() for r in sources):
        raise CombinedSelectionError("Those reflections have no text to read.")
    return sources


def merged_source_files(sources: list[Reflection]) -> list[dict[str, Any]]:
    """The union of the SOURCE REFLECTIONS' attached documents, de-duped.

    Named apart from ``global_context_service.merged_context_files``,
    which merges the always-attached store into ONE reflection's files.
    Both de-duplicate documents, but they take different inputs and
    answer different questions; one name for both invited a silent
    mix-up at the call site.

    The same job description attached to three sittings must reach the
    prompt ONCE -- three copies would burn the 60k budget on one document
    and crowd out the others. Keyed on the attachment id, falling back to
    filename + length for rows written before ids existed.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in sources:
        for f in normalise_context_files(r.context_files):
            key = str(f.get("id") or "") or (
                f"{f.get('filename')}:{len(f.get('text') or '')}"
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
    return out


def synthesis_header(
    sources: list[Reflection], shortened: list[str] | None = None,
) -> str:
    """The synthesis row's OWN transcript: a header naming its sources.

    Not the combined text. That would duplicate tens of thousands of
    characters already stored on the rows this one points at, and would
    render as a wall of repeated words in the history list. What the row
    needs to say is what it IS, and it has to say that without a lookup
    so the history view stays one query.
    """
    ordered = sorted(sources, key=lambda r: (r.created_at or datetime.min))
    lines = [f"Combined analysis of {len(ordered)} reflections:"]
    lines.extend(f"- {reflection_label(r)}" for r in ordered)
    if shortened:
        lines.append(
            "(shortened to fit the analysis budget: " + ", ".join(shortened) + ")"
        )
    return "\n".join(lines)


def create_synthesis(sources: list[Reflection], shortened=None) -> Reflection:
    """Persist the row a combined analysis will hang its proposals on.

    A row is needed at all because ``confirm`` applies actions BY
    reflection id -- proposals with nowhere to live could not be applied.
    Making it a real row rather than a scratch record also means the
    look-back is itself kept, which is the same promise every other
    reflection gets.

    ``input_mode`` is TYPED because nobody dictated this row; it is
    assembled, and claiming VOICE would put a false entry in the history
    label.
    """
    synthesis = Reflection(
        iso_week=current_iso_week(),
        input_mode=ReflectionInputMode.TYPED,
        transcript=synthesis_header(sources, shortened),
        context_files=[],
        raw_segments=[],
        proposed_actions={"explicit": [], "suggested": []},
        synthesis_of=[str(r.id) for r in sources],
    )
    db.session.add(synthesis)
    db.session.commit()
    return synthesis


def synthesis_sources_of(reflection: Reflection) -> list[Reflection]:
    """Re-resolve a stored synthesis' sources, skipping any now gone.

    Used by the #338 re-analyze path so re-running a synthesis reads the
    sittings again rather than its own one-line header. Missing sources
    are dropped rather than raising: a look-back over the four that
    remain is more useful than an error about the fifth.
    """
    out = []
    for raw in reflection.synthesis_of or []:
        rid = _parse_uuid(raw)
        if rid is None:
            continue
        r = get_reflection(rid)
        if r is not None and not r.is_draft:
            out.append(r)
    return out


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
