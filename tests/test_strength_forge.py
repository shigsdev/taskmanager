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


# ── Phase B.2: flare-up phase/day tracking ───────────────────────────
from datetime import timedelta  # noqa: E402

from models import FlareState, db  # noqa: E402
from utils import local_today_date  # noqa: E402


class TestFlareStateService:
    def test_start_flare_creates_active_immediate(self, app):
        with app.app_context():
            flare = svc.start_flare()
            assert flare.phase == "immediate"
            assert flare.ended_on is None
            assert svc.active_flare() is not None

    def test_only_one_active_flare(self, app):
        with app.app_context():
            svc.start_flare()
            with pytest.raises(ValueError):
                svc.start_flare()
            assert FlareState.query.filter(FlareState.ended_on.is_(None)).count() == 1

    def test_set_phase_advances(self, app):
        with app.app_context():
            svc.start_flare()
            svc.set_flare_phase("recovery")
            assert svc.active_flare().phase == "recovery"

    def test_set_invalid_phase_rejected(self, app):
        with app.app_context():
            svc.start_flare()
            with pytest.raises(ValueError):
                svc.set_flare_phase("bogus")

    def test_set_phase_with_no_active_flare_rejected(self, app):
        with app.app_context(), pytest.raises(ValueError):
            svc.set_flare_phase("recovery")

    def test_end_flare_clears_active(self, app):
        with app.app_context():
            svc.start_flare()
            assert svc.end_flare() is True
            assert svc.active_flare() is None
            assert svc.end_flare() is False  # nothing active now

    def test_day_counter_is_one_based(self, app):
        with app.app_context():
            flare = svc.start_flare()
            assert svc.flare_day(flare) == 1
            # Backdate two days → Day 3.
            flare.started_on = local_today_date() - timedelta(days=2)
            db.session.commit()
            assert svc.flare_day(flare) == 3

    def test_summary_inactive_when_none(self, app):
        with app.app_context():
            assert svc.flare_summary() == {"active": False}

    def test_summary_active_shape(self, app):
        with app.app_context():
            svc.start_flare()
            summary = svc.flare_summary()
            assert summary["active"] is True
            assert summary["phase"] == "immediate"
            assert summary["phase_label"] == "Acute Phase"
            assert summary["day"] == 1


class TestFlareStateAPI:
    def test_get_flare_inactive(self, authed_client):
        resp = authed_client.get("/api/strength-forge/flare")
        assert resp.status_code == 200
        assert resp.get_json() == {"active": False}

    def test_post_starts_flare(self, authed_client):
        resp = authed_client.post("/api/strength-forge/flare")
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["active"] is True
        assert body["phase"] == "immediate"

    def test_post_twice_returns_422(self, authed_client):
        authed_client.post("/api/strength-forge/flare")
        resp = authed_client.post("/api/strength-forge/flare")
        assert resp.status_code == 422

    def test_patch_sets_phase(self, authed_client):
        authed_client.post("/api/strength-forge/flare")
        resp = authed_client.patch(
            "/api/strength-forge/flare", json={"phase": "return"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["phase"] == "return"

    def test_patch_invalid_phase_returns_422(self, authed_client):
        authed_client.post("/api/strength-forge/flare")
        resp = authed_client.patch(
            "/api/strength-forge/flare", json={"phase": "bogus"}
        )
        assert resp.status_code == 422

    def test_patch_with_no_active_flare_returns_422(self, authed_client):
        resp = authed_client.patch(
            "/api/strength-forge/flare", json={"phase": "recovery"}
        )
        assert resp.status_code == 422

    def test_delete_ends_flare(self, authed_client):
        authed_client.post("/api/strength-forge/flare")
        resp = authed_client.delete("/api/strength-forge/flare")
        assert resp.status_code == 204
        # Now inactive.
        assert authed_client.get("/api/strength-forge/flare").get_json() == {
            "active": False
        }

    def test_delete_with_no_active_flare_returns_404(self, authed_client):
        resp = authed_client.delete("/api/strength-forge/flare")
        assert resp.status_code == 404


# ── #287: per-set detailed logging ───────────────────────────────────
from models import WorkoutSet  # noqa: E402


def _sets(*triples):
    """Build a list of client set-entries from (exercise_id, reps, resistance)."""
    out = []
    for i, (eid, reps, resistance) in enumerate(triples, start=1):
        out.append({
            "exercise_id": eid, "name": eid.replace("-", " ").title(),
            "set_number": i, "reps": reps, "resistance": resistance,
        })
    return out


class TestWorkoutSetService:
    def test_log_detailed_creates_session_and_sets(self, app):
        with app.app_context():
            session = svc.log_detailed_session("band-a", _sets(
                ("band-squat", 12, "Medium"),
                ("band-squat", 10, "Medium"),
            ))
            assert WorkoutSession.query.count() == 1
            assert WorkoutSet.query.count() == 2
            assert len(session.sets) == 2

    def test_invalid_plan_type_rejected(self, app):
        with app.app_context(), pytest.raises(ValueError):
            svc.log_detailed_session("nope", _sets(("x", 5, "Light")))

    def test_blank_rows_dropped(self, app):
        with app.app_context():
            session = svc.log_detailed_session("band-a", [
                {"exercise_id": "band-squat", "name": "Squat",
                 "set_number": 1, "reps": "", "resistance": ""},
                {"exercise_id": "band-squat", "name": "Squat",
                 "set_number": 2, "reps": 8, "resistance": ""},
            ])
            assert len(session.sets) == 1
            assert session.sets[0].reps == 8

    def test_reps_only_and_resistance_only_both_kept(self, app):
        with app.app_context():
            session = svc.log_detailed_session("mil-1", [
                {"exercise_id": "plank", "name": "Plank", "set_number": 1,
                 "reps": None, "resistance": "Bodyweight"},
                {"exercise_id": "dead-bug", "name": "Dead Bug", "set_number": 1,
                 "reps": 8, "resistance": ""},
            ])
            assert len(session.sets) == 2

    def test_serialize_includes_set_count(self, app):
        with app.app_context():
            session = svc.log_detailed_session("band-a", _sets(("band-squat", 12, "Medium")))
            assert svc.serialize(session)["set_count"] == 1
            # A quick-logged session has zero sets.
            bare = svc.log_session("band-b")
            assert svc.serialize(bare)["set_count"] == 0

    def test_session_detail_shape(self, app):
        with app.app_context():
            session = svc.log_detailed_session("band-a", _sets(
                ("band-squat", 12, "Medium"), ("band-row", 10, "Light"),
            ))
            detail = svc.session_detail(session.id)
            assert detail["set_count"] == 2
            assert len(detail["sets"]) == 2
            assert detail["sets"][0]["exercise_id"] == "band-squat"
            assert detail["sets"][0]["reps"] == 12

    def test_session_detail_missing_returns_none(self, app):
        with app.app_context():
            assert svc.session_detail(uuid.uuid4()) is None

    def test_delete_session_cascades_sets(self, app):
        with app.app_context():
            session = svc.log_detailed_session("band-a", _sets(
                ("band-squat", 12, "Medium"), ("band-squat", 10, "Medium"),
            ))
            assert WorkoutSet.query.count() == 2
            assert svc.delete_session(session.id) is True
            assert WorkoutSession.query.count() == 0
            assert WorkoutSet.query.count() == 0  # children cascade-deleted


class TestWorkoutSetAPI:
    def test_post_with_sets_returns_201_and_count(self, authed_client):
        resp = authed_client.post("/api/strength-forge/sessions", json={
            "plan_type": "band-a",
            "sets": _sets(("band-squat", 12, "Medium"), ("band-squat", 10, "Heavy")),
        })
        assert resp.status_code == 201
        assert resp.get_json()["set_count"] == 2

    def test_post_without_sets_is_quick_log(self, authed_client):
        resp = authed_client.post("/api/strength-forge/sessions", json={"plan_type": "band-a"})
        assert resp.status_code == 201
        assert resp.get_json()["set_count"] == 0

    def test_post_with_sets_invalid_plan_returns_422(self, authed_client):
        resp = authed_client.post("/api/strength-forge/sessions", json={
            "plan_type": "bogus", "sets": _sets(("band-squat", 12, "Medium")),
        })
        assert resp.status_code == 422

    def test_get_detail_returns_sets(self, authed_client):
        created = authed_client.post("/api/strength-forge/sessions", json={
            "plan_type": "band-a", "sets": _sets(("band-squat", 12, "Medium")),
        }).get_json()
        resp = authed_client.get(f"/api/strength-forge/sessions/{created['id']}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["set_count"] == 1
        assert body["sets"][0]["resistance"] == "Medium"

    def test_get_detail_missing_returns_404(self, authed_client):
        resp = authed_client.get(f"/api/strength-forge/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_includes_set_count(self, authed_client):
        authed_client.post("/api/strength-forge/sessions", json={
            "plan_type": "band-a", "sets": _sets(("band-squat", 12, "Medium")),
        })
        body = authed_client.get("/api/strength-forge/sessions").get_json()
        assert any(s["set_count"] == 1 for s in body["sessions"])
