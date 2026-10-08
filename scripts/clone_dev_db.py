"""Copy the local dev SQLite database for a second local test server (#394).

Usage:
    python scripts/clone_dev_db.py <destination>

``run_all_gates.sh`` runs mobile Playwright on a second throwaway local
server (port 5112) so it can run side by side with desktop on 5111. That
server needs its own database, so this makes a copy of the one the app uses:

- Same resolution as the app: ``DATABASE_URL`` from the environment, else
  from ``.env``, else ``sqlite:///dev.db``. A relative SQLite path resolves
  under ``<repo>/instance/`` (Flask-SQLAlchemy 3.1's rule); an absolute one
  is used as is.
- SQLite ONLY. Anything else (Postgres, MySQL, ...) is refused with exit 2
  and nothing is written — this script can never touch a real database.
- Copies with ``sqlite3.Connection.backup()``, so the copy is consistent
  even if server A is a running dev server mid-write.

Prints the absolute destination path with forward slashes, for use in a
``DATABASE_URL``.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_URL = "sqlite:///dev.db"
_SQLITE_PREFIX = "sqlite:///"


class NotSqliteError(ValueError):
    """The configured database is not a SQLite file."""


def resolve_sqlite_path(url: str | None, repo_root: Path) -> Path:
    """Return the SQLite file the app would use for ``url``."""
    url = url or _DEFAULT_URL
    if not url.startswith(_SQLITE_PREFIX):
        raise NotSqliteError(url.split(":", 1)[0])
    path = Path(url[len(_SQLITE_PREFIX):])
    if path.is_absolute():
        return path
    return repo_root / "instance" / path


def clone(src: Path, dest: Path) -> None:
    """Consistent copy of ``src`` to ``dest`` (replacing any old copy)."""
    if not src.exists():
        raise FileNotFoundError(f"source database not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _configured_url(repo_root: Path) -> str | None:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_file = repo_root / ".env"
    if env_file.exists():
        from dotenv import dotenv_values

        return dotenv_values(env_file).get("DATABASE_URL")
    return None


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: python scripts/clone_dev_db.py <destination>\n")
        return 2
    dest = Path(args[0]).resolve()
    try:
        src = resolve_sqlite_path(_configured_url(repo_root), repo_root)
    except NotSqliteError as e:
        # Only the scheme is echoed — never the URL, which may hold credentials.
        sys.stderr.write(
            f"REFUSING: the configured database ({e}://...) is not SQLite. "
            "clone_dev_db.py only copies a local SQLite dev database.\n"
        )
        return 2
    clone(src, dest)
    sys.stdout.write(dest.as_posix() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
