"""Pytest for scripts/check_test_coverage.py (#229).

The actual pytest-with-coverage run isn't exercised here (too slow,
adds 30+s per test). Instead we test the three pure-logic checks
(`check_overall_drift`, `check_per_file_drift`,
`check_critical_path_floors`) + the `_audit` driver against synthetic
inputs. The pytest-runner path is verified once at script-import
time.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.check_test_coverage as cov_mod


@pytest.fixture()
def with_project_root(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cov_mod, "PROJECT_ROOT", tmp_path)
    # _BASELINE_PATH is computed from PROJECT_ROOT at import time, so
    # we also patch it explicitly so the tests see a baseline file
    # under tmp_path.
    monkeypatch.setattr(
        cov_mod, "_BASELINE_PATH",
        tmp_path / "docs" / "audit" / "coverage-baseline.json",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Check: overall-coverage-drift
# ---------------------------------------------------------------------------


class TestCheckOverallDrift:
    def test_within_tolerance_no_finding(self):
        # Baseline 84.1, current 83.5 → diff 0.6pp (under 1.0 tolerance)
        assert cov_mod.check_overall_drift(
            83.5, {"overall": 84.1},
        ) == []

    def test_above_baseline_no_finding(self):
        # Coverage going UP is great — never flag.
        assert cov_mod.check_overall_drift(
            90.0, {"overall": 84.1},
        ) == []

    def test_drift_over_tolerance_flagged(self):
        # 84.1 → 80.5 = 3.6pp drop → flag (over 1pp tolerance).
        findings = cov_mod.check_overall_drift(
            80.5, {"overall": 84.1},
        )
        assert len(findings) == 1
        assert "3.6pp" in findings[0].detail
        assert findings[0].check_id == "overall-coverage-drift"

    def test_exactly_at_tolerance_no_finding(self):
        # 84.1 - 1.0 = 83.1 — diff equals tolerance, NOT > tolerance.
        assert cov_mod.check_overall_drift(
            83.1, {"overall": 84.1},
        ) == []

    def test_missing_overall_baseline_skipped(self):
        # Defensive — baseline without "overall" key returns no
        # findings rather than crashing.
        assert cov_mod.check_overall_drift(
            80.0, {"per_file": {}},
        ) == []


# ---------------------------------------------------------------------------
# Check: per-file-coverage-drift
# ---------------------------------------------------------------------------


class TestCheckPerFileDrift:
    def test_file_within_tolerance_no_finding(self):
        per_file = {"task_service.py": 87.0}
        baseline = {"per_file": {"task_service.py": 90.0}}
        # 3pp drop, under 5pp tolerance.
        assert cov_mod.check_per_file_drift(per_file, baseline) == []

    def test_file_over_tolerance_flagged(self):
        per_file = {"task_service.py": 75.0}
        baseline = {"per_file": {"task_service.py": 90.0}}
        findings = cov_mod.check_per_file_drift(per_file, baseline)
        assert len(findings) == 1
        assert findings[0].path == "task_service.py"
        assert "15.0pp" in findings[0].detail

    def test_file_above_baseline_no_finding(self):
        per_file = {"task_service.py": 95.0}
        baseline = {"per_file": {"task_service.py": 90.0}}
        # Coverage UP — celebrate, don't flag.
        assert cov_mod.check_per_file_drift(per_file, baseline) == []

    def test_new_file_not_in_baseline_skipped(self):
        # A new file not yet in the baseline isn't a regression —
        # operator will run --write-baseline to capture it later.
        per_file = {"new_feature.py": 50.0}
        baseline = {"per_file": {"task_service.py": 90.0}}
        assert cov_mod.check_per_file_drift(per_file, baseline) == []

    def test_deleted_file_in_baseline_skipped(self):
        # File in baseline but missing from current run → file was
        # deleted/moved. Not our problem.
        per_file = {}
        baseline = {"per_file": {"gone.py": 80.0}}
        assert cov_mod.check_per_file_drift(per_file, baseline) == []

    def test_multiple_files_each_flagged_independently(self):
        per_file = {
            "a.py": 50.0,  # was 90 → drop 40pp, flag
            "b.py": 88.0,  # was 90 → drop 2pp, no flag
            "c.py": 70.0,  # was 85 → drop 15pp, flag
        }
        baseline = {
            "per_file": {"a.py": 90.0, "b.py": 90.0, "c.py": 85.0},
        }
        findings = cov_mod.check_per_file_drift(per_file, baseline)
        paths = sorted(f.path for f in findings)
        assert paths == ["a.py", "c.py"]


# ---------------------------------------------------------------------------
# Check: critical-path-floor
# ---------------------------------------------------------------------------


class TestCheckCriticalPathFloors:
    def test_above_floor_no_finding(self):
        # Every critical-path file is well above its floor.
        # voice_service.py: 95.0 satisfies the post-#239 90% floor.
        per_file = {
            "auth.py": 95.0,
            "task_service.py": 90.0,
            "crypto.py": 98.0,
            "recurring_service.py": 88.0,
            "reflection_service.py": 85.0,
            "voice_service.py": 95.0,
        }
        assert cov_mod.check_critical_path_floors(per_file) == []

    def test_below_floor_flagged(self):
        # auth.py at 80% (floor 90) → flag.
        per_file = {"auth.py": 80.0}
        findings = cov_mod.check_critical_path_floors(per_file)
        assert len(findings) == 1
        assert findings[0].path == "auth.py"
        assert "80.0%" in findings[0].detail
        assert "90.0%" in findings[0].detail  # floor mentioned

    def test_missing_file_skipped(self):
        # If a critical-path file isn't in the coverage data
        # (rare — would happen on a partial test run), skip rather
        # than emit a confusing "0%" finding.
        per_file = {"other.py": 100.0}
        assert cov_mod.check_critical_path_floors(per_file) == []

    def test_exactly_at_floor_no_finding(self):
        # Floor is `< floor_pct`, not `<= floor_pct`. Boundary case.
        per_file = {"auth.py": 90.0}  # exactly at the 90.0 floor
        assert cov_mod.check_critical_path_floors(per_file) == []


# ---------------------------------------------------------------------------
# _audit driver (combines the three checks)
# ---------------------------------------------------------------------------


class TestAudit:
    def _write_baseline(self, root: Path, payload: dict):
        (root / "docs" / "audit").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "audit" / "coverage-baseline.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )

    def test_clean_run_no_findings(self, with_project_root: Path):
        # Plant a baseline that matches current → no drift.
        self._write_baseline(with_project_root, {
            "overall": 84.0,
            "per_file": {"task_service.py": 90.0, "auth.py": 95.0,
                         "crypto.py": 98.0},
        })
        findings, per_check = cov_mod._audit(
            per_file={"task_service.py": 90.0, "auth.py": 95.0,
                      "crypto.py": 98.0},
            overall=84.0,
        )
        assert findings == []
        # All three checks enumerated in per_check_counts.
        labels = [c[0] for c in per_check]
        assert labels == [
            "overall-coverage-drift",
            "per-file-coverage-drift",
            "critical-path-floor",
        ]

    def test_overall_drift_alone(self, with_project_root: Path):
        self._write_baseline(with_project_root, {
            "overall": 90.0, "per_file": {"crypto.py": 98.0},
        })
        findings, per_check = cov_mod._audit(
            per_file={"crypto.py": 98.0},
            overall=80.0,
        )
        assert len(findings) == 1
        assert findings[0].check_id == "overall-coverage-drift"

    def test_missing_baseline_returns_helpful_finding(
        self, with_project_root: Path,
    ):
        # No baseline file → single finding telling operator to run
        # --write-baseline. Not noisy on fresh forks.
        findings, per_check = cov_mod._audit(
            per_file={"any.py": 50.0}, overall=50.0,
        )
        assert len(findings) == 1
        assert "missing" in findings[0].detail
        assert "--write-baseline" in findings[0].detail

    def test_all_three_check_categories_aggregate(
        self, with_project_root: Path,
    ):
        # Drift overall + per-file + critical-path all at once.
        self._write_baseline(with_project_root, {
            "overall": 90.0,
            "per_file": {
                "task_service.py": 95.0,
                "auth.py": 95.0,
            },
        })
        findings, per_check = cov_mod._audit(
            per_file={
                "task_service.py": 70.0,  # 25pp drop = per-file flag
                "auth.py": 70.0,           # 25pp drop AND below 90% floor
            },
            overall=70.0,  # 20pp drop = overall flag
        )
        # 1 overall + 2 per-file + 1 critical-path-floor = 4
        # (auth.py fires on per-file drift AND critical floor)
        # task_service.py fires only on per-file drift (current 70 >=
        # floor 85 — wait no, 70 < 85, so it ALSO fires the floor)
        # Hmm: critical floor for task_service is 85.0. 70 < 85 → flag.
        # So expect 1 + 2 + 2 = 5.
        check_ids = sorted(f.check_id for f in findings)
        assert check_ids.count("overall-coverage-drift") == 1
        assert check_ids.count("per-file-coverage-drift") == 2
        assert check_ids.count("critical-path-floor") == 2


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


class TestBaselineIO:
    def test_read_baseline_missing_returns_none(self, with_project_root):
        assert cov_mod._read_baseline() is None

    def test_read_baseline_malformed_returns_none(self, with_project_root):
        (with_project_root / "docs" / "audit").mkdir(parents=True)
        (with_project_root / "docs" / "audit" / "coverage-baseline.json"
        ).write_text("{not valid json", encoding="utf-8")
        assert cov_mod._read_baseline() is None

    def test_write_baseline_round_trip(self, with_project_root):
        cov_mod._write_baseline(83.5, {"a.py": 90.0, "b.py": 75.5})
        data = cov_mod._read_baseline()
        assert data is not None
        assert data["overall"] == 83.5
        assert data["per_file"]["a.py"] == 90.0
        assert "generated_at" in data
        # Docstring inside the JSON for the operator.
        assert "_doc" in data

    def test_write_baseline_rounds_to_2dp(self, with_project_root):
        cov_mod._write_baseline(83.456789, {"a.py": 90.123456})
        data = cov_mod._read_baseline()
        assert data["overall"] == 83.46
        assert data["per_file"]["a.py"] == 90.12


# ---------------------------------------------------------------------------
# extract_per_file_and_total
# ---------------------------------------------------------------------------


class TestExtract:
    def test_parses_pytest_cov_json_shape(self):
        cov_json = {
            "files": {
                "a.py": {"summary": {"percent_covered": 87.5}},
                "b.py": {"summary": {"percent_covered": 92.0}},
            },
            "totals": {"percent_covered": 89.7},
        }
        per_file, total = cov_mod._extract_per_file_and_total(cov_json)
        assert per_file == {"a.py": 87.5, "b.py": 92.0}
        assert total == 89.7

    def test_handles_missing_keys_gracefully(self):
        per_file, total = cov_mod._extract_per_file_and_total({})
        assert per_file == {}
        assert total == 0.0

    def test_skips_files_without_summary(self):
        cov_json = {
            "files": {
                "ok.py": {"summary": {"percent_covered": 90.0}},
                "bad.py": {},  # missing summary
            },
            "totals": {"percent_covered": 90.0},
        }
        per_file, _ = cov_mod._extract_per_file_and_total(cov_json)
        assert per_file == {"ok.py": 90.0}


# ---------------------------------------------------------------------------
# Email subject + body
# ---------------------------------------------------------------------------


class TestSendAuditEmail:
    def _patch_brevo(self, monkeypatch):
        monkeypatch.setenv("BREVO_API_KEY", "fake")
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

    def test_clean_subject_includes_overall_pct(self, monkeypatch):
        cap = self._patch_brevo(monkeypatch)
        cov_mod.send_audit_email(
            findings=[],
            per_check_counts=[
                ("overall-coverage-drift", 0),
                ("per-file-coverage-drift", 0),
                ("critical-path-floor", 0),
            ],
            overall=84.1,
        )
        assert "all clear" in cap["body"]["subject"]
        assert "84.1%" in cap["body"]["subject"]
        # #302: overall % also shown in the body header.
        assert "Overall coverage: 84.1%" in cap["body"]["textContent"]

    def test_findings_subject_includes_count_and_pct(self, monkeypatch):
        cap = self._patch_brevo(monkeypatch)
        f = cov_mod.Finding(
            check_id="overall-coverage-drift",
            detail="dropped 5pp",
        )
        cov_mod.send_audit_email(
            findings=[f],
            per_check_counts=[
                ("overall-coverage-drift", 1),
                ("per-file-coverage-drift", 0),
                ("critical-path-floor", 0),
            ],
            overall=79.0,
        )
        assert "1 issue to review" in cap["body"]["subject"]
        assert "79.0%" in cap["body"]["subject"]
        body = cap["body"]["textContent"]
        assert "dropped 5pp" in body
        assert "overall-coverage-drift — 1 finding" in body

    def test_no_email_when_unconfigured(self, monkeypatch, capsys):
        monkeypatch.delenv("BREVO_API_KEY", raising=False)
        cov_mod.send_audit_email(
            findings=[], per_check_counts=[("x", 0)], overall=84.0,
        )
        assert "Brevo not configured" in capsys.readouterr().err
