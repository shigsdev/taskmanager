"""Unit tests for utils.py helpers without a home elsewhere.

The TZ-aware date helpers (local_today_date / local_date_from_dt /
local_datetime_from_dt), the integer range, fit_length's edge and the
?is_active= filter. Other helpers are tested where they're used:
validate_upload in test_upload_helper.py, strict_int / parse_bool /
parse_text / optional_json_body bodies in test_value_coercion.py,
check_length / fit_length in test_text_lengths.py, the JSON-body
decorators in test_validate_json_body.py, _warn_tz_fallback in
test_background_jobs_439.py. #511 refreshed this file.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

import utils
from utils import (
    INT_MAX,
    INT_MIN,
    ValidationError,
    fit_length,
    local_date_from_dt,
    local_datetime_from_dt,
    local_today_date,
    parse_int,
)


def _freeze(monkeypatch, instant: datetime):
    """Make utils' datetime.now() return ``instant`` (tz-aware, UTC)."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(utils, "datetime", _Frozen)


class TestLocalTodayDate:

    def test_returns_a_date(self):
        assert isinstance(local_today_date(), date)

    @pytest.mark.parametrize("tz,expected", [
        ("America/New_York", date(2026, 5, 20)),  # 11pm the evening before
        ("Asia/Tokyo", date(2026, 5, 21)),        # noon
        ("UTC", date(2026, 5, 21)),
    ])
    def test_today_is_the_configured_zone_s_day(self, monkeypatch, tz, expected):
        monkeypatch.setenv("DIGEST_TZ", tz)
        _freeze(monkeypatch, datetime(2026, 5, 21, 3, 0, tzinfo=UTC))
        assert local_today_date() == expected

    def test_unset_zone_means_new_york(self, monkeypatch):
        monkeypatch.delenv("DIGEST_TZ", raising=False)
        _freeze(monkeypatch, datetime(2026, 5, 21, 3, 0, tzinfo=UTC))
        assert local_today_date() == date(2026, 5, 20)

    def test_unknown_zone_falls_back_to_the_server_date(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TZ", "Not/AZone")
        assert local_today_date() == date.today()


class TestLocalDateFromDt:
    """Audit fix #178 (2026-05-20). Mirrors `local_today_date`'s
    TZ contract but for an arbitrary tz-aware datetime."""

    def test_none_input_returns_none(self):
        assert local_date_from_dt(None) is None

    def test_morning_utc_same_local_date_in_eastern(self, monkeypatch):
        """10am UTC = 5-6am ET — both fall on the same calendar date."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        dt = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
        assert local_date_from_dt(dt) == date(2026, 5, 20)

    def test_late_evening_local_uses_local_date_not_utc(self, monkeypatch):
        """3am UTC May 21 = 11pm ET May 20. The local date is May 20.

        Pre-fix (``dt.date()`` on a UTC-stored timestamp), this would
        return May 21 — the off-by-one that #178 is about."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        dt = datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
        assert local_date_from_dt(dt) == date(2026, 5, 20)

    def test_naive_datetime_assumed_utc(self, monkeypatch):
        """SQLite (dev / tests) hands back NAIVE datetimes for the same
        columns Postgres returns tz-aware — load-bearing, not defensive.
        models._now() writes UTC, so naive means UTC."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        dt = datetime(2026, 5, 21, 3, 0)  # naive
        assert local_date_from_dt(dt) == date(2026, 5, 20)

    def test_different_timezone(self, monkeypatch):
        """Same UTC moment in Asia/Tokyo lands on a different date than
        in America/New_York. 3am UTC May 21 = noon JST May 21."""
        monkeypatch.setenv("DIGEST_TZ", "Asia/Tokyo")
        dt = datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
        assert local_date_from_dt(dt) == date(2026, 5, 21)

    def test_spring_forward_is_crossed(self, monkeypatch):
        """2026-03-08: 06:59Z is 01:59 EST, 07:00Z is 03:00 EDT (the old
        test used 06:00Z, an hour BEFORE the change)."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        before = local_datetime_from_dt(datetime(2026, 3, 8, 6, 59, tzinfo=UTC))
        after = local_datetime_from_dt(datetime(2026, 3, 8, 7, 0, tzinfo=UTC))
        assert (before.hour, before.utcoffset().total_seconds()) == (1, -5 * 3600)
        assert (after.hour, after.utcoffset().total_seconds()) == (3, -4 * 3600)
        assert before.date() == after.date() == date(2026, 3, 8)

    def test_fall_back_hour_happens_twice_on_one_date(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        first = local_datetime_from_dt(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
        second = local_datetime_from_dt(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
        assert (first.hour, first.minute) == (second.hour, second.minute) == (1, 30)
        assert first.utcoffset() != second.utcoffset()
        assert local_date_from_dt(datetime(2026, 11, 1, 6, 30, tzinfo=UTC)) == date(
            2026, 11, 1)


class TestLocalDatetimeFallback:

    def test_unknown_zone_returns_the_instant_in_utc(self, monkeypatch):
        monkeypatch.setenv("DIGEST_TZ", "Not/AZone")
        got = local_datetime_from_dt(datetime(2026, 5, 21, 3, 0))  # naive
        assert got == datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
        assert got.tzinfo is not None


class TestIntegerRange:
    """Postgres ``integer`` is -2**31 .. 2**31-1. #511: the bottom value
    itself was refused, as "too large"."""

    @pytest.mark.parametrize("n", [INT_MIN, -1, 0, INT_MAX])
    def test_the_whole_range_fits(self, n):
        assert parse_int(n, "rank") == n

    def test_one_past_the_top_is_too_large(self):
        with pytest.raises(ValidationError, match="too large"):
            parse_int(INT_MAX + 1, "rank")

    def test_one_past_the_bottom_is_too_small(self):
        with pytest.raises(ValidationError, match="too small"):
            parse_int(INT_MIN - 1, "rank")

    def test_project_order_takes_the_same_range(self, app):
        from models import Project, ProjectType, db
        from project_service import update_project

        p = Project(name="P", type=ProjectType.WORK)
        db.session.add(p)
        db.session.commit()
        assert update_project(p.id, {"priority_order": INT_MIN}).priority_order == INT_MIN
        with pytest.raises(ValidationError):
            update_project(p.id, {"priority_order": INT_MIN - 1})


class TestFitLength:

    @pytest.mark.parametrize("limit", [0, -3])
    def test_a_limit_below_one_gives_empty_not_longer(self, limit):
        assert fit_length("hello", limit) == ""

    def test_limit_one_is_just_the_ellipsis(self):
        assert fit_length("hello", 1) == "…"


class TestActiveFilter:

    @pytest.mark.parametrize("raw,expected", [
        (None, True), ("true", True), ("TRUE", True), ("1", True), ("yes", True),
        ("false", False), ("0", False), ("No", False), ("all", None), ("ALL", None),
    ])
    def test_values_the_pages_and_people_send(self, app, raw, expected):
        with app.test_request_context():
            value, err = utils.active_filter_or_400(raw)
        assert err is None
        assert value is expected

    @pytest.mark.parametrize("raw", ["", " true", "archived", "2"])
    def test_anything_else_is_a_400(self, app, raw):
        with app.test_request_context():
            value, err = utils.active_filter_or_400(raw)
        assert value is None
        assert err[1] == 400
