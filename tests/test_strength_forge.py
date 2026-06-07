"""#282 Strength Forge — diagram-module contract guards.

The 30 inline SVG exercise diagrams are server-rendered from
``strength_forge_diagrams.DIAGRAMS`` (Phase A.1). These tests pin the
contract so a future edit can't silently drop a diagram or emit
malformed SVG — the diagrams are clinically-paired with exercises, so a
missing one means an exercise modal renders without its illustration.
"""
import strength_forge_diagrams as sfd

# Diagram ids referenced by the flare-up protocol (strength_forge_data.js
# flarePhases[*].exercises[*].diagramId). Each MUST have a diagram.
FLARE_DIAGRAM_IDS = {
    "mckenzie", "knee-hug", "walking", "pelvic-tilt", "dead-bug-arms",
    "cat-cow", "glute-bridge", "dead-bug", "pallof-press",
}


def test_diagram_count():
    # 25 workout + 5 flare-specific = 30 in the prototype.
    assert len(sfd.DIAGRAMS) == 30


def test_every_diagram_is_valid_svg():
    for key, svg in sfd.DIAGRAMS.items():
        assert isinstance(svg, str) and svg, f"{key}: empty diagram"
        assert svg.startswith("<svg"), f"{key}: does not start with <svg"
        assert svg.rstrip().endswith("</svg>"), f"{key}: does not end with </svg>"
        assert "viewBox" in svg, f"{key}: missing viewBox"


def test_flare_diagram_ids_present():
    missing = FLARE_DIAGRAM_IDS - set(sfd.DIAGRAMS)
    assert not missing, f"flare protocol references diagrams with no SVG: {missing}"
