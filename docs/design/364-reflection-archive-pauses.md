# #364 — A reflection's archive proposal says which repeating tasks it pauses

Filed 2026-10-01 from #353's spec (§7, decision 10); goal half added by #368.

## What was wrong

Archiving a project (#353) or a goal (#368) pauses its running repeating
tasks on every path, including a `/reflection` proposal: Apply calls
`delete_project` / `delete_goal` (`reflection_service.apply_selected_actions`,
"4. Deletes"), and the cascade lives in the service layer. What that path
lacked is the warning. `/projects` and `/goals` name the templates that will
pause before you archive; a reflection row only reads "Delete project: X",
so you tick it without being told its repeating tasks stop too.

## The surface

- A reflection can archive a project or goal only through a **delete**
  proposal. The update field sets (`_PROJECT_UPDATE_FIELDS`,
  `_GOAL_UPDATE_FIELDS`) have no `is_active`, so an `update` never archives.
- The review renders from the serialized reflection (`reflection_api._serialize`)
  on every path: a fresh analysis, a checkpoint, a combined analysis, and
  #495's History "Review proposals", which re-opens a row from the History
  list.
- `recurring_service.templates_paused_by_archive(project_ids, goal_ids)` is
  the read-only mirror of the cascade's archive branch (#369 uses it for the
  import-undo confirm).

## Decisions

1. **Worked out when the reflection is served, not stored.** A proposal can
   be re-opened days later (#495); a list saved at analysis time would name
   templates that were paused, deleted or renamed since. `_serialize` adds a
   response-only `archive_pauses` map, so it is always current, and it is
   empty once the archive has been applied (its templates are inactive).
2. **A sibling map, not a field on the action.** Each action's identity is
   its canonical JSON (`_action_key` server-side, `reflectionHelpers.actionKey`
   client-side, #437/#495). The client posts the actions back on Apply, so a
   `pauses` field inside them would change that identity whenever the list
   changed and break the "nothing applied twice" dedup. The map is keyed
   `"<entity>:<id>"`, using the action's own id string.
3. **One wording.** The note is `projectArchiveHelpers.archiveConfirmMessage`
   — the same sentence `/projects` and Settings show — with the goal's
   closing line ("… when you unarchive the goal.") for a goal row, the same
   as `/goals`. `reflection.html` loads `project_archive_helpers.js`.
4. **Quiet case stays quiet.** No running template → no key in the map → no
   line under the row. Rows other than a project/goal delete never get one.
5. Information only. The tick box and Apply are unchanged.

## This ship

- `reflection_service.archive_pauses(proposed)`; `_serialize` adds
  `archive_pauses`.
- `reflectionHelpers.archivePauseNote(action, pauses, format)` decides the
  line; `renderActionRow` shows it (`.reflection-action-pause`) under the
  reason.
- Help → Weekly reflection gets one line.
- CACHE_VERSION bump.

## Tests

- `tests/test_reflection_archive_pauses.py` — the map for a project delete
  and a goal delete; a template the user paused, an `update`, a task delete
  and a create get nothing; GET `/api/reflection/<id>` carries it; after
  Apply the map is empty and the template is paused.
- `tests/js/unit/reflection_archive_pause.test.js` — the helper's cases.
- `tests/e2e/reflection_archive_pause.spec.js` — History stubbed: the
  delete-project row shows the line, a delete-goal row the goal wording, a
  row with nothing to pause shows none.
