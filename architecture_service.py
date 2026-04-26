# ruff: noqa: E501
# ^ The `_SCHEMA_DESCRIPTIONS` dict (#44) is plain-English documentation
# data for the /architecture page. Forcing 100-char line wrap on those
# entries adds ~100 extra lines for no readability gain. Reviewing the
# data is easier when each column entry is on one line. The rest of the
# module's code remains short-line; if you add code to this module that
# benefits from the limit, consider moving the SCHEMA_DESCRIPTIONS into
# its own data module.

"""Architecture-page support — render ARCHITECTURE.md + introspect the
running app for live route catalog and ER diagram.

The `/architecture` page (#42) is the in-app system documentation
surface. To prevent the drift that hit ARCHITECTURE.md three times
in early 2026-04, the page is built from sources that move WITH the
code:

- ``render_architecture_md(path)`` — converts the on-disk
  ARCHITECTURE.md to HTML on every request, so updates to the file
  flow to the live page automatically.
- ``build_route_catalog(app)`` — introspects ``app.url_map`` so the
  rendered route list IS the running app's routes, not a hand-edited
  table that can drift.
- ``build_er_diagram()`` — introspects SQLAlchemy ``db.Model.registry``
  so the diagram IS the actual schema, including FK arrows + nullable
  markers + enum value lists. Emits Mermaid ``erDiagram`` syntax for
  client-side rendering.

The hand-written sequence diagrams (recurring spawn, voice memo,
auth) live in ``templates/architecture.html``; they're protected
from drift by the CLAUDE.md cascade-check additions shipped with
this feature, not by code.

Cross-reference ADR-028 for the source-of-truth design.
"""
from __future__ import annotations

import enum
from pathlib import Path
from typing import Any

import markdown as md_lib
from flask import Flask
from markupsafe import Markup

# --- Markdown render --------------------------------------------------------


def render_architecture_md(path: Path | str) -> Markup:
    """Convert ARCHITECTURE.md to HTML.

    Uses the ``markdown`` library with ``fenced_code`` (for triple-
    backtick code blocks, including the ASCII-art components diagram)
    and ``tables`` (for the threat-model table). Bare invocation,
    no plugins beyond the two required by ARCHITECTURE.md content.

    Returns a ``Markup`` object so Jinja renders it as HTML without
    requiring the ``| safe`` filter at the call site (semgrep flags
    ``| safe`` even when the source is repo-tracked, not user input).
    Raises ``FileNotFoundError`` if the path does not exist — callers
    should fall back to a friendly message.

    Source-of-truth note: the input is always a repo-tracked file
    (ARCHITECTURE.md). Never pass user-controlled paths or content
    through this — Markup IS marking the output as trusted HTML, and
    that trust is anchored to the repo, not the request.
    """
    text = Path(path).read_text(encoding="utf-8")
    # S704: input is a repo-tracked .md file (caller passes
    # ARCHITECTURE.md), never user-controlled content. Markup wraps the
    # markdown lib's HTML output so Jinja renders it without `| safe`
    # in the template — that filter trips semgrep's xss audit even on
    # this trusted-source case. ADR-028 covers the trust boundary.
    return Markup(  # noqa: S704
        md_lib.markdown(text, extensions=["fenced_code", "tables"]),
    )  # nosec B704 — input is repo-tracked ARCHITECTURE.md, not user data; ADR-028


# --- Route catalog ----------------------------------------------------------


# Routes that exist for infrastructure (Flask static, OAuth callback,
# health probe) and don't belong in a user-facing architecture catalog.
_HIDDEN_ROUTE_PREFIXES = ("/static/", "/login/")
_HIDDEN_ENDPOINTS = frozenset({"static", "google.login", "google.authorized"})


def build_route_catalog(app: Flask) -> list[dict[str, Any]]:
    """Introspect the Flask app and return route metadata.

    Each entry has:
      - ``method`` — single HTTP verb (rules with multiple verbs are
        expanded; HEAD and OPTIONS are dropped)
      - ``path`` — URL rule
      - ``endpoint`` — Flask endpoint name (function or blueprint.func)
      - ``auth`` — "login" if the view function carries
        ``@login_required``, "public" otherwise. Detected by checking
        for the wrapper attribute set by our auth decorator.
      - ``doc`` — first non-blank line of the view function's docstring
        (truncated to 120 chars), or "" if none

    Sorted by path, then method. Skips Flask's static endpoint and the
    OAuth callback paths — those are infra, not feature surface.
    """
    catalog: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for rule in app.url_map.iter_rules():
        if rule.endpoint in _HIDDEN_ENDPOINTS:
            continue
        if any(rule.rule.startswith(p) for p in _HIDDEN_ROUTE_PREFIXES):
            continue

        view = app.view_functions.get(rule.endpoint)
        auth = _detect_auth(view) if view else "unknown"
        doc = _first_doc_line(view) if view else ""

        for method in (rule.methods or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = (method, rule.rule)
            if key in seen:
                continue
            seen.add(key)
            catalog.append({
                "method": method,
                "path": rule.rule,
                "endpoint": rule.endpoint,
                "auth": auth,
                "doc": doc,
            })

    catalog.sort(key=lambda e: (e["path"], e["method"]))
    return catalog


def split_route_catalog(
    catalog: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a route catalog into (page routes, API endpoints) for #43.

    Page routes = anything not under ``/api/`` (the user-facing tabs +
    `/healthz`); these go in the always-visible table at the top of
    the route-catalog section.

    API endpoints = everything starting with ``/api/`` (~58 of the 75
    rows); these go in a collapsed `<details>` so the page routes
    aren't buried under API noise.

    Single-pass partition; preserves the input ordering inside each
    bucket (already path-sorted by build_route_catalog).
    """
    pages: list[dict[str, Any]] = []
    apis: list[dict[str, Any]] = []
    for entry in catalog:
        if entry["path"].startswith("/api/"):
            apis.append(entry)
        else:
            pages.append(entry)
    return pages, apis


def _detect_auth(view: Any) -> str:
    """Return "login" if the view has the @login_required wrapper, else "public".

    Our decorator (auth.login_required) sets ``__wrapped__`` and the
    underlying function's docstring, so we walk the wrapper chain
    looking for the marker attribute set by our wrapper.
    """
    fn = view
    while fn is not None:
        # Check for our auth marker (set in auth.login_required)
        if getattr(fn, "_login_required", False):
            return "login"
        # Walk through functools.wraps chain
        next_fn = getattr(fn, "__wrapped__", None)
        if next_fn is None or next_fn is fn:
            break
        fn = next_fn
    return "public"


def _first_doc_line(view: Any) -> str:
    """First non-blank line of the view function's docstring, truncated."""
    fn = view
    # Walk to the innermost function (past decorators)
    while True:
        wrapped = getattr(fn, "__wrapped__", None)
        if wrapped is None or wrapped is fn:
            break
        fn = wrapped
    doc = (fn.__doc__ or "").strip()
    if not doc:
        return ""
    first = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
    return first[:120] + ("…" if len(first) > 120 else "")


# --- ER diagram (Mermaid) ---------------------------------------------------

# Columns hidden from the rendered ER diagram for visual readability (#43).
# Every table has these; surfacing them on every box adds noise without
# information. The footnote in the template tells the user they exist.
_HIDDEN_ER_COLUMNS = frozenset({"id", "created_at", "updated_at"})

# Domain grouping for color-coded ER diagram (#43). Maps each table name
# to a group label used as a Mermaid `classDef` selector. Add new tables
# to the right group when introducing a new model — see CLAUDE.md cascade
# row "A new database column / enum member".
_ER_TABLE_GROUPS: dict[str, str] = {
    # Core: things the user creates and interacts with
    "tasks": "core",
    "goals": "core",
    "projects": "core",
    "recurring_tasks": "core",
    # Operational: system-generated records
    "app_logs": "ops",
    "import_log": "ops",
    # Auth: token storage by flask-dance
    "flask_dance_oauth": "auth",
}

# Display order — Mermaid layouts respect entity declaration order
# loosely. Listing related tables together helps clusters form.
_ER_TABLE_ORDER = (
    # Core cluster — Goal/Project parents first, then Task + RecurringTask
    "goals",
    "projects",
    "tasks",
    "recurring_tasks",
    # Operational cluster
    "app_logs",
    "import_log",
    # Auth (orphan)
    "flask_dance_oauth",
)


def build_er_diagram() -> str:
    """Introspect SQLAlchemy models and emit a Mermaid ``erDiagram`` block.

    The output is a string suitable for dropping inside
    ``<pre class="mermaid">…</pre>`` in a template. Mermaid renders it
    client-side via the JS lib loaded on the architecture page.

    Includes:
      - One entity block per ``db.Model`` subclass (excluding tables
        in `_HIDDEN_ER_COLUMNS` — id/created_at/updated_at are noise
        on every box; #43)
      - All non-hidden columns with their type
      - ``PK`` marker for primary keys
      - ``FK`` marker for foreign keys
      - ``"nullable"`` annotation for nullable columns
      - For Enum columns: comma-separated value list as the type
      - Foreign-key relationships rendered as Mermaid arrows
      - `direction LR` (left-to-right) layout for wider screens
      - `classDef` color groups (core/ops/auth) so related tables are
        visually distinguishable at a glance (#43)

    Tables ordered by the curated `_ER_TABLE_ORDER` so related tables
    cluster (Mermaid layouts respect declaration order loosely).
    Columns sorted alphabetically for stable output.
    """
    # Local import — avoids a top-level cycle since architecture_service
    # is imported by app.py, and models.py imports db from extensions
    # which app.py also touches.
    from models import db

    # `direction LR` (left-to-right) reads more naturally than the
    # default top-down for an ER diagram on a wide page.
    lines: list[str] = ["erDiagram", "    direction LR", ""]

    # Collect mappers indexed by table name so we can iterate in the
    # curated `_ER_TABLE_ORDER` (related tables clustered together)
    # rather than alphabetical (which scatters them).
    by_name: dict[str, Any] = {}
    for mapper in db.Model.registry.mappers:
        if mapper.local_table is not None:
            by_name[mapper.local_table.name] = mapper

    # Tables in curated order first; any new (uncurated) tables fall
    # through alphabetically at the end so we never silently drop one.
    ordered_names = [n for n in _ER_TABLE_ORDER if n in by_name]
    leftover = sorted(set(by_name) - set(ordered_names))

    # Track FK relationships to emit AFTER all entities
    relationships: list[str] = []
    # Track which tables we actually emit so classDef only mentions them
    emitted: list[str] = []

    for table_name in [*ordered_names, *leftover]:
        mapper = by_name[table_name]
        table = mapper.local_table

        lines.append(f"    {table_name} {{")
        for col in sorted(table.columns, key=lambda c: c.name):
            if col.name in _HIDDEN_ER_COLUMNS:
                continue
            col_type = _format_col_type(col)
            markers = []
            if col.primary_key:
                markers.append("PK")
            if col.foreign_keys:
                markers.append("FK")
            if col.nullable and not col.primary_key:
                markers.append('"nullable"')
            marker_str = " " + " ".join(markers) if markers else ""
            lines.append(f"        {col_type} {col.name}{marker_str}")
        lines.append("    }")
        emitted.append(table_name)

        # Capture FK arrows for after the entity blocks
        for col in table.columns:
            for fk in col.foreign_keys:
                target_table = fk.column.table.name
                # `||--o{` = target one-to-many to source
                # We emit target → source so "Goal has many Tasks" reads
                # as goals ||--o{ tasks
                relationships.append(
                    f"    {target_table} ||--o{{ {table_name} : {col.name}",
                )

    # Dedup relationships (multi-FK to same parent collapse)
    for rel in dict.fromkeys(relationships):
        lines.append(rel)

    # Color-group `classDef`s + per-table assignments. Mermaid's ER
    # diagram supports `classDef name fill:#color,stroke:#color`, then
    # `class tableName name` to assign. Colors picked for adequate
    # contrast on the existing pale-grey page background.
    lines.append("")
    lines.append("    classDef core fill:#dbeafe,stroke:#1d4ed8,color:#0c1f4d")
    lines.append("    classDef ops fill:#fef3c7,stroke:#a16207,color:#3a2806")
    lines.append("    classDef auth fill:#fce7f3,stroke:#a21caf,color:#3d0a3a")

    # Group tables by their classDef so we can emit one `class A,B,C name` line
    # per group instead of per table — Mermaid accepts comma-separated names.
    groups: dict[str, list[str]] = {"core": [], "ops": [], "auth": []}
    for name in emitted:
        group = _ER_TABLE_GROUPS.get(name)
        if group in groups:
            groups[group].append(name)
    for group_name, members in groups.items():
        if members:
            lines.append(f"    class {','.join(members)} {group_name}")

    return "\n".join(lines)


def _format_col_type(col: Any) -> str:
    """Render a SQLAlchemy column type as a short Mermaid-friendly string.

    For Enum columns, emit the comma-separated value list (e.g.
    ``"work,personal"``) so the diagram surfaces the legal values
    inline. For other types, use the short repr (``str``, ``int``,
    ``bool``, ``date``, ``datetime``, ``uuid``, ``json``).

    Mermaid is fussy about whitespace + special characters in the
    type token, so we strip + replace problematic characters.
    """
    # Enum: detect via the SQLAlchemy type CLASS, not str(col.type) —
    # the latter renders as the underlying SQL type (e.g. "VARCHAR(9)"
    # for non-native enums in flask-sqlalchemy 3.x), so the substring
    # check fails. The SQLAlchemy `Enum` type class always has an
    # `enum_class` attribute when constructed with a Python Enum.
    enum_cls = getattr(col.type, "enum_class", None)
    if enum_cls is not None and isinstance(enum_cls, type) and issubclass(enum_cls, enum.Enum):
        values = ",".join(m.name.lower() for m in enum_cls)
        # Mermaid disallows colons / parens in type tokens
        return f"enum_{values.replace('-', '_')}"

    # Standard SQL types → friendly Python names where possible
    py_type = getattr(col.type, "python_type", None) if hasattr(col.type, "python_type") else None
    if py_type is not None:
        return py_type.__name__

    # Fallback: SQL type string sans length annotations
    type_str = str(col.type).lower()
    return type_str.split("(", 1)[0]


# --- Per-table plain-English schema (#44) ----------------------------------

# Plain-English description for each table + each non-universal column.
# Used by `build_per_table_schema()` to render the per-table cards on the
# /architecture page (#44). Drift-gated by `test_every_column_has_a
# _description` — adding a column to a model without describing it here
# fails the test.
#
# Columns NOT covered: the universal `id`, `created_at`, `updated_at`
# (in `_HIDDEN_ER_COLUMNS`); `_DESCRIPTION_OPTIONAL_COLUMNS` lists any
# others we deliberately don't surface (rare — server-managed bookkeeping
# columns that don't help a user understand the table).
_DESCRIPTION_OPTIONAL_COLUMNS = frozenset({
    # Flask-Dance internal — managed by the OAuth library, doesn't help
    # explain what the table stores from the user's POV.
    "user_id",
})

# Per-table primary-key label (used in the `🔑 Primary key` callout).
# Defaults to "id (UUID, auto-generated)" — override only when the table
# uses something different (e.g. import_log uses batch_id).
_PK_LABEL_DEFAULT = "id (UUID, auto-generated)"

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
            "parent_id":           {"desc": "Parent task (for subtasks)", "fk_target": "tasks.id (self-reference)", "notes": "Optional — one level deep"},
            "recurring_task_id":   {"desc": "The recurring template that spawned this", "fk_target": "recurring_tasks.id", "notes": "Optional"},
            "batch_id":            {"desc": "Bulk-import batch (for recycle-bin undo)", "fk_target": "import_log.batch_id", "notes": "Optional"},
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
            "sort_order": {"desc": "Manual sort order in the project list", "notes": ""},
            "is_active":  {"desc": "Active or archived", "notes": "Archived projects don't appear in capture-bar dropdowns"},
            "goal_id":    {"desc": "Goal this project supports", "fk_target": "goals.id", "notes": "Optional"},
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
            "frequency":          {"desc": "How often it fires", "notes": "daily / weekly / weekdays / monthly_date / monthly_nth_weekday / day_of_week"},
            "day_of_week":        {"desc": "For weekly templates: 0=Mon, 6=Sun", "notes": "Optional"},
            "day_of_month":       {"desc": "For monthly_date templates: 1-31", "notes": "Optional"},
            "nth_weekday":        {"desc": "For monthly_nth_weekday: 1st Tuesday, etc.", "notes": "Optional"},
            "week_of_month":      {"desc": "For monthly_nth_weekday: 1=first week, 5=last", "notes": "Optional, paired with nth_weekday"},
            "notes":              {"desc": "Inherited verbatim by every spawned task", "notes": "Optional"},
            "checklist":          {"desc": "Inherited verbatim by every spawned task", "notes": "Optional list (JSON)"},
            "url":                {"desc": "Inherited verbatim by every spawned task", "notes": "Optional"},
            "subtasks_snapshot":  {"desc": "List of subtasks to also spawn each cycle", "notes": "JSON; captured at template create/update (#26)"},
            "is_active":          {"desc": "Inactive templates don't spawn", "notes": ""},
            "goal_id":            {"desc": "Goal these spawned tasks support", "fk_target": "goals.id", "notes": "Optional"},
            "project_id":         {"desc": "Project these spawned tasks belong to", "fk_target": "projects.id", "notes": "Optional"},
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
    "flask_dance_oauth": {
        "blurb": (
            "Stored Google OAuth tokens, managed entirely by the "
            "Flask-Dance library. You never read or write this directly "
            "— it's used internally to remember that you've signed in."
        ),
        "pk_label": "id (auto-generated by Flask-Dance)",
        "columns": {
            "provider":            {"desc": 'Always "google" for this app', "notes": ""},
            "token":               {"desc": "The encrypted OAuth token", "notes": "Refreshed automatically when it expires"},
            "provider_user_id":    {"desc": "Google's user ID", "notes": ""},
            "provider_user_login": {"desc": "Email address from Google", "notes": "Compared against AUTHORIZED_EMAIL on every request"},
            "created_at":          {"desc": "When the token was first issued", "notes": "Flask-Dance manages this column itself, so it's not in the universal-hidden set"},
        },
    },
}


def build_per_table_schema() -> list[dict[str, Any]]:
    """Combine introspected schema with plain-English descriptions (#44).

    For each ``db.Model`` table (in the curated `_ER_TABLE_ORDER`),
    return a dict with everything the per-table card on the
    /architecture page needs to render:

    - ``name``: table name
    - ``group``: "core" | "ops" | "auth" (from `_ER_TABLE_GROUPS`)
    - ``blurb``: 1-2 sentence plain-English summary (from `_SCHEMA_DESCRIPTIONS`)
    - ``pk_label``: the primary-key column + a friendly label
    - ``columns``: list of {name, desc, notes, fk_target?} dicts in
      definition order, excluding `_HIDDEN_ER_COLUMNS` AND any column
      that has a description marked "skip" (none currently)

    Per-column drift is enforced by `test_every_column_has_a_description`
    — if a model gains a column without a matching entry in
    `_SCHEMA_DESCRIPTIONS`, the test fails.
    """
    from models import db

    by_name: dict[str, Any] = {
        m.local_table.name: m
        for m in db.Model.registry.mappers
        if m.local_table is not None
    }

    out: list[dict[str, Any]] = []

    # Tables visible on the page = curated order ∪ tables from registry
    # ∪ tables we describe (covers `flask_dance_oauth`, which is owned by
    # Flask-Dance and never appears in our `db.Model.registry`). Iterate
    # in `_ER_TABLE_ORDER` first so related tables cluster.
    visible_names = set(by_name) | set(_SCHEMA_DESCRIPTIONS)
    ordered_names = [n for n in _ER_TABLE_ORDER if n in visible_names]
    leftover = sorted(visible_names - set(ordered_names))

    for table_name in [*ordered_names, *leftover]:
        meta = _SCHEMA_DESCRIPTIONS.get(table_name, {})
        cols_out: list[dict[str, Any]] = []

        if table_name in by_name:
            # Introspectable model — merge real columns with descriptions
            table = by_name[table_name].local_table
            for col in table.columns:
                if col.name in _HIDDEN_ER_COLUMNS and col.name not in meta.get("columns", {}):
                    continue
                if col.name in _DESCRIPTION_OPTIONAL_COLUMNS:
                    continue
                col_meta = meta.get("columns", {}).get(col.name, {})
                cols_out.append({
                    "name": col.name,
                    "desc": col_meta.get("desc", ""),
                    "notes": col_meta.get("notes", ""),
                    "fk_target": col_meta.get("fk_target"),
                    "is_fk": bool(col.foreign_keys),
                })
        else:
            # Externally-managed table (Flask-Dance) — render solely from
            # the curated description set. `is_fk` derives from whether
            # the description provided an `fk_target`.
            for col_name, col_meta in meta.get("columns", {}).items():
                cols_out.append({
                    "name": col_name,
                    "desc": col_meta.get("desc", ""),
                    "notes": col_meta.get("notes", ""),
                    "fk_target": col_meta.get("fk_target"),
                    "is_fk": bool(col_meta.get("fk_target")),
                })

        out.append({
            "name": table_name,
            "group": _ER_TABLE_GROUPS.get(table_name, "core"),
            "blurb": meta.get("blurb", ""),
            "pk_label": meta.get("pk_label", _PK_LABEL_DEFAULT),
            "columns": cols_out,
        })

    return out
