---
name: sop-report
description: Generate the 8-phase SOP Compliance Report after a shipped change. Use after every ship — pre-deploy gates done, post-deploy validated, prod smoke green. Captures Planning / Git Workflow / Coding Standards / Quality Gates / Tests / Regression / Documentation / Deploy with [✅] / [⏭️] / [❌] markers per CLAUDE.md.
---

# SOP Compliance Report Skill

## Purpose

Generate the canonical 8-phase **SOP Compliance Report** that CLAUDE.md
mandates printing after every shipped change. Filed as #258-C
(2026-05-29) after CLAUDE.md called out "7× missed reports in the
2026-04-20 sprint" as a recurring failure mode — manual recall of
the format is fragile under shipping pressure.

## When to use this skill

**Print the report ONLY AFTER ALL of Phase 8 is complete** — DEPLOY
GREEN + monitor window passed + prod smoke green. Per CLAUDE.md:

> Do NOT print interim reports with `[⏳] AWAITING` placeholders. One
> clean checklist per PR, with every phase resolved.

For doc-only changes, Phase 8 collapses to `[⏭️] N/A — doc-only
change`. For UI changes Phase 6 is mandatory. For non-UI changes
Phase 6 collapses to `[⏭️] N/A — no UI change`.

## Status indicator legend

- `[✅]` — done and passed
- `[⏭️]` — skipped (N/A) **with reason after it**
- `[❌]` — failed or not done (the change is **not** complete; go
  fix it before declaring done — never mark complete if any row
  is `[❌]`)

A missing report = `[❌]` per CLAUDE.md ("Treat a missing SOP report
as a `[❌]` — the change is not done").

## Template

Adapt the one-line description and phase rows to the actual work
done. **Do not pad with `[✅]` markers for steps that weren't
actually done.**

```
SOP Compliance Report — <one-line description>
──────────────────────────────────────────────────
Phase 1  Planning
  [✅] Checked backlog                        <backlog item or reason>
  [✅] Scoped work                            <brief scope>
  [✅] Identified affected files              <file list>
Phase 2  Git Workflow
  [✅] Pulled latest main                     <SHA / branch state>
  [✅] Feature branch created                 feature/<name>
  [✅] Small logical commits                  <N> commits: <SHA list + one-line summaries>
  [✅] Merged to main + pushed                fast-forward | merge commit
  [✅] Feature branch cleaned up              deleted
Phase 3  Coding Standards
  [✅] Code changes                           <what changed, in one or two sentences>
  [⏭️] Frontend changes                       N/A — no UI change
  [✅] Cascade check                          <which CLAUDE.md cascade rows triggered + what was updated, or "no rows triggered" with brief reason>
  [✅] Security rules followed                <relevant checks — auth, secrets, encryption, etc.>
Phase 4  Quality Gates
  [✅] Ruff                                   PASS (0 warnings)
  [✅] Pytest                                 <n> passed, <coverage>%
  [✅] Jest                                   <n> passed, 0 failed
  [✅] Local Playwright + bandit + semgrep + gitleaks + sync ALL PASS
Phase 5  Tests
  [✅] Tests added/updated                    <what was tested + count>
  [⏭️] Route tests                            N/A — no new routes
Phase 6  Regression (UI changes only)
  [✅] Bypass server started                  seed_dev_data + preview_start
  [✅] Desktop (1280×800)                     <results — element checks + viewport parity>
  [✅] Mobile (375×812)                       <results — touch targets + viewport parity>
  [✅] Console errors                         0
  [✅] Bypass torn down                       .env.dev-bypass deleted
Phase 7  Documentation
  [✅] ARCHITECTURE.md                        <what updated or N/A reason>
  [✅] README.md                              <what updated or N/A reason>
  [✅] BACKLOG.md                             <row moved to Resolved + status updated to ✅>
  [⏭️] CLAUDE.md                              N/A — no SOP rule change
Phase 8  Deploy
  [✅] Deploy validation                      GREEN — <SHA>, all checks ok
  [✅] Error log scan                         PASS (0 server ERROR rows since deploy start)
  [✅] Post-deploy monitor                    5-min MONITOR GREEN
  [✅] Post-deploy smoke test                 <N>/<N> prod Playwright smoke PASS (<time>s)
Summary: <N> done, <N> skipped (N/A), <N> not done
Commits: <SHA list>
```

## Required inputs (gather before generating)

When this skill is invoked, gather:

1. **Description** — one-line summary of the change (`#NNN: title`).
2. **Commits** — the SHAs landed in this ship (usually 1, sometimes
   2 if doc-only follow-up).
3. **Files changed** — `git diff --stat main...HEAD` against the
   feature branch before merge, or `git show <merge-sha> --stat`
   after merge.
4. **Gate results** — pull from `run_all_gates.sh` output:
   - Ruff status
   - Pytest pass count + coverage %
   - Jest pass count
   - Other gates: bandit, pip-audit, npm audit, docs/arch sync,
     semgrep, gitleaks, Playwright local
5. **Deploy validation** — `python scripts/validate_deploy.py
   --monitor-minutes 5` output:
   - Deploy SHA match
   - Auth preflight pass
   - Error log scan pass
   - Monitor window result
6. **Prod smoke result** — `npm run test:e2e:prod` output:
   - Pass count / total
   - Wall-clock duration
7. **UI change?** — if YES, also gather:
   - Phase 6 desktop results (visual + functional + viewport parity)
   - Phase 6 mobile results
   - Console error count
   - Bypass cleanup confirmed (`ls .env.dev-bypass` returns
     "no such file")

## Common patterns by change shape

### Doc-only change (BACKLOG / README / ADR / design doc)

Phase 6 → `[⏭️] N/A — no UI change`. Phase 8 collapses entirely:
`[⏭️] N/A — doc-only change` per CLAUDE.md ("Skip for doc-only
changes"). Mark `[⏭️]` on every Phase 8 row.

### Backend-only change (service / API endpoint / migration)

Phase 6 → `[⏭️] N/A — no UI change`. Phase 8 runs fully.

### UI change (template / CSS / new HTML route)

Phase 6 is **mandatory** at BOTH desktop (1280×800) and mobile
(375×812). The `chrome-devtools-mcp` tool is preferred (#257) when
loaded; Claude Preview is the fallback. Verify viewport parity
(`document.documentElement.scrollWidth <= window.innerWidth`) at
both viewports.

### Refactor with no behavior change

Phase 5 may be `[⏭️] N/A — purely structural`; rely on the
existing test suite as the safety net. Existing Playwright + Jest
must still pass.

## Cascade-row reminders (CLAUDE.md)

When filling Phase 3 "Cascade check", walk the table:

- New static asset → `sw.js` APP_SHELL + `health.py`
  EXPECTED_STATIC_FILES + `CACHE_VERSION` bump
- New route → ARCHITECTURE.md route catalog + nav update
- New env var → README.md table + `.env.example`
- New `db.Model` → `EXPECTED_TABLES` + `_ER_TABLE_GROUPS` +
  `_ER_TABLE_ORDER` + `_SCHEMA_DESCRIPTIONS`
- New column on existing model → `_SCHEMA_DESCRIPTIONS[table][cols]`
- New scheduler job → ARCHITECTURE.md scheduler box + Route catalog
- User-visible behavior → `templates/docs.html` (fact-check pass)
- Security-sensitive refactor → new ADR superseding old
- Module-level side effects in `app.py` → mind the
  `_RUNNING_UNDER_PYTEST` guard (#248 / #259)

A row that wasn't triggered = state "no cascade rows triggered".
A row that WAS triggered and ignored = `[❌]` — the change is
blocked.

## Output format

Render as a Markdown code block so the user can copy-paste into a
commit message or session log. Use box-drawing characters (`──────`)
for the underline. Keep status markers ASCII-aligned vertically so
the report is scannable at a glance.

## Anti-patterns this skill prevents

- **Missing report** — CLAUDE.md tracks the 2026-04-20 sprint
  failure where 7× shipped PRs had no report. The skill makes the
  format mechanical so there's no "I forgot the template" excuse.
- **Interim reports with placeholders** — CLAUDE.md says wait
  until Phase 8 is complete. The skill demands the inputs upfront
  so partial-completion is visible.
- **`[✅]` on rows that didn't run** — the legend insists on
  reasons after `[⏭️]` and treats unjustified `[✅]` as drift.
- **Pad-the-checklist** — only include rows that were actually
  considered for this change shape.
