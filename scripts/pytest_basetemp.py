"""Print a dedicated per-run pytest ``--basetemp`` directory (#360).

Usage:
    python scripts/pytest_basetemp.py <token>

``run_all_gates.sh`` passes ``--basetemp=<output>`` to the pytest gate. With
a basetemp, pytest uses that directory directly and never touches its
numbered dirs or the ``pytest-of-<user>/pytest-current`` link. On Windows
that link can become a broken reparse point, and pytest's end-of-session
cleanup then raises ``PermissionError: [WinError 5]`` — exit 1 with every
test passing and no coverage table, so the gate printed "pytest failed or
coverage below floor" when neither happened.

Where the directory goes matters, because ``--basetemp`` DELETES and
recreates it:

- ``<system temp>/taskmanager-pytest-<token>``: dedicated (never a directory
  holding anything else) and per run (the gate passes its PID, so two runs
  can't wipe each other's tmp trees).
- Outside the repo: inside it, pytest's tmp tree reds the Jest gate (its
  relative ``**/tests/js/**/*.test.js`` testMatch picks up a fixture).
- Absolute, forward slashes only: no later shell / shlex step can eat a
  ``\\`` and turn it into a relative path.

Exit 0 and print the path; exit 2 (nothing on stdout) for a missing or
unsafe token.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


def basetemp_for(token: str) -> str:
    """Return the basetemp path for ``token``; ValueError if the token could
    be anything other than a single plain path component."""
    if not _TOKEN.fullmatch(token or ""):
        raise ValueError(f"unsafe token {token!r}: use letters, digits, _ or -")
    base = Path(tempfile.gettempdir()).resolve()
    return (base / f"taskmanager-pytest-{token}").as_posix()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: pytest_basetemp.py <token>\n")
        return 2
    try:
        path = basetemp_for(args[0])
    except ValueError as exc:
        sys.stderr.write(f"pytest_basetemp: {exc}\n")
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
