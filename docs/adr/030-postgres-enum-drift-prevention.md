# ADR-030: Prevent Postgres-enum-drift bug class permanently

Date: 2026-04-25
Status: ACCEPTED

## Context

A specific bug class hit production **three times** in the span of a
month: a contributor adds a new value to a Python `enum.StrEnum`,
generates an alembic migration, the migration appears to succeed
(alembic_version bumps), but the production Postgres enum was never
actually updated. The next user request that uses the new value gets
`psycopg.errors.InvalidTextRepresentation: invalid input value for
enum X: "Y"`.

Occurrences:

- **#23** (2026-04-19) — `Tier.NEXT_WEEK` missing → `/api/tasks?tier=next_week` 500'd
- **#25** (2026-04-19) — `TaskStatus.CANCELLED` missing → "mark cancelled" 500'd
- **#52** (2026-04-24) — `ProjectType.PERSONAL` missing → "save Personal project" 500'd
  - User-reported as "Save failed:" with a blank message (the secondary
    issue covered by #50 — only `ValidationError` gets shaped into a
    JSON error response; everything else bubbles up as opaque 500).

The first two were patched via a manually-curated `_ensure_postgres
_enum_values()` boot gate in `app.py` that runs `ALTER TYPE … ADD
VALUE IF NOT EXISTS` for each known-missing value, in AUTOCOMMIT
isolation (Postgres rejects `ALTER TYPE … ADD VALUE` inside a
transaction). The third (#52) hit because no one updated the manual
list when `ProjectType.PERSONAL` was introduced.

## Why local tests didn't catch it

Tests run on SQLite (in-memory or `dev.db`). SQLite has no native
enum type — enum columns are stored as `VARCHAR`. The alembic-in-
transaction failure mode (Postgres-only) cannot occur on SQLite. The
full pytest + Playwright local suite passes against SQLite even when
production Postgres is broken. We need protection that operates AT
the gap: catches the bug before code reaches users on real Postgres.

## Decisions

### Layer A — auto-derive the repair gate's ALTER TYPE list

`_ensure_postgres_enum_values()` previously hardcoded a manually-
curated list:

```python
for sql in (
    "ALTER TYPE tier ADD VALUE IF NOT EXISTS 'NEXT_WEEK'",
    "ALTER TYPE tier ADD VALUE IF NOT EXISTS 'TOMORROW'",
    "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'CANCELLED'",
    "ALTER TYPE projecttype ADD VALUE IF NOT EXISTS 'PERSONAL'",  # added retroactively for #52
):
```

That list drifted three times. Replaced with a function
`_build_enum_repair_statements()` that introspects
`db.Model.registry`:

```python
for mapper in db.Model.registry.mappers:
    for col in mapper.local_table.columns:
        enum_cls = getattr(col.type, "enum_class", None)
        if enum_cls is None: continue
        pg_enum_name = enum_cls.__name__.lower()
        for member in enum_cls:
            pairs.add((pg_enum_name, member.name))
```

The bug class is now **impossible by construction** — every Python
enum member used as a column type gets its own `IF NOT EXISTS` ALTER
TYPE every boot. Idempotent for already-present values; auto-repairs
any new ones. No manual list to forget.

Trade-off: emits ~30+ ALTER TYPE statements per boot (most are no-ops).
Negligible cost — boot already takes seconds; AUTOCOMMIT statements
are individually cheap.

### Layer C — `enum_coverage` check on /healthz

Defense in depth. Even if Layer A has a bug (silently fails to emit
the right statement, or someone manually deletes a Postgres enum
value out-of-band), Layer C catches it. New `health.check_enum_coverage()`:

```python
SELECT enumlabel FROM pg_enum
JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
WHERE pg_type.typname = :name
```

…compares the live Postgres enum values to the Python enum members
for every column. Returns `fail: <enum>.<value> missing in Postgres`
if any are absent.

Wired into `run_health_checks()` so it's part of `/healthz`. Triggers
DEPLOY RED in `validate_deploy.py` if drift exists. SQLite-skip
matches the other Postgres-specific checks (`writable_db`, `tables`).

Cost: one cheap catalog query per enum per `/healthz` hit. Railway's
health probe hits this every few seconds; for a single-user app that's
fine. If we ever scale, can be cached briefly.

### Why both A and C

- **A alone** would prevent the bug if it always runs at boot — but
  the gate could itself silently fail (network blip, transaction
  edge case), and we'd be back to the same failure mode without
  noticing.
- **C alone** would catch drift but only AFTER a deploy — won't
  prevent the bug, just surface it faster.
- **A + C** = bug literally cannot reach users:
  1. A patches at boot
  2. C verifies the patch worked
  3. If C reports fail, validate_deploy turns red and prevents the
     deploy from being marked green

## Consequences

**Easy:**
- Cannot recur via the original "forgot to update the manual list"
  vector — there is no manual list anymore.
- Adding a new Python enum member to any model is now a one-line
  change to `models.py`. No app.py edit needed.
- /healthz tells you within seconds of deploy whether enum coverage
  is complete.

**Accepted trade-offs:**
- Boot emits ~30 ALTER TYPE no-ops per startup. Logged at DEBUG; no
  visual noise.
- `enum_coverage` adds one DB roundtrip per enum per /healthz call.
  Single-user app, fine.
- Layer C requires Postgres `pg_catalog` access — SQLite tests skip
  it, which matches the existing pattern.

## Alternatives considered

- **Run pytest against real Postgres in CI** (Option B from the user-
  facing analysis): rejected for now. Single-user app with no shared
  CI; would require Docker compose orchestration in
  `run_all_gates.sh`. A+C eliminate the bug class without the infra
  overhead. If we ever add multi-user support, Postgres-in-CI
  becomes worth it for the broader test surface.
- **Drift-gate test that asserts the manual list is complete**:
  rejected. Just a wrapper around the manual list — still requires
  the contributor to know to update it. A removes the list entirely.
- **Block enum-touching migrations at PR time via a pre-commit
  hook**: rejected. The migration generates correctly; the failure
  is at runtime, not at PR time. Hook would have nothing to detect.
- **Fix `validate_deploy.py` to be smarter about enum errors**:
  rejected. Out of scope; that script is a reactive checker.

## Verification

- `tests/test_health.py::TestCheckEnumCoverage`:
  - Skip on SQLite (the test environment) — matches other PG-only
    checks
  - Mocked DB returning empty pg_enum + Python enum with members →
    fails with `fail: <enum>.<value> missing in Postgres`
  - Mocked DB returning all Python enum members → returns `ok`
- `tests/test_health.py::TestBuildEnumRepairStatements`:
  - Spot-check that known members emit ALTER TYPE statements:
    `ProjectType.PERSONAL` (the #52 case), `Tier.NEXT_WEEK`,
    `Tier.TOMORROW`, `TaskStatus.CANCELLED`
  - Every statement uses `IF NOT EXISTS`
  - No duplicates when same enum used by multiple columns
    (e.g. TaskType in `tasks.type` + `recurring_tasks.type`)
- All 11 quality gates green.
- ARCHITECTURE.md `enum_coverage` mentioned as a check (not a route
  or scheduler — `arch_sync_check.py` doesn't enforce health-check
  names, so no manual edit there).
