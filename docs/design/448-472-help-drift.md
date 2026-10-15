# #448 + #472 — Help copy that drifted from the code

#448 (deep review §B11) listed ten Help claims; #472 (found by #445) added the
digest's "plain text only" and section order and /print's Overdue rule. One
Help-only ship, every claim re-checked against code on 2026-10-14.

## Re-checked and fixed

| Help section | Was wrong | Now says |
|---|---|---|
| Recurring → preview cards | a click "opens the template editor, not a detail panel"; solid cards "have a due date" | opens the latest spawned task's panel (Repeat edits the template) or says when it first spawns; solid = a real task |
| Email digest | "Plain text only"; Overdue third; "not archived"; no 7-day line / button; "excess whitespace stripped"; Brevo only | HTML + plain-text copy; real order (Today → Also due → Goals → counts → ⚠ Overdue → button); open tasks; ends trimmed; SMTP fallback |
| Print view | Overdue = all past-dated; project/goal printed; checklists everywhere; nav hidden by @media print | Overdue = every section but Today; type + due date only; checklists under Today/This Week; no nav on the page, Print/Back don't print; Notes box |
| Filters | three dimensions; project chips only under Work/Personal; "All projects"; goal dropdown with ✕ | four (search added); chips always shown (scoped by type); "All"; goal chip row |
| Auto-categorize / Plan my week | "same cap as voice memo + image scan" | 5/min like ✨ Plan / each other; voice + scan allow 20 |
| Auto-categorize | goals "in-progress / not-started" | not done or archived (incl. on hold) |
| Plan my week | recurring fires "next week", "may flag conflicts"; freezer "frozen > 60 days" | the week being planned, unspawned fires of active templates; "not changed for 60 days" |
| Settings | bin count = batches; Undo/Restore; shows recipient + From; services list | items (tasks + goals of undone imports + deleted tasks); Undo only; shows set / not set; + Google OAuth; full Claude list |
| Calendar | Unscheduled = "every task with no due date"; overdue "under its section" | not Today/Tomorrow (on their cells) or subtasks; Tomorrow/Freezer fall under Backlog & Freezer |
| Recycle bin | import kinds = OneNote / Excel goals / scans; "every row soft-deleted" | every batch kind; open + completed tasks deleted, cancelled left, goals/projects archived |

Item A4 (recycle bin lists ordinary deletes, subtasks come back) was already
correct after #428 / #433. `digest_service.py`'s module docstring said Overdue
is "surfaced first" — fixed with it.

## Found, filed (code, not copy)

- **#478** Empty Bin disabled when the bin holds only project imports.
- **#479** /print lists an overdue This Week task twice.
- **#480** a bulk-deleted imported subtask can be missing from the bin.
