"""Tests for scripts/check_advisories.py — the weekly scheduled
dependency-advisory check (#210).

The real pip-audit / npm audit invocations are intentionally NOT
exercised here — they're external tools, mocking them would just
verify our mocks. We DO test the parsing, the clean-vs-finding logic,
the email-decision branching, and the email payload shape.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def mod():
    """Load scripts/check_advisories.py without running its __main__ block."""
    spec = importlib.util.spec_from_file_location(
        "check_advisories", SCRIPTS_DIR / "check_advisories.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["check_advisories"] = m
    spec.loader.exec_module(m)
    return m


def _fake_run(stdout: str, stderr: str = "", returncode: int = 0):
    """Build a CompletedProcess stand-in that subprocess.run would
    return — only the fields the script reads."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# --- pip-audit parsing -------------------------------------------------------


class TestRunPipAudit:
    def test_clean_when_no_dependencies_have_vulns(self, mod):
        # pip-audit JSON shape — clean tree has dependencies but no vulns.
        clean_json = json.dumps({"dependencies": [
            {"name": "flask", "version": "3.1.3", "vulns": []},
            {"name": "requests", "version": "2.33.0", "vulns": []},
        ]})
        with patch("subprocess.run", return_value=_fake_run(clean_json, "", 0)):
            clean, findings, _ = mod.run_pip_audit()
        assert clean is True
        assert findings == []

    def test_findings_parsed_from_dependencies_block(self, mod):
        vuln_json = json.dumps({"dependencies": [
            {
                "name": "pytest", "version": "8.3.2",
                "vulns": [{
                    "id": "GHSA-6w46-j5rx-g56g",
                    "fix_versions": ["9.0.3"],
                    "description": "test runner CVE example",
                }],
            },
            {"name": "flask", "version": "3.1.3", "vulns": []},
        ]})
        with patch("subprocess.run", return_value=_fake_run(vuln_json, "", 1)):
            clean, findings, _ = mod.run_pip_audit()
        assert clean is False
        assert len(findings) == 1
        f = findings[0]
        assert f["name"] == "pytest"
        assert f["version"] == "8.3.2"
        assert f["id"] == "GHSA-6w46-j5rx-g56g"
        assert f["fix_versions"] == ["9.0.3"]

    def test_unparseable_json_treated_as_not_clean(self, mod):
        with patch("subprocess.run", return_value=_fake_run("not json", "boom", 2)):
            clean, findings, raw = mod.run_pip_audit()
        assert clean is False
        assert findings == []
        # Raw output (stdout + stderr concatenated) is preserved for
        # the Actions log.
        assert "boom" in raw


# --- npm audit parsing -------------------------------------------------------


class TestRunNpmAudit:
    def test_clean_when_no_high_critical(self, mod):
        # npm audit may report low/moderate vulns — script filters
        # them out; only high/critical count.
        clean_json = json.dumps({"vulnerabilities": {
            "left-pad": {"severity": "moderate"},
            "underscore": {"severity": "low"},
        }})
        with patch("subprocess.run", return_value=_fake_run(clean_json, "", 1)):
            clean, findings, _ = mod.run_npm_audit()
        assert clean is True
        assert findings == []

    def test_high_severity_is_a_finding(self, mod):
        vuln_json = json.dumps({"vulnerabilities": {
            "express": {"severity": "high"},
            "lodash": {"severity": "critical"},
            "left-pad": {"severity": "moderate"},  # filtered out
        }})
        with patch("subprocess.run", return_value=_fake_run(vuln_json, "", 1)):
            clean, findings, _ = mod.run_npm_audit()
        assert clean is False
        assert {f["name"] for f in findings} == {"express", "lodash"}
        assert {f["severity"] for f in findings} == {"high", "critical"}

    def test_unparseable_json_treated_as_not_clean(self, mod):
        with patch("subprocess.run", return_value=_fake_run("not json", "", 0)):
            clean, findings, _ = mod.run_npm_audit()
        assert clean is False
        assert findings == []


# --- email decision + payload ------------------------------------------------


class TestSendAdvisoryEmail:
    def _env(self, monkeypatch):
        """Wire up the three Brevo env vars the script needs."""
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "from@taskmanager")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "to@taskmanager")

    def test_skips_when_brevo_not_configured(self, mod, monkeypatch, capsys):
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        # urllib.request.urlopen must NOT be called when env is missing.
        with patch("urllib.request.urlopen") as urlopen:
            mod.send_advisory_email([{"name": "x"}], [])
        assert urlopen.call_count == 0
        captured = capsys.readouterr()
        assert "Brevo not configured" in captured.err

    def test_sends_email_with_findings_in_body(self, mod, monkeypatch):
        self._env(monkeypatch)
        pip_findings = [{
            "name": "pytest", "version": "8.3.2",
            "id": "GHSA-6w46-j5rx-g56g", "fix_versions": ["9.0.3"],
        }]
        npm_findings = [{"name": "express", "severity": "high"}]

        captured_body = {}

        class _FakeResp:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout):
            captured_body["data"] = req.data.decode("utf-8")
            # Brevo authenticates via the `api-key` header (ADR-007 — key
            # never in the URL); urllib title-cases the header key.
            captured_body["auth"] = req.get_header("Api-key")
            return _FakeResp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            mod.send_advisory_email(pip_findings, npm_findings)

        payload = json.loads(captured_body["data"])
        assert captured_body["auth"] == "xkeysib-test"
        assert payload["sender"]["email"] == "from@taskmanager"
        assert payload["to"][0]["email"] == "to@taskmanager"
        # Subject reflects the total count.
        assert "2 new CVE(s)" in payload["subject"]
        body_text = payload["textContent"]
        assert "pytest 8.3.2" in body_text
        assert "GHSA-6w46-j5rx-g56g" in body_text
        assert "fix: 9.0.3" in body_text
        assert "express (high)" in body_text
        assert "requirements-dev.txt" in body_text  # action hint

    def test_no_findings_means_no_email_call(self, mod, monkeypatch):
        # The script's main() short-circuits BEFORE calling send when
        # both audits are clean. We exercise main() here.
        self._env(monkeypatch)
        with (
            patch("check_advisories.run_pip_audit", return_value=(True, [], "")),
            patch("check_advisories.run_npm_audit", return_value=(True, [], "")),
            patch("urllib.request.urlopen") as urlopen,
        ):
            assert mod.main() == 0
            assert urlopen.call_count == 0


# --- main() exit-code contract ----------------------------------------------


class TestMainExit:
    def test_exit_0_when_both_clean(self, mod, monkeypatch):
        with (
            patch("check_advisories.run_pip_audit", return_value=(True, [], "ok")),
            patch("check_advisories.run_npm_audit", return_value=(True, [], "ok")),
        ):
            assert mod.main() == 0

    def test_exit_1_when_pip_has_findings(self, mod, monkeypatch):
        # Send-email is best-effort and shouldn't change the exit code.
        with (
            patch("check_advisories.run_pip_audit",
                  return_value=(False, [{"name": "x", "version": "1",
                                         "id": "Y", "fix_versions": []}], "")),
            patch("check_advisories.run_npm_audit", return_value=(True, [], "")),
            patch("check_advisories.send_advisory_email"),
        ):
            assert mod.main() == 1

    def test_exit_1_when_npm_has_findings(self, mod):
        with (
            patch("check_advisories.run_pip_audit", return_value=(True, [], "")),
            patch("check_advisories.run_npm_audit",
                  return_value=(False, [{"name": "y", "severity": "high"}], "")),
            patch("check_advisories.send_advisory_email"),
        ):
            assert mod.main() == 1
