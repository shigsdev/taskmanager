# #258 — Claude Code automation recommendations

**Status:** OPEN (Priority 1) — filed 2026-05-28 via
`/claude-automation-recommender` skill (claude-code-setup plugin).
No implementation yet. Each recommendation is independently
shippable; pick 1-2 to start with.

**Date:** 2026-05-28

**Recommended starting point:** the `sop-report` skill + the
`ruff` PostToolUse hook. Both pay back on every single PR — the
first eliminates the "I forgot to print the report" failure mode
CLAUDE.md calls out (7× missed reports in the 2026-04-20 sprint);
the second catches lint-fixable issues at edit time instead of
gate time.

---

## Codebase profile

- **Type**: Python 3.14 Flask multi-page PWA + Service Worker
- **Stack**: Flask 3.1 / SQLAlchemy 3.1 / Alembic / PostgreSQL on
  Railway / gunicorn 26 / APScheduler / Fernet / SendGrid
- **Frontend**: vanilla JS, no framework — but Service Worker +
  `CACHE_VERSION` discipline
- **Testing**: pytest+cov (80% floor), Jest, Playwright (4
  projects), bandit, semgrep, gitleaks, pip-audit, npm audit,
  custom drift gates (`docs_sync_check`, `arch_sync_check`,
  no-string-match-only)
- **Existing automation surface**: NO `.claude/agents`, NO
  `.claude/skills`, NO hooks. Heavy reliance on
  `scripts/run_all_gates.sh` + manual SOP cadence in CLAUDE.md.
  Only `.claude/settings.local.json` (permissions allow-list).
- **MCP installed**: chrome-devtools-mcp ✅ (now Phase 6 preferred
  per #257), Claude Preview, Railway (OAuth never completed — see
  #15).

---

## MCP Servers

### #258-A — PostgreSQL MCP (`@modelcontextprotocol/server-postgres`)

**Why**: You probe the live prod schema + state constantly —
checking `app_logs` for the #248 leak, designing `cron_audit` for
#167, scheduler heartbeats, BACKLOG migration questions. Today
every probe is a `curl /api/debug/logs` + Python decode dance
(this session: hit a `cp1252` encoding bug doing exactly this
30 minutes ago). A PG MCP pointed at the prod Postgres URL gives
typed query results without the round-trip ceremony, AND would
make the #167 design ("does `cron_audit` need this column?") a
one-shot rather than spec-it-then-verify.

**Install**:
```bash
claude mcp add postgres -- npx -y @modelcontextprotocol/server-postgres "$DATABASE_PUBLIC_URL"
```

**Caveat**: use the *public* Railway URL (Railway dashboard →
Postgres → Public TCP proxy), NOT `postgres.railway.internal` —
same #168 DNS gotcha applies. Store in `.env` not `.mcp.json`
(it's a secret; `.mcp.json` would commit to repo).

**Effort**: S (~10 min to install + verify).
**Risk**: Low. Read-only credential acceptable here.

---

### #258-B — Complete Railway MCP OAuth flow (closes #15)

**Why**: You shipped #168 *about* `railway run` vs `railway ssh`
DNS pain today. The Railway MCP would let you trigger deploys,
tail logs, and pull env vars from inside Claude — eliminating the
`railway run` / `railway ssh` decision point at the source.
`mcp__railway__authenticate` is already loadable but never been
exercised; closing #15 by spending 5 minutes on the OAuth dance
turns a chronic friction point into a chat affordance.

**Install** (already added, just complete it):
- In Claude: invoke `mcp__railway__authenticate`, then
  `mcp__railway__complete_authentication` per the protocol.

**Effort**: XS (~5 min).
**Risk**: Low — OAuth scope is per-workspace + revocable.

---

## Skills

### #258-C — `sop-report` skill — generate the 8-phase SOP Compliance Report

**Why**: You print this **every PR** (CLAUDE.md mandates it; the
timing rule says "ONLY AFTER ALL of Phase 8 is complete"). The
format is rigid: 8 phases × 3-5 rows each × `[✅]` / `[⏭️]` /
`[❌]` markers. Today I assemble it free-hand from session memory
each time, which is error-prone — the "7× missed reports in the
2026-04-20 sprint" failure mode CLAUDE.md explicitly calls out.
A skill that takes a structured input
(`commits`, `files_changed`, `gates_status`, `deploy_sha`,
`smoke_result`, `cascade_findings`) and emits the canonical
format eliminates that drift class.

**Create**: `.claude/skills/sop-report/SKILL.md`
**Invocation**: Both (Claude triggers automatically at end of
ship; user can `/sop-report` for ad-hoc).

```yaml
---
name: sop-report
description: Generate the 8-phase SOP Compliance Report after a shipped change. Pass commits + files + gate/deploy status; emits the exact CLAUDE.md template.
---
```

**Effort**: S (~30 min — write SKILL.md + the 8-phase template).
**Risk**: Low — read-only / output-only.

---

### #258-D — `cascade-check` skill — walk CLAUDE.md's cascade table

**Why**: The cascade table in CLAUDE.md is **~20 rows long** ("if
you changed X, also update Y"). Skipped rows = the #248-class of
bug (changed `app.py` module behavior, missed `test_deployment.py`
update) or #138 D-B1 (changed CSS grid, missed `minmax(0,...)`
cascade). Today I walk it mentally and rows get missed. A skill
that takes a `git diff --name-only` list and surfaces "you changed
`static/style.css` → bump `CACHE_VERSION` + update `sw.js`
`APP_SHELL` + `health.py` `EXPECTED_STATIC_FILES`" catches every
row mechanically.

**Create**: `.claude/skills/cascade-check/SKILL.md`
**Invocation**: Both.

```yaml
---
name: cascade-check
description: Walks CLAUDE.md's "if you changed X, also update Y" cascade table against changed files. Outputs a per-row checklist with file paths to update or N/A reasons.
---
```

**Effort**: S-M (~45 min — distill the cascade table into a
matchable structure, write the walking logic).
**Risk**: Low.

---

## Hooks

### #258-E — `PostToolUse: ruff format + check on *.py edit`

**Why**: Every `Edit` / `Write` on a `.py` file you eventually
run `ruff check .` at gate time. Catching it on edit is ~50ms vs
gate-time minutes, AND it auto-fixes the trivial UP041 / I001 /
D200 rules without a round-trip. You hit this exact friction
this session (UP041 on `socket.gaierror` after the #168 commit —
manual fix + retry).

**Where**: `.claude/settings.json` (project-level)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "case \"$CLAUDE_FILE_PATH\" in *.py) python -m ruff check --fix --select F,E,W,UP,I --exit-zero \"$CLAUDE_FILE_PATH\" 2>&1 | tail -5 ;; esac"
          }
        ]
      }
    ]
  }
}
```

`--exit-zero` keeps it non-blocking so it's signal not noise.
Gate 1 in `run_all_gates.sh` is still authoritative.

**Effort**: XS (~10 min).
**Risk**: Low — non-blocking, auto-fix only handles safe rules
(F/E/W/UP/I, not S security rules).

---

### #258-F — `PreToolUse: warn on `app.py` module-level edits`

**Why**: The `app = create_app()` at module level was the literal
root cause of the #248 prod-log-leak. Pytest imports app.py →
`create_app()` runs → DBLogHandler attaches to prod DB. CLAUDE.md
now has the `_RUNNING_UNDER_PYTEST` guard, but the guard itself
is fragile — anyone editing the module-level scope could
re-introduce the leak without realizing. A hook that prints a
warning + a pointer to `app.py:880`'s "this branch is
intentionally a bare stub, do NOT add side effects here" comment
is a cheap defense.

**Where**: `.claude/settings.json`

```json
{
  "PreToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "case \"$CLAUDE_FILE_PATH\" in *app.py) echo '⚠️  Editing app.py — module-level side effects are gated by _RUNNING_UNDER_PYTEST (see line 880). Adding side effects outside that guard re-introduces the #248 prod-log-leak.' >&2 ;; esac"
      }]
    }
  ]
}
```

**Effort**: XS (~5 min).
**Risk**: Low — warning-only, doesn't block.

---

## Subagents

### #258-G — `cascade-auditor` subagent — retrospective cascade compliance

**Why**: Complement to the `cascade-check` skill (skill = forward
checklist; subagent = retrospective audit). Runs after Phase 4
gates pass and before commit, reads `git diff`, walks every
cascade row, reports gaps. Catches things like: "you changed
`models.py` adding a column, but `_SCHEMA_DESCRIPTIONS` in
`architecture_service.py` doesn't have an entry — the
`test_every_column_has_a_description` drift-gate test will fail
at next ship". Same class as `feature-dev:code-reviewer` but
cascade-specific.

**Create**: `.claude/agents/cascade-auditor.md`
**Tools**: Glob, Grep, Read, Bash (read-only diff inspection).

**Effort**: M (~1h — write the agent prompt + verify on 3 past
shipped PRs).
**Risk**: Low — read-only, advisory output.

---

### #258-H — `adr-drafter` subagent — drafts ADRs for security refactors

**Why**: CLAUDE.md mandates ADRs for "security-sensitive
refactors (broadened a scope, changed an auth check)" and
`docs/adr/` already has 25+ files in a consistent format. When
you (eg) bump session TTL 24h→30d (PR100) or rework
`safe_call_api` boundaries (ADR-023), the ADR follows a stable
shape: Status, Context, Decision, Consequences, Related. A
subagent that takes a diff + supersede target and drafts the ADR
in-format closes the cascade gap where ADRs get forgotten under
hotfix pressure.

**Create**: `.claude/agents/adr-drafter.md`
**Tools**: Read, Write, Glob, Grep.

**Effort**: M (~1h — write the prompt + verify against ADR-023
and ADR-006 as gold standards).
**Risk**: Low — drafts go to `docs/adr/NNN-*.md` as
PR-reviewable text.

---

## Categories deliberately skipped

- **Plugins** — you already have the relevant ones
  (`frontend-design`, `skill-creator`, `claude-plugins-official`,
  `claude-code-setup`). No high-value addition.
- **Documentation MCP (`context7`)** — already in your plugin
  cache. Useful for live Flask / SQLAlchemy / APScheduler docs
  but lower priority than PG MCP given how stable those library
  APIs are.

---

## Phased rollout (if approved)

The 8 recommendations split cleanly into two waves:

**Wave 1 — pay-back-every-PR** (start here if anything):
1. `sop-report` skill (#258-C)
2. `ruff` PostToolUse hook (#258-E)
3. `app.py` PreToolUse warning hook (#258-F)

Total: ~45 min implementation. ~80% of the value, IMO.

**Wave 2 — situational power-tools**:
4. PostgreSQL MCP (#258-A)
5. Railway MCP OAuth (#258-B / closes #15)
6. `cascade-check` skill (#258-D)
7. `cascade-auditor` subagent (#258-G)
8. `adr-drafter` subagent (#258-H)

Total: ~4-5h spread across sessions. Each independently
shippable.

---

## Open questions before kickoff

- **PG MCP cookie path**: store the public Postgres URL in
  `.env` or in a separate uncommitted `.env.mcp`? Either works;
  separation makes the secret's purpose explicit.
- **Skill invocation default**: should `sop-report` and
  `cascade-check` default to user-invoked-only
  (`disable-model-invocation: true`) or allow Claude to
  auto-trigger? Auto-trigger fits the SOP cadence better but
  could feel noisy.
- **Hook ordering**: if both #258-E and a future `bandit` hook
  fire on `*.py` edits, what's the right order? Ruff first
  (cheap fast-fail) seems right.
- **Cascade-check vs cascade-auditor overlap**: do we ship both,
  or pick one? The skill is forward-looking + user-driven; the
  subagent is retrospective + automation-driven. They complement
  but the skill alone might cover 80% of the value.

Discuss before scoping individual sub-PRs.
