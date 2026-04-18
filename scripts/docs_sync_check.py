#!/usr/bin/env python
"""Audit docs vs code consistency.

Currently checks:
  1. Every env var referenced in code (via ``os.environ.get(...)`` or
     ``os.environ["..."]``) is documented in README.md's env-var table.

Intentionally NOT checked (yet — could be added):
  - Every docstring claim of "narrow scope" (could grep for known
    phrases and require corresponding ADR file)
  - Every file referenced in ARCHITECTURE.md exists
  - Every BACKLOG ✅ item has a corresponding test or ADR

Exit codes:
  0  All checks pass
  1  At least one undocumented item
  2  Usage / repo structure error

Usage:
    python scripts/docs_sync_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Env vars that are set by the platform / framework, not by us, and
# therefore don't need to be in our README env-var table.
ALLOWED_IMPLICIT_VARS = {
    # Flask / Werkzeug
    "FLASK_ENV",
    "FLASK_APP",
    "FLASK_DEBUG",
    "PORT",
    # Standard system env
    "PATH",
    "HOME",
    "USER",
    "USERPROFILE",
    "PWD",
    # Railway-injected (documented as a class — we don't list every one)
    # The triple-tripwire rejects ANY of these being set in dev.
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_GIT_COMMIT_SHA",
    # OAuthlib internal
    "OAUTHLIB_INSECURE_TRANSPORT",
    # Local dev bypass — explicitly documented in CLAUDE.md but not in
    # the README env-var table because users should never set it.
    "LOCAL_DEV_BYPASS_AUTH",
    # Pytest / coverage
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "COVERAGE_FILE",
    # Test-only flags handled in conftest
    "APP_LOG_DISABLE",  # documented but the alias above
    # Gunicorn / WSGI conventions — set by Railway or the Procfile, not
    # by the user. gunicorn.conf.py reads WEB_CONCURRENCY directly.
    "WEB_CONCURRENCY",
}


def find_env_vars_in_code() -> set[str]:
    """Scan all .py files for env var references.

    Scope is *our* Python files (repo root + first-party subdirs). We
    explicitly skip:
      - virtualenv directories (site-packages is noise)
      - tests/ (uses fake env vars via monkeypatch)
      - migrations/ (Alembic-generated)
      - .claude/ (Claude Code worktrees / scratch files)
      - node_modules, __pycache__, caches
    """
    SKIP_PARTS = {
        ".venv", ".venv-mac", "venv", "env",
        "tests", "migrations", "node_modules",
        ".claude", "__pycache__", ".pytest_cache", ".ruff_cache",
    }
    pattern = re.compile(r'os\.environ(?:\.get\(|\[)["\']([A-Z_][A-Z0-9_]*)["\']')
    vars_found: set[str] = set()
    for py_file in REPO.rglob("*.py"):
        if any(p in SKIP_PARTS for p in py_file.parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        vars_found.update(pattern.findall(text))
    return vars_found


def find_env_vars_in_readme() -> set[str]:
    """Pull env var names from README.md's env-var table.

    The table uses backtick-wrapped UPPER_SNAKE in the first column.
    """
    readme_path = REPO / "README.md"
    if not readme_path.exists():
        return set()
    text = readme_path.read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*`([A-Z_][A-Z0-9_]*)`\s*\|", text))


def main() -> int:
    code_vars = find_env_vars_in_code()
    doc_vars = find_env_vars_in_readme()

    missing = code_vars - doc_vars - ALLOWED_IMPLICIT_VARS
    if missing:
        print("ERROR: env vars used in code but not documented in README.md:")
        for var in sorted(missing):
            print(f"  - {var}")
        print()
        print("Either add them to the env-var table in README.md, or add to")
        print("ALLOWED_IMPLICIT_VARS in this script if they're framework-level.")
        return 1

    extra = doc_vars - code_vars - ALLOWED_IMPLICIT_VARS
    if extra:
        print("WARN: env vars in README but never referenced in code:")
        for var in sorted(extra):
            print(f"  - {var}")
        print("(Did the code stop using them? Either remove from README or")
        print("verify they're consumed by an external tool / startup script.)")
        # Warn-only — sometimes README lists Railway-injected vars for
        # operator awareness even though no code reads them.

    print(f"docs_sync_check OK: {len(code_vars)} env vars referenced, all documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
