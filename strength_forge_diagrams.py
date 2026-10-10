"""Strength Forge — exercise SVG diagrams.

Pure-Python, stdlib only. Exposes ``DIAGRAMS``: a dict mapping exercise-id to a
complete, fully-static ``<svg ...>...</svg>`` markup string. All values are
hardcoded — there is no user input.

#282 ported 30 diagrams verbatim from the prototype's ``diagrams.jsx``. #407
redrew them for readability (``docs/design/407-sf-diagram-readability.md``):

* One figure kit, ``_person()``: a body built from a hip point, a torso angle,
  and hand / foot targets (two-bone IK places elbows and knees), drawn with
  thick round strokes and the far-side limbs in a dimmer tone.
* ``ghost=True`` draws the START position faded and dashed under the solid
  FINISH position, so a curl or a press shows its motion.
* A fixed colour key: band = green only, motion arrow = gold, form cue = blue,
  caution = red, captions = warm grey. Every text colour clears 4.5:1 on BG.
* Layout: title on top, figure in the middle, captions in a reserved band at
  the bottom. ``tests/test_strength_forge_diagram_geometry.py`` enforces
  contrast, size, bounds, and that no stroke ever crosses a label.

Angles are SVG degrees: 0 = right, 90 = down, 180 = left, -90 = up.
"""

import math

# ── Colour key (#407) ──
BG = "#131110"      # diagram background (slate-0)
FIG = "#e8eaf0"     # body (near side)
FAR = "#8b93a1"     # body (far side) — depth in side views
PROP = "#4b5563"    # floor, door frames, benches (shapes only, never text)
BAND = "#52c07a"    # resistance band — the ONLY use of green
MOVE = "#c8a84b"    # motion arrows
TITLE = "#c8a84b"   # diagram title
CUE = "#7fb2ff"     # form cues ("SIT TALL", "ELBOWS PINNED")
WARN = "#ff7a7a"    # cautions + flare-protocol titles
CAP = "#b5ada0"     # captions
LEGEND = "#9aa3b2"  # the "faded = start" legend line

STROKE = 3.5
THIGH, SHIN = 32, 32
TORSO = 46
HEAD_R = 11
UARM, FARM = 25, 23
SHOULDER_DROP = 6   # shoulder sits this far down the torso from the neck

H = 220             # standard diagram height
H_GHOST = 235       # + one line for the start/finish legend
LEGEND_TEXT = "faded = start · solid = finish"


def _n(value):
    """Format a number: round to 2 decimals and drop trailing zeros."""
    r = round(float(value), 2)
    if r == int(r):
        return str(int(r))
    return f"{r:.2f}".rstrip("0").rstrip(".")


def _esc(text):
    """Escape XML special chars in label text (unicode glyphs kept as-is)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── vector helpers ──
def _go(p, length, ang):
    a = math.radians(ang)
    return (p[0] + length * math.cos(a), p[1] + length * math.sin(a))


def _ang(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def _ik(a, target, l1, l2, bend):
    """Two-bone IK: the middle joint for a limb rooted at ``a`` reaching for
    ``target``. ``bend`` (+1 / -1) picks which side the joint folds to. An
    out-of-reach target leaves the limb fully extended toward it."""
    d = math.dist(a, target)
    base = _ang(a, target)
    if d >= l1 + l2 - 0.01:
        mid = _go(a, l1, base)
        return mid, _go(mid, l2, base)
    d = max(d, abs(l1 - l2) + 0.01)
    alpha = math.degrees(math.acos((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    return _go(a, l1, base + bend * alpha), target


# ── SVG primitives ──
def _svg(h, body):
    return (
        f'<svg viewBox="0 0 320 {h}" '
        f'style="width:100%;background:{BG};display:block" '
        f'xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )


def _t(x, y, text, color=CUE, size=11, anchor="middle"):
    return (
        f'<text x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}" '
        f'fill="{color}" font-size="{_n(size)}" '
        f'font-family="monospace">{_esc(text)}</text>'
    )


def _title(text, color=TITLE):
    return _t(160, 20, text, color, 13)


def _caps(h, *lines):
    """Caption band at the bottom. Each line is text or (text, colour)."""
    out = []
    n = len(lines)
    for i, line in enumerate(lines):
        text, color = line if isinstance(line, tuple) else (line, CAP)
        out.append(_t(160, h - 8 - 15 * (n - 1 - i), text, color))
    return "".join(out)


def _poly(points, color, width=STROKE, dash=None):
    pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in points)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="{_n(width)}" stroke-linecap="round" '
        f'stroke-linejoin="round"{d}/>'
    )


def _line(p, q, color, width=STROKE, dash=None):
    return _poly([p, q], color, width, dash)


def _quad(p, c, q, color, width=STROKE, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="M {_n(p[0])} {_n(p[1])} Q {_n(c[0])} {_n(c[1])} '
        f'{_n(q[0])} {_n(q[1])}" fill="none" stroke="{color}" '
        f'stroke-width="{_n(width)}" stroke-linecap="round"{d}/>'
    )


def _rect(x, y, w, h, color=PROP):
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
        f'rx="2" fill="{color}"/>'
    )


def _floor(y, x1=14, x2=306):
    return _line((x1, y), (x2, y), PROP, 2.5)


def _band(*points):
    return _poly(points, BAND, 3)


def _arr(p, q, color=MOVE, width=2.5, dash=None):
    ang = _ang(p, q)
    head_base = _go(q, 9, ang + 180)
    left = _go(head_base, 5, ang - 90)
    right = _go(head_base, 5, ang + 90)
    pts = " ".join(f"{_n(x)},{_n(y)}" for x, y in (q, left, right))
    return (
        "<g>"
        + _line(p, head_base, color, width, dash)
        + f'<polygon points="{pts}" fill="{color}" stroke="{color}" stroke-width="1"/>'
        + "</g>"
    )


def _circle(c, r, color, width=2, dash=None, fill="none"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<circle cx="{_n(c[0])}" cy="{_n(c[1])}" r="{_n(r)}" fill="{fill}" '
        f'stroke="{color}" stroke-width="{_n(width)}"{d}/>'
    )


# ── the figure kit ──
def _person(hip, torso=-90, hands=(), feet=(), elbows=(1, 1), knees=(-1, -1),
            front=False, ghost=False, head_ang=None, spine_bow=0):
    """Draw a person; return ``(svg, joints)``.

    ``hip`` is the pelvis point, ``torso`` the angle from hip to neck.
    ``hands`` / ``feet`` are targets, or an explicit ``(mid, end)`` pair when
    IK can't produce the pose (e.g. a seated thigh seen end-on). Index 0 is
    the near limb and 1 the far limb, drawn dimmer (side view); with
    ``front=True`` they are left / right, both bright, with the shoulders
    and hips spread sideways. ``elbows`` / ``knees`` pick each limb's fold
    side. ``spine_bow`` curves the back (cat-cow); ``head_ang`` points the
    head off the torso line (a lifted / dropped head).
    """
    neck = _go(hip, TORSO, torso)
    head = _go(neck, HEAD_R, torso if head_ang is None else head_ang)
    shoulder = _go(neck, SHOULDER_DROP, torso + 180)
    if front:
        shoulders = [(shoulder[0] - 13, shoulder[1]), (shoulder[0] + 13, shoulder[1])]
        hips = [(hip[0] - 7, hip[1]), (hip[0] + 7, hip[1])]
    else:
        shoulders = [shoulder, shoulder]
        hips = [hip, hip]

    def place(root, target, l1, l2, bend):
        if isinstance(target[0], tuple):  # explicit (elbow|knee, hand|foot)
            return target
        return _ik(root, target, l1, l2, bend)

    def tone(i):
        if ghost:
            return FIG
        return FIG if (front or i == 0) else FAR

    dash = "6 4" if ghost else None
    joints = {"hip": hip, "neck": neck, "head": head, "shoulder": shoulder}
    far, near = [], []
    for i, target in enumerate(hands):
        el, hand = place(shoulders[i], target, UARM, FARM, elbows[i])
        joints[f"elbow{i}"], joints[f"hand{i}"] = el, hand
        (near if (front or i == 0) else far).append(
            _poly([shoulders[i], el, hand], tone(i), STROKE, dash))
    for i, target in enumerate(feet):
        kn, foot = place(hips[i], target, THIGH, SHIN, knees[i])
        joints[f"knee{i}"], joints[f"foot{i}"] = kn, foot
        (near if (front or i == 0) else far).append(
            _poly([hips[i], kn, foot], tone(i), STROKE, dash))

    if spine_bow:
        mid = ((hip[0] + neck[0]) / 2, (hip[1] + neck[1]) / 2)
        ctrl = _go(mid, spine_bow, torso + 90)
        spine = _quad(hip, ctrl, neck, FIG, STROKE, dash)
    else:
        spine = _line(hip, neck, FIG, STROKE, dash)
    if front:
        spine += _line(shoulders[0], shoulders[1], FIG, STROKE, dash)
    head_svg = _circle(head, HEAD_R, FIG, STROKE, dash, "none" if ghost else BG)
    body = "".join(far) + spine + head_svg + "".join(near)
    if ghost:
        body = f'<g opacity="0.4">{body}</g>'
    return body, joints


def _standing(x, ghost=False, hands=None, front=False, elbows=(1, 1), foot_y=176):
    """A person standing straight, feet at ``foot_y``."""
    hip = (x, foot_y - THIGH - SHIN)
    feet = [(x - 9, foot_y), (x + 9, foot_y)] if front else [(x + 1, foot_y), (x + 3, foot_y)]
    if hands is None:
        hands = [(x + 2, hip[1] + 8), (x + 4, hip[1] + 8)] if not front else \
            [(x - 18, hip[1] + 6), (x + 18, hip[1] + 6)]
    return _person(hip, -90, hands, feet, elbows=elbows, front=front, ghost=ghost)


def _diagram(title, h, parts, caps, ghost=False, title_color=TITLE):
    body = [_title(title, title_color)] + list(parts)
    lines = list(caps) + ([(LEGEND_TEXT, LEGEND)] if ghost else [])
    body.append(_caps(h, *lines))
    return _svg(h, "".join(body))


DIAGRAMS: dict[str, str] = {}


# ── warm-ups & mobility ──
def _cat_cow():
    parts = [_floor(166)]
    for hip_x, bow, head_ang, label, lx, arrow in (
        (122, -16, 215, "COW · inhale", 98, ((99, 92), (99, 108))),
        (272, 18, 140, "CAT · exhale", 248, ((249, 100), (249, 84))),
    ):
        hip = (hip_x, 126)
        neck = _go(hip, TORSO, 188)
        sh = _go(neck, SHOULDER_DROP, 8)
        body, _ = _person(
            hip, 188, hands=[(sh[0], 166), (sh[0] + 4, 166)],
            feet=[((hip_x, 158), (hip_x + 30, 166)), ((hip_x + 4, 158), (hip_x + 34, 166))],
            head_ang=head_ang, spine_bow=bow)
        parts += [body, _arr(*arrow), _t(lx, 184, label)]
    return _diagram("CAT-COW STRETCH", H, parts,
                    ["Alternate slowly · breathe with it", "10 slow reps · no rest"])


DIAGRAMS["cat-cow"] = _cat_cow()


def _band_pull_apart():
    body, j = _standing(160, front=True, hands=[(96, 74), (224, 74)], elbows=(1, -1))
    parts = [
        body,
        _quad(j["hand0"], (160, 88), j["hand1"], BAND, 3),
        _arr((128, 104), (90, 104)),
        _arr((192, 104), (230, 104)),
    ]
    return _diagram("BAND PULL-APART", H, parts,
                    ["Pull apart to a T · squeeze shoulder blades",
                     "15 reps · light band warm-up"])


DIAGRAMS["band-pull-apart"] = _band_pull_apart()


def _arm_swings():
    body, j = _standing(160, front=True, hands=[(104, 70), (216, 70)], elbows=(1, -1))
    parts = [
        _circle((104, 70), 16, MOVE, 2, "4 3"),
        _circle((216, 70), 16, MOVE, 2, "4 3"),
        _arr((96, 55), (106, 54)),
        _arr((224, 55), (214, 54)),
        body,
    ]
    return _diagram("ARM CIRCLES + SHOULDER ROLLS", H, parts,
                    ["Small circles forward, big circles back",
                     "Then shoulder rolls · 10 each direction"])


DIAGRAMS["arm-swings"] = _arm_swings()


def _leg_swings():
    ghost, _ = _person((110, 112), -90, hands=[(52, 96)],
                       feet=[(66, 166), (113, 176)], knees=(1, -1), ghost=True)
    body, _ = _person((110, 112), -90, hands=[(52, 96)],
                      feet=[(160, 160), (113, 176)], knees=(-1, -1))
    parts = [
        _rect(40, 40, 8, 136),
        _floor(176),
        ghost,
        _quad((70, 178), (110, 196), (156, 170), MOVE, 2, "4 3"),
        body,
    ]
    return _diagram("LEG SWINGS", H_GHOST, parts,
                    ["Swing forward and back, then side to side",
                     "Spine tall · 10 each direction per leg"], ghost=True)


DIAGRAMS["leg-swings"] = _leg_swings()


def _box_breathing():
    sq = [(110, 50), (210, 50), (210, 150), (110, 150), (110, 50)]
    parts = [
        _poly(sq, PROP, 2, "5 4"),
        _arr((120, 50), (200, 50), BAND),
        _arr((210, 60), (210, 140), CUE),
        _arr((200, 150), (120, 150), CUE),
        _arr((110, 140), (110, 60), MOVE),
        _t(160, 40, "INHALE 4s", BAND),
        _t(218, 104, "HOLD 4s", CUE, anchor="start"),
        _t(160, 168, "EXHALE 4s", CUE),
        _t(102, 104, "HOLD 4s", MOVE, anchor="end"),
    ]
    return _diagram("BOX BREATHING  4-4-4-4", H, parts,
                    ["Repeat 4–6 cycles · end of every session",
                     "Lowers cortisol · used by Navy SEALs"])


DIAGRAMS["box-breathing"] = _box_breathing()


# ── band work ──
def _band_squat():
    ghost, _ = _standing(165, ghost=True, hands=[(198, 42), (200, 44)], elbows=(-1, -1))
    body, j = _person((142, 139), -64, hands=[(190, 76), (192, 78)],
                      feet=[(165, 176), (168, 176)], elbows=(-1, -1))
    parts = [
        _rect(222, 28, 14, 8),
        _floor(176),
        _line((58, 139), (112, 139), WARN, 1.5, "4 3"),
        _t(54, 143, "70%", WARN, anchor="end"),
        ghost,
        _band((229, 36), j["hand0"]),
        body,
        _arr((128, 100), (108, 118)),
        _t(76, 96, "HIPS BACK"),
    ]
    return _diagram("BAND ASSISTED SQUAT", H_GHOST, parts,
                    ["60–70% depth only · spine neutral", "3×10 · 60s rest"], ghost=True)


DIAGRAMS["band-squat"] = _band_squat()


def _band_row():
    ghost, _ = _person((110, 164), -90, hands=[(156, 130), (158, 132)],
                       feet=[(178, 164), (180, 166)], ghost=True)
    body, j = _person((110, 164), -90, hands=[(124, 128), (126, 130)],
                      feet=[(178, 164), (180, 166)], elbows=(-1, -1))
    parts = [
        _floor(170),
        ghost,
        _band(j["hand0"], (184, 160)),
        body,
        _arr((166, 146), (132, 146)),
        _t(56, 104, "SIT TALL"),
    ]
    return _diagram("BAND SEATED ROW", H_GHOST, parts,
                    ["Elbows back · squeeze shoulder blades",
                     "Sit tall — never round forward · 3×12"], ghost=True)


DIAGRAMS["band-row"] = _band_row()


def _band_chest_press():
    ghost, _ = _standing(150, ghost=True, hands=[(170, 90), (172, 92)], elbows=(1, 1))
    body, j = _standing(150, hands=[(198, 88), (200, 90)])
    parts = [
        _rect(40, 56, 8, 120),
        _floor(176),
        ghost,
        _band((48, 92), j["hand0"]),
        body,
        _arr((176, 112), (214, 112)),
        _t(244, 92, "PRESS"),
    ]
    return _diagram("STANDING BAND CHEST PRESS", H_GHOST, parts,
                    ["Core braced · no lower-back arch",
                     "Standing removes spinal load · 3×12"], ghost=True)


DIAGRAMS["band-chest-press"] = _band_chest_press()


def _bridge(hip_up, single=False, ghost_hip=None):
    """Supine bridge, head to the left. Returns (ghost_svg, body_svg, joints)."""
    def one(hip, ghost):
        neck_target = (100, 160)
        torso = _ang(hip, neck_target)
        feet = [(186, 171), (190, 171)]
        knees = (-1, -1)
        if single:
            far_foot = feet[1]
            line_ang = _ang(neck_target, hip)
            feet = [_go(hip, THIGH + SHIN, line_ang + 8), far_foot]
            knees = (-1, -1)
        return _person(hip, torso, hands=[(150, 171), (154, 171)], feet=feet,
                       knees=knees, head_ang=180, ghost=ghost)
    g, _ = one(ghost_hip, True) if ghost_hip else ("", None)
    b, j = one(hip_up, False)
    return g, b, j


def _glute_bridge():
    g, b, _ = _bridge((145, 148), ghost_hip=(144, 165))
    parts = [_floor(172), g, b, _arr((214, 152), (214, 120)), _t(150, 100, "SQUEEZE GLUTES")]
    return _diagram("GLUTE BRIDGE", H_GHOST, parts,
                    ["Drive hips up · hold 1s · lower slowly",
                     "Straight line shoulders → knees · 3×15"], ghost=True)


DIAGRAMS["glute-bridge"] = _glute_bridge()


def _lateral_walk():
    body, j = _person((160, 122), -90, hands=[(146, 120), (174, 120)],
                      feet=[(138, 176), (182, 176)], knees=(1, -1), elbows=(1, -1),
                      front=True)
    parts = [
        _floor(176),
        body,
        _band((j["foot0"][0] + 2, 170), (j["foot1"][0] - 2, 170)),
        _arr((112, 150), (70, 150)),
        _arr((208, 150), (250, 150)),
    ]
    return _diagram("BAND LATERAL WALK", H, parts,
                    ["Stay low in a slight squat · toes forward",
                     "3×12 each way · keep the band tight"])


DIAGRAMS["lateral-walk"] = _lateral_walk()


def _pallof_press():
    # View from above: head circle, shoulder line, arms pressing forward (down).
    c = (190, 82)
    sh_l, sh_r = (164, 82), (216, 82)
    ghost = (
        '<g opacity="0.4">'
        + _poly([sh_l, (182, 104)], FIG, STROKE, "6 4")
        + _poly([sh_r, (198, 104)], FIG, STROKE, "6 4")
        + "</g>"
    )
    parts = [
        _t(160, 40, "view from above", CAP),
        _rect(30, 120, 14, 14),
        ghost,
        _band((44, 127), (190, 140)),
        _line(sh_l, sh_r, FIG),
        _poly([sh_l, (186, 140)], FIG),
        _poly([sh_r, (194, 140)], FIG),
        _circle(c, HEAD_R, FIG, STROKE, fill=BG),
        _quad((232, 64), (262, 96), (236, 128), WARN, 2, "4 3"),
        _arr((248, 112), (236, 128), WARN, 2),
        _t(262, 150, "RESIST", WARN),
        _t(262, 164, "THE TWIST", WARN),
    ]
    return _diagram("PALLOF PRESS (ANTI-ROTATION)", H_GHOST, parts,
                    ["Press out · hold 2s · don't let it turn you",
                     "3×10 each side"], ghost=True)


DIAGRAMS["pallof-press"] = _pallof_press()


def _dead_bug(arms_only=False):
    hip = (172, 164)
    floor = _floor(172)
    if arms_only:
        feet = [(206, 171), (210, 171)]
        knees = (-1, -1)
        g_feet = feet
    else:
        feet = [(238, 154), (206, 132)]
        knees = (-1, -1)
        g_feet = [(204, 130), (206, 132)]
    ghost, _ = _person(hip, 180, hands=[(128, 116), (132, 116)], feet=g_feet,
                       knees=knees, head_ang=180, ghost=True)
    body, _ = _person(hip, 180, hands=[(84, 136), (132, 116)], feet=feet,
                      knees=knees, head_ang=180)
    parts = [floor, _line((108, 172), (178, 172), MOVE, 3), ghost, body,
             _arr((112, 104), (88, 124))]
    if arms_only:
        return _diagram("DEAD BUG — ARMS ONLY (FLARE MOD)", H_GHOST, parts,
                        [("BACK FLAT — arms only during a flare", WARN),
                         "Legs stay bent · feet on the floor"],
                        ghost=True, title_color=WARN)
    parts.append(_arr((226, 138), (248, 150)))
    return _diagram("DEAD BUG", H_GHOST, parts,
                    [("BACK FLAT TO FLOOR — always", WARN),
                     "Opposite arm + leg · slow · 3×8 each side"], ghost=True)


DIAGRAMS["dead-bug"] = _dead_bug()


def _face_pull():
    ghost, _ = _standing(150, ghost=True, hands=[(196, 66), (198, 68)])
    body, j = _standing(150, hands=[((132, 58), (174, 56)), ((134, 60), (176, 58))])
    parts = [
        _rect(270, 40, 8, 136),
        _floor(176),
        ghost,
        _band(j["hand0"], (270, 60)),
        body,
        _arr((240, 44), (200, 44)),
        _t(92, 52, "ELBOWS HIGH"),
    ]
    return _diagram("BAND FACE PULL", H_GHOST, parts,
                    ["Pull to your face · elbows high and out",
                     "Squeeze shoulder blades · 3×15"], ghost=True)


DIAGRAMS["face-pull"] = _face_pull()


def _band_rdl():
    ghost, _ = _standing(150, ghost=True)
    body, j = _person((150, 112), -55, hands=[(178, 132), (180, 134)],
                      feet=[(151, 176), (153, 176)])
    parts = [
        _floor(176),
        _line((150, 112), (150, 52), PROP, 1.5, "3 3"),
        _quad((150, 70), (164, 66), (176, 76), WARN, 2),
        ghost,
        _band((136, 176), j["hand0"]),
        _band((166, 176), j["hand0"]),
        body,
        _t(236, 64, "30–40° MAX", WARN),
    ]
    return _diagram("BAND RDL — MINIMAL HINGE", H_GHOST, parts,
                    ["Hinge from the hips · back flat · 3×10",
                     ("Swap for Glute Bridge if disc pain", WARN)], ghost=True)


DIAGRAMS["band-rdl"] = _band_rdl()


def _band_ohp():
    hip = (160, 128)
    feet = [((144, 138), (144, 176)), ((176, 138), (176, 176))]
    ghost, _ = _person(hip, -90, hands=[(126, 64), (194, 64)], feet=feet,
                       elbows=(-1, 1), knees=(1, -1), front=True, ghost=True)
    body, j = _person(hip, -90, hands=[(136, 40), (184, 40)], feet=feet,
                      elbows=(-1, 1), knees=(1, -1), front=True)
    parts = [
        _rect(120, 132, 80, 8),
        _line((126, 140), (126, 176), PROP, 3),
        _line((194, 140), (194, 176), PROP, 3),
        _floor(176),
        ghost,
        _band((j["foot0"][0], 176), j["hand0"]),
        _band((j["foot1"][0], 176), j["hand1"]),
        body,
        _arr((104, 84), (104, 50)),
        _arr((216, 84), (216, 50)),
    ]
    return _diagram("SEATED BAND OVERHEAD PRESS", H_GHOST, parts,
                    ["Sit tall · press overhead · lower slowly",
                     "Seated = no lumbar arch · 3×10"], ghost=True)


DIAGRAMS["band-ohp"] = _band_ohp()


def _band_curl():
    elbow = (161, 97)
    ghost, _ = _standing(160, ghost=True, hands=[(elbow, (163, 120))] * 2)
    body, j = _standing(160, hands=[(elbow, (180, 84))] * 2)
    parts = [
        _floor(176),
        ghost,
        _band((196, 176), j["hand0"]),
        body,
        _arr((206, 120), (206, 84)),
        _t(84, 100, "ELBOWS PINNED"),
    ]
    return _diagram("BAND BICEP CURL", H_GHOST, parts,
                    ["Curl up · 2s hold · 3s lower",
                     "Elbows stay at your sides · 3×12"], ghost=True)


DIAGRAMS["band-curl"] = _band_curl()


def _band_tricep():
    elbow = (161, 97)
    ghost, _ = _standing(160, ghost=True, hands=[(elbow, (182, 86))] * 2)
    body, j = _standing(160, hands=[(elbow, (166, 120))] * 2)
    parts = [
        _rect(196, 26, 26, 8),
        _floor(176),
        ghost,
        _band((209, 34), j["hand0"]),
        body,
        _arr((236, 80), (236, 118)),
        _t(84, 100, "ELBOWS PINNED"),
    ]
    return _diagram("BAND TRICEP PUSHDOWN", H_GHOST, parts,
                    ["Push down · squeeze at the bottom",
                     "Elbows stay pinned · 3×12"], ghost=True)


DIAGRAMS["band-tricep"] = _band_tricep()


# ── bodyweight ──
def _plank_line(foot, theta, legs_len=THIGH + SHIN):
    """Hip + torso angle for a body held in one straight line from ``foot``."""
    return _go(foot, legs_len, theta), theta


def _incline_pushup():
    foot = (236, 175)
    hand = (140, 158)
    g_hip, g_t = _plank_line(foot, -148)
    hip, t = _plank_line(foot, -158)
    ghost, _ = _person(g_hip, g_t, hands=[hand, (142, 158)], feet=[foot, (238, 175)],
                       elbows=(1, 1), ghost=True)
    body, _ = _person(hip, t, hands=[hand, (142, 158)], feet=[foot, (238, 175)],
                      elbows=(1, 1))
    parts = [
        _rect(70, 158, 90, 7),
        _line((78, 165), (78, 176), PROP, 3),
        _line((152, 165), (152, 176), PROP, 3),
        _floor(176),
        ghost,
        body,
        _arr((96, 104), (96, 128)),
        _t(236, 122, "BODY STRAIGHT"),
    ]
    return _diagram("INCLINE PUSH-UP", H_GHOST, parts,
                    ["Higher surface = easier on the lower back",
                     "Elbows ~45° · 3×8–12 · 60s rest"], ghost=True)


DIAGRAMS["incline-pushup"] = _incline_pushup()


def _pike_pushup():
    hand = (112, 174)
    ghost, _ = _person((168, 112), 125, hands=[hand, (116, 174)],
                       feet=[(196, 172), (200, 172)], elbows=(-1, -1), knees=(1, 1),
                       ghost=True)
    body, _ = _person((160, 118), 135, hands=[hand, (116, 174)],
                      feet=[(196, 172), (200, 172)], elbows=(-1, -1), knees=(1, 1))
    parts = [
        _floor(176),
        ghost,
        body,
        _arr((84, 116), (96, 146)),
        _t(204, 84, "HIPS HIGH"),
    ]
    return _diagram("PIKE PUSH-UP", H_GHOST, parts,
                    ["Hips stay UP the whole time",
                     "Lower your head toward the floor · 3×8"], ghost=True)


DIAGRAMS["pike-pushup"] = _pike_pushup()


def _diamond_pushup():
    knee = (190, 174)
    hand = (130, 174)

    def at(theta, ghost):
        hip = _go(knee, THIGH, theta)
        foot = (224, 160)
        return _person(hip, theta, hands=[hand, (132, 174)],
                       feet=[foot, (226, 160)], elbows=(1, 1), knees=(-1, -1),
                       ghost=ghost)
    ghost, _ = at(-141, True)
    body, _ = at(-163, False)
    parts = [_floor(176), ghost, body, _arr((92, 112), (92, 140)),
             _t(252, 120, "TRICEPS")]
    return _diagram("DIAMOND PUSH-UP", H_GHOST, parts,
                    ["Hands in a diamond under your chest",
                     "Knees down to start · 3×6–10"], ghost=True)


DIAGRAMS["diamond-pushup"] = _diamond_pushup()


def _plank():
    foot = (232, 170)
    shoulder = (112, 148)
    theta = _ang(foot, shoulder)
    hip = _go(foot, THIGH + SHIN, theta)
    body, _ = _person(hip, theta, hands=[(88, 172), (92, 172)],
                      feet=[foot, (236, 170)], elbows=(1, 1))
    parts = [
        _floor(172),
        _quad((128, 166), (176, 186), (220, 170), WARN, 2, "4 3"),
        body,
        _t(176, 124, "STRAIGHT LINE"),
    ]
    return _diagram("FOREARM PLANK", H, parts,
                    [("⚠ STOP if hips sag — disc risk", WARN),
                     "Start 20s · add 5s/week · 3 sets"])


DIAGRAMS["plank"] = _plank()


def _australian_pullup():
    heel = (214, 174)
    grip = (120, 80)

    def at(alpha, ghost):
        shoulder = (heel[0] - 116 * math.cos(math.radians(alpha)),
                    heel[1] - 116 * math.sin(math.radians(alpha)))
        theta = _ang(heel, shoulder)
        hip = _go(heel, THIGH + SHIN, theta)
        return _person(hip, theta, hands=[grip, (124, 80)], feet=[heel, (218, 174)],
                       elbows=(-1, -1), ghost=ghost)
    ghost, _ = at(25.5, True)
    body, _ = at(36, False)
    parts = [
        _rect(30, 72, 170, 8),
        _line((40, 80), (40, 176), PROP, 4),
        _floor(176),
        ghost,
        body,
        _t(115, 60, "GRIP TABLE EDGE"),
    ]
    return _diagram("AUSTRALIAN PULL-UP (TABLE ROW)", H_GHOST, parts,
                    ["Pull chest to the table · squeeze blades",
                     "Body straight · 3×8–12"], ghost=True)


DIAGRAMS["australian-pullup"] = _australian_pullup()


def _bw_squat():
    ghost, _ = _standing(165, ghost=True, hands=[(196, 78), (198, 80)])
    body, _ = _person((142, 139), -64, hands=[(196, 108), (198, 110)],
                      feet=[(165, 176), (168, 176)])
    parts = [
        _floor(176),
        _line((58, 139), (112, 139), WARN, 1.5, "4 3"),
        _t(54, 143, "70%", WARN, anchor="end"),
        ghost,
        body,
        _arr((236, 148), (236, 112)),
        _t(268, 166, "DRIVE UP", anchor="middle"),
    ]
    return _diagram("BODYWEIGHT SQUAT", H_GHOST, parts,
                    ["Chest tall · weight in heels · 70% depth",
                     "1s pause at the bottom · 3×15"], ghost=True)


DIAGRAMS["bw-squat"] = _bw_squat()


def _reverse_lunge():
    ghost, _ = _standing(150, ghost=True)
    body, _ = _person((130, 140), -90, hands=[(132, 146), (134, 146)],
                      feet=[(162, 176), (82, 176)], knees=(-1, 1))
    parts = [
        _floor(176),
        ghost,
        body,
        _arr((110, 124), (72, 124)),
        _t(60, 108, "STEP BACK"),
    ]
    return _diagram("REVERSE LUNGE", H_GHOST, parts,
                    ["Step back · back knee toward the floor",
                     "Front shin vertical · 3×10 each leg"], ghost=True)


DIAGRAMS["reverse-lunge"] = _reverse_lunge()


def _glute_bridge_single():
    g, b, _ = _bridge((140, 136), single=True, ghost_hip=(144, 165))
    parts = [_floor(172), g, b, _arr((120, 116), (120, 92)), _t(150, 66, "LEG STRAIGHT")]
    return _diagram("SINGLE-LEG GLUTE BRIDGE", H_GHOST, parts,
                    ["Drive up through the planted foot",
                     "Hold 1s · 3×10 each leg"], ghost=True)


DIAGRAMS["glute-bridge-single"] = _glute_bridge_single()


# ── flare-up protocol (titles in red, as in the flare tab) ──
def _mckenzie():
    hip = (172, 166)
    feet = [(234, 168), (238, 168)]
    ghost, _ = _person(hip, 180, hands=[(126, 170), (130, 170)], feet=feet,
                       elbows=(1, 1), head_ang=180, ghost=True)
    body, _ = _person(hip, -148, hands=[(132, 170), (136, 170)], feet=feet,
                      elbows=(1, 1))
    parts = [
        _floor(172),
        ghost,
        body,
        _arr((84, 160), (84, 128)),
        _t(214, 132, "HIPS STAY DOWN"),
    ]
    return _diagram("McKENZIE PRESS-UP", H_GHOST, parts,
                    ["#1 move for an L4/L5 · L5/S1 flare",
                     "10 reps · hold 2s at the top"], ghost=True, title_color=WARN)


DIAGRAMS["mckenzie"] = _mckenzie()


def _knee_hug():
    hip = (164, 164)
    body, j = _person(hip, 180, hands=[(150, 134), (154, 134)],
                      feet=[((148, 136), (174, 118)), ((152, 136), (178, 118))],
                      elbows=(-1, -1), head_ang=180)
    parts = [
        _floor(172),
        body,
        _arr((214, 112), (184, 124)),
        _t(240, 96, "KNEES TO CHEST"),
    ]
    return _diagram("SUPINE KNEE HUG", H, parts,
                    ["Pull gently · breathe · hold 30s",
                     "Decompresses L4/L5 and L5/S1"], title_color=WARN)


DIAGRAMS["knee-hug"] = _knee_hug()


def _walking():
    body, _ = _person((140, 114), -88, hands=[(160, 132), (124, 128)],
                      feet=[(162, 176), (116, 176)], elbows=(1, 1), knees=(-1, -1))
    parts = [
        _floor(176),
        body,
        _arr((196, 132), (250, 132)),
        _t(236, 108, "UPRIGHT POSTURE"),
    ]
    return _diagram("GENTLE WALKING", H, parts,
                    ["Flat ground · 10–20 min · relaxed pace",
                     ("Stop if pain increases", WARN)], title_color=WARN)


DIAGRAMS["walking"] = _walking()


def _pelvic_tilt():
    g, b, _ = _bridge((142, 152), ghost_hip=(144, 165))
    parts = [_floor(172), g, b, _arr((214, 160), (214, 140)), _t(150, 104, "SMALL RANGE")]
    return _diagram("GLUTE BRIDGE — SMALL RANGE", H_GHOST, parts,
                    ["Lift only ~50% · squeeze glutes 2s",
                     "No band · 3×12"], ghost=True, title_color=WARN)


DIAGRAMS["pelvic-tilt"] = _pelvic_tilt()

DIAGRAMS["dead-bug-arms"] = _dead_bug(arms_only=True)
