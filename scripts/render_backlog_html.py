"""Render BACKLOG.md as a readable single-file HTML page.

Open items first (in progress on top), grouped by section; every done item
collapsed into one expandable group at the bottom. Each item is a one-line
title that expands to its full text. Pure stdlib, no network, no JS libs.

Usage (from the repo root):
    python scripts/render_backlog_html.py               # BACKLOG.md -> backlog.html
    python scripts/render_backlog_html.py SRC.md OUT.html

`backlog.html` is gitignored: it is a local reading copy, regenerated on
demand, never the source of truth.
"""
from __future__ import annotations

import argparse
import html
import re
from dataclasses import dataclass, field
from datetime import datetime

DONE_START = re.compile(
    r"^\W*(✅|🟢|DONE|RESOLVED|SHIPPED|FIXED|CLOSED|WON'?T ?FIX|SUPERSEDED|COMPLETE)",
    re.I,
)
DONE_ANYWHERE = re.compile(r"✅\s*(DONE|SHIPPED|RESOLVED|FIXED)|🟢 auto-detected resolved", re.I)
IN_PROGRESS = re.compile(r"🔄|IN PROGRESS", re.I)

# Sections whose rows are done by definition.
ALL_DONE_SECTIONS = {"Completed", "Resolved (newest first)"}
SKIP_SECTIONS = {"In Progress"}
# Which column carries the state, per table header.
STATUS_COLUMNS = ("Status", "Notes / Status")
WIDE_HEADER = ["#", "Item", "Category", "Priority", "Value", "Effort", "Complexity", "Status"]
DEFERRED = re.compile(r"^\W*(💤|DEFERRED)", re.I)


@dataclass
class Item:
    section: str
    number: str
    title: str
    body: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    state: str = "open"  # open | progress | done
    status: str = ""


def inline(md: str) -> str:
    """Escape, then render the inline markdown BACKLOG.md actually uses."""
    s = html.escape(md, quote=False)
    s = re.sub(r"&amp;(#?\w+);", r"&\1;", s)  # keep authored entities (&rlarr; etc.)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    # `"` is excluded from the URL so a link can't close the href attribute.
    s = re.sub(r'\[([^\]]+)\]\((https?://[^)\s"]+)\)', r'<a href="\2">\1</a>', s)
    return s


def split_row(line: str) -> list[str]:
    """Split a markdown table row on `|`, ignoring pipes inside `code`
    spans and escaped `\\|` (both appear in BACKLOG.md's long cells)."""
    cells, buf, in_code, prev = [], [], False, ""
    for ch in line.strip():
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code and prev != "\\":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        prev = ch
    cells.append("".join(buf))
    return [c.strip() for c in cells[1:-1]]


def title_and_body(text: str) -> tuple[str, str]:
    m = re.match(r"\s*\*\*(.+?)\*\*\s*(?:—|-|:)?\s*(.*)$", text, re.S)
    if m:
        return m.group(1), m.group(2)
    head, _, rest = text.partition(" — ")
    return head, rest


def classify(status: str, section: str) -> str:
    if section in ALL_DONE_SECTIONS:
        return "done"
    if DONE_START.search(status) or DONE_ANYWHERE.search(status):
        return "done"
    if IN_PROGRESS.search(status):
        return "progress"
    return "open"


def parse(md: str) -> tuple[list[Item], str]:
    items: list[Item] = []
    section = ""
    header: list[str] | None = None
    bullet: list[str] | None = None
    in_comment = False

    def flush_bullet():
        nonlocal bullet
        if bullet:
            text = " ".join(x.strip() for x in bullet)
            text = re.sub(r"^- \[[ xX]\]\s*", "", text)
            title, body = title_and_body(text)
            num = re.search(r"#(\d+)", title) or re.search(r"#(\d+)", text)
            state = "done" if bullet[0].lstrip().startswith("- [x]") else "open"
            if section in ALL_DONE_SECTIONS:
                state = classify("", section)
            items.append(Item(section, num.group(1) if num else "", title, body, state=state))
        bullet = None

    for raw in md.splitlines():
        line = raw.rstrip("\n")
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.strip().startswith("<!--") and "-->" not in line:
            in_comment = True
            continue
        if line.startswith("## "):
            flush_bullet()
            section, header = line[3:].strip(), None
            continue
        if line.startswith("#"):  # ### subheadings: keep section, end tables
            flush_bullet()
            header = None
            continue
        if section in SKIP_SECTIONS or not section:
            continue
        if line.startswith("|"):
            flush_bullet()
            cells = split_row(line)
            if header is None:
                header = cells
                continue
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
                continue
            # Some older rows use the 8-column backlog layout under a
            # 4-column header (e.g. early Bugs rows). Their state is always
            # the LAST cell, so read it from there, and label the middle
            # cells with the wider layout's names when the row is wider.
            hdr = header if len(cells) <= len(header) else WIDE_HEADER[:len(cells)]
            row = dict(zip(hdr, cells, strict=False))  # short rows are allowed
            first_col = hdr[0]
            item_col = next((h for h in hdr if h in ("Item", "Finding")), hdr[1])
            status = cells[-1] if hdr[-1] in STATUS_COLUMNS or len(cells) > len(header) else ""
            title, body = title_and_body(row.get(item_col, ""))
            if not title.strip():
                title = row.get(first_col, "").strip("`")
            number = row.get(first_col, "").strip()
            if not number.isdigit():
                number = ""
            fields = [(h, row[h]) for h in hdr
                      if h not in (first_col, item_col) and row.get(h)]
            items.append(Item(section, number, title, body, fields,
                              classify(status, section), status))
            continue
        header = None if not line.strip() else header
        if re.match(r"^- \[[ xX]\]", line):
            flush_bullet()
            bullet = [line]
        elif bullet is not None and (line.startswith("  ") or not line.strip()):
            if line.strip():
                bullet.append(line)
        else:
            flush_bullet()
    flush_bullet()
    title = next((ln[2:] for ln in md.splitlines() if ln.startswith("# ")), "Backlog")
    return items, title


def render_item(it: Item) -> str:
    num = f'<span class="num">#{html.escape(it.number)}</span>' if it.number else ""
    badge = {"progress": '<span class="badge prog">In progress</span>',
             "done": '<span class="badge done">Done</span>'}.get(it.state, "")
    if it.state == "open" and DEFERRED.search(it.status):
        badge = '<span class="badge def">Deferred</span>'
    meta = "".join(
        f'<div class="field"><span class="k">{html.escape(k)}</span>'
        f'<span class="v">{inline(v)}</span></div>'
        for k, v in it.fields)
    body = f'<p class="body">{inline(it.body)}</p>' if it.body.strip() else ""
    search = html.escape(f"{it.number} {it.title} {it.body} "
                         + " ".join(v for _, v in it.fields)).lower()
    return (f'<details class="item {it.state}" data-search="{search}">'
            f'<summary>{num}<span class="title">{inline(it.title)}</span>{badge}'
            f'<span class="sec">{html.escape(it.section)}</span></summary>'
            f'<div class="detail">{meta}{body}</div></details>')


def render(items: list[Item], doc_title: str, source: str) -> str:
    open_order = ["Bugs", "Backlog (prioritized)", "Auto-filed by recurring audits",
                  "Freezer (good ideas, not now)", "Phase 2 Roadmap"]
    live = [i for i in items if i.state != "done"]
    done = [i for i in items if i.state == "done"]
    progress = [i for i in live if i.state == "progress"]
    groups = []
    if progress:
        groups.append(("In progress", progress, True))
    sections = sorted({i.section for i in live if i.state == "open"},
                      key=lambda s: open_order.index(s) if s in open_order else 99)
    for s in sections:
        rows = [i for i in live if i.state == "open" and i.section == s]
        groups.append((s, rows, True))

    def num_key(i: Item):
        return -int(i.number) if i.number.isdigit() else 0

    open_html = "".join(
        f'<section class="group"><h2>{html.escape(name)} '
        f'<span class="count">{len(rows)}</span></h2>'
        + "".join(render_item(i) for i in rows) + "</section>"
        for name, rows, _ in groups)
    done_sorted = sorted(done, key=num_key)
    done_html = "".join(render_item(i) for i in done_sorted)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backlog</title>
<style>
:root {{
  --bg:#f7f6f3; --panel:#ffffff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dc;
  --accent:#2f6fde; --prog:#b26a00; --prog-bg:#fff3df; --done:#2e7d4f; --done-bg:#e6f4ea;
  --code-bg:#f0eee9;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#141416; --panel:#1d1d21; --ink:#ececef; --muted:#9a9aa3; --line:#2c2c33;
  --accent:#7aa7ff; --prog:#ffb648; --prog-bg:#3a2a10; --done:#6fd39a; --done-bg:#16301f;
  --code-bg:#2a2a31; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; }}
main {{ max-width:980px; margin:0 auto; padding:24px 16px 64px; }}
header h1 {{ font-size:24px; margin:0 0 4px; }}
header p {{ margin:0; color:var(--muted); font-size:13px; }}
.stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:16px 0; }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:8px 12px; font-size:13px; color:var(--muted); }}
.stat b {{ color:var(--ink); font-size:18px; margin-right:4px; }}
.controls {{ position:sticky; top:0; z-index:5; background:var(--bg); padding:10px 0;
  display:flex; gap:8px; flex-wrap:wrap; }}
.controls input {{ flex:1 1 240px; min-width:0; padding:10px 12px; font-size:15px;
  border:1px solid var(--line); border-radius:8px; background:var(--panel); color:var(--ink); }}
.controls button {{ padding:10px 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--panel); color:var(--ink); font-size:14px; cursor:pointer; min-height:44px; }}
.group h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
  margin:22px 0 8px; }}
.count {{ background:var(--line); color:var(--ink); border-radius:999px; padding:1px 8px;
  font-size:12px; margin-left:6px; letter-spacing:0; }}
details.item {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
  margin:6px 0; }}
details.item.progress {{ border-left:4px solid var(--prog); }}
details.item > summary {{ list-style:none; cursor:pointer; padding:10px 12px; display:flex;
  gap:8px; align-items:baseline; flex-wrap:wrap; min-height:44px; }}
details.item > summary::-webkit-details-marker {{ display:none; }}
details.item > summary::before {{ content:"▸"; color:var(--muted); width:12px; flex:none; }}
details.item[open] > summary::before {{ content:"▾"; }}
.num {{ font-weight:700; color:var(--accent); flex:none; }}
.title {{ flex:1 1 300px; min-width:0; overflow-wrap:anywhere; }}
.title strong {{ font-weight:600; }}
.sec {{ font-size:12px; color:var(--muted); flex:none; }}
.badge {{ font-size:11px; font-weight:700; border-radius:999px; padding:2px 8px; flex:none; }}
.badge.prog {{ color:var(--prog); background:var(--prog-bg); }}
.badge.done {{ color:var(--done); background:var(--done-bg); }}
.badge.def {{ color:var(--muted); background:var(--line); }}
.detail {{ padding:0 14px 14px 32px; border-top:1px solid var(--line); }}
.field {{ display:flex; gap:10px; font-size:13px; padding-top:8px; }}
.field .k {{ color:var(--muted); flex:0 0 110px; }}
.field .v {{ flex:1; min-width:0; overflow-wrap:anywhere; }}
.body {{ margin:10px 0 0; overflow-wrap:anywhere; }}
code {{ background:var(--code-bg); border-radius:4px; padding:0 4px; font-size:13px;
  overflow-wrap:anywhere; }}
a {{ color:var(--accent); }}
details.closed-group {{ margin-top:32px; }}
details.closed-group > summary {{ cursor:pointer; font-size:15px; font-weight:700;
  text-transform:uppercase; letter-spacing:.04em; color:var(--muted); padding:12px 0;
  min-height:44px; }}
.hidden {{ display:none !important; }}
.empty {{ color:var(--muted); padding:20px 0; }}
@media (max-width:600px) {{ .sec {{ width:100%; padding-left:20px; }}
  .title {{ flex:1 1 0; }}
  .controls input {{ flex-basis:100%; }}
  .controls button {{ flex:1 1 0; }}
  .field {{ flex-direction:column; gap:0; }} .field .k {{ flex:none; }} }}
</style></head>
<body><main>
<header><h1>{html.escape(doc_title)}</h1>
<p>Generated {stamp} from <code>{html.escape(source)}</code>.
Re-run <code>python scripts/render_backlog_html.py</code> to refresh.</p></header>
<div class="stats">
  <div class="stat"><b>{len(progress)}</b>in progress</div>
  <div class="stat"><b>{len(live) - len(progress)}</b>open</div>
  <div class="stat"><b>{len(done)}</b>done</div>
</div>
<div class="controls">
  <input id="q" type="search" placeholder="Search number, title or text…"
         aria-label="Search the backlog">
  <button type="button" id="expand">Expand all</button>
  <button type="button" id="collapse">Collapse all</button>
</div>
<div id="open">{open_html}</div>
<details class="closed-group" id="closed">
<summary>Done <span class="count">{len(done)}</span></summary>
{done_html}
</details>
<p class="empty hidden" id="none">Nothing matches.</p>
</main>
<script>
(function () {{
  var q = document.getElementById("q");
  var items = Array.prototype.slice.call(document.querySelectorAll("details.item"));
  var closed = document.getElementById("closed");
  function apply() {{
    var term = q.value.trim().toLowerCase();
    var shown = 0;
    items.forEach(function (d) {{
      var hit = !term || d.dataset.search.indexOf(term) !== -1;
      d.classList.toggle("hidden", !hit);
      if (hit) shown++;
    }});
    document.querySelectorAll("section.group").forEach(function (g) {{
      var any = g.querySelector("details.item:not(.hidden)");
      g.classList.toggle("hidden", !any);
    }});
    if (term && closed.querySelector("details.item:not(.hidden)")) closed.open = true;
    document.getElementById("none").classList.toggle("hidden", shown > 0);
  }}
  q.addEventListener("input", apply);
  document.getElementById("expand").addEventListener("click", function () {{
    items.forEach(function (d) {{ if (!d.classList.contains("hidden")) d.open = true; }});
  }});
  document.getElementById("collapse").addEventListener("click", function () {{
    items.forEach(function (d) {{ d.open = false; }});
  }});
}})();
</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Render BACKLOG.md as a readable HTML page.")
    ap.add_argument("src", nargs="?", default="BACKLOG.md")
    ap.add_argument("out", nargs="?", default="backlog.html")
    args = ap.parse_args(argv)
    src, out = args.src, args.out
    with open(src, encoding="utf-8") as f:
        md = f.read()
    items, title = parse(md)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(items, title, src.replace("\\", "/").split("/")[-1]))
    counts = {s: sum(1 for i in items if i.state == s) for s in ("progress", "open", "done")}
    print(f"wrote {out}: {len(items)} items {counts}")


if __name__ == "__main__":
    main()
