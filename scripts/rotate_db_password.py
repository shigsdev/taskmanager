"""Change the production Postgres password in one step (#518).

Railway's Postgres keeps its password in two places: inside Postgres (the
password the database checks) and in the Postgres service's
``POSTGRES_PASSWORD`` variable, which every connection URL is built from.
Setting the variable alone does not change what Postgres checks. This script
does the Postgres half over the public URL and prints the new password and
the new public URL, so the variable half is a paste. Help → Rotate every
secret, step 13, walks through it.

Usage (PowerShell, in the taskmanager folder):

    python scripts\\rotate_db_password.py

It asks for the CURRENT ``DATABASE_PUBLIC_URL`` (Railway → Postgres →
Variables); what you paste is hidden. Setting ``DATABASE_PUBLIC_URL`` in the
environment skips the question. Type ROTATE to go ahead.

Once it has run, the app can't open new database connections until
``POSTGRES_PASSWORD`` holds the new password and Railway has deployed, so do
that straight away.

It prints the new password on purpose (like the mint scripts print their
tokens): you paste it into Railway and 1Password. Nothing is logged or
written to disk.

Exit codes: 0 changed and checked, 1 couldn't connect or change it,
2 bad URL or not confirmed, 3 changed but the new password didn't connect.
"""
from __future__ import annotations

import getpass
import os
import secrets
import sys
from collections.abc import Callable
from typing import Any, TextIO
from urllib.parse import quote, unquote, urlsplit, urlunsplit

CONFIRM_WORD = "ROTATE"


def new_password() -> str:
    """43 URL-safe characters: nothing in it needs escaping in a URL."""
    return secrets.token_urlsafe(32)


def check_url(url: str) -> str | None:
    """Why ``url`` can't be used, or None when it can."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "That isn't a database URL."
    if parts.scheme not in ("postgres", "postgresql"):
        return "That isn't a database URL (it should start with postgresql://)."
    if not parts.hostname or not parts.username or not parts.password:
        return "That URL is missing the user, password or host."
    if parts.hostname.endswith(".railway.internal"):
        return ("That's the private DATABASE_URL, which only works inside "
                "Railway. Copy DATABASE_PUBLIC_URL instead.")
    if port is None:
        return "That URL has no port. Copy DATABASE_PUBLIC_URL as it is."
    return None


def user_of(url: str) -> str:
    return unquote(urlsplit(url).username or "")


def with_password(url: str, password: str) -> str:
    """``url`` with its password replaced; everything else kept as it was."""
    parts = urlsplit(url)
    user = parts.netloc.rsplit("@", 1)[0].split(":", 1)[0]
    host = parts.netloc.rsplit("@", 1)[1]
    netloc = f"{user}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def alter_password(conn: Any, user: str, password: str) -> None:
    from psycopg import sql

    conn.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
        sql.Identifier(user), sql.Literal(password)))


def _connect(url: str) -> Any:
    import psycopg

    return psycopg.connect(url, autocommit=True, connect_timeout=15)


def main(
    *,
    environ: dict[str, str] | None = None,
    ask_secret: Callable[[str], str] = getpass.getpass,
    ask: Callable[[str], str] = input,
    connect: Callable[[str], Any] = _connect,
    out: TextIO = sys.stdout,
) -> int:
    env = os.environ if environ is None else environ
    url = (env.get("DATABASE_PUBLIC_URL") or "").strip()
    if not url:
        url = ask_secret(
            "Paste the CURRENT DATABASE_PUBLIC_URL (Railway > Postgres > "
            "Variables). It won't show as you paste: ").strip()
    problem = check_url(url)
    if problem:
        print(problem, file=out)
        return 2

    user = user_of(url)
    print(f"This changes the password of database user '{user}'. The app "
          "can't open new connections until you put the new password in "
          "Railway and deploy.", file=out)
    if ask(f"Type {CONFIRM_WORD} to go ahead: ").strip() != CONFIRM_WORD:
        print("Nothing changed.", file=out)
        return 2

    password = new_password()
    try:
        conn = connect(url)
        try:
            alter_password(conn, user, password)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — say why, never the URL
        print(f"Couldn't change it: {type(e).__name__}. Nothing changed. "
              "Check the URL is the current DATABASE_PUBLIC_URL.", file=out)
        return 1

    new_url = with_password(url, password)
    checked = True
    try:
        connect(new_url).close()
    except Exception:  # noqa: BLE001
        checked = False

    print("", file=out)
    print("The password is changed.", file=out)
    print(f"New password:   {password}", file=out)
    print(f"New public URL: {new_url}", file=out)
    print("", file=out)
    print("Now, straight away:", file=out)
    print("  1. Railway > Postgres > Variables: set POSTGRES_PASSWORD to the "
          "new password.", file=out)
    print("  2. Copy the new public URL, then run:  gh secret set "
          "DATABASE_URL --body (Get-Clipboard)", file=out)
    print("  3. Save the new password in 1Password.", file=out)
    if not checked:
        print("", file=out)
        print("Warning: the new password didn't connect on a test. Keep the "
              "password above, and check it in Railway before you deploy.",
              file=out)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
