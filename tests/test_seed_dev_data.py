"""Tests for scripts/seed_dev_data.py (#520).

The /reflection and /strength-forge E2E suites read history rows that
they never create. A fresh clone's seeded dev.db had none, so ~70
Playwright tests failed. These run the real seed against the test DB and
read the rows back through the same API the pages call.
"""
from __future__ import annotations

import pytest

from models import Reflection, WorkoutSession, WorkoutSet
from scripts import seed_dev_data


@pytest.fixture
def seeded(app, monkeypatch):
    # _seed builds its own app; hand it the test app (in-memory DB) instead.
    monkeypatch.setattr(seed_dev_data, "create_app", lambda: app)
    seed_dev_data._seed()
    return app


class TestReflectionsSeeded:
    def test_history_lists_submitted_reflections(self, seeded, authed_client):
        rows = authed_client.get("/api/reflection").get_json()["reflections"]
        assert len(rows) >= 2  # #335 reads several together
        assert all(not r["is_archived"] and r["is_active"] for r in rows)

    def test_none_is_a_draft(self, seeded):
        # A seeded draft would be restored into the box and break the
        # #324 / #341 draft tests.
        assert Reflection.query.filter_by(is_draft=True).count() == 0

    def test_one_is_untitled_so_the_generated_label_renders(self, seeded):
        assert Reflection.query.filter(Reflection.title.is_(None)).count() >= 1


class TestWorkoutsSeeded:
    def test_track_list_has_a_quick_and_a_detailed_session(self, seeded, authed_client):
        sessions = authed_client.get("/api/strength-forge/sessions").get_json()["sessions"]
        set_counts = [s["set_count"] for s in sessions]
        assert 0 in set_counts  # quick-logged row: .sf-track-del only
        assert any(n > 0 for n in set_counts)  # .sf-track-expandable (#287)


class TestReseedIsIdempotent:
    def test_second_run_replaces_rather_than_adds(self, seeded):
        counts = (Reflection.query.count(), WorkoutSession.query.count(),
                  WorkoutSet.query.count())
        seed_dev_data._seed()
        assert (Reflection.query.count(), WorkoutSession.query.count(),
                WorkoutSet.query.count()) == counts
