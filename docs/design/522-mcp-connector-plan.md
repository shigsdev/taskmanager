# #522 MCP Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `POST /mcp` endpoint that lets Claude (a claude.ai custom connector) create, list, complete, edit and move tasks, authenticated by a scoped token sent as `Authorization: Bearer <token>`.

**Architecture:** Three new modules: `mcp_token.py` (pure sign/parse, a copy of `voice_action_token.py`), `mcp_tools.py` (five tools as thin wrappers over `task_service`, returning MCP `CallToolResult` dicts) and `mcp_api.py` (a Flask blueprint that speaks stateless MCP Streamable HTTP, JSON only, in both the 2026-07-28 and the older `initialize` era). One new decorator in `auth.py` accepts only this token.

**Tech Stack:** Flask, itsdangerous, SQLAlchemy, Flask-Limiter, pytest. No MCP SDK.

**Spec:** `docs/design/522-mcp-connector.md` (and ADR-044, `docs/adr/044-mcp-connector-token.md`). Read both before Task 1.

## Global Constraints

- Token salt `taskmanager-mcp-v1`; lifetime 365 days; denylist `AppSetting` key `mcp_revoked_jtis`.
- Token accepted ONLY as `Authorization: Bearer <token>` on `POST /mcp`. No `/mcp/<token>` route. `/mcp` accepts no OAuth session, validator cookie, voice token, or dev bypass.
- `MCP_LIMIT = "60 per minute"` in `rate_limit.py`.
- Supported versions, in this order: `["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]`. Modern = `2026-07-28`.
- `_meta` version key: `io.modelcontextprotocol/protocolVersion`.
- Allowed `Origin` values: `https://claude.ai`, `https://claude.com` (absent is allowed).
- Error codes: `-32700` parse, `-32600` invalid request / batch, `-32601` unknown method, `-32602` unknown tool or non-object `arguments`, `-32020` HeaderMismatch, `-32022` UnsupportedProtocolVersion, `-32001` Unauthorized (401 body).
- Sections: `inbox, today, tomorrow, this_week, next_week, backlog, freezer` (the `Tier` values). Types: `work, personal`.
- Task view: `{id, title, section, type, due_date, project, notes, status}`; `status` is `open | completed | cancelled | deleted` (from `ACTIVE | ARCHIVED | CANCELLED | DELETED`).
- Audit lines: logger `taskmanager.mcp`, INFO, task id + action only — never the token, never a title or notes.
- Repo rules (CLAUDE.md): no commit until `bash scripts/run_all_gates.sh` is green (Task 6); git email `shigsdev@gmail.com`; never push to `main`.
- Ad-hoc pytest on this Mac: `.venv/bin/python -m pytest <file> --no-cov -q`.

## Review Focus

1. **`"id": 0` is a request, not a notification.** A falsy id must still get an answer; only a missing `id` key means notification. → Task 3 `test_id_zero_is_answered`.
2. **Relative dates ("due Fri").** Claude must know the user's today to turn "Fri" into a date, and a non-ISO date must come back as a clear tool error. → Task 3 `test_instructions_carry_today` and Task 2 `test_create_bad_date_is_tool_error`.
3. **Project names as people type them** (`"  apigee "`, `"APIGEE"`) match; two active projects of that type with the same name are an error, not a guess. → Task 2 `test_project_match_ignores_case_and_spaces`, `test_project_duplicate_name_is_tool_error`.
4. **A too-long or blank title** comes back as a tool error with the app's own message, and nothing is created. → Task 2 `test_create_long_title_is_tool_error`, `test_create_blank_title_is_tool_error`.
5. **A non-JSON or wrongly typed body** (empty body, `text/plain`, a JSON string) is a 400 `-32700`/`-32600`, never a 500. → Task 3 `test_non_json_body_is_parse_error`, `test_non_object_json_is_invalid_request`.

---

### Task 1: The token (mint, parse, revoke, script, CLI)

**Files:**
- Create: `mcp_token.py`
- Create: `scripts/mint_mcp_token.py`
- Modify: `voice_token_service.py` (generalise the denylist helpers by key)
- Modify: `app.py` (add `revoke-mcp-token` CLI next to `revoke-voice-action-token`, ~line 758)
- Test: `tests/test_mcp_token.py`

**Interfaces:**
- Produces:
  - `mcp_token.REVOKED_JTIS_KEY = "mcp_revoked_jtis"`, `mcp_token.DEFAULT_DAYS = 365`
  - `mcp_token.new_jti() -> str` (`secrets.token_hex(8)`)
  - `mcp_token.mint(secret_key: str, email: str, days: int = 365, jti: str | None = None) -> str`
  - `mcp_token.parse(secret_key: str, token: str, authorized_email: str, revoked_jtis: set[str] | frozenset[str] | None = None) -> str | None` — same contract as `voice_action_token.parse`
  - `voice_token_service.read_jti_denylist(key: str, *, lock: bool = False) -> list[str]`
  - `voice_token_service.add_jti_to_denylist(key: str, jti: str) -> bool` (False if already there; raises `ValidationError` on overflow; caller commits)

- [ ] **Step 1: Write the failing tests** in `tests/test_mcp_token.py`, modelled on `tests/test_voice_action_token.py::TestParse` (SECRET `"test-secret"`, EMAIL `"me@example.com"`):
  - `test_round_trip`: `parse(SECRET, mint(SECRET, EMAIL), EMAIL) == EMAIL`
  - `test_default_lifetime_is_365_days`: the payload from `URLSafeTimedSerializer(SECRET, salt="taskmanager-mcp-v1").loads(tok)` has `days == 365`
  - `test_rejects_wrong_secret`, `test_rejects_wrong_email`, `test_rejects_empty_and_garbage`, `test_mint_rejects_nonpositive_days` (`ValueError`)
  - `test_rejects_expired` (same time-travel helper as the voice test, `days=1`, minted 2 days ago)
  - `test_revoked_jti_rejected`: `parse(..., revoked_jtis={"deadbeef00"})` is None for a token minted with that jti, and not None for another jti
  - `test_rejects_tampered`: flip one character in the signature part → None
  - `test_voice_token_is_not_an_mcp_token`: `parse(SECRET, voice_action_token.mint(SECRET, EMAIL, 90), EMAIL) is None`, and `voice_action_token.parse(SECRET, mcp_token.mint(SECRET, EMAIL), EMAIL) is None`
  - `test_revoke_cli_adds_jti` (uses `app.test_cli_runner()`): `invoke(args=["revoke-mcp-token", "abcd1234abcd1234"])` → output contains `Revoked jti abcd1234abcd1234`; the `AppSetting` row `mcp_revoked_jtis` holds it; a second invoke prints `already revoked`; the voice denylist row is untouched
  - `test_mint_script_prints_a_valid_token(monkeypatch, capsys)`: set `SECRET_KEY`/`AUTHORIZED_EMAIL` env, load the script with `importlib.util.spec_from_file_location` (as `tests/test_validator_cookie.py:285` does), set `sys.argv = ["mint_mcp_token.py"]`, `main()` returns 0; stdout parses with `mcp_token.parse`; stderr contains `jti=`

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/bin/python -m pytest tests/test_mcp_token.py --no-cov -q`
  Expected: errors — `ModuleNotFoundError: No module named 'mcp_token'`

- [ ] **Step 3: Implement `mcp_token.py`** as a copy of `voice_action_token.py` with salt `taskmanager-mcp-v1`, the two constants above, and `days` defaulting to `DEFAULT_DAYS`. Module docstring: why it exists (#522, ADR-044), header-only, accepted only by `auth.mcp_token_required`.

- [ ] **Step 4: Generalise the denylist in `voice_token_service.py`.** Rename `_read_denylist` → `read_jti_denylist(key, *, lock=False)` and `_write_denylist` → `_write_jti_denylist(key, jtis)`, add `add_jti_to_denylist(key, jti)`; make the existing `add_revoked_jti(jti)` and every internal caller pass `voice_action_token.REVOKED_JTIS_KEY`. No behaviour change for the voice token — `tests/test_voice_token_settings.py` and `tests/test_voice_action_token.py` must still pass unchanged.

- [ ] **Step 5: Add `flask revoke-mcp-token <jti>`** in `app.py`: inside `app.app_context()`, `added = voice_token_service.add_jti_to_denylist(mcp_token.REVOKED_JTIS_KEY, jti)`, `db.session.commit()`; `ValidationError` → `click.ClickException`; prints `Revoked jti <jti>.` or `jti <jti> already revoked.`

- [ ] **Step 6: Create `scripts/mint_mcp_token.py`**, shaped like `scripts/mint_validator_cookie.py` (no Flask import; `SECRET_KEY` / `AUTHORIZED_EMAIL` from env; `--days` default 365, `--email`): prints the token to stdout with no newline and `\njti=<id>` to stderr; exit 2 with the same messages when env is missing. Docstring usage: `railway run python scripts/mint_mcp_token.py`.

- [ ] **Step 7: Run to verify they pass**
  Run: `.venv/bin/python -m pytest tests/test_mcp_token.py tests/test_voice_action_token.py tests/test_voice_token_settings.py --no-cov -q && .venv/bin/ruff check .`
  Expected: all passed; ruff `All checks passed!`

---

### Task 2: The five tools

**Files:**
- Create: `mcp_tools.py`
- Test: `tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: `task_service.create_task / update_task / list_tasks / get_task / complete_parent_task / list_subtasks`, `utils.ValidationError` (has `.field`), `models.Project / Task / Tier / TaskType / TaskStatus`.
- Produces:
  - `mcp_tools.TOOLS: list[dict]` — in order `create_task, list_tasks, complete_task, update_task, move_task`; each `{"name", "title", "description", "inputSchema", "annotations"}`. `inputSchema` is JSON Schema with `"additionalProperties": False`. `annotations`: `list_tasks` → `{"readOnlyHint": True, "openWorldHint": False}`; the rest → `{"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}`.
  - `class UnknownTool(Exception)`
  - `mcp_tools.call_tool(name: str, arguments: dict) -> dict` — returns a `CallToolResult`: success `{"content": [{"type": "text", "text": <summary>}], "structuredContent": {...}, "isError": False}`; failure `{"content": [{"type": "text", "text": <message>}], "isError": True}`. Raises `UnknownTool` for a name not in `TOOLS`. Never raises `ValidationError`.
  - `mcp_tools.task_view(task: Task) -> dict` — the Global Constraints shape; `project` is the project's name or None; `due_date` ISO or None.
  - `structuredContent`: `{"task": task_view}` for create/complete/update/move; `{"tasks": [...], "count": n}` for list.

Arguments (types per spec table): `create_task` — `title` (string, required), `type` (enum work/personal, required), `due_date` (string, `"format": "date"`), `section` (enum), `project` (string), `notes` (string). `list_tasks` — `section`, `type`, `project`, `status` (enum `open`/`completed`, default open), `limit` (integer 1–200, default 50). `complete_task` — `task_id` (string, required), `complete_subtasks` (boolean, default false). `update_task` — `task_id` (required), `title` (string), `due_date` (string or null), `notes` (string), `project` (string or null); at least one besides `task_id`. `move_task` — `task_id`, `section` (both required).

- [ ] **Step 1: Write the failing tests** in `tests/test_mcp_tools.py` (use the `app` fixture; helpers `_task(**kw)` and `_project(name, type)` add rows directly). Each asserts on the returned dict:
  - `test_tools_listed_in_order`: `[t["name"] for t in TOOLS] == ["create_task", "list_tasks", "complete_task", "update_task", "move_task"]`; every `inputSchema["additionalProperties"] is False`
  - `test_create_minimal_lands_in_inbox`: `call_tool("create_task", {"title": "Draft Apigee vendor questions", "type": "work"})` → `isError False`, `structuredContent["task"]["section"] == "inbox"`, row exists
  - `test_create_with_date_files_by_date`: `due_date` = tomorrow (`utils.local_today_date() + timedelta(days=1)`) → section `"tomorrow"`
  - `test_create_with_section`: `section: "backlog"` → `"backlog"`
  - `test_create_with_project_by_name`: work project "Apigee" → `task["project"] == "Apigee"`
  - `test_project_match_ignores_case_and_spaces`: `project: "  apigee "` → matches "Apigee"
  - `test_project_duplicate_name_is_tool_error`: two active work projects "Apigee" and "apigee" → `isError True`, text contains `2 work projects are named`
  - `test_unknown_project_names_the_choices`: projects "Apigee", "Hiring" (work) → `project: "Nope"` → `isError`, text contains `No active work project is named "Nope"` and `Apigee, Hiring`
  - `test_other_type_project_is_tool_error`: `type: "personal"`, `project: "Apigee"` where Apigee is a work project → `isError`, text contains `No active personal project is named "Apigee"`
  - `test_create_bad_date_is_tool_error`: `due_date: "Fri"` → `isError`, nothing created
  - `test_create_long_title_is_tool_error`: 501-char title → `isError`, text contains `too long`, nothing created
  - `test_create_blank_title_is_tool_error`: `"   "` → `isError`
  - `test_schema_errors_are_tool_errors`: missing `type`; `type: "chores"`; unknown key `priority: 1`; `limit: 500` on list — each `isError True` with a message naming the argument
  - `test_unknown_tool_raises`: `pytest.raises(UnknownTool)` for `"delete_task"`
  - `test_list_defaults_open_top_50`: 60 open tasks + 1 completed → `count == 50`, all `status == "open"`
  - `test_list_filters`: by `section`, `type`, `project`, and `status: "completed"` each return only matching tasks; `limit: 2` returns 2
  - `test_complete_task`: open task → `status == "completed"`
  - `test_complete_with_open_subtasks_needs_flag`: parent + 2 open subtasks → `isError`, text contains `2 open subtasks` and `complete_subtasks: true`; with the flag → parent and both subtasks completed
  - `test_closed_task_is_refused`: for a completed, a cancelled and a deleted task, each of `complete_task`, `update_task` (`title`), `move_task` → `isError`, text contains `only open tasks`
  - `test_unknown_id_is_tool_error`: random UUID → `isError`, text contains `No task with id`; `task_id: "abc"` → `isError`
  - `test_update_fields`: change `title`, `notes`, `due_date`; then `due_date: None` clears it; `project: None` clears the project
  - `test_update_needs_a_field`: only `task_id` → `isError`
  - `test_move_task`: open inbox task → `section: "next_week"` → `task["section"] == "next_week"`
  - `test_audit_lines_have_id_not_title(caplog)`: at INFO on `taskmanager.mcp`, create then move a task titled `"secret-title-xyz"` → records contain `mcp: created task <id>` and `mcp: moved task <id> to today`; `"secret-title-xyz"` appears in no record

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py --no-cov -q`
  Expected: `ModuleNotFoundError: No module named 'mcp_tools'`

- [ ] **Step 3: Implement `mcp_tools.py`.** Decisions the tests don't fix:
  - `_check_args(schema: dict, args: dict) -> str | None` — a small hand-written checker for exactly what `TOOLS` uses: required keys, `additionalProperties: False`, `type` (`string`, `integer`, `boolean`, `["string", "null"]`), `enum`, integer `minimum`/`maximum`. Returns the first problem as a sentence naming the argument; `call_tool` turns it into `isError`. (No jsonschema dependency.)
  - `_resolve_project(name: str, task_type: TaskType) -> uuid.UUID` raising `ValidationError` — exact match on `name.strip().casefold()` among `Project.is_active` projects whose `type.value == task_type.value`. Messages: `No active work project is named "X". Work projects: A, B.` (or `There are no active work projects.`) and `2 work projects are named "X" — rename one in the app first.`
  - Each tool builds a `data` dict holding ONLY the keys the caller passed (`section` → `"tier"`, `project` → `"project_id"`), so `task_service`'s "key present" rules (#386, #427, #466) behave exactly as for the web app.
  - The open-task guard (`task.status != TaskStatus.ACTIVE` → `That task is <completed|cancelled|in the Recycle Bin> — only open tasks can be changed.`) runs before any write.
  - `complete_task`: on `ValidationError` with `field == "subtasks"`, reword using `len(list_subtasks(id))`: `This task has N open subtasks. Call complete_task again with complete_subtasks: true to complete them too.`
  - Any `ValidationError` → `isError` with `str(e)`; call `db.session.rollback()` first.
  - Summaries for Claude (titles allowed here — they are the answer, not a log): e.g. `Created "<title>" in Tomorrow, due 2026-10-31 (id <id>).`; list → one line per task `- <title> · <section>[ · due <date>][ · <project>] (id <id>)`, or `No tasks match.`
  - Audit: `logging.getLogger("taskmanager.mcp").info("mcp: created task %s", task.id)` — likewise `completed`, `updated … (<comma-separated field names>)`, `moved … to <section>`, and `mcp: listed %d tasks`.

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/bin/python -m pytest tests/test_mcp_tools.py --no-cov -q && .venv/bin/ruff check .`
  Expected: all passed; ruff clean

---

### Task 3: The endpoint (auth, protocol, rate limit)

**Files:**
- Create: `mcp_api.py`
- Modify: `auth.py` (add `_mcp_revoked_jtis()` and `mcp_token_required`, after `voice_action_or_login`)
- Modify: `rate_limit.py` (`MCP_LIMIT`)
- Modify: `app.py` (`import mcp_api`; `app.register_blueprint(mcp_api.bp)  # #522 / ADR-044`)
- Modify: `architecture_service.py` (`_detect_auth` returns `"mcp-token"` for the marker)
- Modify: `tests/test_smoke.py` (`"mcp_api"` in `EXPECTED_BLUEPRINTS`)
- Test: `tests/test_mcp_api.py`, plus one test in `tests/test_architecture.py`

**Interfaces:**
- Consumes: `mcp_token.parse`, `mcp_token.REVOKED_JTIS_KEY`, `voice_token_service.read_jti_denylist`, `mcp_tools.TOOLS / call_tool / UnknownTool`, `utils.local_today_date`.
- Produces:
  - `auth.mcp_token_required(view)` — no dev bypass, never calls `login_required`; reads only `Authorization: Bearer …`; valid → `g.mcp = True`, calls `view(*args, **kwargs)`; otherwise 401 with `{"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}}`. Sets `wrapped._mcp_token_required = True`.
  - `rate_limit.MCP_LIMIT = "60 per minute"`
  - `mcp_api.bp` (name `"mcp_api"`, no url prefix) with one rule `POST /mcp`; constants `MODERN_VERSION`, `LEGACY_VERSIONS`, `SUPPORTED_VERSIONS`, `ALLOWED_ORIGINS`, `META_VERSION_KEY`; `build_instructions() -> str`.

Request handling order (each step returns if it answers):
1. `bp.before_request`: `Origin` present and not in `ALLOWED_ORIGINS` → 403 JSON-RPC `-32600` `Forbidden origin`. (Runs before the auth decorator.)
2. `mcp_token_required` → 401.
3. `request.get_json(silent=True, force=True)`: None → 400 `-32700`; a list → 400 `-32600` `Batches are not supported`; not a dict, `jsonrpc != "2.0"` or `method` not a str → 400 `-32600`.
4. No `"id"` key → 202, empty body (covers `notifications/initialized`).
5. Modern (`params._meta[META_VERSION_KEY]` present): version ≠ `MODERN_VERSION` → 400 `-32022` with `data: {"supported": SUPPORTED_VERSIONS, "requested": v}`; then header checks → 400 `-32020`; then dispatch `server/discover`, `tools/list`, `tools/call`, `ping`; unknown → 404 `-32601`; `-32602` → 400. Every result gets `"resultType": "complete"`.
6. Legacy: an `MCP-Protocol-Version` header present and not in `LEGACY_VERSIONS` → 400 `-32600`; dispatch `initialize`, `tools/list`, `tools/call`, `ping`; errors use HTTP 200 (JSON-RPC error body).

Results: `server/discover` → `{"supportedVersions": SUPPORTED_VERSIONS, "capabilities": {"tools": {}}, "instructions": build_instructions(), "_meta": {"serverInfo": SERVER_INFO}}`. `initialize` → `{"protocolVersion": <client's if in LEGACY_VERSIONS else "2025-11-25">, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO, "instructions": build_instructions()}`. `SERVER_INFO = {"name": "taskmanager", "title": "Task Manager", "version": "1"}`. `tools/list` → `{"tools": TOOLS}`. `tools/call` → `call_tool(...)`; missing/non-str `name` or non-dict `arguments` → `-32602`; `UnknownTool` → `-32602` `Unknown tool: <name>`. `ping` → `{}`.

`build_instructions()` names the app, the seven sections, Work/Personal, dates as `YYYY-MM-DD`, Inbox-unless-a-date-or-section, no delete, and starts with `Today is <ISO date> (<Weekday>) in the user's time zone.` from `local_today_date()`.

Mcp-Name decoding: a value matching `=?base64?(.*)?=` is base64-decoded as UTF-8; a decode failure counts as a mismatch.

- [ ] **Step 1: Write the failing tests** in `tests/test_mcp_api.py`. Helpers: `_tok()` = `mcp_token.mint("test-secret", "me@example.com")`; `_modern(method, params=None, id=1, headers=None)` builds the body with `_meta` and the three headers set correctly (override per test); `_legacy(method, params=None, id=1)`. Tests:
  - Modern: `test_discover` (supportedVersions list exactly as Global Constraints, `resultType == "complete"`, `_meta.serverInfo.name == "taskmanager"`); `test_instructions_carry_today` (`local_today_date().isoformat()` in instructions); `test_tools_list_modern` (five names); `test_tools_call_modern_creates_task` (creates; row exists; `isError False`); `test_ping_modern`; `test_unknown_method_modern_404` (`-32601`, HTTP 404)
  - Header mismatch, each 400 `-32020`: `test_missing_protocol_version_header`, `test_protocol_version_header_differs`, `test_mcp_method_header_differs`, `test_mcp_name_missing_on_tools_call`, `test_mcp_name_differs`; and `test_mcp_name_base64_accepted` (`=?base64?Y3JlYXRlX3Rhc2s=?=` for `create_task` → 200)
  - `test_unsupported_modern_version` (`_meta` `"2027-01-01"` → 400 `-32022`, `data.supported` equals the list)
  - Legacy: `test_legacy_initialize_echoes_known_version` (`2025-06-18` → `2025-06-18`), `test_legacy_initialize_unknown_version_gets_latest_legacy` (`"2024-11-05"` → `"2025-11-25"`), `test_legacy_flow` (initialize → notification `notifications/initialized` 202 → `tools/list` → `tools/call` with no `MCP-Protocol-Version` header, all 200), `test_legacy_unknown_method` (HTTP 200, `-32601`), `test_legacy_bad_version_header` (400)
  - Envelope: `test_notification_202_no_body`; `test_id_zero_is_answered` (`"id": 0` → 200 with `"id": 0`); `test_batch_rejected` (400 `-32600`); `test_non_json_body_is_parse_error` (`data="not json"` → 400 `-32700`; empty body → 400); `test_non_object_json_is_invalid_request` (`"hello"` → 400 `-32600`); `test_get_and_delete_are_405`; `test_unknown_tool_is_32602`; `test_arguments_not_object_is_32602`
  - Origin: `test_foreign_origin_403` (`https://evil.example`, even with a valid token → 403); `test_claude_origins_allowed` (both → 200); `test_no_origin_allowed`
  - Auth: `test_no_token_401`, `test_bad_token_401`, `test_revoked_token_401` (jti added via `voice_token_service.add_jti_to_denylist(mcp_token.REVOKED_JTIS_KEY, jti)` + commit), `test_expired_token_401`; `test_token_in_path_is_not_a_route` (`POST /mcp/<token>` → 404); `test_mcp_token_refused_on_api_tasks` (`GET /api/tasks` with the Bearer → 401); `test_mcp_token_refused_on_voice_review` (`GET /api/voice-review/queue` → 401); `test_voice_token_refused_on_mcp`; `test_validator_cookie_refused_on_mcp` (cookie `validator_token` = `validator_cookie.mint(...)`, no Bearer → 401); `test_oauth_session_refused_on_mcp` (`authed_client`, no Bearer → 401); `test_dev_bypass_does_not_open_mcp` (monkeypatch `LOCAL_DEV_BYPASS_AUTH=1`, `AUTHORIZED_EMAIL=me@example.com` env → no Bearer → 401)
  - `test_rate_limited_at_60_per_minute` (the `limiter_on` fixture pattern from `tests/test_utilities_jobs_477.py`; 60 `ping`s → 200, the 61st → 429)
  - `test_token_never_logged(caplog)`: at DEBUG for the root logger, run initialize + a `tools/call` create with a valid token → the token string is in no record's `getMessage()`
  - In `tests/test_architecture.py`: `test_mcp_route_tagged_mcp_token` — `/mcp` catalog entry has `auth == "mcp-token"`

- [ ] **Step 2: Run to verify they fail**
  Run: `.venv/bin/python -m pytest tests/test_mcp_api.py tests/test_architecture.py tests/test_smoke.py --no-cov -q`
  Expected: failures — `/mcp` 404s, `mcp_api` blueprint missing

- [ ] **Step 3: Implement** `MCP_LIMIT`, `auth._mcp_revoked_jtis()` (`frozenset(read_jti_denylist(mcp_token.REVOKED_JTIS_KEY))`, any exception → `frozenset()`, as `_voice_action_revoked_jtis` does), `auth.mcp_token_required`, `mcp_api.py` (view decorated `@bp.post("/mcp")`, `@mcp_token_required`, `@limiter.limit(MCP_LIMIT)`), the blueprint registration, the `_detect_auth` branch, and `"mcp_api"` in `EXPECTED_BLUEPRINTS`. Module docstring of `mcp_api.py`: #522, ADR-044, what the token can and can't do (mirroring `voice_review_api.py`'s).

- [ ] **Step 4: Run to verify they pass**
  Run: `.venv/bin/python -m pytest tests/test_mcp_api.py tests/test_mcp_tools.py tests/test_mcp_token.py tests/test_architecture.py tests/test_smoke.py tests/test_voice_action_token.py --no-cov -q && .venv/bin/ruff check .`
  Expected: all passed; ruff clean

---

### Task 4: Check the protocol with MCP Inspector (manual)

**Files:** none (findings feed back into Task 3 if anything fails).

- [ ] **Step 1:** Start the local server without the bypass: `FLASK_ENV=development .venv/bin/python -m flask run -p 5112` in the background (stop it at the end of this task). Mint a local token from the same `.env` the server reads (it holds `SECRET_KEY` and `AUTHORIZED_EMAIL`): `TOKEN=$(set -a; . ./.env; set +a; .venv/bin/python scripts/mint_mcp_token.py 2>/dev/null)` — never echo it.
- [ ] **Step 2:** `npx @modelcontextprotocol/inspector --cli http://localhost:5112/mcp --transport http --header "Authorization: Bearer $TOKEN" --method tools/list` → five tools. Then `--method tools/call --tool-name create_task --tool-arg title="Inspector test" --tool-arg type=work` → `isError: false`. (If the CLI flags differ in the installed version, use `--help` and the UI mode instead.)
- [ ] **Step 3:** Delete the "Inspector test" task from the dev DB (UI or `flask shell`), stop the server, `unset TOKEN`. Pass = both calls succeed; note which protocol era the Inspector used.

---

### Task 5: Docs

**Files:**
- Modify: `templates/docs.html` (TOC entry + new section `id="claude-connector"`; one step in `#rotate-secrets`)
- Modify: `ARCHITECTURE.md` (Components, Data Flows, Route catalog line for `/mcp`)
- Modify: `CLAUDE.md` (threat model credential bullet + accepted trade-off bullet; a Phase 6 step line + two report rows for the Help section)
- Modify: `README.md` (feature list line)
- Modify: `BACKLOG.md` (row #522, `🔄 IN PROGRESS`)
- Modify: `docs/adr/044-mcp-connector-token.md` (Status → `ACCEPTED`)

- [ ] **Step 1: Help section "Connect Claude (MCP connector)"**: what Claude can do (the five tools, Inbox unless a date or section, no delete/cancel, only open tasks); make a token (`railway run python scripts/mint_mcp_token.py`, note the `jti`); add the connector (claude.ai → Customize → Connectors → Add custom connector → name, URL `https://web-production-3e3ae.up.railway.app/mcp` → Continue → No sign-in → Request header `authorization` = `Bearer <token>`); revoke (`railway run flask revoke-mcp-token <jti>`); expiry after 365 days. Rotate-secrets gets a step: after rotating `SECRET_KEY`, mint a new token and re-enter the header.
- [ ] **Step 2: Fact-check table** (for the review message, not the page): one row per claim, `file:line` — sections (`models.py` Tier), Inbox default (`task_service.py` create_task), 365 days (`mcp_token.py`), the CLI names, the URL, the header form (`auth.py` `mcp_token_required`), no delete (`mcp_tools.TOOLS`). The claude.ai menu path comes from the user's own dialog (2026-10-30), cited as such.
- [ ] **Step 3: ARCHITECTURE.md / CLAUDE.md / README / BACKLOG / ADR** edits above. Route catalog line: `/mcp   # POST — #522 / ADR-044: MCP connector for claude.ai (scoped Bearer token; create/list/complete/update/move tasks)`.
- [ ] **Step 4: Verify** `.venv/bin/python scripts/arch_sync_check.py` and `.venv/bin/python scripts/docs_sync_check.py` exit 0.

---

### Task 6: Gates, Phase 6, ship

- [ ] **Step 1:** `bash scripts/run_all_gates.sh` → `ALL GATES GREEN`. A random Playwright fail that passes alone → check RAM/swap first (CLAUDE.md).
- [ ] **Step 2: Phase 6** on `/docs?nosw=1` at 1280×800 and 375×812 (seed + `preview_start taskmanager-dev-bypass`): the new section and the rotate step render, TOC link jumps below the nav, `scrollWidth <= innerWidth`, no console errors. Screenshots. Tear down (`python scripts/stop_dev_bypass.py`; `ls .env.dev-bypass` → no such file).
- [ ] **Step 3:** Quality Gate Report + Regression Test Report; one commit (`feat(#522): MCP connector for claude.ai`) with the gate trailer and `Co-Authored-By` line; `git push -u origin feature/522-mcp-connector`; `gh pr create --base main`.
- [ ] **Step 4: Ask the user before merging.** Then `gh pr merge <n> --rebase --delete-branch`, `git checkout main && git pull --ff-only origin main`, `python scripts/validate_deploy.py --monitor-minutes 5` (full output, no `tail`), `npm run test:e2e:prod` with `TASKMANAGER_SESSION_COOKIE` exported.
- [ ] **Step 5: Real connector.** Check `APP_LOG_LEVEL` on Railway (`railway variables --json | jq -r .APP_LOG_LEVEL` — only that key): if it isn't `INFO`, the audit lines reach Railway's stdout but not `/api/debug/logs`; say so in the Help text and BACKLOG. Mint the prod token (`railway run .venv/bin/python scripts/mint_mcp_token.py`, piped straight to the clipboard — never printed in chat), walk the user through adding the connector, then have Claude create, list, complete, edit and move a task in a chat, and confirm each on the board.
- [ ] **Step 6:** BACKLOG #522 → ✅ on its own small docs branch + PR; SOP Compliance Report (`sop-report` skill).
