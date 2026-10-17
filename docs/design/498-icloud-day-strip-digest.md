# #498 (#371b): iCloud events on the board's day strip and in the digest

This is the second half of #371. #371a (`f7f5df3`) put the user's iCloud
Calendar events on /calendar. The user set `ICLOUD_*` on Railway on
2026-10-17, and the first production read returned 41 events from "Home".

## User decisions (2026-10-17)

| Question | Choice |
|---|---|
| Day strip, desktop | Each day box shows its **first event**, compact ("9:30am Dentist"), plus "+N" for more |
| Day strip, phone (21px boxes at 375) | A **dot** under the date; tapping it opens /calendar. The strip keeps its height |
| Digest | A "Today's calendar" block at the **top**, before Today's tasks |
| Digest failure | One line; the email still goes out |

## As built

- **Day strip** (`static/app.js`):
  - `dayStripLoadEvents` asks `/api/icloud/events` for the strip's 14 days,
    at most once a minute. The server caches for 15 minutes.
  - A failure is quiet; /calendar is where the error is shown.
  - `renderDayStrip` adds `a.day-cell-event` to `/calendar`.
  - The text comes from `icloudEventHelpers.dayStripSummary` (Jest):
    - a carried-over event reads "until 6:30am";
    - an all-day event shows just its title;
    - the aria-label names the first event and the count.
- **Strip CSS:**
  - Above 900px: the text with an ellipsis, plus "+N".
  - At 900px and below: the link covers the whole box (46px tall, so it
    meets the 44px tap target) and shows a dot.
  - Drops still bubble to the cell.
- **Digest** (`digest_service._calendar_for_day`):
  - calls `fetch_events(today, tomorrow)` and builds rows of
    `{time, title, location}`;
  - order: all-day first, then by start;
  - a red-eye's second day reads "until 6:30 AM", and an event that ended
    exactly at midnight is dropped;
  - any exception becomes a one-line message, never a lost email;
  - in plain text the block reads "TODAY'S CALENDAR (n)"; the HTML version
    is autoescaped.
- **Tests:** `tests/conftest.py` now clears `ICLOUD_*`, so no test can call
  Apple by accident.
