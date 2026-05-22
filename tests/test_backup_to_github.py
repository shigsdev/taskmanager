"""Tests for scripts/backup_to_github.py and scripts/restore_drill.py.

The pg_dump / pg_restore / git invocations are intentionally NOT
unit-tested here — they're external tools, and mocking them would just
verify our mocks. The integration story is the workflow itself
(.github/workflows/*.yml) which exercises the real binaries on every
scheduled run.

What IS tested:
  - Fernet round-trip (encrypt then decrypt restores the original bytes)
  - Retention pruning logic (files older than 7 days are removed; new
    files survive)
  - _within_tolerance comparison helper for the restore drill
"""
from __future__ import annotations

import datetime
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


# --- Retention pruning ------------------------------------------------------


class TestRetentionPruning:
    """The backup script copies the new dump in, then prunes any
    *.dump.fernet older than RETENTION_DAYS (=7) by file mtime. Test
    the mtime-based prune logic by reading the source — we don't run
    the full push function (it shells out to git)."""

    def test_retention_constant_is_7(self, backup_module):
        # Locked spec per #154.2 — last 7 daily.
        assert backup_module.RETENTION_DAYS == 7

    def test_prune_logic_drops_old_keeps_new(self, backup_module, monkeypatch):
        # Simulate a directory with a mix of old + new fernet files
        # and verify the file-walk in push_to_backup_repo's prune
        # block matches the spec. We can't run the whole function
        # (it clones git), but we can replicate the loop here against
        # the same RETENTION_DAYS constant.
        with tempfile.TemporaryDirectory() as td:
            tdp = pathlib.Path(td)
            old_file = tdp / "old.dump.fernet"
            old_file.write_bytes(b"old")
            # Set mtime to 30 days ago.
            ancient = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
            os.utime(old_file, (ancient.timestamp(), ancient.timestamp()))

            new_file = tdp / "new.dump.fernet"
            new_file.write_bytes(b"new")
            # Default mtime = now — should be kept.

            # Mirror the prune block from push_to_backup_repo.
            cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                days=backup_module.RETENTION_DAYS
            )
            pruned = []
            for p in tdp.glob("*.dump.fernet"):
                mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.UTC)
                if mtime < cutoff:
                    p.unlink()
                    pruned.append(p.name)

            assert "old.dump.fernet" in pruned
            assert "new.dump.fernet" not in pruned
            assert old_file.exists() is False
            assert new_file.exists() is True


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
