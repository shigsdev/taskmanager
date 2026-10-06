# Spec #388 — move deploy settings off `railway.toml` before 2026-12-01

**Filed:** 2026-10-05 (found during the new-machine setup: `railway link`
printed the Config-as-Code deprecation warning)
**Status:** decision recorded 2026-10-05 — settings live in the Railway
dashboard only (§4); approved to build ("please now fix the railway.toml")
**Deadline:** 2026-12-01 — "Existing Config as Code files stop being read
on 2026-12-01 (hard cutoff)" (docs.railway.com/infrastructure-as-code).

---

## 1. What `railway.toml` does today

| Setting | Value | Why it matters |
|---|---|---|
| `[build] builder` | `nixpacks` | `nixpacks.toml` forces the Python provider; without Nixpacks, `package.json` (Jest only) makes the build detect Node |
| `[build] watchPatterns` | `**` minus BACKLOG.md, docs/, tests/, .github/, .gitignore, .gitattributes, .pre-commit-config.yaml, README/CLAUDE/ARCHITECTURE.md | #246 — stops the audit bot's `chore(autofile)` commits and doc-only pushes from restarting prod |
| `[deploy] startCommand` | `flask db upgrade && gunicorn app:app -c gunicorn.conf.py` | the ONLY place alembic runs on deploy (CLAUDE.md `migrations: fail` triage points here) |
| `[deploy] healthcheckPath` | `/healthz` | the rolling deploy only promotes a container whose `/healthz` is 200 (503 on critical fails, incl. migrations behind head) |
| `[deploy] healthcheckTimeout` | `120` | ADR-033 sized the boot budget against it |
| `[deploy] restartPolicyType` | `on_failure` | crash → restart |

## 2. What Railway falls back to after the cutoff (measured)

`railway config pull --json` on 2026-10-05 (service `web`,
`7dfddefc-…`) shows the service's own settings — what applies once the
file is ignored:

| Setting | Service value today | Effect at cutoff |
|---|---|---|
| startCommand | `gunicorn app:app -c gunicorn.conf.py` | **migrations stop running** |
| healthcheckPath | `/health` | **`/health` is 404 on prod** → every new deploy fails its health check and never goes live (old container keeps serving) |
| builder | `RAILPACK` | `nixpacks.toml` ignored → likely Node detection, broken build |
| watch patterns | not set | every push redeploys (autofile churn, #246 regresses) |
| healthcheckTimeout / restart policy | not shown | Railway defaults |

Net: from 2026-12-01 no code could ship, and the first schema change
would break. Nothing visible happens before then.

## 3. Why not just run `railway config migrate --apply`

Dry run (`railway config migrate`, 2026-10-05) emits
`.railway/railway.ts` with `service("taskmanager", …)` — but the real
service is **`web`**, so applying it risks managing/creating a second
service. It translates only `start`, `healthcheck`, `healthcheckTimeout`;
`builder` and `watchPatterns` become comments and `restartPolicyType`
disappears — the IaC DSL has no fields for them
(docs.railway.com/infrastructure-as-code/reference). IaC is also not read
on deploy: it is applied by `railway config apply` or the
`railwayapp/config` GitHub Action. And `--apply` immediately clears the
service's Config File settings — a live prod change.

## 4. Decision (user, 2026-10-05): Railway dashboard only

All six settings are set on the `web` service in the Railway dashboard;
`railway.toml` is deleted. One source of truth, no new tooling. The
expected values are recorded in ARCHITECTURE.md ("Deploy configuration")
so they can be re-checked — they are no longer code-reviewed.

## 5. Plan

1. **Dashboard (user, or Claude via the user's Chrome with permission)** —
   service `web` → Settings, set to the values in §1:
   - Builder: **Nixpacks**
   - Watch Paths: the 11 patterns, one per line
   - Custom Start Command: `flask db upgrade && gunicorn app:app -c gunicorn.conf.py`
   - Healthcheck Path: `/healthz`; Healthcheck Timeout: `120`
   - Restart Policy: **On Failure**
   While `railway.toml` exists it still overrides these, so this step has
   no effect on prod by itself. Verify with `railway config pull --json`
   (shows builder / start / healthcheck).
   **Open question for the dashboard step:** if the UI greys fields out
   as "managed by config file", the order flips — see §6.
2. **Code (one commit):** delete `railway.toml`; rewrite the four
   `tests/test_deployment.py` tests that read it into a guard that it
   stays deleted (a re-added file would silently stop working after the
   cutoff); CLAUDE.md `migrations: fail` triage line → dashboard start
   command; ARCHITECTURE.md "Deploy configuration" section with the six
   values + how to re-check; README if it mentions the file.
3. **Ship it:** full gates → merge → backup → push. This push deploys
   with the dashboard settings. Validate: new `git_sha` live (proves the
   build and the `/healthz` health check worked), `migrations: ok`, log
   scan + 5-min monitor, prod smoke.
4. **Watch-paths proof:** the BACKLOG-only "mark shipped" push must NOT
   redeploy (prod `started_at` unchanged).

## 6. Risks and the safety net

- Rolling deploys keep the old container serving until the new one's
  health check passes, and `/healthz` returns 503 if migrations are behind
  head. So a wrong start command, health path or builder makes the
  deploy **fail**, not prod go down. Rollback = fix the dashboard value
  and redeploy (or revert the commit while the file still works, before
  12-01).
- If the dashboard fields are locked while the file exists: delete the
  file first, let that deploy fail safely on the fallback settings
  (old container keeps serving), set the dashboard, redeploy. Acceptable,
  but prefer setting the dashboard first if the UI allows it.
- Nixpacks itself may be deprecated in favour of Railpack later; switching
  builders is out of scope (would need a `railpack.json` / provider
  override and its own test deploy). If the dashboard no longer offers
  Nixpacks, stop and file that as the blocker.

## 6b. What the dashboard showed (2026-10-05) — order flipped

Every relevant field on the `web` service reads *"The value is set in
/railway.toml"* and can't be edited while the file exists; the Builder
picker labels Nixpacks **"Deprecated"**. So §6's fallback order applies
(user approved 2026-10-05):

1. Commit deleting `railway.toml` (+ tests/docs); gates → backup → push.
2. That deploy runs on the fallback settings (Railpack, `/health`, no
   migrations) and is expected to fail its health check; the old
   container keeps serving.
3. Once the fields unlock, set the six values (Claude, in the user's
   Chrome, confirming each before saving).
4. Redeploy the same commit; validate (`git_sha`, `migrations: ok`, log
   scan, 5-min monitor, prod smoke).
5. BACKLOG-only push must not redeploy (Watch Paths proof).

## 7. Out of scope

- Adopting IaC (`.railway/railway.ts`) — rejected in §4.
- Moving migrations to Railway's pre-deploy command — a behaviour change
  with its own failure modes; the start command stays byte-identical.
- Switching to Railpack.
