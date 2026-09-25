"""#341: the same reflection must not be saved — or charged for — twice.

Found by checking WHY two prod rows shared a label after #340. They were
not two sittings: they were one 291-char transcript submitted twice, 33
seconds apart, with a Claude call billed BOTH times ($0.0193 + $0.0197).
A third row had a live draft still holding text already submitted.

The mechanism was client-side (see static/reflection.js #341), but the
client cannot see the other device — submit from the phone while a laptop
still shows that restored draft and it submits the same text again. These
tests pin the server-side guard that makes the duplicate charge
impossible regardless of which client is at fault.

The load-bearing rule underneath everything here is #165: a transcript is
NEVER lost. Several tests below exist only to prove the de-duplication
cannot violate it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import func, select

import auth
from models import Reflection, ReflectionInputMode, db
from reflection_service import find_recent_duplicate, save_reflection


def _bypass_auth(monkeypatch):
    monkeypatch.setattr(
        auth, "get_current_user_email", lambda: "me@example.com"
    )


_ANALYSIS = {
    "explicit": [], "suggested": [], "ai_cost_usd": 0.0193, "snapshot": {},
}

TEXT = (
    "So, I am testing this out for the first time, so I'm just going to "
    "say some words to see if it works."
)


def _count_saved():
    return db.session.scalar(
        select(func.count(Reflection.id)).where(Reflection.is_draft.is_(False))
    )


class TestFindRecentDuplicate:
    """The helper, including the bit that is easy to get wrong on SQLite.

    ``created_at`` comes back NAIVE from SQLite and tz-aware from
    Postgres, while the cutoff is always an aware UTC datetime — so the
    comparison is worth an actual assertion rather than an assumption.
    """

    def test_finds_an_identical_transcript_just_saved(self, app):
        save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        assert find_recent_duplicate(TEXT) is not None

    def test_the_cutoff_actually_excludes_old_rows(self, app):
        r = save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        r.created_at = datetime.now(UTC) - timedelta(hours=3)
        db.session.commit()
        assert find_recent_duplicate(TEXT) is None
        # …and a wide enough window still sees it, which proves the miss
        # above was the CUTOFF and not a broken query.
        assert find_recent_duplicate(TEXT, within_seconds=4 * 3600) is not None

    def test_different_text_is_not_a_duplicate(self, app):
        save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        assert find_recent_duplicate(TEXT + " and one more thought") is None

    def test_whitespace_around_the_text_still_matches(self, app):
        """save_reflection strips; the incoming body may not have."""
        save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        assert find_recent_duplicate("  " + TEXT + "\n") is not None

    def test_an_open_draft_is_never_the_duplicate(self, app, client, monkeypatch):
        """The draft legitimately holds this text until submit retires it.

        Matching it would make the FIRST submit look like a duplicate of
        itself and return an unanalyzed draft as the result.
        """
        _bypass_auth(monkeypatch)
        client.put("/api/reflection/draft", json={"text": TEXT})
        assert find_recent_duplicate(TEXT) is None

    def test_a_soft_deleted_row_is_not_a_duplicate(self, app):
        """Re-entering something binned must actually save."""
        r = save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        r.is_active = False
        db.session.commit()
        assert find_recent_duplicate(TEXT) is None

    def test_empty_text_never_matches(self, app):
        assert find_recent_duplicate("") is None
        assert find_recent_duplicate("   ") is None
        assert find_recent_duplicate(None) is None

    def test_the_newest_match_wins(self, app):
        old = save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        old.created_at = datetime.now(UTC) - timedelta(seconds=60)
        db.session.commit()
        new = save_reflection(
            transcript=TEXT,
            input_mode=ReflectionInputMode.TYPED,
            proposed={"explicit": [], "suggested": []},
        )
        assert find_recent_duplicate(TEXT).id == new.id


class TestSubmittingTwiceChargesOnce:
    """The behaviour the user actually paid for twice."""

    def test_second_submit_makes_no_row_and_no_claude_call(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection", return_value=_ANALYSIS,
        ) as claude:
            first = client.post("/api/reflection", json={"text": TEXT})
            assert first.status_code == 201
            second = client.post("/api/reflection", json={"text": TEXT})
        assert second.status_code == 200
        # ONE row, ONE paid call. This is the whole point.
        assert _count_saved() == 1
        assert claude.call_count == 1

    def test_the_second_submit_still_returns_the_analysis(
        self, app, client, monkeypatch,
    ):
        """Silently succeeding with nothing on screen would be worse."""
        _bypass_auth(monkeypatch)
        rich = {
            "explicit": [{
                "op": "create", "entity": "task",
                "target": "Draft the 90-day plan", "reason": "you said so",
            }],
            "suggested": [], "ai_cost_usd": 0.0193, "snapshot": {},
        }
        with patch("reflection_api.analyze_reflection", return_value=rich):
            first = client.post("/api/reflection", json={"text": TEXT})
            second = client.post("/api/reflection", json={"text": TEXT})
        a, b = first.get_json(), second.get_json()
        assert a["id"] == b["id"]
        assert b["proposed_actions"]["explicit"][0]["target"] \
            == "Draft the 90-day plan"
        assert b["ai_cost_usd"] == 0.0193

    def test_three_rapid_submits_still_leave_one_row(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection", return_value=_ANALYSIS,
        ) as claude:
            for _ in range(3):
                client.post("/api/reflection", json={"text": TEXT})
        assert _count_saved() == 1
        assert claude.call_count == 1

    def test_a_genuinely_different_reflection_still_saves(
        self, app, client, monkeypatch,
    ):
        """The guard must not swallow real work."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection", return_value=_ANALYSIS,
        ) as claude:
            client.post("/api/reflection", json={"text": TEXT})
            r = client.post(
                "/api/reflection", json={"text": TEXT + " Also this."},
            )
        assert r.status_code == 201
        assert _count_saved() == 2
        assert claude.call_count == 2

    def test_the_same_text_much_later_is_a_new_reflection(
        self, app, client, monkeypatch,
    ):
        """The window guards an ACCIDENT, not a deliberate resubmit."""
        _bypass_auth(monkeypatch)
        with patch("reflection_api.analyze_reflection", return_value=_ANALYSIS):
            client.post("/api/reflection", json={"text": TEXT})
            row = db.session.scalars(
                select(Reflection).where(Reflection.is_draft.is_(False))
            ).first()
            row.created_at = datetime.now(UTC) - timedelta(hours=2)
            db.session.commit()
            again = client.post("/api/reflection", json={"text": TEXT})
        assert again.status_code == 201
        assert _count_saved() == 2


class TestRetryingAFailedAnalysis:
    """The 2026-09-24 20:17 row: saved, but its Claude call failed."""

    def test_the_retry_reuses_the_row_instead_of_duplicating_it(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            side_effect=RuntimeError("claude down"),
        ):
            failed = client.post("/api/reflection", json={"text": TEXT})
        assert failed.status_code == 422
        assert failed.get_json()["saved"] is True
        assert _count_saved() == 1

        with patch("reflection_api.analyze_reflection", return_value=_ANALYSIS):
            retry = client.post("/api/reflection", json={"text": TEXT})
        assert retry.status_code == 201
        # Still ONE row — now carrying the analysis it was missing.
        assert _count_saved() == 1
        row = db.session.scalars(
            select(Reflection).where(Reflection.is_draft.is_(False))
        ).first()
        assert row.ai_cost_usd == 0.0193

    def test_a_failed_retry_still_keeps_the_transcript(
        self, app, client, monkeypatch,
    ):
        """#165 is absolute: the words survive however badly this goes."""
        _bypass_auth(monkeypatch)
        with patch(
            "reflection_api.analyze_reflection",
            side_effect=RuntimeError("claude down"),
        ):
            client.post("/api/reflection", json={"text": TEXT})
            client.post("/api/reflection", json={"text": TEXT})
        assert _count_saved() == 1
        row = db.session.scalars(
            select(Reflection).where(Reflection.is_draft.is_(False))
        ).first()
        assert row.transcript == TEXT


class TestTheDraftIsStillRetired:
    """A duplicate submit must not leave the draft behind.

    Returning early without retiring it would recreate the exact
    condition #341 exists to remove: a live draft holding text that is
    already a saved reflection.
    """

    def test_duplicate_submit_clears_the_open_draft(
        self, app, client, monkeypatch,
    ):
        _bypass_auth(monkeypatch)
        with patch("reflection_api.analyze_reflection", return_value=_ANALYSIS):
            client.post("/api/reflection", json={"text": TEXT})
            # A draft reappears (the pre-#341 client did exactly this).
            client.put("/api/reflection/draft", json={"text": TEXT})
            assert client.get("/api/reflection/draft").get_json()["draft"]
            client.post("/api/reflection", json={"text": TEXT})
        assert client.get("/api/reflection/draft").get_json()["draft"] is None
        assert _count_saved() == 1
