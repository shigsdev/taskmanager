# ADR-044: A scoped MCP token lets Claude create, read, complete, edit and move tasks

Date: 2026-10-30

Status: ACCEPTED (#522, user decisions 2026-10-30)

Related: ADR-034 / ADR-042 / ADR-043 (the voice-action token this copies),
ADR-003 / ADR-004 (the read-only validator cookie).

## Context

The user wants Claude in claude.ai (desktop and phone) to log and manage
tasks: "logged: draft Apigee vendor questions, due Fri". claude.ai reaches
external tools through a **custom connector**: a remote MCP server it calls
from Anthropic's servers. The app's Google OAuth is built for a person in a
browser, the validator cookie can't mutate, and the voice token is scoped to
`/api/voice-review/*`.

A custom connector can authenticate with OAuth, or with "No sign-in" plus up
to four fixed **Request headers** ("sent with every request as this
connector's credentials, such as an API key … sent exactly as entered").
The user confirmed their account offers the header form. Making the app an
OAuth provider is several times the work of the feature itself.

## Decision

1. **A new token** in `mcp_token.py`, built like ADR-034's: signed with
   `SECRET_KEY` under salt `taskmanager-mcp-v1`, carrying the authorized
   email and a random `jti`, 365-day lifetime. It is minted with
   `railway run python scripts/mint_mcp_token.py` and revoked with
   `flask revoke-mcp-token <jti>` (denylist in `AppSetting`
   `mcp_revoked_jtis`), or all at once by rotating `SECRET_KEY`.
2. **Accepted only on `/mcp`, only in a header**: `POST /mcp` with
   `Authorization: Bearer <token>`, which the connector sends as a Request
   header. There is no token-in-URL form. `login_required` never reads the
   token, so every other route rejects it, and `/mcp` accepts no other
   credential (no OAuth session, validator cookie, voice token or dev
   bypass).
3. **Five tools** (spec: `docs/design/522-mcp-connector.md`):
   `create_task`, `list_tasks`, `complete_task`, `update_task`,
   `move_task`. Each calls the existing `task_service` functions with only
   its own fields, so every task rule still applies. Only active tasks can
   be changed. No delete, no cancel, nothing outside tasks.
4. **The token stays out of logs.** Request headers aren't logged by the
   app, gunicorn or Railway's HTTP logs, and `scrub_sensitive` already
   redacts `Bearer …` / `Authorization: …` text. Each change and each list
   logs one WARNING-level audit
   line (`mcp: moved task <id> to today`) with no token and no title.
5. 60 requests a minute. Requests with an `Origin` other than claude.ai /
   claude.com are refused (MCP's DNS-rebinding rule).

## Consequences

- **A leaked token can do more than the voice token.** Until it expires,
  is revoked, or `SECRET_KEY` rotates, a holder can create tasks, read
  every task's title and notes, and complete, edit or move active tasks.
  It still can't delete, can't reach goals, projects, recurring templates,
  settings, exports or auth. Every change is visible in the app;
  completions and moves can be undone, but an overwritten title or notes
  can't (there is no edit history).
- **The token lives in claude.ai's connector settings.** Anthropic stores
  the header value ("stored securely and never shown again"), so a leak
  there is a leak of the token. A Railway breach like 2026-10-21's exposes
  `SECRET_KEY`, which can forge a token, so rotating secrets after a breach
  also means minting a new token and re-entering the header (Help → Rotate
  every secret gets a step).
- **Task text reaches Claude chats.** That is the point of the feature. A
  title could carry prompt-injection text aimed at Claude. claude.ai shows
  each tool call and asks first unless the user picks "Always allow", and
  the tools can't do anything a person couldn't undo.
- **We own MCP protocol compliance.** The endpoint is hand-written
  (stateless JSON, both the 2026-07-28 per-request era and the older
  `initialize` era). Protocol tests pin it, and MCP Inspector plus the real
  connector check it before ship.
- **A 365-day token outlives a short one's safety margin.** It was chosen
  because replacing it means re-entering the header in claude.ai. The jti
  denylist gives a one-token kill switch.

## Alternatives considered

- **Make the app an OAuth provider** (Google sign-in once in claude.ai, no
  shared secret). The most secure and works on every account. Rejected for
  now: authorization, token and client-registration endpoints are several
  times the feature's size. It can replace the token later without changing
  the tools.
- **Token in the URL path** (`POST /mcp/<token>`, "No sign-in" with no
  header). Rejected once the user found the header option: Railway's HTTP
  logs record every path, so anyone reading them, or any log drain, would
  hold a working token, and the app would need path redaction in its own
  request log and gunicorn's access log.
- **Reuse the voice token.** Rejected: it would widen ADR-034's scope to
  every task and to reading the whole list, and one leak would expose both
  the Siri Shortcut and Claude. Separate salts and denylists keep them apart.
- **The official MCP SDK** (a second Railway service, or bridged into Flask).
  Rejected by the user: a second deploy target and secrets for five tools,
  or async-in-sync friction with gunicorn's two sync workers.
