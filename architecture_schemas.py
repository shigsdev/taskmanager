# ruff: noqa: E501
# ^ The `_SCHEMA_DESCRIPTIONS` dict (#44) is plain-English documentation
# data for the /architecture page. Forcing 100-char line wrap on those
# entries adds ~100 extra lines for no readability gain. Reviewing the
# data is easier when each column entry is on one line.

"""Per-table plain-English schema descriptions for the /architecture page.

Pure data module (#198) — split out of ``architecture_service.py`` so the
~200-line `_SCHEMA_DESCRIPTIONS` dict no longer dilutes that module's
logic. ``architecture_service`` imports `_SCHEMA_DESCRIPTIONS` back from
here, so every existing reference keeps working unchanged.

`_SCHEMA_DESCRIPTIONS` is the plain-English description for each table +
each non-universal column. Used by ``architecture_service.build_per_table
_schema()`` to render the per-table cards on the /architecture page (#44).
Drift-gated by `test_every_column_has_a_description` — adding a column to
a model without describing it here fails the test.

Columns NOT covered: the universal `id`, `created_at`, `updated_at`
(in ``architecture_service._HIDDEN_ER_COLUMNS``);
``architecture_service._DESCRIPTION_OPTIONAL_COLUMNS`` lists any others
we deliberately don't surface (rare — server-managed bookkeeping columns
that don't help a user understand the table).
"""
from __future__ import annotations

from typing import Any

_SCHEMA_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "tasks": {
        "blurb": (
            "Your to-do items. One row = one task on your board, in any "
            "tier (Today / Tomorrow / This Week / Next Week / Backlog / "
            "Freezer / Inbox), in any status (active / archived / "
            "cancelled)."
        ),
        "columns": {
            "title":               {"desc": "The task itself", "notes": "Required, free text"},
            "type":                {"desc": "Work or Personal", "notes": "Drives which view shows it"},
            "tier":                {"desc": "Where on the board", "notes": "One of: today, tomorrow, this_week, next_week, backlog, freezer, inbox"},
            "status":              {"desc": "Active, archived (done), or cancelled", "notes": "Cancellation can have a reason"},
            "due_date":            {"desc": "When it's due", "notes": "Optional; auto-filled when tier=today/tomorrow"},
            "notes":               {"desc": "Long-form notes on the task", "notes": "Optional"},
            "checklist":           {"desc": "Sub-bullets within the task", "notes": "Optional list (JSON)"},
            "url":                 {"desc": "A link saved with the task", "notes": "Auto-detected from the capture bar; preview fetched server-side"},
            "url_title":           {"desc": "Cached page title for the saved URL", "notes": "Fetched once, displayed on the task card"},
            "cancellation_reason": {"desc": "Why you cancelled it", "notes": "Auto-clears when you reactivate"},
            "sort_order":          {"desc": "Manual sort position within its tier", "notes": "Set when you drag-reorder tasks; lower = higher on the list"},
            "last_reviewed":       {"desc": "When this task was last shown in /review", "notes": "Used to decide which stale tasks to surface in the next review session"},
            "goal_id":             {"desc": "Goal this task supports", "fk_target": "goals.id", "notes": "Optional"},
            "project_id":          {"desc": "Project area this task belongs to", "fk_target": "projects.id", "notes": "Optional"},
            "parent_id":           {"desc": "Parent task (for subtasks)", "fk_target": "tasks.id (self-reference)", "notes": "Optional — one level deep. ON DELETE SET NULL (#175): purging the parent clears this rather than blocking"},
            "recurring_task_id":   {"desc": "The recurring template that spawned this", "fk_target": "recurring_tasks.id", "notes": "Optional"},
            "batch_id":            {"desc": "Bulk-import batch (for recycle-bin undo)", "fk_target": "import_log.batch_id", "notes": "Optional"},
            "planner_ignore":      {"desc": "Weekly-planner 'stop suggesting until I touch it' flag", "notes": "Auto-resets to False on any meaningful field change in update_task()"},
        },
    },
    "goals": {
        "blurb": (
            "Your strategic objectives — the \"why\" tasks roll up to. "
            "One row = one goal you're working toward."
        ),
        "columns": {
            "title":       {"desc": "The goal name", "notes": "Required"},
            "category":    {"desc": "Health, finance, career, etc.", "notes": "One of a fixed set"},
            "priority":    {"desc": "How important right now", "notes": "P1 / P2 / P3"},
            "status":      {"desc": "Active, achieved, or paused", "notes": ""},
            "actions":        {"desc": "Free-text notes on what you're doing for this goal", "notes": "Optional"},
            "target_date":    {"desc": "When you want to hit it", "notes": "Optional"},
            "priority_rank":  {"desc": "Sort order within priority tier", "notes": "Lower = higher in the goals list"},
            "target_quarter": {"desc": "Quarter you're aiming to hit it (e.g. \"Q2 2026\")", "notes": "Optional, free text"},
            "notes":          {"desc": "Long-form notes on the goal", "notes": "Optional"},
            "is_active":      {"desc": "Active or archived", "notes": "Archived goals don't appear in capture-bar dropdowns"},
            "batch_id":       {"desc": "Bulk-import batch (for recycle-bin undo)", "fk_target": "import_log.batch_id", "notes": "Optional"},
        },
    },
    "projects": {
        "blurb": (
            "Work or personal areas that group related tasks (e.g. \"Q2 "
            "OKRs\", \"Home renovation\"). One row = one project area."
        ),
        "columns": {
            "name":       {"desc": "The project name", "notes": "Required"},
            "type":       {"desc": "Work or Personal", "notes": "Filters which view shows it"},
            "color":      {"desc": "Color tag for the project", "notes": "Hex code, set in the UI"},
            "target_quarter": {"desc": "Target quarter for completion (e.g. 2026-Q4)", "notes": "Optional, free-form string"},
            "actions":    {"desc": "Concrete next-actions that move this project forward", "notes": "Optional freeform text"},
            "notes":      {"desc": "Background, context, links, anything useful", "notes": "Optional freeform text"},
            "status":     {"desc": "Lifecycle state of the project", "notes": "not_started / in_progress / done / on_hold (mirrors goals.status)"},
            "priority":   {"desc": "MoSCoW priority bucket for the project", "notes": "must / should / could / need_more_info — optional, mirrors goals.priority"},
            "priority_order": {"desc": "Manual order within type group (drag-and-drop on /projects)", "notes": "Lower = higher on the list"},
            "is_active":  {"desc": "Active or archived", "notes": "Archived projects don't appear in capture-bar dropdowns"},
            "goal_id":    {"desc": "Goal this project supports", "fk_target": "goals.id", "notes": "Optional. ON DELETE SET NULL (#175): purging the goal clears this rather than blocking"},
            "batch_id":   {"desc": "Bulk-import batch (for recycle-bin undo)", "fk_target": "import_log.batch_id", "notes": "Optional"},
        },
    },
    "recurring_tasks": {
        "blurb": (
            "Templates for tasks that repeat. One row = one repeat "
            "template (e.g. \"Walk dog every morning\"). The 00:05 "
            "nightly job uses these to create new tasks each day."
        ),
        "columns": {
            "title":              {"desc": "What the spawned task will be called", "notes": ""},
            "type":               {"desc": "Work or Personal (inherited by spawned tasks)", "notes": ""},
            "frequency":          {"desc": "How often it fires", "notes": "daily / weekly / weekdays / monthly_date / monthly_nth_weekday / day_of_week / multi_day_of_week"},
            "day_of_week":        {"desc": "For weekly templates: 0=Mon, 6=Sun", "notes": "Optional"},
            "days_of_week":       {"desc": "For multi_day_of_week: list of weekdays (e.g. [5, 6] = Sat+Sun)", "notes": "JSON list of integers 0-6 (#75)"},
            "day_of_month":       {"desc": "For monthly_date templates: 1-31", "notes": "Optional"},
            "nth_weekday":        {"desc": "For monthly_nth_weekday: 1st Tuesday, etc.", "notes": "Optional"},
            "week_of_month":      {"desc": "For monthly_nth_weekday: 1=first week, 5=last", "notes": "Optional, paired with nth_weekday"},
            "notes":              {"desc": "Inherited verbatim by every spawned task", "notes": "Optional"},
            "checklist":          {"desc": "Inherited verbatim by every spawned task", "notes": "Optional list (JSON)"},
            "url":                {"desc": "Inherited verbatim by every spawned task", "notes": "Optional"},
            "subtasks_snapshot":  {"desc": "List of subtasks to also spawn each cycle", "notes": "JSON; captured at template create/update (#26)"},
            "is_active":          {"desc": "Inactive templates don't spawn", "notes": ""},
            "end_date":           {"desc": "Optional sunset date — spawn cron skips once today > end_date", "notes": "NULL = run forever (#101)"},
            "start_date":         {"desc": "Optional sunrise date — spawn cron + previews skip when target < start_date", "notes": "NULL = fire from beginning of time. Auto-set from task.due_date in _apply_repeat (#147)"},
            "goal_id":            {"desc": "Goal these spawned tasks support", "fk_target": "goals.id", "notes": "Optional. ON DELETE SET NULL (#175): purging the goal clears this rather than blocking"},
            "project_id":         {"desc": "Project these spawned tasks belong to", "fk_target": "projects.id", "notes": "Optional. ON DELETE SET NULL (#175): purging the project clears this rather than blocking"},
        },
    },
    "app_logs": {
        "blurb": (
            "System-generated log events — errors, warnings, request "
            "traces. One row = one logged event. Surfaced via the "
            "post-deploy validator and the /api/debug/logs endpoint."
        ),
        "columns": {
            "level":         {"desc": "Severity", "notes": "DEBUG / INFO / WARNING / ERROR"},
            "logger_name":   {"desc": "Which Python logger emitted it", "notes": "e.g. app, scan_service"},
            "message":       {"desc": "The log line", "notes": "Sensitive fields scrubbed"},
            "traceback":     {"desc": "Stack trace (if exception)", "notes": "Optional"},
            "request_id":    {"desc": "Correlates events from one HTTP request", "notes": "UUID"},
            "route":         {"desc": "Which URL triggered the log", "notes": "Optional (cron events have none)"},
            "method":        {"desc": "HTTP method", "notes": "Optional"},
            "status_code":   {"desc": "HTTP response code", "notes": "Optional"},
            "source":        {"desc": '"server" or "client" (browser-reported)', "notes": ""},
            "timestamp":     {"desc": "UTC time of the event", "notes": ""},
        },
    },
    "import_log": {
        "blurb": (
            "Audit trail of bulk imports (OneNote text, Excel goals, "
            "image scans, voice memos). One row = one import batch. "
            "Used by the recycle bin to \"undo\" an import in one click."
        ),
        "pk_label": "batch_id (UUID — note: this table uses batch_id as PK rather than the universal id, so created tasks/goals can reference it cleanly)",
        "columns": {
            "batch_id":    {"desc": "Unique identifier for the batch (PK)", "notes": "Tasks/goals from this import reference it via their batch_id FK"},
            "source":      {"desc": "Where it came from", "notes": '"onenote", "excel", "scan", "voice", etc.'},
            "row_count":   {"desc": "Total rows the import attempted (for the audit row)", "notes": ""},
            "task_count":  {"desc": "How many tasks/goals the import actually created", "notes": ""},
            "raw_text":    {"desc": "The pasted/extracted source text", "notes": "Stored for debug + audit"},
            "error":       {"desc": "Failure message (if the import errored partway)", "notes": "Optional"},
            "imported_at": {"desc": "When the import ran", "notes": "Used for the recycle-bin TTL"},
            "undone_at":   {"desc": "When the import was undone (if at all)", "notes": "NULL = still in recycle bin; not-NULL = restored to the active board"},
        },
    },
    "weekly_focus": {
        "blurb": (
            "The 'This Week's Focus' panel on the home board. One row "
            "per (ISO week, slot) holding a free-form focus statement "
            "and an optional Goal link. Past weeks' rows are kept as "
            "silent history snapshots — the panel falls back to the "
            "most recent past week when the current week is empty "
            "(carry-forward UX, no auto-roll on Monday)."
        ),
        "columns": {
            "week_start_date": {"desc": "Monday of the ISO week this slot belongs to", "notes": "Indexed; the display query asks for current_week or falls back to most recent past week"},
            "slot_order":      {"desc": "Position in the slot list (1..N)", "notes": "N comes from app_settings.weekly_focus_slot_count, default 3"},
            "text":             {"desc": "The focus statement", "notes": "Required; 500 char cap"},
            "goal_id":          {"desc": "Optional Goal-link", "fk_target": "goals.id", "notes": "Hybrid mode (Q1 of feature spec): free-form text by default; this column lets a slot point at an existing Goal"},
            "is_active":        {"desc": "Soft-delete flag", "notes": "✕ button on the panel sets this False — past-week rows are preserved"},
        },
    },
    "reflections": {
        "blurb": (
            "Your weekly reflections. You record or type a reflection; "
            "Claude reads it against your active projects/goals/tasks "
            "and proposes create/update/delete changes you review + "
            "confirm. Every transcript is kept forever for future "
            "reference / retrospectives. Audio is never stored — only "
            "the transcript."
        ),
        "columns": {
            "iso_week":               {"desc": "ISO week the reflection belongs to (e.g. \"2026-W20\")", "notes": "Indexed; groups the history view"},
            "input_mode":             {"desc": "How it was captured", "notes": "voice (Whisper-transcribed) or typed"},
            "transcript":             {"desc": "The reflection text itself", "notes": "Required; persisted forever"},
            "audio_duration_seconds": {"desc": "Length of the recording", "notes": "Voice only; NULL for typed"},
            "audio_cost_usd":         {"desc": "Whisper transcription cost", "notes": "Voice only; NULL for typed"},
            "ai_cost_usd":            {"desc": "Approximate Claude cost for the analysis", "notes": "Best-effort from the response usage; NULL if unavailable"},
            "raw_segments":           {"desc": "Per-segment Whisper transcripts from the #232 pause/resume voice flow", "notes": "JSON list of {text, duration_seconds, cost_usd, recorded_at}. Empty list for typed reflections and pre-#237 rows. Persists the original spoken words so a textarea edit doesn't lose them (#237)."},
            "proposed_actions":       {"desc": "Claude's proposed changes", "notes": "JSON {explicit: [...], suggested: [...]}"},
            "applied_actions":        {"desc": "What you actually confirmed + the apply result", "notes": "JSON audit trail; NULL until confirmed"},
            "applied_at":             {"desc": "When the confirmed actions were applied", "notes": "NULL until you confirm"},
        },
    },
    "app_settings": {
        "blurb": (
            "Tiny generic key/value store for runtime configuration "
            "that needs to survive a redeploy without touching env "
            "vars. Single-user app — no per-user namespacing."
        ),
        "columns": {
            "key":    {"desc": "Well-known config name (e.g. 'weekly_focus_slot_count')", "notes": "Unique"},
            "value":  {"desc": "String value (caller parses to int / etc.)", "notes": "500 char cap"},
        },
    },
    # #188 (2026-05-22): a `flask_dance_oauth` entry used to live here,
    # describing a token table with an "encrypted OAuth token" column.
    # No such table exists — Flask-Dance runs on its default session
    # storage (no `storage=` on `make_google_blueprint`), so the signed
    # Flask session cookie holds the OAuth identity. The entry was pure
    # fiction on the /architecture page and has been removed.
}
