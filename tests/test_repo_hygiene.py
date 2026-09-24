"""Repo-level hygiene checks.

Catches things that aren't bugs in the running app but break dev
workflows: line-ending mismatches that disable git hooks, missing
shebangs on scripts, etc. These tests assert at the file-bytes
layer, not via mocks — they verify what's actually in the working
tree right now.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Line-ending hygiene (backlog #39, ADR-027) ----------------------------


# Files that MUST be LF on disk because Mac/Linux interpreters parse the
# shebang byte-by-byte and a stray \r breaks exec.
LF_REQUIRED = [
    ".githooks/pre-commit",
    "scripts/install_dev_tools.sh",
    "scripts/install_git_hooks.sh",
    "scripts/run_all_gates.sh",
]


@pytest.mark.parametrize("rel_path", LF_REQUIRED)
def test_shell_files_have_lf_line_endings(rel_path):
    """A CRLF in any of these files breaks exec on Mac/Linux. The
    `.gitattributes` rules force LF for `*.sh` and `.githooks/*`,
    so this test will fail loudly if someone bypasses those rules
    (e.g. commits with autocrlf override) or removes them."""
    path = REPO_ROOT / rel_path
    assert path.exists(), f"{rel_path} missing — expected to exist"
    raw = path.read_bytes()
    assert b"\r\n" not in raw, (
        f"{rel_path} contains CRLF line endings — Mac/Linux exec will fail "
        f"on the shebang. Re-run `git add --renormalize .` and check "
        f"`.gitattributes` covers this path."
    )


def test_gitattributes_locks_down_githooks_and_shell():
    """The `.gitattributes` file must explicitly force LF for shell
    scripts AND for `.githooks/*` (which has no extension and would
    otherwise fall through to the `* text=auto` default that respects
    Windows autocrlf). This is the root-cause fix from ADR-027."""
    attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attrs, ".gitattributes must force LF for *.sh"
    assert ".githooks/* text eol=lf" in attrs, (
        ".gitattributes must force LF for `.githooks/*` — without this rule, "
        "Windows autocrlf rewrites the hook shebang to CRLF and Mac exec breaks. "
        "See ADR-027 / backlog #39."
    )


def test_pre_commit_hook_has_bash_shebang():
    """The hook file must start with a bash shebang. Belt-and-braces
    on top of the LF check — together they guarantee Mac/Linux can
    exec the file."""
    raw = (REPO_ROOT / ".githooks" / "pre-commit").read_bytes()
    # First line ends at first \n (which we already asserted is LF, not
    # CRLF). The shebang must point to a real bash interpreter.
    first_line = raw.split(b"\n", 1)[0]
    assert first_line == b"#!/usr/bin/env bash", (
        f"pre-commit hook shebang is {first_line!r}; expected "
        f"b'#!/usr/bin/env bash' (no trailing \\r, no other interpreter)."
    )


# --- Text-source byte hygiene (#329) ---------------------------------------


# Suffixes that must stay readable as TEXT. A single NUL byte anywhere in
# one of these makes git, grep and diff classify the whole file as binary:
# `grep -n` then prints "Binary file X matches" instead of the line, and
# reviewers lose the diff. Twice now a test needed to express a byte value
# in a literal and the raw byte landed in the file instead of an escape
# (`\x89PNG` in tests/test_reflection_context.py, `MZ\0` in
# tests/e2e/pages.spec.js). The runtime value is identical either way, so
# the escape costs nothing and keeps the file greppable.
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".sh", ".json", ".yml", ".yaml"}

# Directories that hold generated or vendored bytes we don't author.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
    "htmlcov", "test-results", "playwright-report", ".claude", "instance",
    "migrations/__pycache__",
}


def _tracked_text_files():
    for path in REPO_ROOT.rglob("*"):
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        if SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts):
            continue
        yield path


def test_no_nul_bytes_in_text_sources():
    """A raw NUL turns a source file binary for every text tool."""
    offenders = []
    for path in _tracked_text_files():
        raw = path.read_bytes()
        if b"\x00" in raw:
            line = raw[: raw.index(b"\x00")].count(b"\n") + 1
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert not offenders, (
        "NUL byte(s) found in text source files: "
        + ", ".join(offenders)
        + ". Write the byte as an escape (`\\u0000` in JS, `\\x00` in a "
        "Python bytes literal) instead of embedding it - a raw NUL makes "
        "git and grep treat the file as binary and hides it from diffs."
    )
