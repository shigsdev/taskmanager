"""#407 Strength Forge — diagram readability guards.

The exercise diagrams are hand-placed SVG. Before #407 nothing checked them,
and a render showed captions at ~1.9:1 contrast and labels drawn straight
over the stick figure. These tests make that class of defect mechanical:

* every label colour is readable on the diagram background (WCAG 4.5:1);
* every label is at least 11 viewBox units (~11.7px on a 375px phone);
* every label sits inside the viewBox;
* no two labels overlap;
* no label is crossed by a figure / band / prop stroke.

Labels are monospace, so a label's box is exact: ``len × 0.6 × size`` wide.
Symbols outside basic Latin (arrows, ⚠, ◇) are counted a full 1.0em wide so
a glyph-fallback font can't make a label silently wider than measured.
"""
import math
import re
import xml.etree.ElementTree as ET  # parses only our own hardcoded SVG constants

import pytest

import strength_forge_diagrams as sfd

NS = "{http://www.w3.org/2000/svg}"
MIN_FONT = 11
MIN_CONTRAST = 4.5
EDGE_MARGIN = 3


# ── colour ────────────────────────────────────────────────────────────
def _lum(hex_color):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    chans = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ── geometry ──────────────────────────────────────────────────────────
def _char_w(ch):
    return 0.6 if ord(ch) < 0x2190 else 1.0


def _text_box(t):
    size = float(t.get("font-size"))
    x = float(t.get("x"))
    y = float(t.get("y"))
    width = sum(_char_w(c) for c in (t.text or "")) * size
    anchor = t.get("text-anchor", "start")
    left = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
    return (left, y - 0.75 * size, left + width, y + 0.25 * size)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inflate(box, d):
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)


def _inside(box, x, y):
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _sample_segment(p, q, step=1.0):
    n = max(1, int(math.dist(p, q) / step))
    return [(p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n) for i in range(n + 1)]


def _sample_quad(p0, c, p1, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        out.append((
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t ** 2 * p1[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t ** 2 * p1[1],
        ))
    return out


def _path_points(d):
    """Sample an SVG path. Only M / L / Q are allowed — the diagrams use
    nothing else, and an unparseable command would hide strokes from the
    overlap check, so it fails loudly instead."""
    toks = re.findall(r"[A-Za-z]|-?\d*\.?\d+", d)
    pts, cur, i = [], None, 0
    while i < len(toks):
        cmd = toks[i]
        if cmd == "M":
            cur = (float(toks[i + 1]), float(toks[i + 2]))
            pts.append(cur)
            i += 3
        elif cmd == "L":
            nxt = (float(toks[i + 1]), float(toks[i + 2]))
            pts += _sample_segment(cur, nxt)
            cur = nxt
            i += 3
        elif cmd == "Q":
            c = (float(toks[i + 1]), float(toks[i + 2]))
            nxt = (float(toks[i + 3]), float(toks[i + 4]))
            pts += _sample_quad(cur, c, nxt)
            cur = nxt
            i += 5
        else:
            raise AssertionError(f"unsupported path command {cmd!r} in {d!r}")
    return pts


def _points_attr(s):
    nums = [float(n) for n in re.findall(r"-?\d*\.?\d+", s)]
    return list(zip(nums[0::2], nums[1::2], strict=True))


def _strokes(root):
    """Yield (points, half_width) for every drawn shape, and filled rects as
    ('rect', box). Text never counts as a stroke."""
    for el in root.iter():
        tag = el.tag.replace(NS, "")
        sw = float(el.get("stroke-width", "1"))
        if tag == "line":
            p = (float(el.get("x1")), float(el.get("y1")))
            q = (float(el.get("x2")), float(el.get("y2")))
            yield _sample_segment(p, q), sw / 2
        elif tag in ("polyline", "polygon"):
            pts = _points_attr(el.get("points"))
            if tag == "polygon":
                pts = pts + pts[:1]
            seg = []
            for a, b in zip(pts, pts[1:], strict=False):
                seg += _sample_segment(a, b)
            yield seg, sw / 2
        elif tag in ("circle", "ellipse"):
            cx, cy = float(el.get("cx")), float(el.get("cy"))
            rx = float(el.get("r") or el.get("rx"))
            ry = float(el.get("r") or el.get("ry"))
            yield [(cx + rx * math.cos(a / 30 * math.pi), cy + ry * math.sin(a / 30 * math.pi))
                   for a in range(60)], sw / 2
        elif tag == "path":
            yield _path_points(el.get("d")), sw / 2
        elif tag == "rect":
            x, y = float(el.get("x")), float(el.get("y"))
            yield ("rect", (x, y, x + float(el.get("width")), y + float(el.get("height")))), 0


def _parse(svg):
    root = ET.fromstring(svg)  # noqa: S314 — our own hardcoded SVG, never user input
    _, _, w, h = (float(v) for v in root.get("viewBox").split())
    texts = [t for t in root.iter(f"{NS}text")]
    return root, w, h, texts


IDS = sorted(sfd.DIAGRAMS)


@pytest.mark.parametrize("key", IDS)
def test_label_colours_are_readable(key):
    _, _, _, texts = _parse(sfd.DIAGRAMS[key])
    for t in texts:
        ratio = _contrast(t.get("fill"), sfd.BG)
        assert ratio >= MIN_CONTRAST, (
            f"{key}: {t.text!r} fill {t.get('fill')} is {ratio:.2f}:1 on the background"
        )


@pytest.mark.parametrize("key", IDS)
def test_label_sizes_are_legible(key):
    _, _, _, texts = _parse(sfd.DIAGRAMS[key])
    for t in texts:
        assert float(t.get("font-size")) >= MIN_FONT, f"{key}: {t.text!r} is too small"


@pytest.mark.parametrize("key", IDS)
def test_labels_stay_inside_the_diagram(key):
    _, w, h, texts = _parse(sfd.DIAGRAMS[key])
    for t in texts:
        left, top, right, bot = _text_box(t)
        assert left >= EDGE_MARGIN and right <= w - EDGE_MARGIN and top >= 0 and bot <= h, (
            f"{key}: {t.text!r} box {(round(left), round(top), round(right), round(bot))} "
            f"leaves the {w:g}×{h:g} viewBox"
        )


@pytest.mark.parametrize("key", IDS)
def test_labels_do_not_overlap_each_other(key):
    _, _, _, texts = _parse(sfd.DIAGRAMS[key])
    boxes = [(t.text, _text_box(t)) for t in texts]
    for i, (ta, a) in enumerate(boxes):
        for tb, b in boxes[i + 1:]:
            assert not _overlap(a, b), f"{key}: {ta!r} overlaps {tb!r}"


@pytest.mark.parametrize("key", IDS)
def test_no_stroke_crosses_a_label(key):
    root, _, _, texts = _parse(sfd.DIAGRAMS[key])
    strokes = list(_strokes(root))
    for t in texts:
        box = _text_box(t)
        for pts, half in strokes:
            if pts == "rect" or (isinstance(pts, tuple) and pts[0] == "rect"):
                assert not _overlap(box, pts[1]), f"{key}: a prop shape sits under {t.text!r}"
                continue
            hit = _inflate(box, half)
            assert not any(_inside(hit, x, y) for x, y in pts), (
                f"{key}: a stroke crosses the label {t.text!r}"
            )


def test_geometry_helpers_catch_a_bad_diagram():
    """The guards must be able to fail: a dim, tiny label drawn over a line."""
    bad = (
        '<svg viewBox="0 0 320 100" xmlns="http://www.w3.org/2000/svg">'
        '<line x1="0" y1="50" x2="320" y2="50" stroke="#fff" stroke-width="2"/>'
        '<text x="160" y="53" text-anchor="middle" fill="#374151" font-size="9">HI</text>'
        "</svg>"
    )
    root, _, _, texts = _parse(bad)
    t = texts[0]
    assert _contrast(t.get("fill"), sfd.BG) < MIN_CONTRAST
    assert float(t.get("font-size")) < MIN_FONT
    box = _text_box(t)
    assert any(
        _inside(_inflate(box, half), x, y)
        for pts, half in _strokes(root) if not isinstance(pts, tuple)
        for x, y in pts
    )


def test_path_parser_rejects_unknown_commands():
    with pytest.raises(AssertionError):
        _path_points("M 0 0 A 5 5 0 1 1 10 10")
