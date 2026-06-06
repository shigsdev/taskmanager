"""Strength Forge — exercise SVG diagrams ported from diagrams.jsx.

Pure-Python, stdlib only. Exposes ``DIAGRAMS``: a dict mapping exercise-id to a
complete, fully-static ``<svg ...>...</svg>`` markup string. Every coordinate,
color, and attribute is a faithful, mechanical transcription of the JSX source
(``docs/design/strength-forge/diagrams.jsx`` + ``SvgHelpers.jsx``). All values
are hardcoded — there is no user input.
"""

import math

# ── Colors (from constants.js) ──
# NOTE: BG is mapped to slate-0 (#131110), NOT the prototype's #0d1117.
ACC1 = "#c8a84b"  # gold
ACC2 = "#52c07a"  # green
ACC3 = "#6d9fe8"  # blue
ACC4 = "#e05252"  # red
DIM = "#374151"   # dark muted
FIG = "#e8eaf0"   # figure / text
BG = "#131110"    # diagram background (slate-0)


def _n(value):
    """Format a number: round to 3 decimals and drop trailing zeros."""
    r = round(float(value), 3)
    if r == int(r):
        return str(int(r))
    return f"{r:.3f}".rstrip("0").rstrip(".")


def _esc(text):
    """Escape XML special chars in label text (unicode glyphs kept as-is)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _svg(h, body):
    return (
        f'<svg viewBox="0 0 320 {h}" '
        f'style="width:100%;background:{BG};display:block" '
        f'xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )


def _lbl(x, y, text, color=DIM, size=10, anchor="middle"):
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}" '
        f'fill="{color}" font-size="{_n(size)}" '
        f'font-family="monospace">{_esc(text)}</text>'
    )


def _arr(x1, y1, x2, y2, color=ACC1, dashed=False):
    dx = x2 - x1
    dy = y2 - y1
    ln = math.sqrt(dx * dx + dy * dy)
    ux = dx / ln
    uy = dy / ln
    hx = x2 - ux * 7
    hy = y2 - uy * 7
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    line = (
        f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(hx)}" y2="{_n(hy)}" '
        f'stroke="{color}" stroke-width="1.5"{dash}/>'
    )
    points = (
        f'{_n(x2)},{_n(y2)} '
        f'{_n(hx - uy * 4)},{_n(hy + ux * 4)} '
        f'{_n(hx + uy * 4)},{_n(hy - ux * 4)}'
    )
    poly = f'<polygon points="{points}" fill="{color}"/>'
    return f"<g>{line}{poly}</g>"


def _fig(cx=160, cy=120, headR=13, torsoH=38, legL=44, armAngle=0, color=FIG, legBend=0):
    neck = cy - torsoH
    headY = neck - headR
    ax = math.cos(math.radians(armAngle)) * 30
    ay = math.sin(math.radians(armAngle)) * 30
    kX = legBend
    kY = cy + legL * 0.5
    fY = cy + legL

    def _l(x1, y1, x2, y2):
        return (
            f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
            f'stroke="{color}" stroke-width="2"/>'
        )

    parts = [
        f'<circle cx="{_n(cx)}" cy="{_n(headY)}" r="{_n(headR)}" '
        f'fill="none" stroke="{color}" stroke-width="2"/>',
        _l(cx, headY + headR, cx, cy),
        _l(cx, neck + 8, cx - 28 + ax, neck + 8 + ay),
        _l(cx, neck + 8, cx + 28 - ax, neck + 8 - ay),
        _l(cx, cy, cx - kX, kY),
        _l(cx - kX, kY, cx - 8, fY),
        _l(cx, cy, cx + kX, kY),
        _l(cx + kX, kY, cx + 8, fY),
    ]
    return "<g>" + "".join(parts) + "</g>"


DIAGRAMS: dict[str, str] = {}

DIAGRAMS["cat-cow"] = _svg(185, "".join([
    _lbl(160, 16, "CAT-COW STRETCH", ACC1, 11),
    f'<path d="M 60 88 Q 160 68 260 88" fill="none" stroke="{ACC2}" '
    'stroke-width="2" stroke-dasharray="5 3"/>',
    f'<path d="M 60 88 Q 160 110 260 88" fill="none" stroke="{ACC3}" '
    'stroke-width="2" stroke-dasharray="5 3"/>',
    f'<circle cx="65" cy="93" r="5" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="255" cy="93" r="5" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="65" cy="128" r="5" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="255" cy="128" r="5" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="65" y1="93" x2="65" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="255" y1="93" x2="255" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="65" cy="76" r="11" fill="none" stroke="{FIG}" stroke-width="2"/>',
    _lbl(160, 152, "↑ COW — arch back (inhale)", ACC2, 10),
    _lbl(160, 165, "↓ CAT — round back (exhale)", ACC3, 10),
    _lbl(160, 179, "10 slow reps · no rest", DIM, 9),
]))

DIAGRAMS["band-pull-apart"] = _svg(185, "".join([
    _lbl(160, 16, "BAND PULL-APART", ACC1, 11),
    _fig(cx=160, cy=128, armAngle=0),
    f'<line x1="90" y1="100" x2="132" y2="100" stroke="{ACC2}" stroke-width="3"/>',
    f'<line x1="188" y1="100" x2="230" y2="100" stroke="{ACC2}" stroke-width="3"/>',
    _arr(132, 100, 86, 100, ACC1),
    _arr(188, 100, 234, 100, ACC1),
    _lbl(160, 168, "Pull band apart to a T · squeeze blades", DIM, 9),
    _lbl(160, 180, "15 reps · light band warm-up", DIM, 9),
]))

DIAGRAMS["band-squat"] = _svg(200, "".join([
    _lbl(160, 16, "BAND ASSISTED SQUAT", ACC1, 11),
    f'<rect x="140" y="22" width="40" height="7" rx="3" fill="{DIM}"/>',
    f'<line x1="160" y1="29" x2="160" y2="52" stroke="{ACC2}" '
    'stroke-width="2" stroke-dasharray="4 2"/>',
    f'<line x1="60" y1="152" x2="260" y2="152" stroke="{DIM}" '
    'stroke-width="1" stroke-dasharray="3 3"/>',
    _lbl(54, 156, "70%", ACC4, 9, "end"),
    _fig(cx=160, cy=143, legBend=14, armAngle=-28),
    _lbl(160, 183, "60–70% depth only · spine neutral", DIM, 9),
    _lbl(160, 195, "3×10 · 60s rest", ACC1, 9),
]))

DIAGRAMS["band-row"] = _svg(200, "".join([
    _lbl(160, 16, "BAND SEATED ROW", ACC1, 11),
    f'<line x1="30" y1="163" x2="290" y2="163" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="100" cy="100" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="113" x2="100" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="153" x2="78" y2="163" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="153" x2="122" y2="163" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="125" x2="145" y2="133" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="153" x2="230" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="230" y1="158" x2="278" y2="158" stroke="{ACC2}" stroke-width="3"/>',
    _arr(155, 133, 110, 126, ACC1),
    _lbl(200, 138, "SIT TALL", ACC2, 10),
    _lbl(160, 183, "Elbows back · squeeze blades · 3×12", DIM, 9),
]))

DIAGRAMS["band-chest-press"] = _svg(200, "".join([
    _lbl(160, 16, "STANDING BAND CHEST PRESS", ACC1, 11),
    f'<rect x="262" y="30" width="10" height="148" fill="{DIM}" rx="2"/>',
    f'<line x1="195" y1="113" x2="265" y2="113" stroke="{ACC2}" stroke-width="3"/>',
    _fig(cx=160, cy=140, armAngle=10),
    _arr(150, 113, 110, 113, ACC1),
    _lbl(85, 108, "PRESS →", ACC2, 10),
    _lbl(160, 185, "Core braced · no back arch · 3×12", DIM, 9),
]))

DIAGRAMS["glute-bridge"] = _svg(190, "".join([
    _lbl(160, 16, "GLUTE BRIDGE", ACC1, 11),
    f'<line x1="20" y1="158" x2="300" y2="158" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="78" cy="128" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="78" y1="141" x2="178" y2="141" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="178" y1="98" x2="178" y2="141" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="178" y1="98" x2="208" y2="138" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="208" y1="138" x2="213" y2="158" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="178" y1="141" x2="153" y2="158" stroke="{FIG}" stroke-width="2"/>',
    _arr(178, 128, 178, 96, ACC2),
    _lbl(210, 95, "SQUEEZE GLUTES", ACC2, 9),
    _lbl(160, 174, "Drive hips up · hold 1s · lower slow", DIM, 9),
]))

DIAGRAMS["lateral-walk"] = _svg(190, "".join([
    _lbl(160, 16, "BAND LATERAL WALK", ACC1, 11),
    f'<line x1="98" y1="160" x2="222" y2="160" stroke="{ACC2}" stroke-width="3"/>',
    _fig(cx=160, cy=136, legBend=22),
    _arr(88, 118, 52, 118, ACC1),
    _arr(232, 118, 268, 118, ACC1),
    _lbl(160, 185, "Stay in squat · toes forward · 3×12 each", DIM, 9),
]))

DIAGRAMS["pallof-press"] = _svg(200, "".join([
    _lbl(160, 16, "PALLOF PRESS (ANTI-ROTATION)", ACC1, 11),
    f'<rect x="20" y="78" width="10" height="60" fill="{DIM}" rx="2"/>',
    f'<line x1="30" y1="113" x2="128" y2="113" stroke="{ACC2}" stroke-width="3"/>',
    _fig(cx=160, cy=143, armAngle=5),
    _arr(143, 113, 103, 113, ACC1),
    _arr(177, 113, 217, 113, ACC1),
    _lbl(232, 108, "HOLD 2s", ACC2, 10),
    f'<path d="M 160 88 Q 192 73 197 103" fill="none" stroke="{ACC4}" '
    'stroke-width="1.5" stroke-dasharray="3 2"/>',
    _lbl(205, 78, "resist", ACC4, 9),
    _lbl(160, 185, "Press out · hold 2s · resist rotation · 3×10 each", DIM, 9),
]))

DIAGRAMS["dead-bug"] = _svg(200, "".join([
    _lbl(160, 16, "DEAD BUG", ACC1, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="98" cy="123" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="98" y1="136" x2="198" y2="136" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="198" y1="136" x2="198" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="118" y1="128" x2="118" y2="93" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="178" y1="128" x2="178" y2="93" stroke="{FIG}" stroke-width="2"/>',
    _arr(118, 93, 83, 66, ACC2),
    f'<line x1="198" y1="136" x2="233" y2="153" stroke="{ACC2}" stroke-width="2"/>',
    _arr(233, 153, 263, 163, ACC2),
    f'<line x1="98" y1="168" x2="198" y2="168" stroke="{ACC1}" stroke-width="2"/>',
    _lbl(148, 183, "BACK FLAT TO FLOOR — always", ACC4, 9),
]))

DIAGRAMS["face-pull"] = _svg(200, "".join([
    _lbl(160, 16, "BAND FACE PULL", ACC1, 11),
    f'<rect x="265" y="83" width="10" height="50" fill="{DIM}" rx="2"/>',
    f'<line x1="183" y1="110" x2="268" y2="110" stroke="{ACC2}" stroke-width="3"/>',
    _fig(cx=148, cy=143, armAngle=-5),
    _arr(128, 106, 98, 106, ACC1),
    f'<line x1="126" y1="106" x2="106" y2="88" stroke="{ACC2}" '
    'stroke-width="1.5" stroke-dasharray="3 2"/>',
    f'<line x1="170" y1="106" x2="190" y2="88" stroke="{ACC2}" '
    'stroke-width="1.5" stroke-dasharray="3 2"/>',
    _lbl(160, 78, "ELBOWS HIGH", ACC2, 10),
    _lbl(160, 185, "Pull to face · elbows out · squeeze · 3×15", DIM, 9),
]))

DIAGRAMS["band-rdl"] = _svg(200, "".join([
    _lbl(160, 16, "BAND RDL — MINIMAL HINGE", ACC1, 11),
    f'<circle cx="180" cy="70" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="180" y1="83" x2="160" y2="118" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="160" y1="118" x2="148" y2="163" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="160" y1="118" x2="172" y2="163" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="172" y1="93" x2="148" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="188" y1="93" x2="172" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="128" y1="163" x2="190" y2="163" stroke="{ACC2}" stroke-width="3"/>',
    f'<path d="M 160 118 Q 195 98 190 78" fill="none" stroke="{ACC4}" '
    'stroke-width="1.5" stroke-dasharray="3 2"/>',
    _lbl(207, 93, "30–40°", ACC4, 10),
    _lbl(207, 105, "MAX", ACC4, 10),
    _lbl(160, 185, "Hinge 30–40° only · back flat · 3×10", DIM, 9),
]))

DIAGRAMS["band-ohp"] = _svg(200, "".join([
    _lbl(160, 16, "SEATED BAND OVERHEAD PRESS", ACC1, 11),
    f'<rect x="123" y="138" width="74" height="10" rx="2" fill="{DIM}"/>',
    f'<line x1="130" y1="148" x2="130" y2="173" stroke="{DIM}" stroke-width="3"/>',
    f'<line x1="190" y1="148" x2="190" y2="173" stroke="{DIM}" stroke-width="3"/>',
    f'<circle cx="160" cy="88" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="160" y1="101" x2="160" y2="138" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="160" y1="138" x2="143" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="160" y1="138" x2="177" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="148" y1="113" x2="130" y2="78" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="172" y1="113" x2="190" y2="78" stroke="{FIG}" stroke-width="2"/>',
    _arr(130, 78, 130, 53, ACC2),
    _arr(190, 78, 190, 53, ACC2),
    f'<line x1="128" y1="163" x2="192" y2="163" stroke="{ACC2}" stroke-width="3"/>',
    _lbl(160, 185, "Sit tall · press overhead · 3×10", DIM, 9),
]))

DIAGRAMS["band-curl"] = _svg(200, "".join([
    _lbl(160, 16, "BAND BICEP CURL", ACC1, 11),
    _fig(cx=160, cy=148),
    f'<line x1="128" y1="168" x2="192" y2="168" stroke="{ACC2}" stroke-width="3"/>',
    f'<line x1="148" y1="120" x2="138" y2="98" stroke="{ACC2}" stroke-width="2"/>',
    _arr(138, 110, 138, 90, ACC1),
    _lbl(116, 88, "CURL ↑", ACC1, 10),
    _lbl(163, 108, "ELBOWS PINNED", DIM, 9),
    _lbl(160, 185, "2s hold · 3s lower · 3×12", DIM, 9),
]))

DIAGRAMS["band-tricep"] = _svg(200, "".join([
    _lbl(160, 16, "BAND TRICEP PUSHDOWN", ACC1, 11),
    f'<rect x="140" y="22" width="40" height="7" rx="2" fill="{DIM}"/>',
    f'<line x1="160" y1="29" x2="160" y2="78" stroke="{ACC2}" stroke-width="3"/>',
    _fig(cx=160, cy=148),
    f'<line x1="148" y1="120" x2="148" y2="146" stroke="{ACC2}" stroke-width="2"/>',
    f'<line x1="172" y1="120" x2="172" y2="146" stroke="{ACC2}" stroke-width="2"/>',
    _arr(148, 128, 148, 148, ACC1),
    _arr(172, 128, 172, 148, ACC1),
    _lbl(103, 133, "ELBOWS PINNED", DIM, 9),
    _lbl(160, 185, "Press down · squeeze · 3×12", DIM, 9),
]))

DIAGRAMS["incline-pushup"] = _svg(200, "".join([
    _lbl(160, 16, "INCLINE PUSH-UP", ACC1, 11),
    f'<rect x="38" y="98" width="104" height="12" rx="4" fill="{DIM}"/>',
    f'<line x1="48" y1="110" x2="28" y2="143" stroke="{DIM}" stroke-width="3"/>',
    f'<line x1="132" y1="110" x2="132" y2="143" stroke="{DIM}" stroke-width="3"/>',
    f'<circle cx="83" cy="74" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="83" y1="86" x2="200" y2="146" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="83" y1="90" x2="68" y2="104" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="83" y1="90" x2="98" y2="104" stroke="{FIG}" stroke-width="2"/>',
    _arr(83, 88, 83, 106, ACC4),
    _arr(83, 106, 83, 88, ACC2),
    _lbl(232, 141, "BODY STRAIGHT", DIM, 9),
    _lbl(160, 180, "Higher surface = easier on lower back", DIM, 9),
    _lbl(160, 192, "3×8–12 · 60s rest", ACC1, 9),
]))

DIAGRAMS["pike-pushup"] = _svg(198, "".join([
    _lbl(160, 16, "PIKE PUSH-UP", ACC1, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<line x1="78" y1="168" x2="160" y2="88" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="242" y1="168" x2="160" y2="88" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="160" cy="88" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    _arr(160, 100, 160, 126, ACC1),
    _lbl(185, 123, "HEAD ↓", ACC1, 10),
    _lbl(160, 78, "HIPS HIGH", ACC2, 10),
    _lbl(160, 184, "Hips stay UP throughout · 3×8", DIM, 9),
]))

DIAGRAMS["diamond-pushup"] = _svg(200, "".join([
    _lbl(160, 16, "DIAMOND PUSH-UP", ACC1, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="108" cy="83" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="108" y1="95" x2="200" y2="158" stroke="{FIG}" stroke-width="2"/>',
    f'<polygon points="158,138 168,146 178,138 168,130" fill="none" '
    f'stroke="{ACC2}" stroke-width="2"/>',
    _lbl(168, 118, "◇ HANDS", ACC2, 10),
    _arr(108, 93, 148, 123, ACC1),
    _lbl(83, 148, "TRICEPS", ACC1, 10),
    _lbl(160, 185, "Diamond hands · knees OK to start · 3×6–10", DIM, 9),
]))

DIAGRAMS["plank"] = _svg(190, "".join([
    _lbl(160, 16, "FOREARM PLANK", ACC1, 11),
    f'<line x1="20" y1="153" x2="300" y2="153" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="88" cy="108" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="88" y1="120" x2="230" y2="138" stroke="{FIG}" stroke-width="3"/>',
    f'<line x1="93" y1="123" x2="93" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="113" y1="125" x2="113" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="228" y1="138" x2="235" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="86" y1="120" x2="230" y2="138" stroke="{ACC2}" '
    'stroke-width="1" stroke-dasharray="4 3"/>',
    _lbl(160, 103, "STRAIGHT LINE", ACC2, 10),
    f'<path d="M 88 138 Q 160 163 230 146" fill="none" stroke="{ACC4}" '
    'stroke-width="1.5" stroke-dasharray="3 2"/>',
    _lbl(160, 175, "⚠ STOP if hips sag — disc risk", ACC4, 9),
    _lbl(160, 187, "Start 20s · add 5s/week · 3 sets", ACC1, 9),
]))

DIAGRAMS["australian-pullup"] = _svg(200, "".join([
    _lbl(160, 16, "AUSTRALIAN PULL-UP (TABLE ROW)", ACC1, 11),
    f'<rect x="58" y="68" width="204" height="12" rx="3" fill="{DIM}"/>',
    f'<line x1="78" y1="80" x2="78" y2="113" stroke="{DIM}" stroke-width="4"/>',
    f'<line x1="242" y1="80" x2="242" y2="113" stroke="{DIM}" stroke-width="4"/>',
    f'<line x1="20" y1="163" x2="300" y2="163" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="88" cy="128" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="88" y1="140" x2="228" y2="150" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="228" y1="150" x2="233" y2="163" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="90" y1="128" x2="98" y2="80" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="108" y1="130" x2="118" y2="80" stroke="{FIG}" stroke-width="2"/>',
    _arr(98, 118, 98, 83, ACC1),
    _lbl(160, 43, "GRIP TABLE EDGE", ACC2, 10),
    _lbl(160, 185, "Pull chest to table · squeeze blades · 3×8–12", DIM, 9),
]))

DIAGRAMS["bw-squat"] = _svg(200, "".join([
    _lbl(160, 16, "BODYWEIGHT SQUAT", ACC1, 11),
    f'<line x1="50" y1="146" x2="270" y2="146" stroke="{DIM}" '
    'stroke-width="1" stroke-dasharray="4 3"/>',
    _lbl(44, 150, "70%", ACC4, 9, "end"),
    _fig(cx=160, cy=138, legBend=20, armAngle=-22),
    _arr(160, 153, 160, 173, ACC4),
    _arr(160, 173, 160, 153, ACC2),
    _lbl(222, 168, "DRIVE UP thru heels", ACC2, 9),
    _lbl(160, 190, "Chest tall · 1s pause · 3×15", DIM, 9),
]))

DIAGRAMS["reverse-lunge"] = _svg(200, "".join([
    _lbl(160, 16, "REVERSE LUNGE", ACC1, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="148" cy="73" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="148" y1="86" x2="148" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="148" y1="128" x2="138" y2="153" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="138" y1="153" x2="133" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="148" y1="128" x2="193" y2="146" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="193" y1="146" x2="193" y2="168" stroke="{FIG}" stroke-width="2"/>',
    _arr(148, 133, 183, 143, ACC1, dashed=True),
    _lbl(216, 145, "STEP BACK", ACC1, 9),
    _lbl(160, 184, "Step back · knee near floor · 3×10 each", DIM, 9),
]))

DIAGRAMS["glute-bridge-single"] = _svg(195, "".join([
    _lbl(160, 16, "SINGLE-LEG GLUTE BRIDGE", ACC1, 11),
    f'<line x1="20" y1="160" x2="300" y2="160" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="78" cy="120" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="78" y1="132" x2="183" y2="132" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="183" y1="98" x2="183" y2="132" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="183" y1="98" x2="198" y2="138" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="198" y1="138" x2="203" y2="160" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="183" y1="132" x2="238" y2="116" stroke="{ACC2}" stroke-width="2"/>',
    f'<line x1="238" y1="116" x2="266" y2="116" stroke="{ACC2}" stroke-width="2"/>',
    _lbl(268, 111, "EXTENDED", ACC2, 9, "start"),
    _arr(183, 118, 183, 96, ACC1),
    _lbl(160, 178, "Drive up · extend one leg · 3×10 each", DIM, 9),
]))

DIAGRAMS["box-breathing"] = _svg(210, "".join([
    _lbl(160, 16, "BOX BREATHING  4-4-4-4", ACC1, 11),
    f'<rect x="73" y="33" width="114" height="114" rx="6" fill="none" '
    f'stroke="{ACC1}" stroke-width="1.5" stroke-dasharray="5 3"/>',
    _arr(130, 33, 73, 33, ACC2),
    _lbl(115, 28, "INHALE 4s", ACC2, 10),
    _arr(187, 73, 187, 33, ACC3),
    _lbl(202, 60, "HOLD 4s", ACC3, 9, "start"),
    _arr(130, 147, 187, 147, ACC3),
    _lbl(115, 160, "EXHALE 4s", ACC3, 10),
    _arr(73, 107, 73, 147, ACC1),
    _lbl(60, 124, "HOLD 4s", ACC1, 9, "end"),
    _lbl(160, 177, "Repeat 4–6 cycles · end of every session", DIM, 9),
    _lbl(160, 190, "Lowers cortisol · used by Navy SEALs", ACC2, 9),
]))

DIAGRAMS["arm-swings"] = _svg(195, "".join([
    _lbl(160, 16, "ARM CIRCLES + SHOULDER ROLLS", ACC1, 11),
    _fig(cx=160, cy=138, armAngle=0),
    f'<path d="M 128 108 A 35 35 0 1 1 128 108.1" fill="none" stroke="{ACC1}" '
    'stroke-width="1.5" stroke-dasharray="4 3"/>',
    f'<path d="M 192 108 A 35 35 0 1 0 192 108.1" fill="none" stroke="{ACC1}" '
    'stroke-width="1.5" stroke-dasharray="4 3"/>',
    _arr(128, 73, 128, 76, ACC1),
    _arr(192, 76, 192, 73, ACC1),
    _lbl(160, 180, "Full circles · forward then backward · 10 each", DIM, 9),
]))

DIAGRAMS["leg-swings"] = _svg(200, "".join([
    _lbl(160, 16, "LEG SWINGS", ACC1, 11),
    f'<rect x="36" y="28" width="10" height="157" fill="{DIM}" rx="2"/>',
    f'<circle cx="93" cy="68" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="93" y1="81" x2="93" y2="128" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="93" y1="98" x2="46" y2="98" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="46" cy="98" r="4" fill="{ACC1}"/>',
    f'<line x1="93" y1="128" x2="86" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<path d="M 93 128 Q 128 146 143 168" fill="none" stroke="{ACC2}" '
    'stroke-width="2" stroke-dasharray="4 2"/>',
    f'<path d="M 93 128 Q 63 146 50 166" fill="none" stroke="{ACC3}" '
    'stroke-width="2" stroke-dasharray="4 2"/>',
    f'<line x1="93" y1="128" x2="138" y2="160" stroke="{ACC2}" stroke-width="2"/>',
    _arr(123, 156, 140, 161, ACC2),
    _lbl(153, 160, "FORWARD", ACC2, 9),
    _lbl(40, 173, "BACK", ACC3, 9, "end"),
    _lbl(160, 192, "10 swings each direction per leg", DIM, 9),
]))

DIAGRAMS["mckenzie"] = _svg(200, "".join([
    _lbl(160, 16, "McKENZIE PRESS-UP", ACC4, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="90" cy="138" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="90" y1="150" x2="230" y2="155" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="230" y1="155" x2="240" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="100" y1="145" x2="105" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="130" y1="147" x2="135" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<circle cx="90" cy="108" r="12" fill="none" stroke="{ACC2}" '
    'stroke-width="2" stroke-dasharray="3 2"/>',
    _arr(90, 138, 90, 110, ACC2),
    _lbl(60, 105, "PRESS UP", ACC2, 10),
    _lbl(195, 148, "HIPS STAY", DIM, 9),
    _lbl(195, 158, "ON FLOOR", DIM, 9),
    _lbl(160, 182, "#1 exercise for L4/L5 and L5/S1 flare", ACC2, 9),
    _lbl(160, 195, "10 reps · hold 2s at top", ACC1, 9),
]))

DIAGRAMS["knee-hug"] = _svg(195, "".join([
    _lbl(160, 16, "SUPINE KNEE HUG", ACC4, 11),
    f'<line x1="20" y1="165" x2="300" y2="165" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="85" cy="125" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="85" y1="138" x2="180" y2="148" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="180" y1="148" x2="185" y2="165" stroke="{FIG}" stroke-width="2"/>',
    f'<path d="M 100 130 Q 155 100 165 130" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<path d="M 100 138 Q 155 120 165 138" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<ellipse cx="155" cy="128" rx="20" ry="15" fill="none" stroke="{ACC2}" stroke-width="2"/>',
    _lbl(155, 128, "KNEES", ACC2, 9),
    _arr(185, 145, 165, 132, ACC2),
    _lbl(160, 180, "Pull knees gently to chest · breathe · hold 30s", DIM, 9),
    _lbl(160, 192, "Decompresses L4/L5 and L5/S1", ACC2, 9),
]))

DIAGRAMS["walking"] = _svg(190, "".join([
    _lbl(160, 16, "GENTLE WALKING", ACC4, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    _fig(cx=100, cy=138, armAngle=-20, legBend=8),
    _fig(cx=210, cy=138, armAngle=20, legBend=-8, color="#4b5563"),
    _arr(130, 128, 178, 128, ACC2),
    _lbl(160, 118, "UPRIGHT POSTURE", ACC2, 10),
    _lbl(160, 182, "Flat surface · 10–20 min · stop if pain increases", DIM, 9),
]))

DIAGRAMS["pelvic-tilt"] = _svg(195, "".join([
    _lbl(160, 16, "GLUTE BRIDGE — SMALL RANGE", ACC4, 11),
    f'<line x1="20" y1="162" x2="300" y2="162" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="80" cy="128" r="12" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="80" y1="140" x2="175" y2="142" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="175" y1="118" x2="175" y2="142" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="175" y1="118" x2="200" y2="148" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="200" y1="148" x2="204" y2="162" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="175" y1="142" x2="152" y2="162" stroke="{FIG}" stroke-width="2"/>',
    _arr(175, 135, 175, 116, ACC2),
    _lbl(215, 112, "SMALL RANGE", ACC2, 9),
    _lbl(215, 122, "50% only", DIM, 9),
    _lbl(160, 178, "Small hip lift · squeeze glutes · 2s hold", DIM, 9),
    _lbl(160, 190, "No band · 3×12", ACC1, 9),
]))

DIAGRAMS["dead-bug-arms"] = _svg(200, "".join([
    _lbl(160, 16, "DEAD BUG — ARMS ONLY (FLARE MOD)", ACC4, 11),
    f'<line x1="20" y1="168" x2="300" y2="168" stroke="{DIM}" stroke-width="2"/>',
    f'<circle cx="98" cy="123" r="13" fill="none" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="98" y1="136" x2="198" y2="148" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="198" y1="148" x2="215" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="175" y1="140" x2="152" y2="168" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="118" y1="128" x2="118" y2="93" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="178" y1="128" x2="178" y2="93" stroke="{FIG}" stroke-width="2"/>',
    _arr(118, 93, 83, 66, ACC2),
    f'<line x1="98" y1="136" x2="75" y2="162" stroke="{FIG}" stroke-width="2"/>',
    f'<line x1="98" y1="136" x2="120" y2="162" stroke="{FIG}" stroke-width="2"/>',
    _lbl(240, 155, "LEGS STAY BENT", ACC4, 9),
    f'<line x1="98" y1="168" x2="198" y2="168" stroke="{ACC1}" stroke-width="2"/>',
    _lbl(148, 183, "BACK FLAT — arms only during flare", ACC4, 9),
]))
