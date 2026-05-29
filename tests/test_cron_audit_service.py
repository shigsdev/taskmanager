"""Tests for ``cron_audit_service`` (#167 scheduler self-heal).

Strategy: real Flask app context + SQLite memory DB via the ``app``
+ ``client`` fixtures from conftest.py. Monkey-patch the four
``cron_jobs.JOB_ORDER`` helpers so we exercise ``replay_missed`` ↔
``CronAudit`` rows without touching real task / recurring logic.
"""
from __future__ import annotations

import datetime as _dt

import pytest

import cron_audit_service as audit
from cron_jobs import JOB_ORDER
from models import CronAudit, db


def _set_audit_row(job_id: str, when: _dt.datetime, status: str = "OK") -> None:
    """Helper: seed a CronAudit row directly."""
    row = db.session.get(CronAudit, job_id)
    if row is None:
        row = CronAudit(
            job_id=job_id,
            last_fire_at=when,
            last_status=status,
            last_rowcount=0,
            last_elapsed_ms=0.0,
        )
        db.session.add(row)
    else:
        row.last_fire_at = when
        row.last_status = status
    db.session.commit()


def _today_at(hour: int, minute: int, *, ref: _dt.datetime | None = None) -> _dt.datetime:
    """Return today's ``HH:MM`` as a TZ-aware UTC datetime."""
    base = ref or _dt.datetime.now(_dt.UTC)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture
def stub_helpers(monkeypatch):
    """Replace the four service helpers with stubs that record their calls.

    Returns the call list so tests can inspect order + count + the
    return value each stub produced.
    """
    calls: list[tuple[str, int]] = []
    import recurring_service
    import task_service

    monkeypatch.setattr(
        task_service, "roll_tomorrow_to_today",
        lambda: (calls.append(("roll", 3)), 3)[1],
    )
    monkeypatch.setattr(
        task_service, "promote_due_today_tasks",
        lambda: (calls.append(("promote", 2)), 2)[1],
    )
    monkeypatch.setattr(
        task_service, "realign_tiers_with_due_dates",
        lambda: (calls.append(("realign", 1)), 1)[1],
    )
    monkeypatch.setattr(
        recurring_service, "spawn_today_tasks",
        lambda: (calls.append(("spawn", 4)), ["t1", "t2", "t3", "t4"])[1],
    )
    return calls


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------


class TestRecord:
    def test_creates_row_on_first_call(self, app):
        with app.app_context():
            audit.record(
                "tomorrow_roll",
                status="OK", rowcount=5, elapsed_ms=123.4,
            )
            row = db.session.get(CronAudit, "tomorrow_roll")
            assert row is not None
            assert row.last_status == "OK"
            assert row.last_rowcount == 5
            assert row.last_elapsed_ms == pytest.approx(123.4)
            # SQLite (test fixture) strips tzinfo on round-trip; Postgres
            # (prod) preserves it. The replay_missed comparison
            # normalises either way (see test_naive_last_fire_at_*).
            assert row.last_fire_at is not None

    def test_updates_existing_row(self, app):
        with app.app_context():
            audit.record("recurring_spawn", status="OK", rowcount=1, elapsed_ms=10)
            audit.record("recurring_spawn", status="OK", rowcount=7, elapsed_ms=99)
            row = db.session.get(CronAudit, "recurring_spawn")
            assert row.last_rowcount == 7
            assert row.last_elapsed_ms == pytest.approx(99)

    def test_unknown_job_id_no_op(self, app, caplog):
        with app.app_context():
            with caplog.at_level("WARNING", logger="cron_audit_service"):
                audit.record(
                    "not_a_real_job",
                    status="OK", rowcount=0, elapsed_ms=0,
                )
            row = db.session.get(CronAudit, "not_a_real_job")
            assert row is None
            assert any("unknown job_id" in r.getMessage() for r in caplog.records)

    def test_pinned_timestamp_honored(self, app):
        with app.app_context():
            when = _dt.datetime(2026, 5, 28, 12, 0, 0, tzinfo=_dt.UTC)
            audit.record(
                "promote_due_today",
                status="OK", rowcount=0, elapsed_ms=0, when=when,
            )
            row = db.session.get(CronAudit, "promote_due_today")
            # SQLite may strip tz on storage — compare wall-clock fields.
            assert row.last_fire_at.year == 2026
            assert row.last_fire_at.month == 5
            assert row.last_fire_at.day == 28
            assert row.last_fire_at.hour == 12
            assert row.last_fire_at.minute == 0


# ---------------------------------------------------------------------------
# replay_missed()
# ---------------------------------------------------------------------------


class TestReplayMissed:
    def test_all_fresh_runs_every_job_in_order(self, app, stub_helpers):
        """Empty CronAudit + container booted at 06:00 → all 4 run."""
        with app.app_context():
            # Boot at 06:00 — well past every nightly fire (00:01-00:05).
            now = _today_at(6, 0)
            results = audit.replay_missed(now=now)

            statuses = [r["status"] for r in results]
            assert statuses == ["OK"] * 4
            order = [c[0] for c in stub_helpers]
            assert order == ["roll", "promote", "realign", "spawn"]

            # All four audit rows present, all with last_fire_at == now
            # at the wall-clock level (SQLite may drop tzinfo on storage).
            for job_id, _h, _m, _spec in JOB_ORDER:
                row = db.session.get(CronAudit, job_id)
                assert row is not None
                assert row.last_status == "OK"
                assert row.last_fire_at.replace(tzinfo=_dt.UTC) == now

    def test_already_ran_today_skipped(self, app, stub_helpers):
        """Audit row says it fired at 00:01 — second replay at 06:00 = no-op."""
        with app.app_context():
            now = _today_at(6, 0)
            # Each job already fired at its scheduled time.
            for job_id, h, m, _spec in JOB_ORDER:
                _set_audit_row(job_id, _today_at(h, m))

            results = audit.replay_missed(now=now)
            assert all(r["status"] == "SKIPPED" for r in results)
            assert all(r["reason"] == "already ran today" for r in results)
            assert stub_helpers == []

    def test_one_missed_others_fresh(self, app, stub_helpers):
        """Only ``recurring_spawn`` has a stale audit → only it replays."""
        with app.app_context():
            now = _today_at(6, 0)
            # Three jobs fired today, recurring_spawn last fired yesterday.
            for job_id, h, m, _spec in JOB_ORDER[:-1]:
                _set_audit_row(job_id, _today_at(h, m))
            yesterday = _today_at(0, 5) - _dt.timedelta(days=1)
            _set_audit_row("recurring_spawn", yesterday)

            results = audit.replay_missed(now=now)
            ran = [r for r in results if r["status"] == "OK"]
            skipped = [r for r in results if r["status"] == "SKIPPED"]
            assert len(ran) == 1 and ran[0]["job_id"] == "recurring_spawn"
            assert len(skipped) == 3
            assert [c[0] for c in stub_helpers] == ["spawn"]

    def test_future_today_skipped(self, app, stub_helpers):
        """Deploy lands at 00:00:30, boots at 00:00:45 — nothing replays
        because every nightly fire is in the future today.

        Mitigates the deploy-during-fire-window race documented in the
        BACKLOG #167 row.
        """
        with app.app_context():
            now = _today_at(0, 0).replace(second=45)
            results = audit.replay_missed(now=now)
            assert all(r["status"] == "SKIPPED" for r in results)
            assert all(
                r["reason"] == "scheduled time is in the future today"
                for r in results
            )
            assert stub_helpers == []

    def test_failure_isolated_to_one_job(self, app, monkeypatch):
        """``promote_due_today`` raises — the other 3 still run, statuses
        per-job, exit results carry ERROR for the failed job only.
        """
        import recurring_service
        import task_service

        calls = []

        def boom_promote():
            calls.append("promote")
            raise RuntimeError("synthetic test failure")

        monkeypatch.setattr(task_service, "roll_tomorrow_to_today",
                            lambda: (calls.append("roll"), 1)[1])
        monkeypatch.setattr(task_service, "promote_due_today_tasks", boom_promote)
        monkeypatch.setattr(task_service, "realign_tiers_with_due_dates",
                            lambda: (calls.append("realign"), 2)[1])
        monkeypatch.setattr(recurring_service, "spawn_today_tasks",
                            lambda: (calls.append("spawn"), [])[1])

        with app.app_context():
            now = _today_at(6, 0)
            results = audit.replay_missed(now=now)
            statuses = {r["job_id"]: r["status"] for r in results}

            assert statuses == {
                "tomorrow_roll": "OK",
                "promote_due_today": "ERROR",
                "realign_tiers_with_due_dates": "OK",
                "recurring_spawn": "OK",
            }
            assert calls == ["roll", "promote", "realign", "spawn"]

            # ERROR is also recorded in the audit row so the next boot's
            # replay can see it.
            row = db.session.get(CronAudit, "promote_due_today")
            assert row.last_status == "ERROR"

    def test_idempotency_second_call_same_day_no_op(self, app, stub_helpers):
        """Two consecutive replays in the same boot — second is a no-op."""
        with app.app_context():
            now = _today_at(6, 0)

            r1 = audit.replay_missed(now=now)
            assert [r["status"] for r in r1] == ["OK"] * 4
            assert len(stub_helpers) == 4

            # Second call right away. now is the same; the rows we just
            # wrote have last_fire_at == now → all skipped.
            r2 = audit.replay_missed(now=now)
            assert all(r["status"] == "SKIPPED" for r in r2)
            assert len(stub_helpers) == 4  # no new calls

    def test_naive_last_fire_at_normalised_to_utc(self, app, stub_helpers):
        """A pre-#167 audit row could carry a TZ-naive timestamp; the
        comparison must not raise.
        """
        with app.app_context():
            now = _today_at(6, 0)
            # Seed a TZ-naive row that says we already ran today.
            scheduled_naive = _today_at(0, 1).replace(tzinfo=None)
            row = CronAudit(
                job_id="tomorrow_roll",
                last_fire_at=scheduled_naive,
                last_status="OK",
                last_rowcount=0,
                last_elapsed_ms=0.0,
            )
            db.session.add(row)
            db.session.commit()
            # Mark the rest fresh-today so they skip via the
            # already-ran branch too.
            for job_id, h, m, _spec in JOB_ORDER[1:]:
                _set_audit_row(job_id, _today_at(h, m))

            results = audit.replay_missed(now=now)
            roll_result = next(r for r in results if r["job_id"] == "tomorrow_roll")
            assert roll_result["status"] == "SKIPPED"
            assert roll_result["reason"] == "already ran today"
            assert stub_helpers == []
