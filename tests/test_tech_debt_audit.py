"""Pytest for scripts/check_tech_debt.py (#228).

Each check has positive + negative cases. Same fixture pattern as
test_bug_pattern_scan.py / test_security_posture_scan.py — point
PROJECT_ROOT at a tmp_path so each test fully controls the file
tree it sees, and patch ``_walk_tracked_files`` to walk the
tmp_path directly (no real git in the fixture).
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

import scripts.check_tech_debt as td_mod


@pytest.fixture()
def with_project_root(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(td_mod, "PROJECT_ROOT", tmp_path)

    def _walk_under_tmp():
        return [p for p in tmp_path.rglob("*") if p.is_file()]

    monkeypatch.setattr(td_mod, "_walk_tracked_files", _walk_under_tmp)
    return tmp_path


# ---------------------------------------------------------------------------
# Check (a): TODO/FIXME accumulation
# ---------------------------------------------------------------------------


class TestTodoFixmeAccumulationCheck:
    def test_clean_codebase_no_findings(self, with_project_root: Path):
        (with_project_root / "service.py").write_text(
            "def f(): pass\n", encoding="utf-8",
        )
        assert td_mod.check_todo_fixme_accumulation() == []

    def test_per_file_hotspot_flagged(self, with_project_root: Path):
        # > 5 TODOs in one file = hotspot finding.
        (with_project_root / "service.py").write_text(
            "\n".join(f"# TODO marker {i}" for i in range(7)),
            encoding="utf-8",
        )
        findings = td_mod.check_todo_fixme_accumulation()
        # 7 markers in 1 file: under the grand-total threshold (25)
        # but over the per-file threshold (5). One finding only.
        assert len(findings) == 1
        assert "service.py" in findings[0].path
        assert "7" in findings[0].detail

    def test_grand_total_threshold_flagged(self, with_project_root: Path):
        # Spread 30 markers across 6 files of 5 each — none hits the
        # per-file threshold, but the grand total exceeds 25.
        for i in range(6):
            (with_project_root / f"f{i}.py").write_text(
                "\n".join(["# TODO marker"] * 5),
                encoding="utf-8",
            )
        findings = td_mod.check_todo_fixme_accumulation()
        assert len(findings) == 1
        assert "30 TODO" in findings[0].detail
        assert "threshold" in findings[0].detail.lower()

    def test_both_per_file_and_total_can_fire(self, with_project_root: Path):
        # One huge file (15 markers) + 4 small files of 3 each = total
        # 27, which is over 25 AND the big file hits the per-file
        # threshold. Two findings — the hotspot file + the grand-total.
        (with_project_root / "huge.py").write_text(
            "\n".join(["# TODO huge"] * 15),
            encoding="utf-8",
        )
        for i in range(4):
            (with_project_root / f"small_{i}.py").write_text(
                "\n".join(["# TODO small"] * 3),
                encoding="utf-8",
            )
        findings = td_mod.check_todo_fixme_accumulation()
        assert len(findings) == 2  # huge.py hotspot + grand-total

    def test_tests_dir_skipped(self, with_project_root: Path):
        tests = with_project_root / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text(
            "\n".join(["# TODO in test"] * 50),
            encoding="utf-8",
        )
        assert td_mod.check_todo_fixme_accumulation() == []

    def test_markdown_files_skipped(self, with_project_root: Path):
        # BACKLOG.md / CLAUDE.md legitimately reference the pattern.
        (with_project_root / "BACKLOG.md").write_text(
            "\n".join(["TODO: ship the feature"] * 50),
            encoding="utf-8",
        )
        assert td_mod.check_todo_fixme_accumulation() == []

    def test_audit_script_self_skipped(self, with_project_root: Path):
        # The audit script + its tests reference the regex literal
        # "TODO" and would false-positive otherwise.
        scripts = with_project_root / "scripts"
        scripts.mkdir()
        (scripts / "check_tech_debt.py").write_text(
            "\n".join(["# TODO regex"] * 50),
            encoding="utf-8",
        )
        assert td_mod.check_todo_fixme_accumulation() == []

    def test_all_4_marker_types_count(self, with_project_root: Path):
        # TODO, FIXME, XXX, HACK — all 4 count toward the total.
        (with_project_root / "service.py").write_text(
            "# TODO 1\n# FIXME 2\n# XXX 3\n# HACK 4\n"
            + "\n".join(["# TODO filler"] * 3),
            encoding="utf-8",
        )
        # 7 markers (4 distinct kinds + 3 filler) > per-file threshold of 5
        findings = td_mod.check_todo_fixme_accumulation()
        assert len(findings) == 1
        assert "7" in findings[0].detail

    def test_word_boundary_avoids_substring_false_positives(
        self, with_project_root: Path,
    ):
        # `# todo` (lowercase) shouldn't match (word-boundary regex
        # is case-sensitive). `# AUTOMODE` shouldn't match TODO either.
        (with_project_root / "service.py").write_text(
            "# todo lowercase\n# AUTOMODE\n# xxxhack\n",
            encoding="utf-8",
        )
        assert td_mod.check_todo_fixme_accumulation() == []


# ---------------------------------------------------------------------------
# Check (b): dependency drift
# ---------------------------------------------------------------------------


class TestDependencyDriftCheck:
    def test_major_behind_pip_dep_flagged(self, with_project_root, monkeypatch):
        class _MockProc:
            returncode = 0
            stdout = json.dumps([{
                "name": "boltons",
                "version": "21.0.0",
                "latest_version": "25.0.0",
            }])
        # Patch both pip + npm subprocess.run; first call = pip, second = npm
        calls = {"i": 0}
        def fake_run(cmd, **kw):
            calls["i"] += 1
            if calls["i"] == 1:
                return _MockProc()
            class _Empty:
                returncode = 0
                stdout = ""
            return _Empty()
        monkeypatch.setattr(td_mod.subprocess, "run", fake_run)
        findings = td_mod.check_dependency_drift()
        assert len(findings) == 1
        assert "boltons" in findings[0].detail
        assert "4 major" in findings[0].detail

    def test_same_major_pip_dep_not_flagged(self, with_project_root, monkeypatch):
        """Minor / patch bumps are NOT flagged — this audit only
        catches major-version drift to avoid noise."""
        class _MockProc:
            returncode = 0
            stdout = json.dumps([{
                "name": "requests",
                "version": "2.31.0",
                "latest_version": "2.32.4",  # same major
            }])
        class _Empty:
            returncode = 0
            stdout = ""

        def fake_run(cmd, **kw):
            return _MockProc() if "pip" in str(cmd) else _Empty()
        monkeypatch.setattr(td_mod.subprocess, "run", fake_run)
        assert td_mod.check_dependency_drift() == []

    def test_npm_outdated_flagged(self, with_project_root, monkeypatch):
        class _PipEmpty:
            returncode = 0
            stdout = ""
        class _NpmProc:
            # npm outdated returns non-zero EXIT when there ARE outdated
            # packages — that's not an error from our POV.
            returncode = 1
            stdout = json.dumps({
                "express": {"current": "4.21.1", "latest": "5.1.0"},
            })
        calls = {"i": 0}
        def fake_run(cmd, **kw):
            calls["i"] += 1
            return _PipEmpty() if calls["i"] == 1 else _NpmProc()
        monkeypatch.setattr(td_mod.subprocess, "run", fake_run)
        findings = td_mod.check_dependency_drift()
        assert len(findings) == 1
        assert "express" in findings[0].detail
        assert "1 major" in findings[0].detail

    def test_tool_missing_returns_empty(self, with_project_root, monkeypatch):
        """If pip / npm aren't on the runner, the check silently
        returns no findings rather than crashing."""
        def fake_run(cmd, **kw):
            raise FileNotFoundError("not on this host")
        monkeypatch.setattr(td_mod.subprocess, "run", fake_run)
        assert td_mod.check_dependency_drift() == []

    def test_malformed_pip_json_skipped(self, with_project_root, monkeypatch):
        class _Bad:
            returncode = 0
            stdout = "not json"
        class _Empty:
            returncode = 0
            stdout = ""
        calls = {"i": 0}
        def fake_run(cmd, **kw):
            calls["i"] += 1
            return _Bad() if calls["i"] == 1 else _Empty()
        monkeypatch.setattr(td_mod.subprocess, "run", fake_run)
        # Don't crash; just no findings from the malformed source.
        assert td_mod.check_dependency_drift() == []


class TestSemverMajor:
    def test_basic(self):
        assert td_mod._semver_major("1.2.3") == 1
        assert td_mod._semver_major("25.0.0") == 25
        assert td_mod._semver_major("v3.1") == 3
        assert td_mod._semver_major("0.0.1") == 0

    def test_unparseable_returns_none(self):
        assert td_mod._semver_major("") is None
        assert td_mod._semver_major("abc") is None
        assert td_mod._semver_major(None) is None

    def test_no_dot_ok(self):
        # Single-integer version like "10" still parses.
        assert td_mod._semver_major("10") == 10


# ---------------------------------------------------------------------------
# Check (c): stale tests
# ---------------------------------------------------------------------------


class TestStaleTestsCheck:
    def test_fresh_test_not_flagged(self, with_project_root, monkeypatch):
        tests = with_project_root / "tests"
        tests.mkdir()
        (tests / "test_fresh.py").write_text("def test_x(): pass\n",
                                              encoding="utf-8")
        today = datetime.date.today().isoformat() + "T00:00:00+00:00"

        class _Result:
            returncode = 0
            stdout = today

        monkeypatch.setattr(
            td_mod.subprocess, "run",
            lambda *a, **kw: _Result(),
        )
        assert td_mod.check_stale_tests() == []

    def test_stale_test_flagged(self, with_project_root, monkeypatch):
        tests = with_project_root / "tests"
        tests.mkdir()
        (tests / "test_stale.py").write_text("def test_x(): pass\n",
                                              encoding="utf-8")
        # 1 year ago — well past the 180-day threshold.
        long_ago = (
            (datetime.date.today() - datetime.timedelta(days=365))
            .isoformat() + "T00:00:00+00:00"
        )

        class _Result:
            returncode = 0
            stdout = long_ago

        monkeypatch.setattr(
            td_mod.subprocess, "run",
            lambda *a, **kw: _Result(),
        )
        findings = td_mod.check_stale_tests()
        assert len(findings) == 1
        assert "test_stale.py" in findings[0].path
        assert "365 days" in findings[0].detail

    def test_no_tests_dir_returns_empty(self, with_project_root):
        # Tests directory missing → not a finding, just nothing to check.
        assert td_mod.check_stale_tests() == []

    def test_git_failure_does_not_crash(
        self, with_project_root, monkeypatch,
    ):
        tests = with_project_root / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text("", encoding="utf-8")

        class _Failed:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(
            td_mod.subprocess, "run",
            lambda *a, **kw: _Failed(),
        )
        # Don't crash; just no findings.
        assert td_mod.check_stale_tests() == []


# ---------------------------------------------------------------------------
# Driver / main + email
# ---------------------------------------------------------------------------


def _plant_clean_fixtures(root: Path):
    """Minimal tree that makes every check report 0 findings.
    Used by the main() exit-code tests below.
    """
    # No production-source files with TODO markers, no stale tests
    # (no tests dir at all → 0 findings), and we monkeypatch
    # subprocess.run so dependency-drift returns empty.


class TestMainExitCodes:
    def test_main_clean_exit_zero(
        self, with_project_root: Path, capsys, monkeypatch,
    ):
        # Make dependency-drift return [] by stubbing subprocess.
        class _Empty:
            returncode = 0
            stdout = ""

        monkeypatch.setattr(
            td_mod.subprocess, "run",
            lambda *a, **kw: _Empty(),
        )
        sent = []
        monkeypatch.setattr(td_mod, "send_audit_email",
                            lambda findings, *, per_check_counts: sent.append(
                                {"findings": findings, "counts": per_check_counts},
                            ))
        rc = td_mod.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "CLEAN" in out
        assert len(sent) == 1
        assert sent[0]["findings"] == []
        labels = [label for label, _ in sent[0]["counts"]]
        assert "todo-fixme-accumulation" in labels
        assert "dependency-drift" in labels
        assert "stale-tests" in labels

    def test_main_with_findings_exit_one(
        self, with_project_root: Path, capsys, monkeypatch,
    ):
        # Plant a hotspot so todo-fixme reports a finding.
        (with_project_root / "huge.py").write_text(
            "\n".join(["# TODO marker"] * 8),
            encoding="utf-8",
        )

        class _Empty:
            returncode = 0
            stdout = ""

        monkeypatch.setattr(
            td_mod.subprocess, "run",
            lambda *a, **kw: _Empty(),
        )
        sent = []
        monkeypatch.setattr(td_mod, "send_audit_email",
                            lambda findings, *, per_check_counts: sent.append(
                                {"findings": findings, "counts": per_check_counts},
                            ))
        rc = td_mod.main()
        assert rc == 1
        assert len(sent) == 1
        assert len(sent[0]["findings"]) == 1
        assert sent[0]["findings"][0].check_id == "todo-fixme-accumulation"


class TestSendAuditEmail:
    def _patch_sendgrid(self, monkeypatch):
        monkeypatch.setenv("SENDGRID_API_KEY", "fake")
        monkeypatch.setenv("DIGEST_FROM_EMAIL", "from@x")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "to@x")
        captured = {}

        class _FakeResp:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def _fake_urlopen(req, timeout=None):  # noqa: ARG001
            import json as _j
            captured["body"] = _j.loads(req.data.decode("utf-8"))
            return _FakeResp()

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        return captured

    def test_clean_subject(self, monkeypatch):
        cap = self._patch_sendgrid(monkeypatch)
        td_mod.send_audit_email(
            findings=[],
            per_check_counts=[("todo-fixme-accumulation", 0),
                              ("dependency-drift", 0),
                              ("stale-tests", 0)],
        )
        assert "CLEAN" in cap["body"]["subject"]
        body = cap["body"]["content"][0]["value"]
        assert "ALL CHECKS CLEAN" in body
        assert "dependency-drift: 0 finding(s)" in body

    def test_findings_subject(self, monkeypatch):
        cap = self._patch_sendgrid(monkeypatch)
        f = td_mod.Finding(check_id="dependency-drift",
                           detail="pkg X stuck at 1 — latest 4 (3 major)")
        td_mod.send_audit_email(
            findings=[f],
            per_check_counts=[("todo-fixme-accumulation", 0),
                              ("dependency-drift", 1),
                              ("stale-tests", 0)],
        )
        assert "1 finding(s)" in cap["body"]["subject"]
        body = cap["body"]["content"][0]["value"]
        assert "pkg X stuck at 1" in body

    def test_no_email_when_unconfigured(self, monkeypatch, capsys):
        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        td_mod.send_audit_email(
            findings=[],
            per_check_counts=[("todo-fixme-accumulation", 0)],
        )
        assert "SendGrid not configured" in capsys.readouterr().err
