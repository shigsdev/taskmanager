"""Tests for scripts/run_missed_crons.py.

We monkey-patch the four service helpers so the tests verify the
script's orchestration (order, filter, error-isolation, --date wiring,
dry-run guard, summary format) without exercising the real DB logic
— those helpers have their own dedicated test files.
"""
from __future__ import annotations

import importlib.util
import pathlib
import socket
import sys
from datetime import date

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "run_missed_crons.py"


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
        # #167: realigned to match the actual scheduler job IDs in
        # ``app.py:_start_digest_scheduler`` (sourced from
        # ``cron_jobs.JOB_ORDER``). The pre-#167 script kept a local
        # rename (``realign_tiers`` → 3rd) that drifted from the
        # scheduler's ``realign_tiers_with_due_dates`` — the two
        # paths are now reconciled to one ID per job.
        ids = [j[0] for j in runner.JOB_ORDER]
        assert ids == [
            "tomorrow_roll",
            "promote_due_today",
            "realign_tiers_with_due_dates",
            "recurring_spawn",
        ]

    def test_daily_digest_intentionally_excluded(self, runner):
        # Bundling digest here would risk an accidental re-send;
        # POST /api/digest/send is the documented manual trigger.
        assert "daily_digest" not in runner.VALID_JOB_IDS


class TestPreflightDatabaseUrl:
    """#168 — fast-fail with a hint when DATABASE_URL is unreachable.

    Exercises the ``_preflight_database_url`` helper directly; it runs
    before ``create_app()`` so we don't need to boot the Flask app.
    """

    def test_exits_when_railway_internal_host_unresolvable(
        self, runner, monkeypatch, capsys,
    ):
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgres://u:p@postgres.railway.internal:5432/railway",
        )

        def fake_getaddrinfo(host, _port):
            raise socket.gaierror("Name or service not known")

        with pytest.raises(SystemExit) as exc:
            runner._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "postgres.railway.internal" in err
        assert "railway ssh" in err

    def test_exits_on_socket_timeout(self, runner, monkeypatch, capsys):
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgres://u:p@postgres.railway.internal:5432/railway",
        )

        def fake_getaddrinfo(host, _port):
            raise TimeoutError("timed out")

        with pytest.raises(SystemExit) as exc:
            runner._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert exc.value.code == 2
        assert "railway ssh" in capsys.readouterr().err

    def test_noop_when_dns_resolves(self, runner, monkeypatch):
        """Inside Railway, the lookup succeeds — preflight must return."""
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgres://u:p@postgres.railway.internal:5432/railway",
        )

        called = {"yes": False}

        def fake_getaddrinfo(host, _port):
            called["yes"] = True
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

        # Should NOT raise. No SystemExit.
        runner._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert called["yes"], "preflight should have probed DNS"

    def test_noop_when_database_url_not_railway_internal(self, runner, monkeypatch):
        """Local dev / external Postgres URLs skip the check entirely."""
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/dev")

        def boom(host, _port):
            raise AssertionError(
                "preflight must not probe DNS for non-Railway hosts"
            )

        # Should NOT raise — early-returns before calling getaddrinfo.
        runner._preflight_database_url(getaddrinfo=boom)

    def test_noop_when_database_url_unset(self, runner, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)

        def boom(host, _port):
            raise AssertionError("preflight must not probe DNS when env is unset")

        runner._preflight_database_url(getaddrinfo=boom)


class TestShebangPinned:
    """#169 — shebang must stay at ``#!/opt/venv/bin/python`` so
    ``railway ssh && /app/scripts/run_missed_crons.py`` keeps working.
    A future PR that drops the shebang (e.g. by reformatting the
    top-of-file docstring) reverts #169 silently — this drift gate
    catches it at pytest time.
    """

    def test_shebang_is_first_line(self):
        first_line = SCRIPT_PATH.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "#!/opt/venv/bin/python", (
            f"shebang drift: expected '#!/opt/venv/bin/python' "
            f"on line 1, got {first_line!r}. See BACKLOG #169."
        )

    def test_script_has_executable_bit_in_git(self):
        """``git update-index --chmod=+x`` set the mode bit so the file
        ships executable in the deployed image — ``railway ssh && ./scripts/...``
        depends on it.

        Skipped on filesystems that don't carry execute bits (Windows NTFS).
        The mode lives in the git index either way; this test just guards
        the working-tree state where it CAN be observed.
        """
        import os
        import stat

        try:
            mode = SCRIPT_PATH.stat().st_mode
        except OSError:
            pytest.skip("cannot stat script")

        # On Windows, NTFS doesn't carry +x; trust the git index check
        # in the sibling test below instead.
        if os.name == "nt":
            pytest.skip("Windows filesystem has no +x bit")

        assert mode & stat.S_IXUSR, (
            "scripts/run_missed_crons.py is not user-executable in the "
            "working tree. See BACKLOG #169 — run "
            "`git update-index --chmod=+x scripts/run_missed_crons.py`."
        )

    def test_executable_bit_recorded_in_git(self):
        """Final-authority check: the git index records mode 100755.

        Survives Windows working-tree limitations because git's index
        carries the bit regardless of filesystem support.
        """
        import subprocess  # noqa: S404 — test-only, fixed-arg invocation

        # noqa S603 + S607 — fixed argv, no user input; "git" is on PATH
        # in every dev + CI environment we support.
        result = subprocess.run(  # noqa: S603
            ["git", "ls-files", "-s", "scripts/run_missed_crons.py"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=str(SCRIPTS_DIR.parent),
        )
        # Format: "<mode> <sha> <stage>\t<path>"
        mode = result.stdout.split()[0]
        assert mode == "100755", (
            f"git index has scripts/run_missed_crons.py at mode {mode}, "
            f"expected 100755 (executable). See BACKLOG #169."
        )
