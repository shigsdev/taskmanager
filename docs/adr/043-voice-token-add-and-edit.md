# ADR-043: The voice-action token can add a task and rename or re-date one (amends ADR-034)

Date: 2026-10-18

Status: ACCEPTED (#500, user decisions 2026-10-18)

Amends: ADR-034 (scoped voice-review action token). Its token format, salt,
lifetime, email lockdown, per-jti denylist and kill-switches are unchanged,
and so is ADR-042 (minting and revoking from /settings). This ADR widens what
the token can **do**, on two new routes in the same blueprint.

## Context

ADR-034 limited the token to reading the review queue and completing,
moving (Today / Tomorrow / Next Week / Backlog) or cancelling a task. On
2026-10-17 the user asked for the Siri Shortcut to also add tasks and edit
them, and chose "edit title / due date" as the edits. On 2026-10-18,
building the Shortcut from the Help showed the per-word design was too hard
to set up: every spoken word needed its own If block, and "rename" and "due"
would have added more blocks, each with a second question. The user chose
to send the spoken answer as-is and let the app interpret it.

## Decision

Two routes in `voice_review_api.py`, both `@voice_action_or_login` like the
rest of the blueprint:

- `POST /api/voice-review/<id>/answer` with `{"text": "<what was said>"}`.
  `voice_answer.interpret_answer` (fixed rules, no AI, no network) turns the
  text into exactly ONE action: complete, cancel, move (the same four-section
  whitelist as `/move`), rename, set the due date, clear the due date, or
  skip. A command must be the whole answer, so one answer can't do two
  things. Only that action's own keys reach `update_task` (`title`,
  `due_date` or `tier`), or `complete_parent_task` / `cancel_parent_task`.
  A task that isn't active is left alone. 120 per minute.
- `POST /api/voice-review/tasks` with `{"text": "..."}`.
  `voice_answer.parse_new_task` reads `[work|personal] [task] <title> [due
  <date>]`, and only `title`, `type` and `due_date` reach `create_task`. The
  task lands in the Inbox, or the date's section (#386, the same rule as ➕ New
  Task). 30 per minute.

Both routes read only `text`. Any other JSON key is ignored. Both answer
with a `say` sentence for Siri on every path, including 400 and 404.

The token still can't delete, bulk-edit, read anything beyond the queue,
touch settings, exports, goals or projects, or set any other task field
(notes, project, goal, URL, checklist, type of an existing task, Freezer /
This Week / Inbox moves). `/api/tasks*` still rejects it (`@login_required`
never reads the bearer).

## Consequences

- **A larger blast radius if the token leaks.** On top of ADR-034's
  complete / move / cancel, a holder can now:
  - add up to 30 tasks a minute to the Inbox (or a dated section), and
  - rename any open task, or change or clear its due date (which moves it
    to the date's section, the panel's own rule).

  That's still no data read beyond the queue's titles, no deletion, no
  auth escalation. Every change is visible and reversible in the app.
  Revocation is unchanged: the per-jti denylist from /settings or the CLI,
  or rotating `SECRET_KEY`.
- **The app now interprets free text on a mutating path.** That text comes
  from the authenticated user's own dictation. The parser is deterministic
  and pure, so a sentence it doesn't recognise changes nothing and says so.
  The text is never stored except as a title the user asked for, and it
  never reaches a prompt or a shell.
- **The Shortcut gets much simpler.** Part 2 is four actions with no If
  blocks (Help → Hands-free voice review). The old per-word routes stay, so
  a Shortcut already built on them keeps working.
- The scope tests grow: `tests/test_voice_answer_api.py` checks that extra
  keys are ignored, that inactive tasks are left alone, and that
  `/api/tasks` POST and PATCH still refuse the token. These sit next to
  ADR-034's matrix in `tests/test_voice_action_token.py`.

## Alternatives considered

- **Separate If blocks per command, plus "What's the new name?" / "What
  date?" questions** (the Shortcut does the interpreting, and the app takes
  only exact values). Rejected by the user: too many steps for someone who
  hasn't built a Shortcut before. It's the shape the old Help described,
  and it was the reason the setup stalled.
- **An LLM to interpret the answer.** Rejected: it adds a network call and
  a prompt-injection surface on a mutating path, and fixed rules cover the
  handful of commands.
- **A separate, wider token for add / edit.** Rejected: two tokens to mint
  and paste for one Shortcut, and the user is the single holder of both.

## Related

- ADR-034: the token this amends. ADR-042: minting and revoking it from
  /settings.
- `docs/design/500-siri-add-and-edit-by-voice.md`: the spec.
- `voice_answer.py`: the rules. `tests/test_voice_answer.py` covers them.
