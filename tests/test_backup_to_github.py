"""Tests for scripts/backup_to_github.py and scripts/restore_drill.py.

pg_dump / pg_restore themselves run only in the workflow
(.github/workflows/*.yml); here pg_dump is faked to check its argv.
git DOES run here, against a local bare repo standing in for the
backup repo — #511 found the 7-day prune had never removed a file,
which a test that copied the prune loop (instead of running
push_to_backup_repo) could not see. Every backup is now kept.

What IS tested:
  - Fernet round-trip; an invalid key exits 2, before the dump
  - push_to_backup_repo keeps every backup; clone / push failures exit 3
  - the password rides in PGPASSWORD, never argv (#164); a failed dump exits 1
  - main(): 0 when verified, 4 when pushed but not verified, alerts on a
    missing secret
  - the status email (success / not verified / unset / failed send)
  - restore drill: the newest dump by name; _within_tolerance
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile

import pytest

# Load the script modules without running their __main__ block.
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def backup_module():
    return _load("backup_to_github")


@pytest.fixture(scope="module")
def restore_module():
    return _load("restore_drill")


# --- Fernet round-trip ------------------------------------------------------


class TestFernetRoundTrip:
    def test_encrypt_then_decrypt_restores_original(
        self, backup_module, restore_module,
    ):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        original = b"-- pg_dump custom format binary bytes here --" * 100

        with tempfile.TemporaryDirectory() as td:
            tdp = pathlib.Path(td)
            plain_path = tdp / "test.dump"
            plain_path.write_bytes(original)

            enc_path = backup_module.encrypt_in_place(plain_path, key)
            assert enc_path.exists()
            assert enc_path.suffix == ".fernet"
            assert not plain_path.exists(), "plaintext should be removed after encrypt"

            decrypted_path = tdp / "round-trip.dump"
            restore_module.decrypt(enc_path, key, decrypted_path)
            assert decrypted_path.read_bytes() == original

    def test_decrypt_with_wrong_key_exits_3(self, backup_module, restore_module):
        from cryptography.fernet import Fernet
        good = Fernet.generate_key().decode()
        bad = Fernet.generate_key().decode()

        with tempfile.TemporaryDirectory() as td:
            tdp = pathlib.Path(td)
            plain = tdp / "test.dump"
            plain.write_bytes(b"some bytes")
            enc = backup_module.encrypt_in_place(plain, good)
            with pytest.raises(SystemExit) as excinfo:
                restore_module.decrypt(enc, bad, tdp / "out.dump")
            assert excinfo.value.code == 3


# --- #164: keep the DB password out of pg_dump's argv -----------------------


class TestSplitDbUrl:
    """split_db_url() must strip the password out of the connection URL
    (so it never lands in pg_dump's argv / `ps aux`) while preserving
    every other connection component."""

    def test_password_is_extracted_and_removed_from_url(self, backup_module):
        url = "postgresql://app_user:s3cr3t@db.railway.app:5432/railway"
        sanitized, password = backup_module.split_db_url(url)
        assert password == "s3cr3t"
        # The password must not survive anywhere in the sanitized URL.
        assert "s3cr3t" not in sanitized
        # ...but every other component must.
        assert sanitized == "postgresql://app_user@db.railway.app:5432/railway"

    def test_query_params_are_preserved(self, backup_module):
        url = "postgresql://u:p@host:5432/db?sslmode=require&connect_timeout=10"
        sanitized, password = backup_module.split_db_url(url)
        assert password == "p"
        assert "p@host" not in sanitized
        assert sanitized.endswith("?sslmode=require&connect_timeout=10")
        assert "@host:5432/db" in sanitized

    def test_url_without_password_is_unchanged(self, backup_module):
        # Local trust-auth URLs carry no password — nothing to strip.
        url = "postgresql://localhost:5432/taskmanager"
        sanitized, password = backup_module.split_db_url(url)
        assert password == ""
        assert sanitized == url

    def test_percent_encoded_password_is_decoded(self, backup_module):
        # PGPASSWORD wants the literal value, so a %-encoded password
        # in the URL must be url-decoded on the way out.
        url = "postgresql://u:p%40ss%2Fword@host:5432/db"
        sanitized, password = backup_module.split_db_url(url)
        assert password == "p@ss/word"
        # The raw (still-encoded) secret must not linger in the URL.
        assert "p%40ss%2Fword" not in sanitized
        assert sanitized == "postgresql://u@host:5432/db"


# --- Tolerance helper -------------------------------------------------------


class TestWithinTolerance:
    def test_equal_passes(self, restore_module):
        assert restore_module._within_tolerance(100, 100) is True

    def test_within_5_percent_passes(self, restore_module):
        assert restore_module._within_tolerance(105, 100) is True
        assert restore_module._within_tolerance(95, 100) is True

    def test_at_5_percent_boundary_passes(self, restore_module):
        # Inclusive boundary — exactly 5% diff is acceptable.
        assert restore_module._within_tolerance(105, 100) is True

    def test_beyond_5_percent_fails(self, restore_module):
        assert restore_module._within_tolerance(106, 100) is False
        assert restore_module._within_tolerance(94, 100) is False

    def test_zero_live_zero_scratch_passes(self, restore_module):
        # Edge: empty DB on both sides should pass (don't div by 0).
        assert restore_module._within_tolerance(0, 0) is True

    def test_zero_live_nonzero_scratch_fails(self, restore_module):
        # If live is empty but scratch isn't, the dump is somehow
        # bigger than reality — fail.
        assert restore_module._within_tolerance(1, 0) is False
# --- #511: every backup is kept -- run against a real local git remote -------


def _git(*args, cwd=None):
    import subprocess

    return subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=cwd, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def origin(tmp_path):
    """A bare repo holding a README and ten old daily dumps — what the real
    backup repo looks like, minus 300 files."""
    bare = tmp_path / "origin.git"
    _git("init", "--bare", "--initial-branch=main", str(bare))
    seed = tmp_path / "seed"
    _git("clone", str(bare), str(seed))
    (seed / "README.md").write_text("backups\n")
    for day in range(1, 11):
        (seed / f"taskmanager-202605{day:02d}T090000Z.dump.fernet").write_bytes(b"x")
    _git("add", "-A", cwd=seed)
    _git("commit", "-m", "seed", cwd=seed)
    _git("push", "origin", "HEAD:main", cwd=seed)
    return bare


def _dumps_in(bare, tmp_path, name="check"):
    out = tmp_path / name
    _git("clone", str(bare), str(out))
    return sorted(p.name for p in out.glob("*.dump.fernet"))


class TestEveryBackupIsKept:

    def test_push_keeps_every_earlier_backup(self, backup_module, origin, tmp_path):
        new = tmp_path / "taskmanager-20261019T073000Z.dump.fernet"
        new.write_bytes(b"new")
        sha = backup_module.push_to_backup_repo(new, str(origin))
        assert len(sha) == 40
        names = _dumps_in(origin, tmp_path)
        assert len(names) == 11
        assert names[-1] == new.name

    def test_no_retention_setting_is_left_to_mislead(self, backup_module):
        assert not hasattr(backup_module, "RETENTION_DAYS")

    def test_same_file_twice_is_not_a_new_commit(self, backup_module, origin, tmp_path):
        new = tmp_path / "taskmanager-20261019T073000Z.dump.fernet"
        new.write_bytes(b"new")
        backup_module.push_to_backup_repo(new, str(origin))
        assert backup_module.push_to_backup_repo(new, str(origin)) == ""

    def test_a_clone_that_fails_exits_3(self, backup_module, tmp_path):
        new = tmp_path / "x.dump.fernet"
        new.write_bytes(b"x")
        with pytest.raises(SystemExit) as exc:
            backup_module.push_to_backup_repo(new, str(tmp_path / "no-such-repo"))
        assert exc.value.code == 3

    def test_a_refused_push_exits_3(self, backup_module, tmp_path):
        """A non-bare origin refuses a push to its checked-out branch."""
        work = tmp_path / "work"
        _git("init", "--initial-branch=main", str(work))
        (work / "README.md").write_text("x")
        _git("add", "-A", cwd=work)
        _git("commit", "-m", "seed", cwd=work)
        new = tmp_path / "taskmanager-20261019T073000Z.dump.fernet"
        new.write_bytes(b"new")
        with pytest.raises(SystemExit) as exc:
            backup_module.push_to_backup_repo(new, str(work))
        assert exc.value.code == 3


class TestRestoreDrillPicksTheNewest:

    def test_newest_by_name_whatever_the_mtimes(self, restore_module, tmp_path):
        names = [f"taskmanager-202605{d:02d}T090000Z.dump.fernet" for d in (3, 10, 7)]
        for i, n in enumerate(names):
            (tmp_path / n).write_bytes(b"x")
            # mtime order: the 10th is OLDEST -- the old sort picked the 7th.
            t = 2_000_000_000 + (0 if "10T" in n else 100 + i)
            os.utime(tmp_path / n, (t, t))
        assert restore_module.newest_backup(tmp_path).name == names[1]

    def test_fetch_uses_the_newest_from_the_repo(self, restore_module, origin, tmp_path):
        latest = restore_module.fetch_latest_backup(str(origin), tmp_path / "drill")
        assert latest.name == "taskmanager-20260510T090000Z.dump.fernet"


class TestPgDump:

    def _fake_run(self, calls, returncode=0):
        def run(cmd, **kw):
            calls.append((cmd, kw))
            out = pathlib.Path(cmd[cmd.index("--file") + 1])
            out.write_bytes(b"PGDMP")

            class P:
                pass
            p = P()
            p.returncode, p.stderr, p.stdout = returncode, "boom", ""
            return p
        return run

    def test_password_rides_in_the_env_not_argv(self, backup_module, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(backup_module.subprocess, "run", self._fake_run(calls))
        meta = backup_module.run_pg_dump(
            "postgresql://u:s3cr3t@db.example:5432/railway", tmp_path / "a.dump")
        (cmd, kw), = calls
        assert not any("s3cr3t" in part for part in cmd)
        assert kw["env"]["PGPASSWORD"] == "s3cr3t"
        assert "--format=custom" in cmd
        assert meta["size_bytes"] == 5

    def test_a_failed_dump_exits_1(self, backup_module, monkeypatch, tmp_path):
        monkeypatch.setattr(backup_module.subprocess, "run",
                            self._fake_run([], returncode=1))
        with pytest.raises(SystemExit) as exc:
            backup_module.run_pg_dump("postgresql://u:p@h/db", tmp_path / "a.dump")
        assert exc.value.code == 1

    def test_an_invalid_key_exits_2(self, backup_module, tmp_path):
        p = tmp_path / "a.dump"
        p.write_bytes(b"x")
        with pytest.raises(SystemExit) as exc:
            backup_module.encrypt_in_place(p, "not-a-fernet-key")
        assert exc.value.code == 2


# --- main(): the job's own verdict ---------------------------------------------


class TestMain:

    @pytest.fixture
    def env(self, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        monkeypatch.setenv("BACKUP_FERNET_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("BACKUP_REPO_URL", "git@example:backups.git")

    @pytest.fixture
    def stubs(self, backup_module, monkeypatch):
        calls = {"emails": [], "dumped": False}

        def dump(url, path):
            calls["dumped"] = True
            path.write_bytes(b"PGDMP")
            return {"size_bytes": 5, "elapsed_sec": 1.0}

        monkeypatch.setattr(backup_module, "run_pg_dump", dump)
        monkeypatch.setattr(backup_module, "push_to_backup_repo", lambda p, u: "a" * 40)
        monkeypatch.setattr(backup_module, "send_status_email",
                            lambda **kw: calls["emails"].append(kw))
        return calls

    def test_a_good_run_is_0_with_a_success_email(self, backup_module, env, stubs,
                                                  monkeypatch):
        monkeypatch.setattr(backup_module, "_query_row_counts",
                            lambda url: {"active_tasks": 41, "goals": 9, "projects": 7})
        assert backup_module.main() == 0
        assert stubs["emails"][-1]["success"] is True

    @pytest.mark.parametrize("counts", [
        {},                                               # count query failed
        {"active_tasks": 0, "goals": 0, "projects": 0},   # an empty database
    ])
    def test_unverified_backup_is_4_with_a_warning(self, backup_module, env, stubs,
                                                   monkeypatch, counts):
        monkeypatch.setattr(backup_module, "_query_row_counts", lambda url: counts)
        assert backup_module.main() == 4
        email = stubs["emails"][-1]
        assert email["success"] is False
        assert email["sha"] == "a" * 40    # it WAS pushed
        assert email["error"]

    def test_a_bad_key_fails_before_the_dump(self, backup_module, env, stubs, monkeypatch):
        monkeypatch.setenv("BACKUP_FERNET_KEY", "nope")
        with pytest.raises(SystemExit) as exc:
            backup_module.main()
        assert exc.value.code == 2
        assert stubs["dumped"] is False
        assert stubs["emails"][-1]["success"] is False

    def test_a_missing_secret_still_sends_the_alert(self, backup_module, env, stubs,
                                                    monkeypatch):
        monkeypatch.delenv("DATABASE_URL")
        with pytest.raises(SystemExit) as exc:
            backup_module.main()
        assert exc.value.code == 1
        assert stubs["emails"] and stubs["emails"][-1]["success"] is False


class TestStatusEmail:

    def test_unset_brevo_sends_nothing(self, backup_module, monkeypatch, capsys):
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        sent = []
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: sent.append(a))
        backup_module.send_status_email(success=True, dump_meta={}, counts={}, sha="x")
        assert sent == []
        assert "skipping email" in capsys.readouterr().err

    def _capture(self, monkeypatch):
        import json as _json

        monkeypatch.setenv("BREVO_API_KEY", "k")
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "from@example.com")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "to@example.com")
        sent = []

        class Resp:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=None):
            sent.append(_json.loads(req.data))
            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        return sent

    def test_success_email_says_every_backup_is_kept(self, backup_module, monkeypatch):
        sent = self._capture(monkeypatch)
        backup_module.send_status_email(
            success=True, dump_meta={"size_bytes": 1}, counts={"active_tasks": 1},
            sha="abc")
        body = sent[0]["textContent"]
        assert "Every daily backup is kept" in body
        assert "pruned" not in body.lower()

    def test_unverified_email_names_the_problem(self, backup_module, monkeypatch):
        sent = self._capture(monkeypatch)
        backup_module.send_status_email(
            success=False, dump_meta={}, counts={}, sha="abc123", error="Empty DB?")
        assert "NOT VERIFIED" in sent[0]["subject"]
        assert "Empty DB?" in sent[0]["textContent"]
        assert "abc123" in sent[0]["textContent"]

    def test_a_failed_send_never_raises(self, backup_module, monkeypatch):
        import urllib.error

        monkeypatch.setenv("BREVO_API_KEY", "k")
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "a@b.c")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "a@b.c")

        def boom(*a, **k):
            raise urllib.error.URLError("down")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        backup_module.send_status_email(success=True, dump_meta={}, counts={}, sha="x")


def test_unverified_reason(backup_module):
    assert backup_module.unverified_reason({}) is not None
    assert backup_module.unverified_reason(
        {"active_tasks": 0, "goals": 0, "projects": 0}) is not None
    assert backup_module.unverified_reason(
        {"active_tasks": 0, "goals": 3, "projects": 0}) is None
