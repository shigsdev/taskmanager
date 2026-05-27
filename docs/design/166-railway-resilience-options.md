# #166 — Railway Resilience: Options Analysis

**Status:** Pre-decision design doc. No code commitment yet. Reviewed → choose
direction → split into sub-PRs against #166.

**Filed:** 2026-05-19 during the Railway / GCP US East outage.

---

## Incident that prompted this

**May 19–20, 2026** — Google Cloud blocked Railway's entire GCP account.
Railway's control plane (dashboard, GraphQL API, internal networking) runs
on GCP, so when GCP suspended the account, Railway went largely dark.

Public timeline from `status.railway.com`:

| UTC | Event |
|---|---|
| May 19 22:29 | Investigating widespread disruption ("no healthy upstream", login failures, dashboard unreachable) |
| May 19 22:43 | Identified — upstream cloud provider access "restored" |
| May 19 23:37 | Identified — Google Cloud has **blocked Railway's account**; escalated |
| May 20 00:37 | Restoring GCP-hosted infrastructure that powers dashboard / API / control plane |
| May 20 01:23 | Continuing GCP recovery; evaluating alternative paths in parallel |
| May 20 01:34 | Compute recovered on GCP; networking still broken |
| May 20 01:34 | Gradual recovery on Railway metal workloads; non-enterprise builds throttled |

**Effects on this app:**

- `web-production-3e3ae.up.railway.app/healthz` → first 404 from
  `railway-edge`, then connection-accepted-but-no-response (HTTP 000 with
  TCP connect succeeding)
- `railway.com` dashboard → 404 then 000 then back to 200
- `backboard.railway.com/graphql/v2` (Railway API) → 503 for ~3 hours
- Railway CLI → OAuth refresh failed (`HTTP 503` then `invalid_grant` once
  the refresh token expired during the outage); needs `railway login`
- App container appears to have survived but SQLAlchemy session pool
  wedged: settings page showed "database connection: Session error";
  `pool_pre_ping` (PR31) + `pool_recycle: 1800` (PR55) couldn't recover
  because the Postgres networking on Railway's side was down
- Railway paused all deploys/restarts platform-wide → couldn't even kick
  the container to rebuild the connection pool

**Net duration of data-access outage for the user:** several hours, with
no actionable workaround other than wait.

---

## What we're defending against

This row is *not* about "make Railway never go down" — it's about
preserving user value during the kinds of failures we've now seen.

Failure modes worth modeling (with rough probability based on what we've
hit since 2026-04 deploy):

| Failure mode | Probability | Today's blast radius | What we want |
|---|---|---|---|
| Railway region (US East) brief outage (< 15 min) | High (~monthly) | App unreachable | Tolerable today; could be invisible with PWA cache |
| Railway control-plane outage (dashboard + API down, app intermittent) | Medium (~yearly) | App degraded, can't restart | Read access for the user |
| Railway-wide multi-hour outage (this incident) | Low (~rarely) | Full data-access outage | Read access; ideally capture-and-replay |
| Railway suspends our account (billing, ToS, etc.) | Very low | Permanent outage until resolved | Off-platform data export so we don't lose history |
| Postgres data corruption / wrong-DB writes | Very low | Data loss | Off-platform backup |
| Cloudflare outage (affects `railway.com` edge) | Low | Same as #1 | Same as #1 |
| GCP outage cascading through Railway | Now-known | Same as this incident | Same as #3 |

The pattern in the right column: **read access during outage** + **off-platform
backup of state** covers most of these. Write access during outage is
nice-to-have, not table-stakes, for a single-user PWA.

---

## Recovery objectives (proposed for discussion)

These are *proposals* — confirm or revise:

- **RTO (Recovery Time Objective)** — read access: **< 5 min**. The user
  pulls out their phone, the PWA shows last-known state. No human action.
- **RTO — write access**: **best-effort**. If Railway is down, write can
  be deferred. Don't engineer to keep writes flowing during an outage.
- **RPO (Recovery Point Objective)** — read access: **stale up to 24h
  is acceptable**. The user knows what they were working on; today's
  fresh captures may be missing.
- **RPO — backup**: **24h is acceptable** for full-data export. If
  Railway is permanently lost, we lose at most a day's worth.

If the user wants tighter RPO on captures (e.g., "I want offline-queued
writes that replay on reconnect"), Option C grows significantly.

---

## Options scoreboard

| # | Option | Read during outage | Capture during outage | New infra | Effort | Maintenance | Recommended? |
|---|---|---|---|---|---|---|---|
| A | Read-only local laptop mirror | ✅ if laptop available | ❌ | Local cron / GitHub Action + SQLite | M (1–2 days) | Low | ✅ Phase 3 |
| B | Local primary + Railway as sync replica | ✅ | ✅ | DB sync infra + always-on laptop | L (1+ weeks) | High | ❌ |
| C | Expanded PWA offline cache (read-only) | ✅ (mobile + desktop) | ❌ in v1 | None (extend existing SW) | M-L (2–3 days) | Medium | ✅ Phase 2 |
| C+ | PWA offline cache + offline write queue | ✅ | ✅ with conflict risk | IndexedDB queue | XL (~1 week) | High | ⏸ revisit if Phase 2 lands and we want more |
| D | Multi-provider warm standby (Fly.io / Render) | ✅ | ✅ | DB replication + DNS LB + 2x deploy | XL (~1 week + ongoing) | High | ❌ |
| E | Off-Railway status widget (Cloudflare Pages) | ❌ (no data, just status) | ❌ | Static page + GitHub Action | XS (2–3h) | ~0 | ✅ Phase 1 |
| F | Hybrid: E + C + A | ✅ | ❌ in v1 | Combo of above | Sum of phases | Low (incremental) | ✅ this is what we recommend |
| G | Switch off Railway entirely | Depends on new host | Depends | New host migration | L (~1–2 weeks) | Same as today | ❌ (just trades providers) |
| H | Periodic JSON/CSV export to off-Railway storage | ❌ (raw data only) | ❌ | S3 / Backblaze / Gist | XS (2–3h) | Low | ✅ Pair with A for backup guarantee |

**Legend:**
- Effort: XS (<1d), S (1d), M (2–4d), L (1w), XL (>1w).
- Maintenance: ongoing tax once shipped.
- "Read during outage" assumes a single device — multi-device read parity is harder.

---

## Detailed walkthroughs

### Option A — Read-only local laptop mirror

**Concept:** a nightly job dumps Railway Postgres to a SQLite file kept on
the user's laptop. A `scripts/local_mirror.py` boots a minimal Flask
process in read-only mode pointing at the SQLite, served at
`localhost:5000`. When Railway is down, the user runs the script and
browses last-known state.

**How:**

1. **Nightly dump.** Two options for *who* does the dump:
   - **Railway-side cron** (preferred): APScheduler job calls
     `pg_dump --data-only --format=plain` and uploads the result to an
     off-Railway bucket (Backblaze B2, Cloudflare R2, or a GitHub Releases
     asset). Off-Railway means even a Railway outage doesn't block the
     restore.
   - **Laptop-side cron**: scheduled task on the laptop pulls from
     Railway Postgres directly. Requires the laptop to be on at dump time,
     and Railway DB connection to be available — which is exactly what
     fails during an outage. So this is the worse option.
2. **Restore script.** `scripts/local_mirror.py` downloads the latest
   dump from the off-Railway bucket (or uses the most recent local copy
   if download fails), loads it into a SQLite file, and starts Flask with
   `SQLALCHEMY_DATABASE_URI=sqlite:///./local_mirror.db` and a
   `READ_ONLY=true` flag.
3. **Read-only mode.** Add a middleware that rejects all non-GET requests
   with `503 — local mirror is read-only`. Don't need to change every
   route; one global guard is fine.
4. **Auth.** Skip OAuth on the local mirror. Bind to `127.0.0.1` so it's
   not reachable from anywhere else. Document the threat model (local
   laptop access only).

**What you get:**
- Full app UI with last-night's data.
- Search, browse, planning — all the read flows.
- Works even if Railway is permanently gone (you have the data + the code).

**What you don't get:**
- Captures: anything new the user typed during the outage doesn't reach
  the mirror. User has to remember to write it down (Notes app, etc.) and
  re-enter when Railway comes back.
- Mobile access: laptop only.

**Effort breakdown:** ~1.5–2 days
- 0.5d: scheduled `pg_dump` → off-Railway bucket (Backblaze B2 is cheap)
- 0.5d: `local_mirror.py` boot script + read-only middleware
- 0.5d: tests + the runbook
- 0.5d: validate end-to-end (intentionally break Railway in dev, recover)

**Risk:** very low. SQLite + read-only flag is well-trodden. Postgres-to-
SQLite has type-coercion edge cases (enums, JSON columns) but the data
model here is small.

---

### Option B — Full local primary + Railway as sync replica

**Concept:** flip the topology — the laptop is the canonical DB, Railway
syncs from it.

**Why it doesn't fit our use case:**

- User reads/writes from mobile PWA during the day. Every mobile write
  would have to round-trip to a laptop, which would need to be always-on
  and publicly reachable (ngrok or similar). That's strictly worse than
  Railway for ~99% of the year.
- DB sync from local → Railway requires either logical replication
  (which Railway-managed Postgres may not support without elevated perms)
  or a CDC layer (Debezium-class) — a whole new component to debug.
- Conflict resolution is non-trivial: if both ends drift, what wins?

**Verdict:** not recommended. Mobile-first PWAs want cloud-primary.

---

### Option C — Expanded PWA offline cache (read-only)

**Concept:** the existing Service Worker already caches static assets
(CSS, JS, HTML shell). Extend it to also cache the *responses* of
`/api/tasks`, `/api/goals`, `/api/projects`, `/api/recurring/previews`
with a stale-while-revalidate strategy. When the PWA can't reach the
network, the SW serves the last cached responses out of IndexedDB and
the UI renders normally with a small "offline — last sync N min ago"
banner.

**How:**

1. **Cache strategy.** For read endpoints listed above:
   - Network-first with a 3s timeout → fall back to cache if timeout.
   - On successful fetch, write the response to a `Cache` named
     `api-v1` (separate from `app-shell-v<CACHE_VERSION>` so app updates
     don't blow away data).
2. **Offline indicator.** New `static/connectivity.js` module: small
   helper that exposes `connectivityStatus()` returning `online` /
   `degraded` / `offline`, plus a banner that renders when status ≠
   `online`. Hooks the existing `apiFetch` (`static/api_client.js`) so it
   reports cache-vs-network on each call.
3. **Write behavior in v1: hard-disable.** During an outage (= multiple
   consecutive write failures), show a "Railway unreachable — read-only
   mode" toast and grey out the capture bar / save buttons. *Don't* try
   to queue writes in v1 — that's a deep rathole (see C+).
4. **Tests.** Playwright with network conditions throttled to offline;
   assert the cache-served board renders and the capture bar disables
   gracefully.
5. **Phase-6 considerations:** the bypass disables the SW (per CLAUDE.md
   `?nosw=1` rule), so Phase 6 needs a separate scenario where the SW IS
   active and we tear the network down. That's a new test rig.

**What you get:**
- Read access on mobile AND desktop, per-device, automatically, no user
  action.
- Standard PWA pattern. Trello, Notion, Asana all do this.
- Builds on existing SW (CACHE_VERSION ladder, ADR-028 architecture
  source-of-truth).

**What you don't get in v1:**
- Offline writes. User can read but not capture during outage. If they
  *must* capture, they fall back to Notes app + re-enter later.
- Multi-device freshness: if the phone hasn't been opened in 3 days,
  the cache is 3 days stale.

**Effort breakdown:** ~2–3 days
- 1d: extend SW with the API cache + the cache key strategy
- 0.5d: connectivity banner + `apiFetch` integration
- 0.5d: write-mode disable when offline
- 0.5d: Playwright "offline" test scenario (new test rig)
- 0.5d: cascade — `sw.js` `APP_SHELL`, `EXPECTED_STATIC_FILES`,
  CACHE_VERSION bump, docs page update

**Risk:** medium. SW has historically been fragile in this codebase —
PR47 false-positive prompt + PR49 hard-recover + PR53 stale-tab fixes.
Adding API caching to the SW expands its responsibility. Need
disciplined Jest + Playwright coverage of the cache logic, not just the
SW lifecycle.

---

### Option C+ — PWA offline cache *with* write queue

**Concept:** v2 of Option C. During an outage, instead of disabling
writes, queue them in IndexedDB. When connectivity returns, replay the
queue in order, with conflict detection.

**Why we'd defer:**
- Conflict resolution is genuinely hard. If the user edits the same task
  on phone (offline) and desktop (online during outage), what wins?
  Last-write-wins is the simplest answer but can silently drop work.
- Adds a multi-day engineering project on top of Option C's already
  M-L cost.
- For a single user, the probability of *actually* needing this (must
  capture during a multi-hour outage AND can't use a fallback like a
  Notes app) is very low.

**Verdict:** defer to a follow-up row if Option C ships and we still
want more.

---

### Option D — Multi-provider warm standby

**Concept:** deploy a second copy of the app to Fly.io or Render. Use
Cloudflare's load balancer + health checks to fail DNS over when Railway
is unhealthy. Postgres logical replication from Railway → Fly.io.

**Why it's overkill for a single-user app:**
- 2x infra cost (~$10–20/mo extra, plus Cloudflare LB $5/mo).
- DB logical replication is non-trivial and Railway-managed Postgres
  doesn't reliably support it without elevated perms.
- Now you have *two* deploy pipelines, *two* secret stores, *two* set of
  env vars to keep in sync. Permanent maintenance tax.
- The failure mode that bit us today (GCP blocked Railway's account) is
  rare enough that engineering 2 days/year of mitigation isn't worth a
  full-time multi-provider operation.

**Verdict:** not recommended for this app.

---

### Option E — Off-Railway status widget

**Concept:** a static page hosted on Cloudflare Pages (or GitHub Pages,
or Netlify — anywhere that isn't Railway). The page does a periodic
client-side `fetch('https://web-production-3e3ae.up.railway.app/healthz')`
and shows:

- Current status: 🟢 healthy / 🟡 degraded / 🔴 down
- Last-success timestamp ("12 min ago")
- Deployed `git_sha`
- A 24h sparkline of healthz response times (optional)
- Manual notes section the user can edit (just a textarea backed by
  localStorage)

**What you get:**
- During an outage, the user has a definitive URL that *isn't* on Railway
  to confirm "yes Railway is down, here's how long, here's what's
  deployed."
- Confidence + no scrolling through Railway's status page.
- Optional: paste in the official Railway status incident link.

**What you don't get:**
- Any actual data access. This is just an information surface.

**Effort breakdown:** ~2–3 hours
- 1h: static HTML + a tiny JS poller
- 0.5h: deploy to Cloudflare Pages from a new folder in the repo
- 0.5h: add the URL to README / docs page so the user remembers it
- 0.5h: optional — GitHub Action records uptime to a JSON file in the
  repo for the sparkline

**Risk:** ~0. Static page, no DB, no auth, no secrets. CORS on `/healthz`
is the only thing to check — currently `/healthz` is unauthenticated and
should allow cross-origin GET.

---

### Option F — Hybrid: E → C → A

**The recommendation.** Ship in three phases:

**Phase 1 (this week if we want): Option E — status widget.**
~3h of work, immediate user value during the *next* outage ("at least I
know what's going on without going to Railway"). Almost no maintenance.

**Phase 2 (next sprint): Option C — PWA offline cache, read-only.**
2–3 days. The biggest coverage gain. Mobile PWA becomes useful during
outages. Reuses SW infra. Disciplined testing required given SW
fragility.

**Phase 3 (when convenient): Option A — laptop mirror + off-Railway backup.**
~2 days. Covers the "long outage + I'm at my laptop" scenario. Also
gives us the off-Railway backup guarantee (Option H is implicit here —
the nightly `pg_dump` to Backblaze IS the off-platform backup).

Total: ~5–6 days of work, spread across three sub-PRs against #166. Each
phase is independently valuable — Phase 1 alone is worth shipping even
if we never do 2 and 3.

---

### Option G — Switch off Railway entirely

**Why this isn't a resilience play:**

Migrating to Fly.io or Render or self-hosted just trades one provider's
outages for another's. Every provider has outages. The structural
problem is "one host, no fallback," not "Railway specifically."

If the user has *other* reasons to leave Railway (cost, features, dev
experience), that's a separate decision — file as a new BACKLOG row.
Don't conflate it with resilience.

**Verdict:** not a resilience option.

---

### Option H — Periodic JSON/CSV export to off-Railway storage

**Concept:** nightly job dumps tasks, goals, projects as JSON to a
non-Railway bucket. No app, just data.

**Why we'd include it:** as the **backup guarantee** baked into Option A.
Even if we never build the laptop mirror, the nightly export is cheap
insurance against "Railway loses our DB" or "Railway suspends our
account permanently."

**Effort:** XS standalone (~2h), or free if it's part of Option A's
Phase 3 (the `pg_dump` already produces the artifact).

**Verdict:** ship as part of Phase 3 (Option A). Don't ship standalone.

---

## Decision points (for the discussion)

1. **Confirm RTO/RPO proposal above?** Specifically: is "read-only during
   outage, write deferred" acceptable, or does the user need offline
   writes (which pushes us to C+ and a much bigger build)?

2. **Sign off on the three-phase plan (E → C → A)?** Or change the
   order / drop a phase?

3. **Phase 1 (status widget) — go now?** It's a 3-hour ship that pays
   off the next time Railway hiccups, and we've now had two outages in
   the last month worth tracking. Cheapest, lowest-risk, immediate value.

4. **Where does the off-Railway bucket live?** Backblaze B2 (cheap,
   simple), Cloudflare R2 (free egress to Cloudflare, S3-API), or a
   GitHub repo (free, version-controlled, but limited size)? Implication
   for Phases 1 and 3.

5. **Phase 3 backup retention?** 30 days rolling? Forever? Implications
   for storage cost (negligible at this data scale either way) and
   recovery scenarios.

6. **Phase 2 SW caching scope?** Just tasks/goals/projects (the board)?
   Or also recurring previews, calendar data, completed tasks? The more
   we cache, the more we have to invalidate on writes.

---

## What's NOT in scope for this row

- Switching off Railway (Option G — file separately if desired)
- Multi-region active-active (Option D — overkill)
- Offline write queue (Option C+ — deferred to a follow-up row after
  Phase 2 lands)
- "Make Railway never go down" (not a thing)

---

## Open questions and unknowns

- **Does `/healthz` need CORS?** For Option E to work from
  cloudflare-pages.dev (a different origin), the response needs
  `Access-Control-Allow-Origin: *` (or specific origin). Currently
  unknown — needs a one-line probe. If we need to add it, it's a tiny
  app change (`@app.after_request`).
- **Does Railway's Postgres allow `pg_dump` from the running container's
  network?** It does today (DATABASE_URL works), but worth confirming
  the connection limits don't trip a nightly dump.
- **SW + iOS Safari quirks.** PWA on iOS has historically lost the SW
  registration after a few days idle. The cache may be more ephemeral
  than we'd like. Worth testing on an actual iPhone before committing to
  Phase 2 as the primary resilience layer.
- **Race between Phase 2 (SW caching) and existing SW recovery code**
  (PR47/49/53). Adding API caching to the SW expands the SW's
  responsibility; need to confirm `_hardRecover` still works when the
  cache contains stale API data.
