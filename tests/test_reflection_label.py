"""#340: how an unnamed sitting is named in prompts and synthesis headers.

Two bugs, one cause. ``reflection_label`` used ``created_at.date()``:

1. Two untitled sittings on one day produced byte-identical labels, so a
   stored synthesis header listed the same line twice and the prompt
   fences could not be told apart.
2. ``.date()`` is the UTC date. A 9pm ET reflection is 01:00 UTC the NEXT
   day, so the label already named the wrong day and already disagreed
   with the history row the user reads — no collision required.

Both are fixed by rendering the instant in the user's zone, which is the
convention ``utils.local_today_date`` has used since audit fix #128.

The tz is pinned per-test rather than inherited from the environment:
these assertions are about a CONVERSION, and a test that passes only on a
machine already set to New York proves nothing.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

import auth
from models import Reflection, ReflectionInputMode, db
from reflection_service import (
    combined_transcript,
    continuation_block,
    recent_reflections_block,
    reflection_label,
    synthesis_block,
    synthesis_header,
)
from utils import local_date_from_dt, local_datetime_from_dt

EASTERN = "America/New_York"


@pytest.fixture(autouse=True)
def _pin_tz(monkeypatch):
    monkeypatch.setenv("DIGEST_TZ", EASTERN)


def _refl(created_at: datetime, *, title=None, transcript="words") -> Reflection:
    """An UNSAVED row — the label functions are pure reads."""
    return Reflection(
        iso_week="2026-W20",
        input_mode=ReflectionInputMode.TYPED,
        transcript=transcript,
        title=title,
        created_at=created_at,
        proposed_actions={"explicit": [], "suggested": []},
    )


class TestLocalDatetimeFromDt:
    def test_converts_utc_to_the_users_zone(self):
        got = local_datetime_from_dt(datetime(2026, 5, 18, 1, 30, tzinfo=UTC))
        assert (got.year, got.month, got.day) == (2026, 5, 17)
        assert (got.hour, got.minute) == (21, 30)

    def test_a_naive_value_is_read_as_utc(self):
        """The SQLite shape. Not defensive — it is the dev default."""
        naive = datetime(2026, 5, 18, 1, 30)
        aware = datetime(2026, 5, 18, 1, 30, tzinfo=UTC)
        assert local_datetime_from_dt(naive) == local_datetime_from_dt(aware)

    def test_none_passes_through(self):
        assert local_datetime_from_dt(None) is None

    def test_the_date_helper_still_agrees_with_it(self):
        """local_date_from_dt now delegates; it must not have drifted."""
        dt = datetime(2026, 5, 18, 1, 30, tzinfo=UTC)
        assert local_date_from_dt(dt) == local_datetime_from_dt(dt).date()
        assert local_date_from_dt(None) is None


class TestLabelNamesTheUsersDay:
    def test_a_late_evening_sitting_keeps_its_own_day(self):
        """The bug that needed no collision to bite.

        01:30 UTC on the 18th IS 9:30pm on the 17th for the user, and the
        history row says the 17th. A label saying the 18th contradicts the
        screen the user is looking at.
        """
        label = reflection_label(_refl(datetime(2026, 5, 18, 1, 30, tzinfo=UTC)))
        assert label.startswith("2026-05-17")
        assert "2026-05-18" not in label

    def test_a_midday_sitting_is_unchanged_in_date(self):
        label = reflection_label(_refl(datetime(2026, 5, 17, 16, 5, tzinfo=UTC)))
        assert label == "2026-05-17 12:05"

    def test_the_time_is_included(self):
        label = reflection_label(_refl(datetime(2026, 5, 17, 13, 45, tzinfo=UTC)))
        assert label == "2026-05-17 09:45"

    def test_a_user_given_name_still_wins_the_tail(self):
        """#339's naming is the better signal and must survive."""
        label = reflection_label(
            _refl(datetime(2026, 5, 17, 13, 45, tzinfo=UTC), title="DTCC week 1")
        )
        assert label == "2026-05-17 09:45 · DTCC week 1"

    def test_a_blank_title_is_not_treated_as_a_name(self):
        label = reflection_label(
            _refl(datetime(2026, 5, 17, 13, 45, tzinfo=UTC), title="   ")
        )
        assert label == "2026-05-17 09:45"

    def test_a_row_with_no_timestamp_falls_back_to_the_iso_week(self):
        """Belt and braces: created_at is never null in practice."""
        assert reflection_label(_refl(None)) == "2026-W20"


class TestTwoSittingsOnOneDay:
    """The filed bug: identical lines for different sittings.

    Both timestamps below are deliberately inside ONE UTC day, so the old
    ``created_at.date()`` rule really did produce byte-identical labels.
    A pair straddling UTC midnight would have looked distinct under the
    old rule — by naming the wrong day — and so would not reproduce it;
    that case is covered separately in ``test_a_same_day_pair_that…``.
    """

    MORNING = datetime(2026, 5, 17, 13, 12, tzinfo=UTC)     # 09:12 ET
    AFTERNOON = datetime(2026, 5, 17, 19, 45, tzinfo=UTC)   # 15:45 ET

    def _rows(self):
        return [_refl(self.MORNING), _refl(self.AFTERNOON)]

    def test_their_labels_differ(self):
        a = reflection_label(_refl(self.MORNING))
        b = reflection_label(_refl(self.AFTERNOON))
        assert a != b
        assert a.startswith("2026-05-17") and b.startswith("2026-05-17")

    def test_the_synthesis_header_lists_them_distinctly(self):
        """The line the user actually reads in their history."""
        header = synthesis_header(self._rows())
        lines = [ln for ln in header.splitlines() if ln.startswith("- ")]
        assert len(lines) == 2
        assert len(set(lines)) == 2, header

    def test_the_prompt_fences_are_distinguishable(self):
        text, _ = combined_transcript(self._rows())
        assert "2026-05-17 09:12" in text
        assert "2026-05-17 15:45" in text

    def test_the_span_line_names_both_ends(self):
        block = synthesis_block(self._rows())
        assert "2026-05-17 09:12 to 2026-05-17 15:45" in block

    def test_a_same_day_pair_that_straddles_utc_midnight(self):
        """Morning and late evening ET — one local day, two UTC days.

        The old rule made these LOOK distinct, but only because the
        evening one had drifted onto the 18th. Both must now name the
        17th AND still differ.
        """
        a = reflection_label(_refl(self.MORNING))
        b = reflection_label(_refl(datetime(2026, 5, 18, 1, 40, tzinfo=UTC)))
        assert a.startswith("2026-05-17") and b.startswith("2026-05-17")
        assert a != b
        assert b.endswith("21:40")

    def test_three_on_one_day_all_differ(self):
        rows = [
            _refl(datetime(2026, 5, 17, 12, 0, tzinfo=UTC)),    # 08:00 ET
            _refl(datetime(2026, 5, 17, 18, 30, tzinfo=UTC)),   # 14:30 ET
            _refl(datetime(2026, 5, 18, 2, 15, tzinfo=UTC)),    # 22:15 ET
        ]
        labels = [reflection_label(r) for r in rows]
        assert len(set(labels)) == 3, labels
        assert all(x.startswith("2026-05-17") for x in labels), labels

    def test_two_in_the_same_minute_still_collide(self):
        """Stated, not fixed — and the workaround is one click.

        Minute resolution cannot separate two sittings saved inside the
        same minute. That needs two reflections submitted seconds apart,
        which is not a thing this feature produces; naming one (#339)
        resolves it outright. Pinning the limit here so a future reader
        knows it was considered rather than missed.
        """
        t = datetime(2026, 5, 17, 13, 12, tzinfo=UTC)
        assert reflection_label(_refl(t)) == reflection_label(_refl(t))
        named = _refl(t, title="the second one")
        assert reflection_label(named) != reflection_label(_refl(t))


class TestTheSerialisedTimestamp:
    """#340: dev and prod must agree on what a stored instant means."""

    def test_created_at_always_carries_an_offset(self, app, client, monkeypatch):
        monkeypatch.setattr(
            auth, "get_current_user_email", lambda: "me@example.com"
        )
        resp = client.put("/api/reflection/draft", json={"text": "hello"})
        assert resp.status_code == 200
        created = resp.get_json()["draft"]["created_at"]
        # Without this, SQLite emits a bare "2026-09-25T18:04:56.481501"
        # and the browser reads the UTC wall clock AS local time.
        assert created.endswith("+00:00"), created

    def test_updated_at_also_carries_an_offset(self, app, client, monkeypatch):
        """#341: #340 fixed created_at and left this one naive on SQLite.

        `updated_at` is what `formatSavedAt` subtracts from now() for the
        "last saved N ago" banner, so a bare timestamp parses as LOCAL,
        lands in the future, and the negative age clamps to "just now" —
        a draft from three days ago read as fresh in dev.
        """
        monkeypatch.setattr(
            auth, "get_current_user_email", lambda: "me@example.com"
        )
        resp = client.put("/api/reflection/draft", json={"text": "hello"})
        assert resp.status_code == 200
        draft = resp.get_json()["draft"]
        assert draft["updated_at"].endswith("+00:00"), draft["updated_at"]
        assert draft["created_at"].endswith("+00:00"), draft["created_at"]

    def test_the_offset_survives_the_history_list(
        self, app, client, monkeypatch,
    ):
        monkeypatch.setattr(
            auth, "get_current_user_email", lambda: "me@example.com"
        )
        no_analysis = {
            "explicit": [], "suggested": [], "ai_cost_usd": 0.0, "snapshot": {},
        }
        with patch(
            "reflection_api.analyze_reflection", return_value=no_analysis,
        ):
            client.post("/api/reflection", json={"text": "a week of work"})
        listing = client.get("/api/reflection").get_json()["reflections"]
        assert listing, "expected the submitted reflection"
        assert listing[0]["created_at"].endswith("+00:00")


class TestOneRuleNotThree:
    """#340: the label rule had three open-coded copies.

    ``reflection_label``, ``recent_reflections_block`` and
    ``continuation_block`` each built their own "date, plus the name if
    there is one" string — so each carried its own copy of the UTC-date
    drift, and the same sitting could be named three different ways in
    one prompt. All three now go through ``reflection_label``.
    """

    LATE = datetime(2026, 5, 18, 1, 40, tzinfo=UTC)  # 21:40 ET on the 17th

    def test_the_continuity_block_uses_the_users_day(self, app):
        r = _refl(self.LATE, transcript="something I said earlier")
        db.session.add(r)
        db.session.commit()
        block = recent_reflections_block()
        assert "[2026-05-17 21:40]" in block, block
        assert "2026-05-18" not in block

    def test_the_continuation_block_uses_the_users_day(self):
        block = continuation_block(_refl(self.LATE))
        assert "2026-05-17 21:40" in block
        assert "2026-05-18" not in block

    def test_all_three_name_one_sitting_identically(self, app):
        """The drift this consolidation exists to prevent."""
        r = _refl(self.LATE, title="Week 1 planning", transcript="words here")
        db.session.add(r)
        db.session.commit()
        label = reflection_label(r)
        assert label in recent_reflections_block()
        assert label in continuation_block(r)
        assert label in synthesis_header([r])
