"""Tests for `scripts/backlog_autofile.py` (#242, 2026-05-27).

The autofile module owns the BACKLOG.md `## Auto-filed by recurring
audits` section. These tests cover the upsert state machine:

- New finding → insert row
- Repeat finding → refresh last_seen, preserve first_seen + notes
- Disappearing finding → annotate `🟢 auto-detected resolved YYYY-MM-DD`
- Re-appearing finding → strip the prior resolved annotation
- Path-keyed vs path-less findings (dedup tail differs)
- Operator-edited notes survive a re-run

Each test gets a temporary BACKLOG.md so the real file isn't touched.
The fixtures use monkeypatch to point the module at the temp file.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import backlog_autofile


@dataclass
class _Finding:
    """Duck-typed mock matching the audit Finding dataclasses."""
    check_id: str
    detail: str = ""
    path: str = ""


_MINIMAL_BACKLOG = """\
# BACKLOG (test fixture)

## Resolved

(nothing)

## Auto-filed by recurring audits

<!-- explainer block -->

| Audit row | Finding | First seen | Last seen | Notes / Status |
|---|---|---|---|---|
<!-- autofile-section-end -->

## Backlog (prioritized)

(nothing)
"""


@pytest.fixture()
def temp_backlog(tmp_path, monkeypatch):
    """Point the module at a per-test temp BACKLOG.md."""
    path = tmp_path / "BACKLOG.md"
    path.write_text(_MINIMAL_BACKLOG, encoding="utf-8")
    monkeypatch.setattr(backlog_autofile, "BACKLOG_PATH", path)
    return path


class TestSlug:
    """Slug normalisation underpinning dedup keys."""

    def test_basic_path_slugs_cleanly(self):
        assert backlog_autofile._slug("static/style.css") == "static-style.css"

    def test_lowercases(self):
        assert backlog_autofile._slug("Foo Bar") == "foo-bar"

    def test_collapses_runs(self):
        assert backlog_autofile._slug("a   b//c") == "a-b-c"

    def test_strips_outer_hyphens(self):
        assert backlog_autofile._slug("--foo--") == "foo"

    def test_long_detail_string_does_not_break(self):
        # A path-less finding's detail might be a long sentence; the
        # slug just needs to be stable + non-empty.
        slug = backlog_autofile._slug(
            "overall coverage at 83.5% dropped below baseline 86.0% - 1pp",
        )
        assert "overall-coverage" in slug
        # Slug must not contain pipe / newline / table-breaking chars.
        assert "|" not in slug
        assert "\n" not in slug


class TestMakeMarkerKey:
    """Canonical marker-key composition."""

    def test_includes_all_three_parts(self):
        key = backlog_autofile.make_marker_key(
            "tech-debt", "dependency-drift", "cryptography",
        )
        assert key == "tech-debt/dependency-drift/cryptography"

    def test_slugifies_path_tail(self):
        key = backlog_autofile.make_marker_key(
            "bug-pattern", "bare-1fr-grids", "static/style.css",
        )
        assert key == "bug-pattern/bare-1fr-grids/static-style.css"


class TestInsertNew:
    """First time a finding is seen → new row appears."""

    def test_inserts_path_keyed_row(self, temp_backlog):
        findings = [_Finding(
            check_id="dependency-drift",
            detail="pip dep stuck at 46.0.7 — latest is 48.0.0",
            path="cryptography",
        )]
        result = backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-27",
        )
        assert result == {"inserted": 1, "updated": 0, "auto_resolved": 0}

        text = temp_backlog.read_text(encoding="utf-8")
        assert "audit-row: tech-debt/dependency-drift/cryptography" in text
        # The finding text shows path-prefixed.
        assert "**cryptography**" in text
        # Both dates set to today.
        assert "| 2026-05-27 | 2026-05-27 |" in text

    def test_inserts_path_less_row_using_detail_slug(self, temp_backlog):
        # Coverage-audit's overall-drift finding has path="(repo)" — the
        # autofile should slugify the detail instead.
        findings = [_Finding(
            check_id="overall-coverage-drift",
            detail="overall coverage at 83.5% < baseline 86.0% - 1pp",
            path="(repo)",
        )]
        result = backlog_autofile.upsert_findings(
            "coverage", findings, today="2026-05-27",
        )
        assert result["inserted"] == 1

        text = temp_backlog.read_text(encoding="utf-8")
        assert (
            "audit-row: coverage/overall-coverage-drift/overall-coverage"
            in text
        )
        # Path-less row renders detail directly (no `**path**` prefix).
        assert "**(repo)**" not in text

    def test_multiple_findings_one_run(self, temp_backlog):
        findings = [
            _Finding(check_id="dependency-drift", path="cryptography",
                     detail="2 majors behind"),
            _Finding(check_id="dependency-drift", path="gunicorn",
                     detail="4 majors behind"),
        ]
        result = backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-27",
        )
        assert result == {"inserted": 2, "updated": 0, "auto_resolved": 0}

        text = temp_backlog.read_text(encoding="utf-8")
        assert "tech-debt/dependency-drift/cryptography" in text
        assert "tech-debt/dependency-drift/gunicorn" in text


class TestUpdateExisting:
    """Second run with the same finding → last_seen refreshes, first_seen stays."""

    def test_repeat_finding_refreshes_last_seen(self, temp_backlog):
        findings = [_Finding(
            check_id="dependency-drift",
            detail="2 majors behind",
            path="cryptography",
        )]
        # First run: insert.
        backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-20",
        )
        # Second run: same finding, later date.
        result = backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-27",
        )
        assert result == {"inserted": 0, "updated": 1, "auto_resolved": 0}

        text = temp_backlog.read_text(encoding="utf-8")
        # first_seen sticks to 2026-05-20, last_seen advances to 27.
        assert "| 2026-05-20 | 2026-05-27 |" in text

    def test_repeat_finding_preserves_operator_notes(self, temp_backlog):
        """Bug shape: operator adds context to the Notes cell ("in flight
        on feature/foo"); next audit run must NOT clobber it."""
        findings = [_Finding(
            check_id="dependency-drift",
            detail="2 majors behind",
            path="cryptography",
        )]
        backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-20",
        )

        # Operator edits the file by hand to add a note.
        text = temp_backlog.read_text(encoding="utf-8")
        text = text.replace(
            "| 2026-05-20 | 2026-05-20 |  |",
            "| 2026-05-20 | 2026-05-20 | in flight on feature/241-bump |",
        )
        temp_backlog.write_text(text, encoding="utf-8")

        # Re-run.
        backlog_autofile.upsert_findings(
            "tech-debt", findings, today="2026-05-27",
        )

        text = temp_backlog.read_text(encoding="utf-8")
        assert "in flight on feature/241-bump" in text


class TestAutoResolved:
    """A previously-flagged finding stops appearing → row gets the
    🟢 auto-detected resolved annotation but isn't deleted."""

    def test_disappearing_finding_gets_annotated(self, temp_backlog):
        # Day 1: cryptography drift flagged.
        backlog_autofile.upsert_findings(
            "tech-debt",
            [_Finding(
                check_id="dependency-drift",
                detail="2 majors behind",
                path="cryptography",
            )],
            today="2026-05-20",
        )
        # Day 2: audit clean-passes (no findings at all).
        result = backlog_autofile.upsert_findings(
            "tech-debt", [], today="2026-05-27",
        )
        assert result == {"inserted": 0, "updated": 0, "auto_resolved": 1}

        text = temp_backlog.read_text(encoding="utf-8")
        assert "🟢 auto-detected resolved 2026-05-27" in text
        # The row itself stays in place (history preserved).
        assert "tech-debt/dependency-drift/cryptography" in text

    def test_auto_resolved_is_idempotent(self, temp_backlog):
        """Running clean-passes for two consecutive weeks shouldn't
        re-stamp the resolved annotation. The note stays at the first
        clean-pass date for human review clarity."""
        backlog_autofile.upsert_findings(
            "tech-debt",
            [_Finding(check_id="x", detail="d", path="p")],
            today="2026-05-20",
        )
        # First clean-pass.
        backlog_autofile.upsert_findings(
            "tech-debt", [], today="2026-05-27",
        )
        # Second clean-pass — should NOT re-stamp.
        result = backlog_autofile.upsert_findings(
            "tech-debt", [], today="2026-06-03",
        )
        assert result["auto_resolved"] == 0

        text = temp_backlog.read_text(encoding="utf-8")
        # Original resolved date stays.
        assert "🟢 auto-detected resolved 2026-05-27" in text
        # No second annotation got appended. (We count concrete
        # date-stamped instances, NOT the YYYY-MM-DD placeholder in
        # the explainer comment.)
        assert text.count("🟢 auto-detected resolved 2026-") == 1
        assert "🟢 auto-detected resolved 2026-06-03" not in text

    def test_reappearing_finding_strips_resolved_marker(self, temp_backlog):
        """Day 1: flag. Day 2: clean → auto-resolved. Day 3: re-flagged
        → resolved marker stripped + last_seen refreshed (the issue is
        back; operator needs to see that)."""
        finding = _Finding(check_id="x", detail="d", path="p")
        backlog_autofile.upsert_findings(
            "tech-debt", [finding], today="2026-05-20",
        )
        backlog_autofile.upsert_findings(
            "tech-debt", [], today="2026-05-27",
        )
        result = backlog_autofile.upsert_findings(
            "tech-debt", [finding], today="2026-06-03",
        )
        assert result == {"inserted": 0, "updated": 1, "auto_resolved": 0}

        text = temp_backlog.read_text(encoding="utf-8")
        # Resolved marker stripped from the row (the explainer block
        # always contains the literal phrase as a placeholder, so we
        # check for a concrete date stamp not in the file).
        assert "🟢 auto-detected resolved 2026-" not in text
        # last_seen advanced; first_seen preserved.
        assert "| 2026-05-20 | 2026-06-03 |" in text

    def test_other_audit_findings_dont_trigger_auto_resolve(
        self, temp_backlog,
    ):
        """If the bug-pattern audit runs clean but the tech-debt row
        exists, the tech-debt row should NOT auto-resolve just because
        bug-pattern was empty. Audit_name scoping matters."""
        backlog_autofile.upsert_findings(
            "tech-debt",
            [_Finding(check_id="x", detail="d", path="p")],
            today="2026-05-20",
        )
        # Now a bug-pattern run with no findings shouldn't touch the
        # tech-debt row.
        result = backlog_autofile.upsert_findings(
            "bug-pattern", [], today="2026-05-27",
        )
        assert result == {"inserted": 0, "updated": 0, "auto_resolved": 0}

        text = temp_backlog.read_text(encoding="utf-8")
        # The explainer block always contains the literal phrase as a
        # placeholder; check for a concrete date stamp instead.
        assert "🟢 auto-detected resolved 2026-" not in text


class TestSectionAnchorErrors:
    """Defensive errors when BACKLOG.md is missing required anchors."""

    def test_missing_section_raises(self, tmp_path, monkeypatch):
        path = tmp_path / "BACKLOG.md"
        path.write_text("# A backlog without the autofile section\n",
                        encoding="utf-8")
        monkeypatch.setattr(backlog_autofile, "BACKLOG_PATH", path)
        with pytest.raises(ValueError, match="autofile section"):
            backlog_autofile.upsert_findings("tech-debt", [])

    def test_missing_backlog_file_raises(self, tmp_path, monkeypatch):
        path = tmp_path / "BACKLOG.md"  # does not exist
        monkeypatch.setattr(backlog_autofile, "BACKLOG_PATH", path)
        with pytest.raises(FileNotFoundError):
            backlog_autofile.upsert_findings("tech-debt", [])


class TestRowOrderStable:
    """Rows are sorted by marker_key on re-render so diffs are stable."""

    def test_rows_render_in_alphabetical_marker_order(self, temp_backlog):
        backlog_autofile.upsert_findings(
            "tech-debt",
            [
                _Finding(check_id="dependency-drift", path="zebra", detail="z"),
                _Finding(check_id="dependency-drift", path="alpha", detail="a"),
            ],
            today="2026-05-27",
        )
        text = temp_backlog.read_text(encoding="utf-8")
        alpha_idx = text.index("/alpha")
        zebra_idx = text.index("/zebra")
        assert alpha_idx < zebra_idx


class TestCliEntryPoint:
    """The argparse CLI for ad-hoc seeding."""

    def test_cli_inserts_a_row(self, temp_backlog, capsys):
        rc = backlog_autofile.main([
            "--audit", "tech-debt",
            "--check-id", "dependency-drift",
            "--path", "cryptography",
            "--detail", "2 majors behind",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "inserted=1" in out
        text = temp_backlog.read_text(encoding="utf-8")
        assert "tech-debt/dependency-drift/cryptography" in text
