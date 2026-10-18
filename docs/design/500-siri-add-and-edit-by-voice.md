# #500 — Siri: add a task, and rename or re-date one, by voice

Status: building 2026-10-18 on `feature/500`. Folds in #503 (the Shortcut
Help needs a first-timer rewrite).

## 1. User decisions (2026-10-18)

1. **One "answer" action.** The Shortcut sends whatever the user said about a
   task to the app, unchanged; the app works out what was meant and returns a
   sentence for Siri to say. No If blocks in the Shortcut. The per-word routes
   (`/complete`, `/move`, `/cancel`) stay for Shortcuts already built on them.
2. **Dates said naturally** ("due Friday", "due October 25"), read by fixed
   rules — no AI. An unclear date changes nothing and Siri says so.
3. **Work or Personal said each time** when adding ("work call Sam",
   "personal buy milk"); no type word → Personal.

## 2. Routes (all `@voice_action_or_login`, under `/api/voice-review`)

### `POST /<id>/answer` `{"text": "<what you said>"}`

Always answers with a `say` sentence. 200 for anything understood or not
understood (`ok` true / false); 404 (task gone) and 400 (no text) carry `say`
too, so a Shortcut that speaks `say` never goes silent.

| You say (case, punctuation ignored) | Does | Siri says |
|---|---|---|
| complete / done / mark (it) complete | completes it (+ open subtasks, as `/complete`) | Marked complete. |
| cancel / cancel it | cancels it | Cancelled. |
| today, tomorrow, next week, backlog (optionally "move (it) to …") | moves it (`/move`'s whitelist) | Moved to Tomorrow. |
| rename (it) (to) X / call it X / change the name to X | title = X as dictated (500-char limit) | Renamed to "X". |
| due <date> / set the due date to <date> | due date = that date; the section follows the date (task_service #74 / #386 rules, as the panel) | Due Friday, October 23. It's in This Week. |
| no due date / remove (or clear) the due date | due date cleared | Due date removed. |
| skip / next / pass | nothing | Skipped. |
| anything else | nothing | I didn't catch that, so I left it as it is. |
| due + a date it can't read | nothing | I didn't understand that date, so I left it as it is. |

A command must be the whole answer ("complete it tomorrow" matches nothing),
so one answer can never do two things. A task that isn't active any more
(completed, cancelled, deleted) is left alone: "That task isn't open any
more, so I skipped it." Only `title`, `due_date`, `tier` and status reach the
task — the text never maps to any other field.

### `POST /tasks` `{"text": "<what you said>"}`

`[work|personal] [task] <title> [due <date>]`. The type word is optional
(Personal); a trailing "due <date>" sets the due date only when the date reads,
otherwise it stays part of the title. Lands in the Inbox, or the date's section
when dated (create_task's #386 rule, same as ➕ New Task). First letter
capitalized; trailing period dropped. 201 with `say`: 'Added "Buy milk" to
your Inbox as a personal task.' Empty → 200, `ok: false`, "I didn't hear a
task, so nothing was added." No project, goal, notes or other field — only
`title`, `type`, `due_date` reach `create_task`.

Rate limits: `/answer` 120/min (as `/complete`), `/tasks` 30/min.

## 3. Dates (`voice_answer.parse_spoken_date`, relative to local today)

- today, tomorrow, the day after tomorrow
- a weekday ("Friday", "on Friday", "this Friday"): the next one after today,
  never today itself
- "next Friday": the Friday of next week (Mon–Sun, the app's Next Week)
- "October 25", "Oct 25th", "25 October", "the 25th", "10/25" (month/day);
  an optional year; without one, the next time that date comes round
- "in 3 days", "in a week", "in two weeks" (numbers as digits or one–ten)

## 4. Security — ADR-043 amends ADR-034

The token can now create a task (title, type, due date; Inbox or the date's
section) and change an active task's title and due date. Still no delete, no
other fields, no reads beyond the queue, no settings / exports / bulk. A
leaked token could add junk tasks (30/min) or rename tasks — larger than
ADR-034's blast radius, still bounded and revocable the same ways. The
scope-rejection matrix grows: the token still can't `POST /api/tasks` or
`PATCH /api/tasks/<id>`, and extra JSON keys on the new routes are ignored.
CLAUDE.md threat model updated.

## 5. Help and the Shortcut (#503)

Help → "Hands-free voice review (Siri Shortcut)" is rewritten for someone who
has never built a Shortcut: Part 1 reads the tasks (unchanged), Part 2 is four
actions (Dictate Text → Get Contents of URL to `/answer` → Get Dictionary
Value `say` → Speak Text), plus a second Shortcut "Add a task". The two steps
the old Help gave that Shortcuts can't do (rename an action's output,
"Otherwise If") go. The /settings card's hint says the token can now add and
edit. The setup guide page sent in chat gets the same Part 2.

## 6. Tests (red first)

- `tests/test_voice_answer.py` — the parser with a fixed today: every phrase
  in §2–3, the whole-answer rule, casing kept on rename, unreadable dates.
- `tests/test_voice_answer_api.py` — both routes with a real token: each
  action lands, `say` on every answer, inactive / missing task, extra keys
  ignored, the token still refused on `/api/tasks`.

## 7. Not in this ship

Adding a subtask, notes, a project or goal by voice; deleting by voice.
