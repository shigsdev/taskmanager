# ADR-008: Bulk task operations — single endpoint, partial-failure semantics

Date: 2026-04-19
Status: ACCEPTED

## Context

Backlog #21 ("Bulk task operations") asked for a way to take an
action on multiple tasks at once (set type, move tier, assign
goal/project, mark complete, delete). Current state: every change
is one task at a time. As task volume grows, batch operations
become essential.

Two main design decisions to make:

1. **One endpoint or many?** A single
   ``PATCH /api/tasks/bulk`` that accepts an arbitrary updates dict,
   vs. one endpoint per action (``/api/tasks/bulk-tier``,
   ``/api/tasks/bulk-complete``, etc.). Single endpoint = less code,
   uniform validation; many endpoints = clearer intent per call,
   easier per-action authorization.
2. **All-or-nothing transaction or per-task best-effort?** If 5 of
   10 tasks have a validation error on the proposed update, do we
   roll back the whole batch or commit the 5 that worked?

## Decision

**Single endpoint** ``PATCH /api/tasks/bulk`` accepting:

```json
{
  "task_ids": ["<uuid>", "<uuid>", ...],
  "updates": { "type": "work", "tier": "today", ... }
}
```

The ``updates`` dict accepts any subset of the per-task PATCH
fields, so each task is processed via the existing ``update_task``
function — cascade rules (subtask goal/project inheritance) and
field-level validation behave identically to single-task updates.

**Per-task best-effort.** If task A succeeds and task B raises a
ValidationError on the same update, A is committed and B is
reported in an ``errors[]`` array. The 200 response shape:

```json
{
  "updated": 4,
  "not_found": ["<uuid>"],
  "errors": [{"id": "<uuid>", "field": "tier", "message": "invalid tier"}]
}
```

**Cap at 200 task_ids per call.** Sanity guard against accidental
"select all 5000 tasks" — far beyond any realistic personal-board
batch.

**Mutation method (PATCH) requires real OAuth.** The validator
cookie's GET-only branch in ``login_required`` means automated
agents cannot bulk-modify data even with a valid cookie. Test
``test_bulk_requires_login`` codifies this invariant.

**Delete is NOT in the bulk endpoint.** Delete uses the existing
per-task ``DELETE /api/tasks/<id>`` iterated client-side. Reasons:
(1) keeps recycle-bin batch_id semantics identical to single
deletes, (2) avoids a separate "bulk-delete" endpoint with its own
auth surface, (3) the response per delete is just 204 — no shared
transaction state to manage.

## Consequences

**Easy:**
- Adding a new bulk action (e.g. for #25 "cancelled status" or #27
  "tomorrow tier") is just adding a button in the toolbar — no new
  endpoint
- Per-task validation errors give the user a precise report instead
  of a confusing "the whole batch failed because one item was bad"
- Performance scales: 200-task batches are a single HTTP call

**Hard / accepted trade-offs:**
- Partial failure means callers must inspect the response (not just
  status code) to know what happened. Frontend handles this with a
  short summary alert when any errors occur.
- `bulk_update_tasks` calls `db.session.rollback()` on per-task
  errors — this means if one task in the batch raises, in-flight
  changes to that ONE task are rolled back, but earlier successful
  tasks in the same batch are NOT (they were committed via
  `update_task`'s implicit commit). Think of it as one transaction
  per task, not one per batch.

## Alternatives considered

- **One endpoint per action**: rejected — would multiply route
  surface for no clear gain. Auth model is the same per route.
- **All-or-nothing transaction**: rejected — for a personal app,
  a partial-failure UX where the user sees "4 worked, 1 didn't, fix
  this one and retry" beats "everything rolled back, figure out
  which task triggered it." If we ever build a multi-user app,
  revisit (concurrent edits make all-or-nothing more important).
- **GraphQL batch mutation**: massive overkill for one bulk endpoint.
- **Server-side delete in the bulk endpoint**: rejected per the
  reasons above. Iterating DELETE per task is fine at the scale
  we're targeting (max 200 tasks × ~50ms = 10 sec worst case;
  typical case will be 5-20 tasks).
