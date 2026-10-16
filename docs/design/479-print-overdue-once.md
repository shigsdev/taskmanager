# #479 — /print lists an overdue This Week task once

Filed 2026-10-14 by the #448 Help check. Checked 2026-10-16 against
`app.py` `print_page` and `templates/print.html`.

## What was wrong

`print_page` builds **Overdue** from every active past-dated task except
Today's, and **This Week** from every active This Week task. An overdue This
Week task printed twice: in red under Overdue, and plain under This Week.
It's uncommon — the 00:03 re-sort moves a This Week task whose day has
passed to Today — but it happens between midnight and the re-sort, or when
the re-sort missed a night. The everyday half: a Today task past its date
(where the re-sort puts them) printed once, under Today, with nothing to say
it's overdue.

## This ship (the "list it once, marked" option — the digest's #445 rule)

- Overdue holds the sections that don't print on their own (Inbox,
  Tomorrow, Next Week, Backlog, Freezer): every active past-dated task
  NOT in Today or This Week.
- Today and This Week still list every open task in them; one past its due
  date is printed in the Overdue red, its meta reading
  "… · overdue, was due 2026-10-12" instead of "· due …". Its checklist
  still prints under it (the Overdue list never had checklists).
- Help → Print view: the Overdue line and the Layout line say so.

The quiet cases: a This Week / Today task due today or later prints
exactly as before; an overdue Backlog task is still under Overdue.
