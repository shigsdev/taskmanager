"""Unit tests for utils.py — the TZ-aware date conversion helpers.

These exercise the helpers directly (no DB, no Flask context) so the
TZ math can be verified with synthetic datetimes. Integration tests
that exercise the helpers through call sites live in the respective
service / endpoint test modules.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from utils import local_date_from_dt, local_today_date


class TestLocalTodayDate:
    """Sanity check on the existing helper. The exhaustive TZ
    behavior is exercised indirectly via every call site."""

    def test_returns_a_date(self):
        result = local_today_date()
        assert isinstance(result, date)


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
        """Tz-naive datetimes shouldn't appear given ``timezone=True``
        columns, but defend anyway: treat naive as UTC, convert."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        dt = datetime(2026, 5, 21, 3, 0)  # naive
        assert local_date_from_dt(dt) == date(2026, 5, 20)

    def test_different_timezone(self, monkeypatch):
        """Same UTC moment in Asia/Tokyo lands on a different date than
        in America/New_York. 3am UTC May 21 = noon JST May 21."""
        monkeypatch.setenv("DIGEST_TZ", "Asia/Tokyo")
        dt = datetime(2026, 5, 21, 3, 0, tzinfo=UTC)
        assert local_date_from_dt(dt) == date(2026, 5, 21)

    def test_dst_transition_safe(self, monkeypatch):
        """Sanity check around a DST boundary. 6am UTC on 2026-03-08
        (US spring-forward Sunday) is 1am EST → 2am EDT, both still
        March 8 locally."""
        monkeypatch.setenv("DIGEST_TZ", "America/New_York")
        dt = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)
        assert local_date_from_dt(dt) == date(2026, 3, 8)
