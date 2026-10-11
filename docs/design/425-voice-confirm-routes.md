# #425 — Voice memo goals, projects and "Make recurring" reach the server

Filed 2026-10-11 by the deep review (§A1). Help's "Voice memo" section
(`templates/docs.html` "Routing to task / goal / project") promises that a
candidate can be routed to a goal or a project, that each carries a goal
category the parser infers, and (#155) that "↻ Make recurring" turns it into a
recurring template. None of it reaches the database from the real screen.

## 1. Surface — the whole voice memo review → confirm path

| Step | Code | Problem |
|---|---|---|
| Parse response | `voice_api.py` `upload` builds `candidates_out` (~147-164) | Drops `category` — `_normalise_voice_candidates` infers it (#172), but the review row's Category dropdown always starts on "Personal growth" |
| Review row | `voice_memo.js` `renderCandidate`: route badge (~414-427), Category (~650-669), ↻ Make recurring (~697-709) | Sets `route`, `category`, `repeat` on the candidate — fine |
| Make recurring pop-up | `voice_memo.js` `openRecurringModal` (~720-845) | Offers Weekly / Monthly by Nth weekday with no check for the fields they need, and has no Week-of-month field at all; `create_recurring` then 422s and the server swallows it |
| Confirm payload | `voice_memo.js` `confirmCandidates` (~857-865) | Sends only title/type/tier/due_date/project_id/goal_id/included — **drops `route`, `category`, `repeat`**. Since #67 (2026-04-26) / #155 (2026-05-09) every goal, project and recurring item became an Inbox task |
| Server confirm | `voice_api.py` `confirm` (~197-327) | Routes correctly when the fields arrive; a recurring candidate that fails is logged and dropped with no warning in the response |
| Done message | `voice_memo.js` (~887-890) | Always "N tasks added to Inbox", whatever was made and wherever it was filed; ignores `warning` |

Why tests missed it: `tests/test_voice_memo.py` posts `route` / `repeat` by
hand; the Playwright tests stub the parse and never confirm.

## 2. This ship

1. `static/voice_memo_helpers.js` (dual export, Jest-tested):
   - `buildConfirmPayload(candidates, onlySelected)` — forwards `route`,
     `category`, `repeat` with the existing fields; drops blank titles and
     unticked rows when `onlySelected`, as today.
   - `repeatProblem(repeat)` — `null`, or a readable reason a repeat can't be
     saved: Weekly needs a day; Monthly by date needs a day 1-31; Monthly by
     Nth weekday needs a week (1st-4th) and a day.
   - `confirmSummary(data)` — "Added 2 tasks, 1 goal, 1 project and
     1 recurring task." from the response lists, plus `data.warning`.
2. `voice_memo.js`: use the three helpers; the pop-up gets a "Week of month"
   select (1st-4th) and refuses to save an incomplete repeat with an inline
   message instead of closing.
3. `voice_api.py`: forward `category` in the parse response; count recurring
   candidates that couldn't be created and say so in `warning`.
4. Tests, red on the old code:
   - Jest for the three helpers.
   - pytest: the parse response carries `category`; a recurring candidate
     the server can't create produces a warning.
   - Playwright (desktop + mobile, real MediaRecorder on the fake mic, parse
     stubbed, **confirm unstubbed**): one row cycled to GOAL with category
     Health, one to PROJECT, one made Weekly on Monday, one left a task →
     Add All → the goal, project and template exist (read back through the
     API) and the done message names all four kinds. The pop-up refuses
     Weekly with no day.
5. Help: no new claim — Help already describes this behaviour. Add one line
   for ↻ Make recurring (it is undocumented) and fact-check it.
6. CACHE_VERSION bump.

## 3. Out of scope

- Claude doesn't infer a repeat; the pop-up starts empty (its code comment
  says "pre-filled with Claude's inferred recurrence"). The comment is
  corrected here; inference is a feature, not filed.
- The rest of the voice memo failure handling (lost audio / review on a
  failed upload or confirm) is #442; double-tap on Add All is #429.
