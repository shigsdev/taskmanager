"""#518: scripts/rotate_db_password.py — changes the Postgres password over
the public URL and prints the new URL. Nothing here touches a real database:
``connect`` is a fake that records what it was asked to do."""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"

URL = "postgresql://postgres:oldPass%2Fx@junction.proxy.rlwy.net:33732/railway"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load("rotate_db_password")


class FakeConn:
    def __init__(self, log, url):
        self.log, self.url = log, url

    def execute(self, query):
        self.log.append(("execute", self.url, query))

    def close(self):
        self.log.append(("close", self.url))


def _fake_connect(log, fail_urls=()):
    def connect(url):
        log.append(("connect", url))
        if url in fail_urls:
            raise OSError("connection refused")
        return FakeConn(log, url)
    return connect


def _run(mod, *, url=URL, confirm="ROTATE", env=None, fail_urls=()):
    log, out, asked = [], io.StringIO(), []
    rc = mod.main(
        environ={} if env is None else env,
        ask_secret=lambda prompt: (asked.append(prompt), url)[1],
        ask=lambda prompt: confirm,
        connect=_fake_connect(log, fail_urls),
        out=out,
    )
    return rc, log, out.getvalue(), asked


class TestHelpers:
    def test_new_password_is_long_and_url_safe(self, mod):
        a, b = mod.new_password(), mod.new_password()
        assert a != b and len(a) >= 40
        assert all(c.isalnum() or c in "-_" for c in a)

    def test_with_password_keeps_the_rest(self, mod):
        new = mod.with_password(URL, "N3w-pass_word")
        assert new == "postgresql://postgres:N3w-pass_word@junction.proxy.rlwy.net:33732/railway"

    def test_with_password_keeps_query(self, mod):
        new = mod.with_password(URL + "?sslmode=require", "p")
        assert new.endswith("/railway?sslmode=require")

    def test_user_of(self, mod):
        assert mod.user_of(URL) == "postgres"

    @pytest.mark.parametrize("url, words", [
        ("", "isn't a database URL"),
        ("https://example.com/x", "isn't a database URL"),
        ("postgresql://junction.proxy.rlwy.net:33732/railway", "missing"),
        ("postgresql://postgres:pw@postgres.railway.internal:5432/railway", "DATABASE_PUBLIC_URL"),
        ("postgresql://postgres:pw@junction.proxy.rlwy.net/railway", "no port"),
        ("postgresql://postgres:pw@host:notaport/railway", "isn't a database URL"),
    ])
    def test_check_url_refuses(self, mod, url, words):
        assert words in mod.check_url(url)

    def test_check_url_accepts_the_public_url(self, mod):
        assert mod.check_url(URL) is None

    def test_alter_password_quotes_both_parts(self, mod):
        # The password goes in as a literal and the user as an identifier,
        # so a quote in either can't break out of the statement.
        log = []
        mod.alter_password(FakeConn(log, URL), 'we"ird', "it's")
        query = log[0][2]
        rendered = query.as_string(None)
        assert rendered == """ALTER ROLE "we""ird" WITH PASSWORD 'it''s'"""


class TestMain:
    def test_changes_then_checks_the_new_password(self, mod):
        rc, log, out, asked = _run(mod)
        assert rc == 0
        assert asked  # the URL was asked for, hidden
        # Old URL: connect, ALTER, close. Then the new URL connects.
        assert log[0] == ("connect", URL)
        assert log[1][0] == "execute"
        password = out.split("New password:")[1].split()[0]
        assert password in log[1][2].as_string(None)
        new_url = mod.with_password(URL, password)
        assert ("connect", new_url) in log
        assert f"New public URL: {new_url}" in out
        assert "POSTGRES_PASSWORD" in out
        assert "gh secret set DATABASE_URL --body (Get-Clipboard)" in out

    def test_url_from_the_environment_skips_the_question(self, mod):
        rc, _log, _out, asked = _run(mod, url="ignored",
                                     env={"DATABASE_PUBLIC_URL": URL})
        assert rc == 0 and asked == []

    def test_not_confirmed_changes_nothing(self, mod):
        rc, log, out, _ = _run(mod, confirm="rotate please")
        assert rc == 2 and log == []
        assert "Nothing changed." in out

    def test_bad_url_changes_nothing(self, mod):
        rc, log, out, _ = _run(mod, url="postgresql://u:p@postgres.railway.internal:5432/d")
        assert rc == 2 and log == []
        assert "DATABASE_PUBLIC_URL" in out

    def test_connect_failure_says_nothing_changed_and_hides_the_url(self, mod):
        rc, log, out, _ = _run(mod, fail_urls=(URL,))
        assert rc == 1
        assert not any(e[0] == "execute" for e in log)
        assert "Nothing changed" in out
        assert "oldPass" not in out and "junction" not in out

    def test_new_password_not_connecting_warns_but_shows_it(self, mod):
        # The ALTER ran, so the new password is the only one that works now:
        # it must still be printed.
        log, out = [], io.StringIO()
        calls = {"n": 0}

        def connect(url):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("no")
            return FakeConn(log, url)

        rc = mod.main(environ={"DATABASE_PUBLIC_URL": URL}, ask=lambda p: "ROTATE",
                      connect=connect, out=out)
        text = out.getvalue()
        assert rc == 3
        assert "New password:" in text and "didn't connect" in text
