# #522 — Let Claude manage tasks through an MCP connector

User request 2026-10-30, from a claude.ai chat: let Claude create tasks "in
any chat in this project, with a line like 'logged: draft Apigee vendor
questions, due Fri'", and on the phone. Decisions made with the user the
same day: Claude may **create, list, complete, edit and move** tasks (no
delete); the endpoint is written directly in Flask (no SDK, no second
service); the connector uses claude.ai's "No sign-in" with a **Request
header** `authorization: Bearer <token>` (the user confirmed the dialog
offers it, "sent exactly as entered"), so the token never sits in a URL.

## What exists

- The app is Flask on gunicorn sync workers (`gunicorn.conf.py`, 2 workers).
  The official MCP Python SDK is ASGI, so it does not drop into this app.
- `task_service.create_task / update_task / list_tasks` and
  `complete_parent_task` hold every task rule: a dated task lands in its
  section (#386), a date that doesn't fit a section is dropped (#466), a
  project of the other type is refused (#475), closed or deleted tasks are
  refused (#474, #493), open subtasks are completed only when asked (#433).
- The Siri voice-action token (`voice_action_token.py`, ADR-034/042/043) is
  the template for a scoped, mutating, non-OAuth credential: signed with
  `SECRET_KEY` under its own salt, a random `jti`, a revocation denylist in
  `AppSetting`, accepted by one decorator only.
- `scrub_sensitive` already redacts `Bearer …` and `Authorization: …`
  values in log text.

## Protocol (MCP Streamable HTTP, JSON responses only)

Current MCP is revision **2026-07-28** ("modern": no handshake, every request
carries `_meta`). Older clients use an `initialize` handshake ("legacy",
2025-11-25 and earlier). We don't know which one claude.ai speaks, so the
server is **dual-era**, as the spec's compatibility matrix allows. It never
streams: every request gets one `application/json` answer.

Endpoint: `POST /mcp`, token in `Authorization: Bearer …`. There is no
token-in-URL form.

**Every request**

- Body must be one JSON-RPC object. An array (batch) → 400, `-32600`.
- `Origin` present and not `https://claude.ai` or `https://claude.com` →
  403 (MCP's DNS-rebinding rule). No `Origin` (a server-side caller) is fine.
- A notification (no `id`) → 202, no body.
- `GET` / `DELETE` → 405. `Mcp-Session-Id` and `Last-Event-ID` are ignored;
  the server never mints a session.

**Modern request** (`params._meta["io.modelcontextprotocol/protocolVersion"]`
present)

- Version must be `2026-07-28`, else 400 + `-32022`
  UnsupportedProtocolVersionError with
  `supported: ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]`.
- `MCP-Protocol-Version` must equal the `_meta` version, `Mcp-Method` must
  equal `method`, and for `tools/call` `Mcp-Name` (after decoding a
  `=?base64?…?=` value) must equal `params.name`. Missing or different →
  400 + `-32020` HeaderMismatch. No tool uses `x-mcp-header`.
- Methods: `server/discover` (supportedVersions, `capabilities: {tools: {}}`,
  `_meta.serverInfo`, `instructions`), `tools/list`, `tools/call`, `ping`.
  Results carry `resultType: "complete"`. Unknown method → 404 + `-32601`.

**Legacy request** (no `_meta` version)

- `initialize` → `protocolVersion` = the client's if it is one of
  2025-11-25 / 2025-06-18 / 2025-03-26, else 2025-11-25;
  `capabilities: {tools: {}}`, `serverInfo`, `instructions`. No session id.
- Then `tools/list`, `tools/call`, `ping` with the same tools. A missing
  `MCP-Protocol-Version` header is treated as 2025-03-26 (spec permits).
- Unknown method → JSON-RPC `-32601`.

`instructions` tell Claude what the app is: sections, Work/Personal, dates as
`YYYY-MM-DD`, and that new tasks go to the Inbox unless a date or section
places them.

## Tools

Five tools, in this order, each a thin wrapper over `task_service` so every
rule above still applies. Section values: `inbox`, `today`, `tomorrow`,
`this_week`, `next_week`, `backlog`, `freezer`. A task is returned as
`{id, title, section, type, due_date, project, notes, status}`; each result
has a one-line text summary plus `structuredContent`.

| Tool | Arguments | Does |
|---|---|---|
| `create_task` | `title`*, `type`* (`work`/`personal`), `due_date`, `section`, `project` (name), `notes` | `create_task`; Inbox unless a date or section places it |
| `list_tasks` | `section`, `type`, `project`, `status` (`open` default / `completed`), `limit` (50, max 200) | Read-only (`readOnlyHint`) |
| `complete_task` | `task_id`*, `complete_subtasks` (false) | `complete_parent_task`; with open subtasks and no flag, an error says how many and to pass `complete_subtasks: true` |
| `update_task` | `task_id`*, `title`, `due_date` (null clears), `notes`, `project` (null clears) | `update_task` with only those keys |
| `move_task` | `task_id`*, `section`* | `update_task` with `tier` only |

`project` is matched case-insensitively by exact name among active projects
of the task's type; no match → a tool error naming the projects of that
type. Only an **active** task can be completed, updated or moved. No tool
deletes, cancels, touches goals, recurring templates, settings or exports.

Errors: a `task_service.ValidationError`, a refused rule, or an argument
that breaks the tool's `inputSchema` (missing, wrong type, not in the enum,
unknown key) comes back as a tool result with `isError: true` and a plain
message, so Claude can correct itself — MCP 2025-11-25 moved input
validation errors to tool results for exactly this. Only an unknown tool
name or `arguments` that isn't an object is a JSON-RPC `-32602`.

## The credential (ADR-044)

- New module `mcp_token.py`, a copy of the voice-token design: signed with
  `SECRET_KEY`, salt `taskmanager-mcp-v1` (distinct from session, validator
  and voice salts), carries the authorized email + a random `jti`, **365-day**
  lifetime (the dialog never shows a saved header again, so replacing it
  means re-entering the header or re-adding the connector).
- Revocation: `jti` denylist in `AppSetting` key `mcp_revoked_jtis`, written
  by `flask revoke-mcp-token <jti>`; `SECRET_KEY` rotation kills all tokens.
- Minting: `railway run python scripts/mint_mcp_token.py` prints the token
  (like `mint_validator_cookie.py`). No `/settings` card in v1.
- Accepted **only** by the `/mcp` route's decorator. `login_required` never
  reads it, so every other route rejects it. A missing / bad / revoked /
  expired token → 401 with a JSON-RPC error and no detail of why. The local
  dev bypass does NOT open `/mcp`; local testing mints a local token.
- Rate limit: new `MCP_LIMIT = "60 per minute"` on the route.

**Keeping the token out of logs.** It only ever travels in the
`Authorization` header. Neither the app's request log nor gunicorn's access
log records request headers, Railway's HTTP logs record the path (`/mcp`)
and not headers, and `scrub_sensitive`'s existing `bearer` / `authz`
patterns redact it if any log text ever quotes the header.

**Audit.** Every change a tool makes (and every list) logs one WARNING line —
WARNING because `configure_logging` keeps WARNING and up by default —
`mcp: created task <id>`, `mcp: moved task <id> to today` — never the token,
never the title (titles can hold anything). Visible at `/api/debug/logs`.

## Security notes (go into ADR-044 and CLAUDE.md's threat model)

- Blast radius of a leaked token: create tasks, read every task's title and
  notes, complete / edit / move active tasks — until it expires, is revoked,
  or `SECRET_KEY` rotates. No delete, nothing outside tasks. Wider than the
  voice token (which reads only the review queue), narrower than an OAuth
  session.
- Task text flows into Claude chats, which is the point; a task title could
  carry prompt-injection text. claude.ai shows tool calls and asks before
  running them unless the user chooses "Always allow".
- `/mcp` ignores cookies entirely, so a browser session can't be ridden into
  it (and the `Origin` check refuses browsers anyway).

## Testing

- `tests/test_mcp_token.py`: mint/parse round trip, wrong salt, other email,
  expired, revoked `jti`, tampered.
- `tests/test_mcp_api.py` (protocol): modern `server/discover`, `tools/list`,
  `tools/call`; each HeaderMismatch case; base64 `Mcp-Name`; unsupported
  version; legacy `initialize` → `tools/list` → `tools/call`; notification
  202; batch 400; GET/DELETE 405; Origin 403 / allowed / absent; 401 for no /
  bad / revoked token; a token in the URL path (`/mcp/<token>`) is not a
  route (404); the token is refused on `/api/tasks`; the voice token and
  validator cookie are refused on `/mcp`; the dev bypass doesn't open
  `/mcp`; rate limit; no log row holds the token.
- `tests/test_mcp_tools.py`: each tool's happy path and each refusal (title
  missing, bad type, bad date, unknown project, other-type project, closed
  task, open subtasks, unknown id), section placement by date, `update_task`
  null clears, `list_tasks` filters and limit, audit line written without
  the title.
- Manual: MCP Inspector against the local server with a local token; after
  deploy, the real claude.ai connector creates, lists, completes, edits and
  moves a task, and each shows on the board.

## Docs

- ADR-044 (new credential); CLAUDE.md threat model gets the token.
- ARCHITECTURE.md: Components + Data Flows + Route catalog (`/mcp`);
  `arch_sync_check` enforces the catalog.
- Help (`templates/docs.html`): a short "Connect Claude" section (what Claude
  can do, how to mint the token, how to add the connector, how to revoke) —
  fact-check table + Phase 6 at 1280 and 375.
- BACKLOG.md: #522.

## Out of scope

OAuth; a `/settings` card to mint/revoke; SSE streaming, resources, prompts;
delete or cancel; goals, recurring templates, projects as objects. Each can
come later without changing the endpoint.
