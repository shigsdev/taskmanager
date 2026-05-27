"""Pytest for scripts/check_security_posture.py (#227).

Each check function has positive (should-flag) + negative (should-be-
clean) cases. The checks read real disk paths (docs/security/*.json,
app.py, models.py, CLAUDE.md, `git log`), so tests use monkeypatch
to point `PROJECT_ROOT` at a tmp_path containing fixtures — never
touches the live repo.

Anti-pattern #3 compliance: every test exercises an actual check
function output, never string-matches the script source.
"""
from __future__ import annotations

import datetime
import importlib
import json
from pathlib import Path

import pytest

import scripts.check_security_posture as sp_mod


@pytest.fixture()
def with_project_root(monkeypatch, tmp_path: Path):
    """Point check_security_posture.PROJECT_ROOT at a fresh tmp_path
    so each test fully controls what files are 'in the repo'.
    """
    monkeypatch.setattr(sp_mod, "PROJECT_ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Check (a): pat-inventory
# ---------------------------------------------------------------------------


class TestPatInventoryCheck:
    def _write_inventory(self, root: Path, tokens: list[dict]):
        (root / "docs" / "security").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "security" / "pat-inventory.json").write_text(
            json.dumps({"tokens": tokens}), encoding="utf-8",
        )

    def test_missing_file_is_clean(self, with_project_root: Path):
        # No PAT inventory file at all → not an issue (operator may
        # be SSH-only). Return empty findings list.
        assert sp_mod.check_pat_inventory() == []

    def test_empty_tokens_list_is_clean(self, with_project_root: Path):
        self._write_inventory(with_project_root, [])
        assert sp_mod.check_pat_inventory() == []

    def test_null_expires_at_is_flagged(self, with_project_root: Path):
        # Forever-PAT is the highest-risk shape: a stolen token can
        # never be silently revoked by lapse.
        self._write_inventory(with_project_root, [{
            "name": "no-expiry-pat",
            "expires_at": None,
            "last_used_at": datetime.date.today().isoformat(),
        }])
        findings = sp_mod.check_pat_inventory()
        assert len(findings) == 1
        assert "expires_at is null" in findings[0].detail
        assert "no-expiry-pat" in findings[0].detail

    def test_far_future_expiry_is_flagged(self, with_project_root: Path):
        # > 90 days is the cap. Pick 200 days out to be unambiguous.
        far = datetime.date.today() + datetime.timedelta(days=200)
        self._write_inventory(with_project_root, [{
            "name": "long-leash-pat",
            "expires_at": far.isoformat(),
            "last_used_at": datetime.date.today().isoformat(),
        }])
        findings = sp_mod.check_pat_inventory()
        assert any("long-leash-pat" in f.detail for f in findings)
        assert any("days away" in f.detail for f in findings)

    def test_in_range_expiry_is_clean(self, with_project_root: Path):
        # 60 days out — within the 90-day cap.
        soon = datetime.date.today() + datetime.timedelta(days=60)
        self._write_inventory(with_project_root, [{
            "name": "short-leash-pat",
            "expires_at": soon.isoformat(),
            "last_used_at": datetime.date.today().isoformat(),
        }])
        assert sp_mod.check_pat_inventory() == []

    def test_long_idle_last_used_is_flagged(self, with_project_root: Path):
        # > 60 days since last use → consider revoking.
        old = datetime.date.today() - datetime.timedelta(days=90)
        soon = datetime.date.today() + datetime.timedelta(days=30)
        self._write_inventory(with_project_root, [{
            "name": "idle-pat",
            "expires_at": soon.isoformat(),
            "last_used_at": old.isoformat(),
        }])
        findings = sp_mod.check_pat_inventory()
        assert len(findings) == 1
        assert "idle-pat" in findings[0].detail
        assert "days ago" in findings[0].detail

    def test_recent_last_used_is_clean(self, with_project_root: Path):
        soon = datetime.date.today() + datetime.timedelta(days=30)
        recent = datetime.date.today() - datetime.timedelta(days=10)
        self._write_inventory(with_project_root, [{
            "name": "fresh-pat",
            "expires_at": soon.isoformat(),
            "last_used_at": recent.isoformat(),
        }])
        assert sp_mod.check_pat_inventory() == []

    def test_malformed_json_emits_a_finding(self, with_project_root: Path):
        # Don't silently skip — if the inventory file is unparseable,
        # the audit can't do its job; surface that explicitly.
        (with_project_root / "docs" / "security").mkdir(parents=True)
        (with_project_root / "docs" / "security" / "pat-inventory.json"
        ).write_text("{not valid json", encoding="utf-8")
        findings = sp_mod.check_pat_inventory()
        assert len(findings) == 1
        assert "could not parse" in findings[0].detail

    def test_non_dict_token_entry_skipped(self, with_project_root: Path):
        # Defensive: a malformed entry (e.g. accidentally a bare string)
        # is silently skipped rather than crashing the audit.
        self._write_inventory(with_project_root, [
            "not-a-dict",
            {"name": "real", "expires_at": None,
             "last_used_at": datetime.date.today().isoformat()},
        ])
        findings = sp_mod.check_pat_inventory()
        assert len(findings) == 1  # only the real entry flagged
        assert "real" in findings[0].detail


# ---------------------------------------------------------------------------
# Check (b): oauth-scope-drift
# ---------------------------------------------------------------------------


class TestOAuthScopeDriftCheck:
    def _write_app_py(self, root: Path, scopes: list[str]):
        scope_repr = ",\n            ".join(repr(s) for s in scopes)
        (root / "app.py").write_text(
            "google_bp = make_google_blueprint(\n"
            "    client_id=os.environ.get('GOOGLE_CLIENT_ID'),\n"
            "    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),\n"
            "    scope=[\n"
            f"        {scope_repr},\n"
            "    ],\n"
            ")\n",
            encoding="utf-8",
        )

    def _write_allowlist(self, root: Path, scopes: list[str]):
        (root / "docs" / "security").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "security" / "oauth-scopes.json").write_text(
            json.dumps({"scopes": scopes}), encoding="utf-8",
        )

    def test_matching_scopes_clean(self, with_project_root: Path):
        scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
        self._write_app_py(with_project_root, scopes)
        self._write_allowlist(with_project_root, scopes)
        assert sp_mod.check_oauth_scope_drift() == []

    def test_new_scope_in_code_flagged(self, with_project_root: Path):
        # app.py added a scope not in the allowlist — flag it. This is
        # the "did you mean to expand the blast radius?" alert.
        self._write_app_py(with_project_root, [
            "openid",
            "https://www.googleapis.com/auth/calendar.readonly",  # NEW
        ])
        self._write_allowlist(with_project_root, ["openid"])
        findings = sp_mod.check_oauth_scope_drift()
        assert len(findings) == 1
        assert "calendar.readonly" in findings[0].detail
        assert "NEW" in findings[0].detail

    def test_removed_scope_in_code_flagged(self, with_project_root: Path):
        # Allowlist drift the other way — remind the operator to
        # update the JSON to match the now-narrower app.py scope.
        self._write_app_py(with_project_root, ["openid"])
        self._write_allowlist(with_project_root, [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",  # REMOVED
        ])
        findings = sp_mod.check_oauth_scope_drift()
        assert len(findings) == 1
        assert "userinfo.email" in findings[0].detail
        assert "REMOVED" in findings[0].detail

    def test_missing_allowlist_flagged_with_instructions(
        self, with_project_root: Path,
    ):
        self._write_app_py(with_project_root, ["openid"])
        # NO allowlist file.
        findings = sp_mod.check_oauth_scope_drift()
        assert len(findings) == 1
        assert "missing" in findings[0].detail
        assert "create" in findings[0].detail

    def test_nested_parens_in_app_py_doesnt_break_match(
        self, with_project_root: Path,
    ):
        # The real app.py has `os.environ.get(...)` calls in the
        # make_google_blueprint kwargs ABOVE scope=. The original
        # regex broke on the inner `)` of those calls. This test locks
        # in the simpler `scope=[...]` regex that handles nested parens.
        scope_repr = ",\n            ".join([
            repr("openid"),
            repr("https://www.googleapis.com/auth/userinfo.email"),
            repr("https://www.googleapis.com/auth/userinfo.profile"),
        ])
        (with_project_root / "app.py").write_text(
            "from flask_dance.contrib.google import make_google_blueprint\n"
            "google_bp = make_google_blueprint(\n"
            "    client_id=os.environ.get('GOOGLE_CLIENT_ID'),\n"
            "    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),\n"
            "    scope=[\n"
            f"        {scope_repr},\n"
            "    ],\n"
            ")\n",
            encoding="utf-8",
        )
        self._write_allowlist(with_project_root, [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ])
        # Should be clean — the regex finds all 3 scopes despite the
        # nested function-call parens above them.
        assert sp_mod.check_oauth_scope_drift() == []


# ---------------------------------------------------------------------------
# Check (c): unencrypted-sensitive-columns
# ---------------------------------------------------------------------------


class TestUnencryptedSensitiveColumnsCheck:
    def _write_models(self, root: Path, models_text: str, with_crypto=False):
        (root / "models.py").write_text(models_text, encoding="utf-8")
        (root / "crypto.py").write_text(
            "def encrypt(s): return s\ndef decrypt(s): return s\n",
            encoding="utf-8",
        )
        # crypto.py import in models.py is the signal that SOMETHING
        # is being encrypted — toggled via the with_crypto flag.

    def test_sensitive_column_without_crypto_import_flagged(
        self, with_project_root: Path,
    ):
        self._write_models(with_project_root, (
            "class User:\n"
            "    api_token: Mapped[str] = mapped_column(String(200))\n"
        ))
        findings = sp_mod.check_unencrypted_sensitive_columns()
        assert len(findings) == 1
        assert "api_token" in findings[0].detail.lower()

    def test_secret_named_column_flagged(self, with_project_root: Path):
        self._write_models(with_project_root, (
            "class Cfg:\n"
            "    sendgrid_secret: Mapped[str] = mapped_column(String(200))\n"
        ))
        findings = sp_mod.check_unencrypted_sensitive_columns()
        assert len(findings) == 1
        assert "sendgrid_secret" in findings[0].detail.lower()

    def test_password_named_column_flagged(self, with_project_root: Path):
        self._write_models(with_project_root, (
            "class Acct:\n"
            "    user_password: Mapped[str] = mapped_column(String(200))\n"
        ))
        assert len(sp_mod.check_unencrypted_sensitive_columns()) == 1

    def test_exception_appsetting_key_not_flagged(
        self, with_project_root: Path,
    ):
        # `AppSetting.key` is in _SENSITIVE_COLUMN_EXCEPTIONS — it's
        # the settings-row identifier, not a credential. Lock in.
        self._write_models(with_project_root, (
            "class AppSetting:\n"
            "    key: Mapped[str] = mapped_column(String(100))\n"
        ))
        assert sp_mod.check_unencrypted_sensitive_columns() == []

    def test_crypto_import_present_no_flag(self, with_project_root: Path):
        # When crypto.py IS imported into models.py, the check trusts
        # the column might route through encrypt/decrypt. (False
        # negative for unrouted-but-imported case is acceptable —
        # the goal is catching "forgot to import crypto at all".)
        self._write_models(with_project_root, (
            "from crypto import encrypt, decrypt\n"
            "class User:\n"
            "    api_token: Mapped[str] = mapped_column(String(200))\n"
        ))
        assert sp_mod.check_unencrypted_sensitive_columns() == []

    def test_non_sensitive_name_not_flagged(self, with_project_root: Path):
        # `title`, `description`, etc. — not in the regex.
        self._write_models(with_project_root, (
            "class Task:\n"
            "    title: Mapped[str] = mapped_column(String(200))\n"
            "    description: Mapped[str] = mapped_column(Text)\n"
        ))
        assert sp_mod.check_unencrypted_sensitive_columns() == []

    def test_missing_models_or_crypto_returns_empty(
        self, with_project_root: Path,
    ):
        # Defensive — no models.py = nothing to check. Don't crash.
        assert sp_mod.check_unencrypted_sensitive_columns() == []


# ---------------------------------------------------------------------------
# Check (d): threat-model-freshness
# ---------------------------------------------------------------------------


class TestThreatModelFreshnessCheck:
    def test_freshly_touched_claude_md_clean(
        self, with_project_root: Path, monkeypatch,
    ):
        (with_project_root / "CLAUDE.md").write_text("threat model", encoding="utf-8")
        # Mock subprocess.run to return today's date.
        today_iso = datetime.date.today().isoformat() + "T00:00:00+00:00"

        class _MockResult:
            returncode = 0
            stdout = today_iso

        monkeypatch.setattr(
            sp_mod.subprocess, "run",
            lambda *a, **kw: _MockResult(),
        )
        assert sp_mod.check_threat_model_freshness() == []

    def test_stale_claude_md_flagged(
        self, with_project_root: Path, monkeypatch,
    ):
        (with_project_root / "CLAUDE.md").write_text("stale", encoding="utf-8")
        old_iso = (
            (datetime.date.today() - datetime.timedelta(days=365))
            .isoformat() + "T00:00:00+00:00"
        )

        class _MockResult:
            returncode = 0
            stdout = old_iso

        monkeypatch.setattr(
            sp_mod.subprocess, "run",
            lambda *a, **kw: _MockResult(),
        )
        findings = sp_mod.check_threat_model_freshness()
        assert len(findings) == 1
        assert "CLAUDE.md" in findings[0].path
        assert "review" in findings[0].detail.lower()

    def test_missing_claude_md_returns_empty(self, with_project_root: Path):
        # No CLAUDE.md → no finding (the cron didn't break the audit,
        # the file just isn't here in this checkout).
        assert sp_mod.check_threat_model_freshness() == []

    def test_git_log_failure_does_not_crash(
        self, with_project_root: Path, monkeypatch,
    ):
        (with_project_root / "CLAUDE.md").write_text("x", encoding="utf-8")

        class _MockResult:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(
            sp_mod.subprocess, "run",
            lambda *a, **kw: _MockResult(),
        )
        # Git log error → no finding (don't break the audit; that's a
        # different ops issue and shouldn't shadow the security
        # findings).
        assert sp_mod.check_threat_model_freshness() == []


# ---------------------------------------------------------------------------
# Driver / main + email payload
# ---------------------------------------------------------------------------


def _plant_clean_fixtures(root: Path):
    """Set up tmp_path so all 4 checks have CLEAN inputs. Used by the
    main()-level tests as the baseline state."""
    (root / "docs" / "security").mkdir(parents=True, exist_ok=True)
    # OAuth allowlist matching the app.py scopes below.
    (root / "docs" / "security" / "oauth-scopes.json").write_text(
        json.dumps({"scopes": ["openid"]}),
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        "scope=['openid']\n",
        encoding="utf-8",
    )
    # crypto.py + models.py with no sensitive-named columns.
    (root / "crypto.py").write_text(
        "def encrypt(s): return s\n",
        encoding="utf-8",
    )
    (root / "models.py").write_text(
        "class Task:\n    title: Mapped[str] = mapped_column(String(200))\n",
        encoding="utf-8",
    )


class TestMainExitCodes:
    def test_main_clean_exit_zero(
        self, with_project_root: Path, capsys, monkeypatch,
    ):
        _plant_clean_fixtures(with_project_root)
        sent = []
        monkeypatch.setattr(sp_mod, "send_audit_email",
                            lambda findings, *, per_check_counts: sent.append(
                                {"findings": findings, "counts": per_check_counts},
                            ))
        rc = sp_mod.main([])
        assert rc == 0
        assert "CLEAN" in capsys.readouterr().out
        # Confirmation-on-clean email IS sent (1 call, 0 findings).
        assert len(sent) == 1
        assert sent[0]["findings"] == []
        # Per-check counts come through with each label.
        labels = [label for label, _ in sent[0]["counts"]]
        assert "pat-inventory" in labels
        assert "oauth-scope-drift" in labels
        assert "unencrypted-sensitive-columns" in labels
        assert "threat-model-freshness" in labels

    def test_main_with_findings_exit_one(
        self, with_project_root: Path, capsys, monkeypatch,
    ):
        # Plant the clean baseline THEN flip one input so check (a)
        # reports exactly one finding — verifies main() routes a
        # single finding to the email payload correctly.
        _plant_clean_fixtures(with_project_root)
        (with_project_root / "docs" / "security" / "pat-inventory.json"
        ).write_text(
            json.dumps({"tokens": [{
                "name": "no-expiry",
                "expires_at": None,
                "last_used_at": datetime.date.today().isoformat(),
            }]}),
            encoding="utf-8",
        )
        sent = []
        monkeypatch.setattr(sp_mod, "send_audit_email",
                            lambda findings, *, per_check_counts: sent.append(
                                {"findings": findings, "counts": per_check_counts},
                            ))
        rc = sp_mod.main([])
        assert rc == 1
        assert len(sent) == 1
        assert len(sent[0]["findings"]) == 1
        assert sent[0]["findings"][0].check_id == "pat-inventory"


class TestSendAuditEmail:
    def _patch_sendgrid(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "from@example.com")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "to@example.com")

        captured = {}

        class _FakeResp:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def _fake_urlopen(req, timeout=None):  # noqa: ARG001
            import json as _json
            captured["url"] = req.full_url
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            return _FakeResp()

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        return captured

    def test_clean_run_subject_says_CLEAN(self, monkeypatch):
        cap = self._patch_sendgrid(monkeypatch)
        sp_mod.send_audit_email(
            findings=[],
            per_check_counts=[
                ("pat-inventory", 0),
                ("oauth-scope-drift", 0),
                ("unencrypted-sensitive-columns", 0),
                ("threat-model-freshness", 0),
            ],
        )
        assert "CLEAN" in cap["body"]["subject"]
        body_text = cap["body"]["content"][0]["value"]
        assert "ALL CHECKS CLEAN" in body_text
        assert "pat-inventory: 0 finding(s)" in body_text

    def test_findings_run_subject_has_count(self, monkeypatch):
        cap = self._patch_sendgrid(monkeypatch)
        f = sp_mod.Finding(check_id="pat-inventory", detail="leaky token")
        sp_mod.send_audit_email(
            findings=[f],
            per_check_counts=[
                ("pat-inventory", 1),
                ("oauth-scope-drift", 0),
                ("unencrypted-sensitive-columns", 0),
                ("threat-model-freshness", 0),
            ],
        )
        assert "1 finding(s)" in cap["body"]["subject"]
        body_text = cap["body"]["content"][0]["value"]
        assert "== pat-inventory (1 finding(s)) ==" in body_text
        assert "leaky token" in body_text

    def test_no_email_sent_when_sendgrid_unconfigured(
        self, monkeypatch, capsys,
    ):
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("DIGEST_FROM_EMAIL", raising=False)
        monkeypatch.delenv("DIGEST_TO_EMAIL", raising=False)
        sp_mod.send_audit_email(
            findings=[],
            per_check_counts=[("pat-inventory", 0)],
        )
        err = capsys.readouterr().err
        assert "SendGrid not configured" in err

    def test_module_loads_cleanly(self):
        # Defensive — if a circular import sneaks in, this fails.
        importlib.reload(sp_mod)
