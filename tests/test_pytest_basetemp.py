"""Tests for scripts/pytest_basetemp.py (#360).

The pytest gate passes `--basetemp=<this script's output>` so a broken
`pytest-of-<user>/pytest-current` reparse point on Windows can no longer red a
fully passing suite. `--basetemp` DELETES and recreates the directory it is
given, and a path inside the repo reds the Jest gate, so where this points is
the whole safety story.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts import pytest_basetemp

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "pytest_basetemp.py"


class TestBasetempFor:
    def test_is_a_dedicated_dir_under_the_system_temp_dir(self):
        path = pytest_basetemp.basetemp_for("1234")
        assert Path(path).name == "taskmanager-pytest-1234"
        assert Path(path).parent.resolve() == Path(tempfile.gettempdir()).resolve()

    def test_is_absolute_with_forward_slashes_only(self):
        """A `\\` can be eaten by any later shlex/shell step, turning the path
        RELATIVE — pytest would then build its tmp tree inside the repo."""
        path = pytest_basetemp.basetemp_for("1234")
        assert "\\" not in path
        assert Path(path).is_absolute()

    def test_is_never_inside_the_repo(self):
        """Inside the repo, pytest's tmp tree reds Jest: its relative
        `**/tests/js/**/*.test.js` testMatch picks up the fixture
        test_bug_pattern_scan.py writes."""
        path = Path(pytest_basetemp.basetemp_for("1234")).resolve()
        assert REPO_ROOT.resolve() not in (path, *path.parents)

    def test_distinct_tokens_give_distinct_dirs(self):
        """Two gate runs must not wipe each other's tmp trees."""
        assert pytest_basetemp.basetemp_for("1") != pytest_basetemp.basetemp_for("2")

    @pytest.mark.parametrize("token", ["", "../x", "a/b", "a\\b", "has space", ".", ".."])
    def test_unsafe_tokens_are_refused(self, token):
        with pytest.raises(ValueError):
            pytest_basetemp.basetemp_for(token)


class TestCommandLine:
    """Run it the way the gate does: a fresh interpreter, stdout captured."""

    def _run(self, *args):
        return subprocess.run(  # noqa: S603 — fixed interpreter + repo script
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, timeout=60, check=False,
        )

    def test_prints_the_path_and_exits_0(self):
        result = self._run("4321")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == pytest_basetemp.basetemp_for("4321")

    def test_bad_token_exits_2_and_prints_nothing(self):
        result = self._run("../escape")
        assert result.returncode == 2
        assert result.stdout == ""
        assert "token" in result.stderr

    def test_missing_token_exits_2(self):
        result = self._run()
        assert result.returncode == 2
        assert result.stdout == ""
