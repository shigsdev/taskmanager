"""Tests for scripts/clone_dev_db.py (#394).

The gate script runs mobile Playwright on a second local server with its own
copy of the dev database. The copy must be of the SAME file the app uses,
consistent even if the source is being written, and the script must never
touch anything that is not SQLite.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import clone_dev_db


def _make_db(path, rows=3):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [(f"r{i}",) for i in range(rows)])
    con.commit()
    con.close()


class TestResolveSqlitePath:
    def test_default_is_instance_dev_db(self, tmp_path):
        assert clone_dev_db.resolve_sqlite_path(None, tmp_path) == (
            tmp_path / "instance" / "dev.db"
        )

    def test_relative_path_resolves_under_instance(self, tmp_path):
        assert clone_dev_db.resolve_sqlite_path("sqlite:///other.db", tmp_path) == (
            tmp_path / "instance" / "other.db"
        )

    def test_absolute_path_is_kept(self, tmp_path):
        target = (tmp_path / "elsewhere" / "x.db").resolve()
        url = "sqlite:///" + target.as_posix()
        assert clone_dev_db.resolve_sqlite_path(url, tmp_path) == target

    @pytest.mark.parametrize("url", [
        "postgresql://u:p@host/db",
        "postgresql+psycopg://u:p@host/db",
        "postgres://u:p@host/db",
        "mysql://u:p@host/db",
    ])
    def test_non_sqlite_is_refused(self, url, tmp_path):
        with pytest.raises(clone_dev_db.NotSqliteError):
            clone_dev_db.resolve_sqlite_path(url, tmp_path)


class TestClone:
    def test_copy_has_same_rows_and_source_is_untouched(self, tmp_path):
        src = tmp_path / "instance" / "dev.db"
        src.parent.mkdir()
        _make_db(src, rows=5)
        before = src.read_bytes()
        dest = tmp_path / "copy.db"

        clone_dev_db.clone(src, dest)

        con = sqlite3.connect(dest)
        assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 5
        con.close()
        assert src.read_bytes() == before

    def test_overwrites_a_stale_copy(self, tmp_path):
        src = tmp_path / "src.db"
        _make_db(src, rows=2)
        dest = tmp_path / "copy.db"
        _make_db(dest, rows=9)

        clone_dev_db.clone(src, dest)

        con = sqlite3.connect(dest)
        assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        con.close()

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            clone_dev_db.clone(tmp_path / "nope.db", tmp_path / "copy.db")


class TestMain:
    def test_prints_forward_slash_destination(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "instance" / "dev.db"
        src.parent.mkdir()
        _make_db(src)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///dev.db")
        dest = tmp_path / "out" / "dev-mobile.db"

        rc = clone_dev_db.main([str(dest)], repo_root=tmp_path)

        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert "\\" not in out
        assert out == dest.resolve().as_posix()
        assert dest.exists()

    def test_refuses_postgres_with_exit_2_and_writes_nothing(
        self, tmp_path, monkeypatch, capsys,
    ):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example/prod")
        dest = tmp_path / "copy.db"

        rc = clone_dev_db.main([str(dest)], repo_root=tmp_path)

        assert rc == 2
        assert not dest.exists()
        err = capsys.readouterr().err
        assert "not SQLite" in err
        assert "u:p@" not in err  # never echo credentials
