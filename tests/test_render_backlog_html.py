"""Tests for `scripts/render_backlog_html.py`.

The generator turns BACKLOG.md into a single readable HTML page: open
items on top, done items in one collapsed group. These tests pin the
parsing rules that BACKLOG.md's real shapes depend on (pipes inside
code spans, old wide rows under a narrow header, `- [x]` bullets,
status words anywhere in a cell) and the escaping that keeps the page
from executing anything a row happens to contain.
"""
from __future__ import annotations

from scripts import render_backlog_html as rb

FIXTURE = """# Task Manager Backlog

<!--
| 999 | **A commented-out row** | OPEN |
-->

## In Progress

| # | Item | Status |
|---|---|---|
| 900 | **Mirror of an in-flight row** | 🔄 |

## Bugs

| # | Item | Notes / Status |
|---|---|---|
| 10 | **Pipe in `a | b` code** — body text | OPEN |
| 11 | **Old wide row** | bug | P1 | High | S | Low | ✅ DONE |
| 12 | **Shipped note mid-cell** | OPEN — filed. **✅ DONE — shipped in abc** |

### Subheading ends the table

## Backlog (prioritized)

| # | Item | Status |
|---|---|---|
| 20 | **Being built** — details | 🔄 IN PROGRESS — gates pending |
| 21 | **Parked idea** | 💤 DEFERRED |

## Completed

- [x] **#5 Finished thing** — first line
  continues here
- [x] **#6 Another**
"""


def _by_number(items):
    return {i.number: i for i in items}


def test_split_row_ignores_pipes_in_code_and_escaped_pipes():
    assert rb.split_row(r"| 1 | uses `a | b` and x \| y | OPEN |") == [
        "1", r"uses `a | b` and x \| y", "OPEN"]


def test_classify_states():
    assert rb.classify("OPEN", "Completed") == "done"
    assert rb.classify("✅ DONE — shipped", "Bugs") == "done"
    assert rb.classify("OPEN — filed. ✅ SHIPPED in abc", "Bugs") == "done"
    assert rb.classify("🔄 IN PROGRESS — gates pending", "Bugs") == "progress"
    assert rb.classify("OPEN", "Bugs") == "open"
    assert rb.classify("💤 DEFERRED", "Bugs") == "open"


def test_parse_reads_sections_rows_and_bullets():
    items, title = rb.parse(FIXTURE)
    got = _by_number(items)
    assert title == "Task Manager Backlog"
    # In Progress mirror and the commented-out row are skipped.
    assert "900" not in got and "999" not in got
    assert got["10"].title == "Pipe in `a | b` code"
    assert got["10"].body == "body text"
    assert got["10"].state == "open"
    assert got["11"].state == "done"  # status read from the LAST cell
    assert ("Category", "bug") in got["11"].fields
    assert got["12"].state == "done"
    assert got["20"].state == "progress"
    assert got["21"].state == "open"
    assert got["5"].state == "done" and got["5"].section == "Completed"
    assert got["5"].body == "first line continues here"
    assert got["6"].title == "#6 Another"


def test_inline_escapes_html_and_keeps_links_inside_the_href():
    out = rb.inline('<script>alert(1)</script> **bold** `code`')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<strong>bold</strong>" in out and "<code>code</code>" in out
    assert rb.inline("[docs](https://example.com/a)") == (
        '<a href="https://example.com/a">docs</a>')
    # A URL with a quote stays plain text: no tag is built, so the quote
    # can't close an href and smuggle in a handler.
    hostile = rb.inline('[x](https://a.test/"onmouseover="alert(1))')
    assert "<a " not in hostile


def test_render_puts_open_first_and_done_in_a_collapsed_group():
    items, title = rb.parse(FIXTURE)
    page = rb.render(items, title, "BACKLOG.md")
    closed = page.index('<details class="closed-group" id="closed">')
    assert page.index("Being built") < closed  # open/in-progress above
    assert page.index("Finished thing") > closed  # done below
    assert '<details class="closed-group" id="closed" open' not in page
    assert '<span class="badge prog">In progress</span>' in page
    assert '<span class="badge def">Deferred</span>' in page


def test_main_defaults_to_backlog_md_and_backlog_html(tmp_path, monkeypatch, capsys):
    (tmp_path / "BACKLOG.md").write_text(FIXTURE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rb.main([])
    page = (tmp_path / "backlog.html").read_text(encoding="utf-8")
    assert "Parked idea" in page
    assert "wrote backlog.html: 7 items" in capsys.readouterr().out


def test_main_accepts_explicit_paths(tmp_path):
    src = tmp_path / "in.md"
    out = tmp_path / "out.html"
    src.write_text(FIXTURE, encoding="utf-8")
    rb.main([str(src), str(out)])
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
