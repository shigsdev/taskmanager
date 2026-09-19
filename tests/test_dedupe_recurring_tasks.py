"""Tests for scripts/dedupe_recurring_tasks.py planning logic (#319 cleanup).

``_plan`` is deliberately DB-free so the removal rules can be exercised
directly — the destructive part (delete_task) is the app's own soft-delete and
is covered by task_service tests. These assert the rules that decide what gets
removed, because getting that wrong destroys user data.
"""
from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "dedupe_recurring_tasks",
    Path(__file__).resolve().parents[1] / "scripts" / "dedupe_recurring_tasks.py",
)
dedupe = importlib.util.module_from_spec(_SPEC)
sys.modules["dedupe_recurring_tasks"] = dedupe
_SPEC.loader.exec_module(dedupe)


class _T:
    """Minimal task stand-in matching the attributes ``_plan`` reads."""

    def __init__(self, *, status, created_at, due=date(2026, 9, 8),
                 rt_id="tpl-1", title="Agenda"):
        self.id = uuid.uuid4()
        self.title = title
        self.due_date = due
        self.status = status
        self.created_at = created_at
        self.recurring_task_id = rt_id


def _ids(pairs):
    return {str(d.id) for _keep, drops in pairs for d in drops}


class TestRuleA:
    def test_two_active_same_day_keeps_oldest(self):
        old = _T(status="active", created_at=100)
        new = _T(status="active", created_at=200)
        a, b = dedupe._plan([new, old])
        assert len(a) == 1
        keep, drops = a[0]
        assert keep is old, "must keep the ORIGINAL cron spawn"
        assert [d.id for d in drops] == [new.id]
        assert b == []

    def test_three_active_keeps_only_oldest(self):
        rows = [_T(status="active", created_at=c) for c in (300, 100, 200)]
        a, _b = dedupe._plan(rows)
        keep, drops = a[0]
        assert keep.created_at == 100
        assert len(drops) == 2

    def test_single_active_is_left_alone(self):
        a, b = dedupe._plan([_T(status="active", created_at=100)])
        assert a == [] and b == []


class TestRuleB:
    def test_active_with_archived_sibling_is_removed(self):
        done = _T(status="archived", created_at=100)
        resurrected = _T(status="active", created_at=200)
        a, b = dedupe._plan([done, resurrected])
        assert a == []
        assert len(b) == 1
        keep, drops = b[0]
        assert keep is done, "the completion record must be what survives"
        assert [d.id for d in drops] == [resurrected.id]

    def test_cancelled_sibling_also_counts(self):
        _a, b = dedupe._plan([
            _T(status="cancelled", created_at=100),
            _T(status="active", created_at=200),
        ])
        assert len(b) == 1


class TestSafety:
    def test_never_removes_settled_rows(self):
        rows = [
            _T(status="archived", created_at=100),
            _T(status="cancelled", created_at=110),
            _T(status="deleted", created_at=120),
            _T(status="active", created_at=200),
        ]
        a, b = dedupe._plan(rows)
        removed = _ids(a) | _ids(b)
        for r in rows:
            if r.status != "active":
                assert str(r.id) not in removed

    def test_non_spawned_tasks_are_ignored(self):
        """A manually-created task that merely shares a title/day is untouched."""
        rows = [
            _T(status="active", created_at=100, rt_id=None),
            _T(status="active", created_at=200, rt_id=None),
        ]
        assert dedupe._plan(rows) == ([], [])

    def test_rows_without_due_date_are_ignored(self):
        rows = [
            _T(status="active", created_at=100, due=None),
            _T(status="active", created_at=200, due=None),
        ]
        assert dedupe._plan(rows) == ([], [])

    def test_different_days_are_not_duplicates(self):
        rows = [
            _T(status="active", created_at=100, due=date(2026, 9, 8)),
            _T(status="active", created_at=200, due=date(2026, 9, 9)),
        ]
        assert dedupe._plan(rows) == ([], [])

    def test_different_templates_are_not_duplicates(self):
        rows = [
            _T(status="active", created_at=100, rt_id="tpl-1"),
            _T(status="active", created_at=200, rt_id="tpl-2"),
        ]
        assert dedupe._plan(rows) == ([], [])

    def test_enum_style_status_objects_supported(self):
        """Real Task.status is an enum — ``_plan`` reads ``.value``."""
        class _Enum:
            def __init__(self, v):
                self.value = v

        old = _T(status=_Enum("active"), created_at=100)
        new = _T(status=_Enum("active"), created_at=200)
        a, _b = dedupe._plan([old, new])
        assert len(a) == 1
        assert a[0][0] is old


class TestProductionIncident:
    def test_reproduces_the_reported_four_rows(self):
        """The exact shape of the user's 2026-09-07 report.

        One Rule-A pair (2 active "Agenda" for 09-08) plus three Rule-B rows
        (Morning Prep / Evening prep / AI Training resurrected on 09-07 after
        being completed) → 4 removals, all the 00:38:55 replay's doing.
        """
        rows = [
            _T(status="active", created_at=1, due=date(2026, 9, 8),
               rt_id="agenda", title="Agenda for Working Group Meeting"),
            _T(status="active", created_at=2, due=date(2026, 9, 8),
               rt_id="agenda", title="Agenda for Working Group Meeting"),
        ]
        for name in ("Morning Prep", "Evening prep", "AI Training (Monday)"):
            rows += [
                _T(status="archived", created_at=1, due=date(2026, 9, 7),
                   rt_id=name, title=name),
                _T(status="active", created_at=2, due=date(2026, 9, 7),
                   rt_id=name, title=name),
            ]
        a, b = dedupe._plan(rows)
        assert len(a) == 1
        assert len(b) == 3
        assert len(_ids(a) | _ids(b)) == 4


class TestPreflightDatabaseUrl:
    """#168 — fast-fail with a hint when invoked outside Railway's network.

    Filed after the 2026-09-19 operator run: `railway run` from a laptop
    produced a ~100-line SQLAlchemy traceback instead of the one-line hint
    that #168 shipped for run_missed_crons.py. Same guard, same contract.
    """

    _RAILWAY_URL = "postgres://u:p@postgres.railway.internal:5432/railway"

    def test_exits_2_with_hint_when_host_unresolvable(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", self._RAILWAY_URL)

        def fake_getaddrinfo(host, _port):
            raise socket.gaierror("getaddrinfo failed")

        with pytest.raises(SystemExit) as exc:
            dedupe._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "postgres.railway.internal" in err
        assert "railway ssh" in err
        # The hint must name THIS script, not run_missed_crons.py.
        assert "dedupe_recurring_tasks.py" in err

    def test_exits_2_on_timeout(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", self._RAILWAY_URL)

        def fake_getaddrinfo(host, _port):
            raise TimeoutError("timed out")

        with pytest.raises(SystemExit) as exc:
            dedupe._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert exc.value.code == 2
        assert "railway ssh" in capsys.readouterr().err

    def test_noop_inside_railway_where_dns_resolves(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", self._RAILWAY_URL)
        probed = {"yes": False}

        def fake_getaddrinfo(host, _port):
            probed["yes"] = True
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]

        dedupe._preflight_database_url(getaddrinfo=fake_getaddrinfo)  # no raise
        assert probed["yes"], "preflight should have probed DNS"

    def test_noop_for_non_railway_host(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost:5432/dev")

        def boom(host, _port):
            raise AssertionError("must not probe DNS for a non-Railway host")

        dedupe._preflight_database_url(getaddrinfo=boom)

    def test_noop_when_database_url_unset(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)

        def boom(host, _port):
            raise AssertionError("must not probe DNS with no DATABASE_URL")

        dedupe._preflight_database_url(getaddrinfo=boom)

    def test_restores_default_socket_timeout(self, monkeypatch):
        """The guard mutates the global default timeout — it must put it back
        even on the exit path, or it silently reshapes every later socket."""
        monkeypatch.setenv("DATABASE_URL", self._RAILWAY_URL)
        before = socket.getdefaulttimeout()

        def fake_getaddrinfo(host, _port):
            raise socket.gaierror("nope")

        with pytest.raises(SystemExit):
            dedupe._preflight_database_url(getaddrinfo=fake_getaddrinfo)
        assert socket.getdefaulttimeout() == before


class TestInvocationContract:
    """#169 — the in-container invocation must keep working."""

    _PATH = Path(__file__).resolve().parents[1] / "scripts" / "dedupe_recurring_tasks.py"

    def test_shebang_pins_the_container_venv(self):
        first = self._PATH.read_text(encoding="utf-8").splitlines()[0]
        assert first == "#!/opt/venv/bin/python"

    def test_git_index_mode_is_executable(self):
        """Windows has no +x bit, but the git index mode ships to the
        container — assert THAT so `/app/scripts/...` stays runnable."""
        # noqa S603 + S607 — fixed argv, no user input; "git" is on PATH
        # in every dev + CI environment we support.
        out = subprocess.run(  # noqa: S603
            ["git", "ls-files", "-s", "scripts/dedupe_recurring_tasks.py"],  # noqa: S607
            capture_output=True, text=True, check=True,
            cwd=str(self._PATH.parents[1]),
        ).stdout
        assert out.startswith("100755"), f"expected mode 100755, got: {out!r}"
