"""#502: the gates check THIS checkout, whether or not it is a worktree.

Claude sessions run in parallel in `.claude/worktrees/<name>`, nested
inside the main checkout. Two gates got that wrong on 2026-10-17:

- Jest's relative `**/tests/js/**` testMatch also collected every nested
  worktree's tests (68 -> 138 suites in the main checkout), so a half-done
  parallel session could turn this checkout's gate red.
- docs_sync_check skipped any file whose ABSOLUTE path had a `.claude`
  part, so inside a worktree it skipped every file, found 0 env vars and
  passed without checking anything.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Jest -------------------------------------------------------------------


def _jest_ignores(config_dir: Path) -> list[str]:
    """testPathIgnorePatterns of jest.config.js as loaded from config_dir."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    out = subprocess.run(  # noqa: S603 -- fixed argv, no user input
        [node, "-e", "console.log(JSON.stringify(require(process.argv[1])"
         ".testPathIgnorePatterns || []))", str(config_dir / "jest.config.js")],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(out.stdout)


def _ignored(patterns: list[str], path: str) -> bool:
    import re
    return any(re.search(p, path) for p in patterns)


def test_main_checkout_jest_ignores_nested_worktrees(tmp_path):
    main = tmp_path / "taskmanager"
    main.mkdir()
    shutil.copy(REPO_ROOT / "jest.config.js", main / "jest.config.js")
    patterns = _jest_ignores(main)
    nested = main / ".claude" / "worktrees" / "other" / "tests" / "js" / "unit" / "x.test.js"
    own = main / "tests" / "js" / "unit" / "x.test.js"
    assert _ignored(patterns, str(nested))
    assert _ignored(patterns, nested.as_posix())
    assert not _ignored(patterns, str(own))


def test_a_worktree_still_runs_its_own_tests(tmp_path):
    wt = tmp_path / "taskmanager" / ".claude" / "worktrees" / "mine"
    wt.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "jest.config.js", wt / "jest.config.js")
    patterns = _jest_ignores(wt)
    own = wt / "tests" / "js" / "unit" / "x.test.js"
    assert not _ignored(patterns, str(own))
    assert not _ignored(patterns, own.as_posix())


def test_jest_lists_no_nested_worktree_test_here():
    """End to end on the real checkout: plant a test file in a nested
    worktree dir and ask Jest what it would run."""
    npx = shutil.which("npx")
    if npx is None:
        pytest.skip("npx not installed")
    if "/.claude/worktrees/" in REPO_ROOT.as_posix() + "/":
        pytest.skip("this checkout is itself a worktree")
    probe = REPO_ROOT / ".claude" / "worktrees" / "_502_probe" / "tests" / "js" / "unit"
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "probe.test.js").write_text("test('x', () => {});\n", encoding="utf-8")
    try:
        out = subprocess.run(  # noqa: S603 -- fixed argv, no user input
            [npx, "jest", "--listTests"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=120, shell=False,
        )
        listed = out.stdout.splitlines()
        assert any(Path(p).name.endswith(".test.js") for p in listed), out.stderr
        assert not [p for p in listed if ".claude" in Path(p).parts]
    finally:
        shutil.rmtree(REPO_ROOT / ".claude" / "worktrees" / "_502_probe", ignore_errors=True)


# --- docs_sync_check --------------------------------------------------------


def _scan(monkeypatch, repo: Path) -> set[str]:
    import scripts.docs_sync_check as d
    monkeypatch.setattr(d, "REPO", repo)
    return d.find_env_vars_in_code()


def test_docs_sync_reads_a_worktree_checkout(tmp_path, monkeypatch):
    wt = tmp_path / "taskmanager" / ".claude" / "worktrees" / "mine"
    wt.mkdir(parents=True)
    (wt / "app.py").write_text('import os\nos.environ.get("MY_SETTING")\n', encoding="utf-8")
    assert _scan(monkeypatch, wt) == {"MY_SETTING"}


def test_docs_sync_skips_nested_worktrees_and_tests(tmp_path, monkeypatch):
    main = tmp_path / "taskmanager"
    (main / ".claude" / "worktrees" / "other").mkdir(parents=True)
    (main / "tests").mkdir()
    (main / "app.py").write_text('import os\nos.environ["MINE"]\n', encoding="utf-8")
    (main / ".claude" / "worktrees" / "other" / "app.py").write_text(
        'import os\nos.environ.get("THEIRS")\n', encoding="utf-8")
    (main / "tests" / "t.py").write_text('import os\nos.environ.get("TESTONLY")\n',
                                         encoding="utf-8")
    assert _scan(monkeypatch, main) == {"MINE"}
