# #438 — Week rollover rules

Deep review 2026-10-11 §B4 ("needs a decision"). User decisions
2026-10-12, recorded below.

## What happens today

Four nightly jobs (`cron_jobs.JOB_ORDER`): 00:01 `tomorrow_roll`, 00:02
`promote_due_today`, 00:03 `realign_tiers_with_due_dates`, 00:05
`recurring_spawn`. Only the realign moves tasks between weeks, and it
only touches **dated** tasks:

- An **undated Next Week** task is never moved. #220 clears the date
  when you punt to Next Week, so most Next Week tasks are undated. On
  2026-10-12, prod had 10 undated Next Week tasks, some created 51–169
  days earlier, and 1 task in This Week.
- A dated **This Week / Next Week** task whose date has passed is mapped
  by `_tier_for_due_date`: a date earlier this week stays This Week,
  and a date from an earlier week goes to **Backlog**. So on Monday
  everything unfinished from last week is quietly sent to Backlog,
  still carrying its overdue date. Only Today is protected (#170).

## Decisions (user, 2026-10-12)

1. **Undated Next Week → This Week when the week arrives.**
2. **A This Week / Next Week task whose date has passed moves to Today
   the next night**, where it shows as overdue: the "overdue stays in
   sight" rule that #170 (Today) and #386 (filing) already follow.
   Backlog, Freezer and Inbox are untouched.

## Design

Both live in `realign_tiers_with_due_dates` (00:03), which already runs
in an isolated session and is replayed by `cron_audit_service` if a run
is missed.

**Rule 2** is a change to the dated loop: for a task in THIS_WEEK or
NEXT_WEEK with `due_date < today`, the target is TODAY. Everything else
keeps `_tier_for_due_date`.

**Rule 1** runs once per ISO week, not "if today is Monday":
- an `AppSetting` row `week_roll_last_iso_week` holds the week last rolled;
- if it differs from the current ISO week (DIGEST_TZ), every active
  undated NEXT_WEEK task moves to THIS_WEEK and the marker is updated;
- **if the row doesn't exist yet (the first run after deploy), it is only
  recorded.** Tasks you put in Next Week during the current week mean
  the coming week, so the first roll happens on the following Monday
  (2026-10-19 for this deploy).

Why not "if Monday": a missed Monday run is replayed later (on boot or
the next day), and a weekday check would skip it.

Known edge: if the Monday run is late (replayed after you've already
moved something into Next Week that Monday), that task rolls too. That
needs a missed cron plus a same-morning punt; accepted.

## Help

`templates/docs.html` gets a "Week rollover" paragraph in the sections
area, next to the "Tomorrow → Today roll", which already documents the
00:01 job.

## Tests

- pytest: undated Next Week moves to This Week on a new week, once only;
  the first run only records; a dated Next Week task is unaffected by the
  week roll; a This Week task dated yesterday moves to Today; a Next Week
  task with a past date moves to Today; a This Week task dated later this
  week stays; a Backlog task with a past date is unchanged by the new
  rule; Today-overdue stays (#170); Freezer and Inbox are untouched.
- No page code changes (the board renders the tiers it gets), so no
  Jest or Playwright; Help copy is checked in Phase 6.
