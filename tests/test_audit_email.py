"""Unit tests for scripts/audit_email.py — the shared audit-alert body
renderer (#302). Exercises the OUTPUT of render() directly (not a string
match against source): subject shape, preamble, per-check descriptions,
only-fired detail blocks, compact clean list, header/subject extras.
"""
from __future__ import annotations

from scripts import audit_email

_COMMON = {
    "today": "2026-07-14",
    "tag": "tech-debt",
    "title": "Weekly tech-debt audit",
    "unit_word": "audit",
    "cadence_adj": "weekly",
    "scope_blurb": "code-quality signals that drift over time",
    "descriptions": {
        "dependency-drift": "A dependency stuck a major version behind.",
        "stale-tests": "A test file untouched for 180+ days.",
    },
    "todo_steps": ["Fix each finding.", "Re-run the audit."],
}


def test_clean_subject_and_body():
    subject, body = audit_email.render(
        per_check_counts=[("dependency-drift", 0), ("stale-tests", 0)],
        findings_by_check={},
        **_COMMON,
    )
    assert subject == "[Taskmanager tech-debt] ✓ all clear (2 checks) — 2026-07-14"
    assert "RESULT: ✓ all clear — 0 findings across 2 checks. Nothing to do." in body
    # Preamble carries the cadence + the "missing email is the signal" framing.
    assert "an automated weekly audit of the repo" in body
    assert "a week with no email means the audit itself stopped running" in body
    # Each check listed with its description; no detail blocks on a clean run.
    assert "✓ dependency-drift — A dependency stuck a major version behind." in body
    assert "WHAT TO DO" not in body


def test_findings_body_only_fired_checks_get_blocks():
    subject, body = audit_email.render(
        per_check_counts=[("dependency-drift", 2), ("stale-tests", 0)],
        findings_by_check={
            "dependency-drift": [
                ("", ["pip 'cryptography' 48 -> 49 (1 major behind)"]),
                ("", ["npm 'jscpd' 4 -> 5 (1 major behind)"]),
            ],
        },
        **_COMMON,
    )
    assert subject == "[Taskmanager tech-debt] 2 issues to review — 2026-07-14"
    assert "RESULT: 2 issues to review, in 1 of 2 checks." in body
    assert "dependency-drift — 2 findings" in body
    assert "• pip 'cryptography' 48 -> 49 (1 major behind)" in body
    # The clean check gets NO empty block, just the compact list.
    assert "stale-tests — 0" not in body
    assert "Clean this run: stale-tests" in body
    # Numbered next steps rendered from todo_steps.
    assert "  1. Fix each finding." in body
    assert "  2. Re-run the audit." in body


def test_singular_issue_noun():
    subject, _ = audit_email.render(
        per_check_counts=[("dependency-drift", 1)],
        findings_by_check={"dependency-drift": [("", ["one"])]},
        **_COMMON,
    )
    assert "1 issue to review" in subject  # not "1 issues"


def test_finding_with_location_renders_indented_lines():
    _subject, body = audit_email.render(
        per_check_counts=[("dependency-drift", 1)],
        findings_by_check={
            "dependency-drift": [("static/style.css:42", ["the code", "FIX: do X"])],
        },
        **_COMMON,
    )
    assert "  static/style.css:42" in body
    assert "      the code" in body
    assert "      FIX: do X" in body


def test_subject_and_header_extras():
    subject, body = audit_email.render(
        per_check_counts=[("overall-coverage-drift", 0)],
        findings_by_check={},
        subject_extra=" (84.1%)",
        header_extra=["Overall coverage: 84.1%"],
        **{**_COMMON, "tag": "coverage", "descriptions": {"overall-coverage-drift": "x"}},
    )
    assert "(84.1%)" in subject
    assert "Overall coverage: 84.1%" in body


def test_monthly_cadence_wording():
    _subject, body = audit_email.render(
        per_check_counts=[("dependency-drift", 0)],
        findings_by_check={},
        **{**_COMMON, "cadence_adj": "monthly"},
    )
    assert "an automated monthly audit" in body
    assert "a month with no email means" in body
