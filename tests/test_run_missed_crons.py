"""Tests for scripts/run_missed_crons.py.

We monkey-patch the four service helpers so the tests verify the
script's orchestration (order, filter, error-isolation, --date wiring,
dry-run guard, summary format) without exercising the real DB logic
— those helpers have their own dedicated test files.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import date

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location(
        "run_missed_crons", SCRIPTS_DIR / "run_missed_crons.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_missed_crons"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_helpers(monkeypatch, runner):
    """Replace the four helper functions with stubs that record their calls."""
    calls: list[tuple[str, dict]] = []

    def make(name, return_value):
        def _stub(**kwargs):
            calls.append((name, kwargs))
            return return_value
        return _stub

    import recurring_service
    import task_service

    monkeypatch.setattr(task_service, "roll_tomorrow_to_today", make("roll", 3))
    monkeypatch.setattr(task_service, "promote_due_today_tasks", make("promote", 2))
    monkeypatch.setattr(task_service, "realign_tiers_with_due_dates", make("realign", 1))
    monkeypatch.setattr(
        recurring_service, "spawn_today_tasks", make("spawn", ["t1", "t2", "t3", "t4"]),
    )
    return calls


class TestJobOrder:
    def test_default_runs_all_four_in_scheduler_order(self, runner, fake_helpers, capsys):
        rc = runner.main([])
        assert rc == 0
        assert [c[0] for c in fake_helpers] == ["roll", "promote", "realign", "spawn"]
        out = capsys.readouterr().out
        assert "tomorrow_roll" in out
        assert "recurring_spawn" in out

    def test_summary_reports_rowcounts(self, runner, fake_helpers, capsys):
        runner.main([])
        out = capsys.readouterr().out
        # roll=3, promote=2, realign=1, spawn=len(list)==4
        assert "3" in out
        assert "2" in out
        assert "1" in out
        assert "4" in out
        assert "4 succeeded, 0 failed" in out


class TestOnlyFilter:
    def test_only_one_job(self, runner, fake_helpers):
        runner.main(["--only", "recurring_spawn"])
        assert [c[0] for c in fake_helpers] == ["spawn"]

    def test_only_subset_preserves_order(self, runner, fake_helpers):
        runner.main(["--only", "recurring_spawn,tomorrow_roll"])
        # Order from JOB_ORDER, not from arg sequence
        assert [c[0] for c in fake_helpers] == ["roll", "spawn"]

    def test_unknown_job_id_exits(self, runner, fake_helpers):
        with pytest.raises(SystemExit):
            runner.main(["--only", "tomorrow_roll,not_a_real_job"])
        assert fake_helpers == []


class TestDateOverride:
    def test_date_passed_only_to_spawn(self, runner, fake_helpers):
        runner.main(["--date", "2026-05-19"])
        spawn_call = next(c for c in fake_helpers if c[0] == "spawn")
        assert spawn_call[1] == {"target_date": date(2026, 5, 19)}
        # Other helpers received no kwargs
        for name, kwargs in fake_helpers:
            if name != "spawn":
                assert kwargs == {}

    def test_missing_date_means_no_kwarg_to_spawn(self, runner, fake_helpers):
        runner.main([])
        spawn_call = next(c for c in fake_helpers if c[0] == "spawn")
        assert spawn_call[1] == {}

    def test_invalid_date_exits(self, runner, fake_helpers):
        with pytest.raises(SystemExit):
            runner.main(["--date", "yesterday"])


class TestErrorIsolation:
    def test_one_failure_does_not_block_remaining_jobs(
        self, runner, monkeypatch, capsys,
    ):
        calls: list[str] = []
        import recurring_service
        import task_service

        def boom(**_kw):
            calls.append("roll")
            raise RuntimeError("synthetic")

        monkeypatch.setattr(task_service, "roll_tomorrow_to_today", boom)
        monkeypatch.setattr(
            task_service, "promote_due_today_tasks",
            lambda **_kw: (calls.append("promote"), 0)[1],
        )
        monkeypatch.setattr(
            task_service, "realign_tiers_with_due_dates",
            lambda **_kw: (calls.append("realign"), 0)[1],
        )
        monkeypatch.setattr(
            recurring_service, "spawn_today_tasks",
            lambda **_kw: (calls.append("spawn"), [])[1],
        )

        rc = runner.main([])
        assert rc == 1
        assert calls == ["roll", "promote", "realign", "spawn"]
        out = capsys.readouterr().out
        assert "ERROR" in out
        assert "1 failed" in out


class TestDryRun:
    def test_dry_run_monkeypatches_session_commit(self, runner, monkeypatch):
        """Each helper's commit gets swapped for a rollback inside the guard."""
        from sqlalchemy.orm import Session

        captured: list[str] = []
        original_commit = Session.commit

        def fake_helper(**_kw):
            # Simulate what the real helpers do: open a Session, then commit.
            # Inside the dry-run guard, commit is patched to rollback.
            assert Session.commit is not original_commit, (
                "dry-run guard did not patch Session.commit"
            )
            captured.append("ran")
            return 0

        import recurring_service
        import task_service

        monkeypatch.setattr(task_service, "roll_tomorrow_to_today", fake_helper)
        monkeypatch.setattr(task_service, "promote_due_today_tasks", fake_helper)
        monkeypatch.setattr(task_service, "realign_tiers_with_due_dates", fake_helper)
        monkeypatch.setattr(
            recurring_service, "spawn_today_tasks", lambda **_kw: (captured.append("ran"), [])[1],
        )

        rc = runner.main(["--dry-run"])
        assert rc == 0
        assert captured == ["ran", "ran", "ran", "ran"]
        # Guard cleans up after itself
        assert Session.commit is original_commit

    def test_dry_run_marks_summary_status(self, runner, fake_helpers, capsys):
        runner.main(["--dry-run"])
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "OK" not in out.split("Result:")[0]  # status column is DRY-RUN, not OK


class TestJobRegistry:
    def test_job_order_matches_scheduler(self, runner):
        ids = [j[0] for j in runner.JOB_ORDER]
        assert ids == [
            "tomorrow_roll",
            "promote_due_today",
            "realign_tiers",
            "recurring_spawn",
        ]

    def test_daily_digest_intentionally_excluded(self, runner):
        # Bundling digest here would risk an accidental re-send;
        # POST /api/digest/send is the documented manual trigger.
        assert "daily_digest" not in runner.VALID_JOB_IDS
