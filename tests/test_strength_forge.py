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


# ── Phase B.1: workout-session tracking ──────────────────────────────
import uuid  # noqa: E402

import pytest  # noqa: E402

import strength_forge_service as svc  # noqa: E402
from models import WorkoutSession  # noqa: E402


class TestWorkoutSessionService:
    def test_log_session_creates_row(self, app):
        with app.app_context():
            session = svc.log_session("band-a")
            assert session.plan_type == "band-a"
            assert WorkoutSession.query.count() == 1

    def test_invalid_plan_type_rejected(self, app):
        with app.app_context():
            with pytest.raises(ValueError):
                svc.log_session("bogus-plan")
            assert WorkoutSession.query.count() == 0

    def test_summary_counts_this_week(self, app):
        with app.app_context():
            svc.log_session("band-a")
            svc.log_session("mil-1")
            summary = svc.session_summary()
            assert summary["total"] == 2
            assert summary["this_week"] == 2  # both logged today

    def test_delete_session(self, app):
        with app.app_context():
            session = svc.log_session("band-b")
            assert svc.delete_session(session.id) is True
            assert WorkoutSession.query.count() == 0
            assert svc.delete_session(session.id) is False  # already gone


class TestWorkoutSessionAPI:
    def test_post_logs_session(self, authed_client):
        resp = authed_client.post(
            "/api/strength-forge/sessions", json={"plan_type": "band-a"}
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["plan_type"] == "band-a"
        assert body["label"]

    def test_post_invalid_returns_422(self, authed_client):
        resp = authed_client.post(
            "/api/strength-forge/sessions", json={"plan_type": "nope"}
        )
        assert resp.status_code == 422

    def test_get_sessions_returns_summary(self, authed_client):
        authed_client.post(
            "/api/strength-forge/sessions", json={"plan_type": "mil-2"}
        )
        resp = authed_client.get("/api/strength-forge/sessions")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] >= 1
        assert any(s["plan_type"] == "mil-2" for s in body["sessions"])

    def test_delete_session(self, authed_client):
        created = authed_client.post(
            "/api/strength-forge/sessions", json={"plan_type": "band-b"}
        ).get_json()
        resp = authed_client.delete(f"/api/strength-forge/sessions/{created['id']}")
        assert resp.status_code == 204

    def test_delete_missing_returns_404(self, authed_client):
        resp = authed_client.delete(f"/api/strength-forge/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404
