# #363 — `/recurring` shows paused templates (and Resume works)

Bug (filed 2026-10-01, #353 sweep): `static/recurring.js:137` asks for
`/api/recurring?active_only=false`, but the route reads only `?all=1`
(`recurring_api.py:74`). The page has only ever received active templates,
so a paused row never renders — **Pause makes a template vanish and Resume
is unreachable**. The `· PAUSED` meta, the editor's Resume button and the
bulk *Resume (active)* entry all exist, and none of it can run.

It is not a one-character fix. Delete writes the same `is_active=False`
as Pause (`recurring_service.delete_recurring`), so fixing only the
param would bring back every template ever deleted, all labelled PAUSED.

Prod on 2026-10-11: 30 templates, **13 inactive**, and nothing records
which of them were paused and which were deleted.

**User decision (2026-10-11): all 13 become Paused.** Nothing is lost.
They show on `/recurring` as PAUSED, and the user deletes the ones they
don't want.

## 1. Surface (every reader/writer of a template's active state)

| Where | What it does today | Change |
|---|---|---|
| `recurring_service.delete_recurring` (single `DELETE /api/recurring/<id>` and `DELETE /api/recurring/bulk`) | `is_active=False`, clears both archive markers | also stamps `deleted_at` |
| `task_service._update_repeat` (Repeat → none on a task) | `is_active=False` on the linked template, unlinks the task | also stamps `deleted_at`: removing the repeat ends the series, it doesn't pause it |
| `recurring_service.update_recurring` (`PATCH` single + bulk) | `is_active` change clears both markers, only on an actual change | an explicit `is_active` now always clears them (§3.5); `is_active: true` on a deleted row clears `deleted_at` (§3.4) |
| `recurring_service.list_recurring(active_only=False)` → `GET ?all=1` | returns every row, deleted included | excludes deleted rows |
| `static/recurring.js` `load()` | sends `?active_only=false` (ignored) | sends `?all=1` |
| `static/goals.js:937` (#352 move-impact count, `?all=1`) | counts deleted templates too | stops counting deleted ones, so the count matches what the user can see. The server cascade itself is unchanged |
| `cascade_parent_archive` / `templates_paused_by_archive` / spawn / previews / settings count | filter on `is_active` / markers | unchanged. Deleted rows are inactive with both markers cleared, so none of them can touch one |
| `recycle_service` purge | clears markers by parent | unchanged |
| `_serialize` (API) | no markers | adds `paused_by_project_archive` / `paused_by_goal_archive` for the row label |
| `templates/docs.html` `#recurring` | "While it's paused this way, a repeating task doesn't appear in the /recurring list … Unarchiving is how you bring it back." | rewritten (§3.7) |

## 2. Model

New nullable `recurring_tasks.deleted_at` (timestamptz). The three states:

| State | `is_active` | `deleted_at` |
|---|---|---|
| Active | true | NULL |
| Paused (by user, or by an archive with a marker) | false | NULL |
| Deleted | false | set |

Migration on top of `u0c1d2e3f4a5`: add the column only. Existing rows
stay NULL, which **is** the user's decision: every inactive row becomes
Paused. No data backfill.

## 3. This ship

1. **Schema + migration** as above. Model comment, `ARCHITECTURE.md`
   PostgreSQL box, and `_SCHEMA_DESCRIPTIONS` entries for `deleted_at`
   (plus `is_active` reworded to "False = paused or deleted").
2. **Delete stamps `deleted_at`** in both delete paths (§1). The marker
   clearing stays as it is.
3. **`list_recurring(active_only=False)` excludes deleted rows**;
   `recurring.js` sends `?all=1`. Deleted templates never reach the page.
4. **Re-setting Repeat on a task whose template was deleted on
   `/recurring` revives that template.** Deleting there leaves spawned
   tasks linked. (Repeat → none on the task itself unlinks it, so
   setting Repeat again later creates a fresh template.) That's today's
   behaviour through
   `_update_repeat → update_recurring(..., is_active: True)`. Kept as is:
   `is_active: true` clears `deleted_at`. It's only reachable from the
   task panel, by a user who explicitly turned Repeat back on.
5. **An explicit `is_active` in a PATCH is the user's decision and clears
   both archive markers, even when it doesn't change the value.** Today a
   bulk *Pause* on a template an archive already paused is a no-op that
   keeps the marker, so the next unarchive wakes a template the user just
   told to stay paused. (This is the #368 review note on the #363 row.)
   Safe because the `/recurring` editor's Save does not send `is_active`
   (`buildRecurringEditPayload`, verified). `_update_repeat` sends
   `is_active: true` only on templates that are already active (an
   archive-paused one reads back as Repeat "none" and returns early
   under #353).
6. **The row says why it is paused.** The new
   `recurringHelpers.recurringPausedLabel(rt)` returns:
   - `""` for an active row
   - `"PAUSED"` for a plain pause
   - `"PAUSED — project archived"`, `"PAUSED — goal archived"` or
     `"PAUSED — project and goal archived"` for an archive pause

   It's Jest-tested (anti-pattern #3). Resume on an archive-paused row is
   allowed: it's an explicit override and it clears the markers (#353
   rule), even though the parent is still archived.
7. **Help copy** (`#recurring`, the archived-parent subsection): a paused
   template stays on `/recurring`, muted and marked PAUSED (with the
   reason if an archive paused it). Resume brings it back early. Delete
   removes it from the list. Fact-check table goes in the review message.
   The `/recurring` bullet gets a sentence on paused vs deleted.
8. **CLAUDE.md Phase 6** gains a `/recurring` paused-row line and report
   rows.

## 4. Tests

- **pytest (service):** delete stamps `deleted_at` (single + bulk route);
  `list_recurring(active_only=False)` returns paused and not deleted;
  remove-repeat stamps `deleted_at`; `is_active: true` on a deleted row
  clears it; explicit `is_active: false` on an archive-paused row clears
  both markers and the next unarchive leaves it paused (red first);
  an editor-shaped PATCH without `is_active` keeps the markers.
- **pytest (API):** `GET ?all=1` lists paused, not deleted; serializer
  carries both markers; `GET` with no param is unchanged (active only).
- **Jest:** `recurringPausedLabel`, all five cases.
- **Playwright (local):** a paused template **renders** on `/recurring`
  with PAUSED, the editor offers Resume, Resume brings it back to active;
  a deleted template does not render; an archive-paused row shows its
  reason. This is the test the row asked for.

## 5. Out of scope (filed separately)

- **#414 — a deleted template still blocks a goal's hard delete.**
  `goal_service.goal_reference_counts` counts every `RecurringTask` row,
  deleted included. A goal whose only remaining referrer is a deleted
  template therefore refuses "Delete permanently" with a reason the user
  can't act on, because the template is invisible and can't be removed.
  Pre-existing (deleted templates already sat there as inactive rows).
  This ship makes the deleted state explicit, but it doesn't change the
  guard.
- No restore UI for deleted templates. Delete means gone, which matches
  how the page already words it.
- The task detail panel showing Repeat "none" for a task whose template
  is paused is deliberate (#353) and stays.
