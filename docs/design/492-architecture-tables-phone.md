# #492 — /architecture's gate tables on a phone

Found in #459's Phase 6 on 2026-10-15.

## What was wrong (re-measured 2026-10-16 at 375)

Three of the four `table.quality-gates` tables were wider than their
343px box (scroll widths 641, 599, 678): the first column's unbroken test
names in `<code>` are `nowrap`, so it alone took 247–412px and the
description columns sat to the right. Correction to the row: the tables
are `display: block; overflow-x: auto` (#217) and no ancestor clips them,
so the columns COULD be reached — by a sideways swipe inside each table,
per row, with the first column wider than the screen. Readable in theory,
not in practice.

## Tried first

Letting the first column and `<code>` wrap, then `overflow-wrap: anywhere`
on the other cells: everything fits, but the auto table layout crushes a
column to 37–42px ("Sc he dul e", "Mo nd ays"). Four columns of prose don't
fit 343px as a table.

## This ship

At ≤767px each row stacks into a card (`static/style.css`): the header row
is hidden, the first cell is the card's heading, and every other cell is
labelled with its column ("SCHEDULE", "WHAT IT SCANS") from a `data-label`
the inline script on `templates/architecture.html` copies from the table's
`<th>`s. `<code>` may break anywhere there. Above 767px nothing changes.
CACHE_VERSION v346.

## Tests

`tests/e2e/architecture_tables.spec.js`: at 375 every cell of every gate
table is inside the screen and the page doesn't scroll sideways (red
before: tables 2–4 at 512 / 615 / 428); at 1280 the rows are still
table rows (the quiet case).
