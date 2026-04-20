# ADR-016: Tier → due_date auto-fill for TODAY and TOMORROW

Date: 2026-04-20
Status: ACCEPTED

## Context

Backlog #28 — before this change, the tier and due_date fields were
fully orthogonal. A user dragging a task into TODAY or TOMORROW still
had to separately set the due_date to match. For those two tiers the
semantics are redundant: the tier IS the date. This caused two
user-visible frictions:

- Quick-capture flow was always two steps: type the task with
  `#today`, then open the detail panel and pick today's date.
- The digest's "ALSO DUE TODAY (from other tiers)" section never
  fired for Today-tier tasks because their due_date was usually null,
  even though everyone in Today was conceptually due today.

The backlog entry asked for: "moving a task to Today sets
due_date=today; moving to Tomorrow sets it to tomorrow. Probably
FILL-IF-NULL (don't clobber an explicit user choice)."

## Decisions

### 1. Fill-if-null only — never overwrite

`_auto_fill_tier_due_date(task, data)` runs after all explicit
mutations and only touches `due_date` when both are true:

- `"due_date"` was NOT in the incoming request body.
- `task.due_date` ended up null after all the explicit updates applied.

If the user provided `"due_date": "2026-12-31"`, they get that value.
If they provided `"due_date": null`, they get null (auto-fill
respects the explicit intent, not just the final value). If they
didn't mention the field at all, auto-fill decides based on tier.

### 2. Only TODAY and TOMORROW trigger the fill

Other tiers (BACKLOG, THIS_WEEK, NEXT_WEEK, FREEZER, INBOX) have
no implicit date — THIS_WEEK is a range, BACKLOG is "someday,"
etc. Auto-filling those would be invented semantics.

### 3. Moving OUT of TODAY/TOMORROW does NOT clear due_date

If a user has a TODAY task with due_date=today and they move it to
BACKLOG, the due_date stays. Matches the backlog design note
("user may still want the reminder") and fits the broader pattern
of "don't clobber data the user might be using."

### 4. Uses DIGEST_TZ for "today" and "tomorrow"

`_local_today_date()` reads `DIGEST_TZ` (default
`America/New_York`) and returns the current date in that timezone.
Rationale: the server runs in UTC on Railway; a task created at 10pm
ET (3am UTC the next calendar day) would have been auto-filled with
the wrong date under a plain `date.today()`. Same TZ convention as
the Tomorrow auto-roll cron (#27), so behaviour is self-consistent
across the two related features.

Fallback: if `zoneinfo` / `tzdata` isn't available at runtime (rare
on Railway but possible on stripped-down containers), falls through
to server-local `date.today()`. Non-ideal but better than crashing.

### 5. Applies uniformly across all mutation paths

Called from both `create_task` and `update_task`. Bulk PATCH
(`bulk_update_tasks`) calls `update_task` per id, so bulk gets the
behaviour automatically. Drag-to-tier in the UI issues a PATCH
with `{tier: "today"}` — same path.

### 6. No UI, template, CSS, or JS change

Pure backend. The existing capture-bar, detail-panel, drag-drop,
and bulk toolbar all emit the same PATCH shapes; the server now
fills in the missing `due_date` transparently. Phase 6 per-viewport
regression is technically not required per CLAUDE.md's "UI change"
trigger, but was done anyway via curl against the live bypass
server to verify all four flows end-to-end.

## Consequences

**Easy:**
- Zero schema change.
- All existing tests unaffected — `_make_task` in the test helper
  uses the Model constructor directly, bypassing `create_task`, so
  test fixtures keep their null due_dates.
- Rollback is trivial: revert the single helper call in each of
  create_task and update_task.

**Hard / accepted trade-offs:**
- A user who typed `#today` 5 days ago and has been dragging the
  task around will now find it has an auto-filled due_date from 5
  days ago — stale. The digest's "overdue" section will pick it up.
  Acceptable: it IS overdue; the digest is doing its job. If this
  becomes noisy, the fix is to also reset due_date on the move
  INTO Today (making the fill a "re-fill when re-entering Today"
  instead of "fill if null"). That's more aggressive and overrides
  user data, so punting until observed.
- The `zoneinfo` lookup on every create / update is cheap but not
  free. Acceptable for a single-user app; if we ever multi-tenant
  we'd cache the ZoneInfo object.

## Alternatives considered

- **Overwrite on tier change regardless of existing value**: rejected
  — violates the broader "don't clobber user data" rule. Would
  surprise users who moved a specific-date task into Today.
- **Also clear due_date when moving OUT of TODAY/TOMORROW**:
  rejected per the backlog's design note ("user may still want the
  reminder").
- **Do it client-side in the capture bar / detail panel**:
  rejected — would only cover those two paths; drag-drop and bulk
  would still be stuck. Server-side covers everything by construction.
- **Plain `date.today()` without DIGEST_TZ**: rejected — breaks for
  evening-hours users whose UTC has rolled over.

## Verification

- **Unit**: 11 new `TestTierDueDateAutoFill` tests in
  `tests/test_tasks_api.py` covering create (today fills, tomorrow
  fills, explicit date respected, inbox/backlog don't fill), update
  (move-to-today fills, move-to-tomorrow fills, explicit date
  wins, `due_date: null` in same PATCH is respected, move-OUT
  leaves date intact), and bulk (tier=today fills each null).
- **Integration**: full suite 985 passed, 3 skipped.
- **Live verification** via bypass server curl calls — all four
  canonical flows produced correct due_date values:
  - `POST tier=today, no due_date` → fills today
  - `POST tier=tomorrow, no due_date` → fills tomorrow
  - `POST tier=today, explicit due_date=2027-01-15` → respects
  - `PATCH tier=today` from backlog → fills today
  - `PATCH tier=backlog` from today → due_date unchanged
