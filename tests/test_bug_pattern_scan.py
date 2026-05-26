"""Pytest for ``scripts/check_bug_patterns.py`` (#226).

Each check function has at least a positive case (synthetic file that
SHOULD trip the check) and a negative case (synthetic file that should
NOT trip it). The checks read real disk paths, so the tests use
``monkeypatch`` to point ``PROJECT_ROOT`` at a ``tmp_path`` containing
fixtures — never modifies the live working tree.

This is the "exercise the path" approach (CLAUDE.md anti-pattern #3):
each test mocks the inputs and asserts on the OUTPUTS of the actual
function, not on the source bytes of the file.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Import the module fresh per-test via a fixture so PROJECT_ROOT can be
# patched at the module level.
import scripts.check_bug_patterns as bp_mod


@pytest.fixture()
def with_project_root(monkeypatch, tmp_path: Path):
    """Point ``check_bug_patterns.PROJECT_ROOT`` at a fresh tmp_path,
    and stub ``_walk_tracked_files`` to walk that tmp_path's actual
    files (so each test fully controls what's "in the repo").
    """
    monkeypatch.setattr(bp_mod, "PROJECT_ROOT", tmp_path)

    def _walk_under_tmp():
        return [p for p in tmp_path.rglob("*") if p.is_file()]

    monkeypatch.setattr(bp_mod, "_walk_tracked_files", _walk_under_tmp)
    return tmp_path


# ---------------------------------------------------------------------------
# Check (a): bare-1fr-grids
# ---------------------------------------------------------------------------


class TestBare1frGridsCheck:
    def test_bare_1fr_is_flagged(self, with_project_root: Path):
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".plan-row {\n"
            "    grid-template-columns: 1fr;\n"
            "}\n",
            encoding="utf-8",
        )
        findings = bp_mod.check_bare_1fr_grids()
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "bare-1fr-grids"
        assert f.path == "static/style.css"
        assert f.line_num == 2
        assert "1fr" in f.line

    def test_wrapped_minmax_is_clean(self, with_project_root: Path):
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".plan-row { grid-template-columns: minmax(0, 1fr); }\n",
            encoding="utf-8",
        )
        assert bp_mod.check_bare_1fr_grids() == []

    def test_repeat_with_minmax_is_clean(self, with_project_root: Path):
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".day-strip { grid-template-columns: repeat(7, minmax(0, 1fr)); }\n",
            encoding="utf-8",
        )
        assert bp_mod.check_bare_1fr_grids() == []

    def test_repeat_bare_1fr_is_flagged(self, with_project_root: Path):
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".day-strip { grid-template-columns: repeat(7, 1fr); }\n",
            encoding="utf-8",
        )
        assert len(bp_mod.check_bare_1fr_grids()) == 1

    def test_mixed_track_bare_1fr_is_flagged(self, with_project_root: Path):
        # First track is bare 1fr (bad), second is wrapped (fine).
        # The mixed declaration still has a bare-1fr offender → flag.
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".mixed { grid-template-columns: 1fr minmax(0, 1fr); }\n",
            encoding="utf-8",
        )
        assert len(bp_mod.check_bare_1fr_grids()) == 1

    def test_minmax_with_nonzero_min_is_clean(self, with_project_root: Path):
        # `minmax(120px, 1fr)` — the min track has a real lower bound,
        # so the column can't shrink below 120px but can grow to 1fr.
        # That's fine; the D-B1 class is specifically `minmax(0, 1fr)`
        # vs bare `1fr` where shrinkage past max-content matters.
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".grid { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }\n",
            encoding="utf-8",
        )
        assert bp_mod.check_bare_1fr_grids() == []

    def test_fixed_pixel_track_is_clean(self, with_project_root: Path):
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".sidebar-grid { grid-template-columns: 220px minmax(0, 1fr); }\n",
            encoding="utf-8",
        )
        assert bp_mod.check_bare_1fr_grids() == []

    def test_missing_css_file_is_clean(self, with_project_root: Path):
        # No style.css at all → no findings, no crash.
        assert bp_mod.check_bare_1fr_grids() == []

    def test_11fr_does_not_match_1fr(self, with_project_root: Path):
        # Word-boundary regression: `11fr` shouldn't trip the 1fr check.
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".weird { grid-template-columns: 11fr; }\n",
            encoding="utf-8",
        )
        assert bp_mod.check_bare_1fr_grids() == []


# ---------------------------------------------------------------------------
# Check (b): embedded-url-credentials
# ---------------------------------------------------------------------------


class TestEmbeddedUrlCredentialsCheck:
    def test_user_password_url_is_flagged(self, with_project_root: Path):
        (with_project_root / "config.py").write_text(
            'API_URL = "https://shigsdev:secrettoken123@api.example.com/v1"\n',
            encoding="utf-8",
        )
        findings = bp_mod.check_embedded_url_credentials()
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "embedded-url-credentials"
        assert f.path == "config.py"
        # Credential must be MASKED in the recorded line so the email
        # never ships the secret.
        assert "secrettoken123" not in f.line
        assert "****" in f.line

    def test_user_only_url_is_flagged(self, with_project_root: Path):
        (with_project_root / "config.py").write_text(
            'URL = "https://shigsdev@github.com/owner/repo.git"\n',
            encoding="utf-8",
        )
        findings = bp_mod.check_embedded_url_credentials()
        assert len(findings) == 1

    def test_plain_https_url_is_clean(self, with_project_root: Path):
        (with_project_root / "config.py").write_text(
            'URL = "https://github.com/owner/repo.git"\n',
            encoding="utf-8",
        )
        assert bp_mod.check_embedded_url_credentials() == []

    def test_email_address_is_clean(self, with_project_root: Path):
        # Email address contains @ but isn't a credential URL.
        (with_project_root / "config.py").write_text(
            'EMAIL = "alice@example.com"\n',
            encoding="utf-8",
        )
        assert bp_mod.check_embedded_url_credentials() == []

    def test_allowlisted_docs_are_skipped(self, with_project_root: Path):
        # README.md is allowlisted because it documents the bad pattern
        # in security context. The check should NOT flag an embedded
        # cred there even though the literal pattern is present.
        (with_project_root / "README.md").write_text(
            "Bad pattern example: `https://user:token@github.com/...`\n",
            encoding="utf-8",
        )
        assert bp_mod.check_embedded_url_credentials() == []

    def test_binary_files_skipped_gracefully(self, with_project_root: Path):
        # A file we can't decode as UTF-8 shouldn't blow up the scan.
        (with_project_root / "binary.dat").write_bytes(b"\xff\xfe\x00\x01\x02\x03")
        # Should not raise.
        assert bp_mod.check_embedded_url_credentials() == []


# ---------------------------------------------------------------------------
# Check (d): state-mutating-get-routes
# ---------------------------------------------------------------------------


class TestStateMutatingGetRoutesCheck:
    def test_get_post_route_is_flagged(self, with_project_root: Path):
        (with_project_root / "routes.py").write_text(
            '@bp.route("/save", methods=["GET", "POST"])\n'
            "def save(): pass\n",
            encoding="utf-8",
        )
        findings = bp_mod.check_state_mutating_get_routes()
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "state-mutating-get-routes"
        assert f.path == "routes.py"
        assert "POST" in f.message

    def test_get_only_route_is_clean(self, with_project_root: Path):
        (with_project_root / "routes.py").write_text(
            '@bp.route("/healthz", methods=["GET"])\n'
            "def healthz(): pass\n",
            encoding="utf-8",
        )
        assert bp_mod.check_state_mutating_get_routes() == []

    def test_post_only_route_is_clean(self, with_project_root: Path):
        (with_project_root / "routes.py").write_text(
            '@bp.route("/save", methods=["POST"])\n'
            "def save(): pass\n",
            encoding="utf-8",
        )
        assert bp_mod.check_state_mutating_get_routes() == []

    def test_bp_get_decorator_is_clean(self, with_project_root: Path):
        # `@bp.get(...)` is the explicit single-verb form — preferred
        # over `@bp.route(..., methods=["GET"])` and definitely not
        # flagged because there's no `methods=[...]` list at all.
        (with_project_root / "routes.py").write_text(
            '@bp.get("/items")\n'
            "def list_items(): pass\n",
            encoding="utf-8",
        )
        assert bp_mod.check_state_mutating_get_routes() == []

    def test_get_patch_delete_route_lists_all_verbs(self, with_project_root: Path):
        (with_project_root / "routes.py").write_text(
            '@bp.route("/item/<int:id>", methods=["GET", "PATCH", "DELETE"])\n'
            "def handler(id): pass\n",
            encoding="utf-8",
        )
        findings = bp_mod.check_state_mutating_get_routes()
        assert len(findings) == 1
        # All offending verbs surface in the message so the operator
        # knows what to split apart.
        assert "DELETE" in findings[0].message
        assert "PATCH" in findings[0].message

    def test_script_self_is_not_flagged(self, with_project_root: Path):
        # The bug-pattern script + its tests contain example route
        # patterns; those should never be flagged.
        scripts_dir = with_project_root / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "check_bug_patterns.py").write_text(
            '_METHODS_LIST_RE = re.compile(r\'methods=\\["GET", "POST"\\]\')\n',
            encoding="utf-8",
        )
        assert bp_mod.check_state_mutating_get_routes() == []


# ---------------------------------------------------------------------------
# Check (f): raw-tier-string-compare
# ---------------------------------------------------------------------------


class TestRawTierStringCompareCheck:
    def test_tier_eq_string_is_flagged(self, with_project_root: Path):
        (with_project_root / "service.py").write_text(
            'def is_today(task):\n'
            '    return task.tier == "today"\n',
            encoding="utf-8",
        )
        findings = bp_mod.check_raw_tier_string_compare()
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "raw-tier-string-compare"
        assert f.path == "service.py"
        assert f.line_num == 2

    def test_tier_neq_string_is_flagged(self, with_project_root: Path):
        # `!=` also bypasses the enum, same risk class.
        (with_project_root / "service.py").write_text(
            'def is_not_today(t):\n'
            '    return t.tier != "today"\n',
            encoding="utf-8",
        )
        assert len(bp_mod.check_raw_tier_string_compare()) == 1

    def test_string_on_left_side_is_flagged(self, with_project_root: Path):
        # `"today" == task.tier` (reversed) is the same bug.
        (with_project_root / "service.py").write_text(
            'def f(task):\n'
            '    return "today" == task.tier\n',
            encoding="utf-8",
        )
        assert len(bp_mod.check_raw_tier_string_compare()) == 1

    def test_tier_enum_compare_is_clean(self, with_project_root: Path):
        # Comparing to Tier.TODAY (the enum member) is the safe path.
        (with_project_root / "service.py").write_text(
            'def f(task):\n'
            '    return task.tier == Tier.TODAY\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []

    def test_querystring_read_is_clean(self, with_project_root: Path):
        # `request.args.get("tier")` is reading a querystring key
        # named "tier"; nothing's being compared to a tier-value string.
        (with_project_root / "route.py").write_text(
            'def index():\n'
            '    return request.args.get("tier")\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []

    def test_test_files_are_skipped(self, with_project_root: Path):
        # Tests legitimately compare enum.value strings; they shouldn't
        # be scanned by this check.
        tests_dir = with_project_root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_x.py").write_text(
            'def test_thing(task):\n'
            '    assert task.tier == "today"\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []

    def test_migration_files_are_skipped(self, with_project_root: Path):
        # Migrations are frozen historical schema mutations — they may
        # reference old enum string values that no longer match
        # current Tier members. Never "fix" a migration after it has
        # been applied to a deployed DB.
        mig_dir = with_project_root / "migrations" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "0001_init.py").write_text(
            'def upgrade():\n'
            '    if tier == "today":\n'
            '        pass\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []

    def test_non_python_file_is_skipped(self, with_project_root: Path):
        # JS source can compare strings to tier values legitimately
        # (the API returns strings, not enum members).
        (with_project_root / "app.js").write_text(
            'if (task.tier === "today") { foo(); }\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []

    def test_bare_word_tier_does_not_match_attribute(self, with_project_root: Path):
        # `self.tier` should match, `task.tiered` (a different name)
        # should NOT match. Word-boundary guard.
        (with_project_root / "service.py").write_text(
            'def f(task):\n'
            '    return task.tiered == "today"\n',
            encoding="utf-8",
        )
        assert bp_mod.check_raw_tier_string_compare() == []


# ---------------------------------------------------------------------------
# Check (e) #226b: unbalanced-type-work
# ---------------------------------------------------------------------------


class TestUnbalancedTypeWorkCheck:
    """#226b (2026-05-26): JS `.type === "work"` check without a paired
    "personal" reference in the same window. Bug #57's other cascade
    row (the original incident was the task-detail save handler).
    """

    def test_unbalanced_work_check_is_flagged(self, with_project_root: Path):
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "app.js").write_text(
            'function save(task) {\n'
            '    if (task.type === "work") {\n'
            '        payload.project_id = projSelect.value;\n'
            '    }\n'
            '    return payload;\n'
            '}\n',
            encoding="utf-8",
        )
        findings = bp_mod.check_unbalanced_type_work()
        assert len(findings) == 1
        f = findings[0]
        assert f.check_id == "unbalanced-type-work"
        assert f.path == "static/app.js"
        assert f.line_num == 2

    def test_paired_work_and_personal_branches_are_clean(self, with_project_root: Path):
        # Classic if/else — work on one line, personal on the next.
        # Heuristic finds "personal" in the ±20 window → balanced.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "filter.js").write_text(
            'function filter(tasks, view) {\n'
            '    if (view === "work") {\n'
            '        tasks = tasks.filter((t) => t.type === "work");\n'
            '    } else if (view === "personal") {\n'
            '        tasks = tasks.filter((t) => t.type === "personal");\n'
            '    }\n'
            '    return tasks;\n'
            '}\n',
            encoding="utf-8",
        )
        assert bp_mod.check_unbalanced_type_work() == []

    def test_unbalanced_not_equal_to_work_is_flagged(self, with_project_root: Path):
        # `.type !== "work"` with no personal counterpart is the same
        # bug class — the negative branch silently includes personal
        # without the developer thinking about it.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "app.js").write_text(
            'function shouldShow(task, view) {\n'
            '    if (view === "work" && task.type !== "work") return false;\n'
            '    return true;\n'
            '}\n',
            encoding="utf-8",
        )
        assert len(bp_mod.check_unbalanced_type_work()) == 1

    def test_comment_with_type_work_is_not_flagged(self, with_project_root: Path):
        # JSDoc / comment text discussing the bug pattern (like the
        # comment in static/task_detail_payload.js) must not trigger.
        # Comments don't start with `.type` — the regex requires the
        # leading dot — but this case is worth locking in.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "app.js").write_text(
            '/**\n'
            ' * Bug #57: a stale `type === "work"` check used to drop\n'
            ' * project_id for personal tasks.\n'
            ' */\n'
            'function noop() {}\n',
            encoding="utf-8",
        )
        # The literal `type === "work"` inside the JSDoc has no leading
        # dot, so the regex doesn't match. Clean.
        assert bp_mod.check_unbalanced_type_work() == []

    def test_line_comment_after_match_is_not_flagged(self, with_project_root: Path):
        # `// only on work tasks` comment after the actual match — the
        # match IS real code; flag stays.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "app.js").write_text(
            'function pickWorkOnly(task) {\n'
            '    return task.type === "work";  // workaround for issue X\n'
            '}\n',
            encoding="utf-8",
        )
        # Real code, no "personal" reference within ±20 lines.
        assert len(bp_mod.check_unbalanced_type_work()) == 1

    def test_personal_in_comment_still_counts_as_balanced(self, with_project_root: Path):
        # Comments mentioning "personal" near a work check are evidence
        # the author considered the personal branch — even if the code
        # itself doesn't have it. We accept this as a deliberate
        # false-negative trade-off: false-positive on comments is
        # noisier than false-negative on a one-off check that's
        # documented.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        (static_dir / "app.js").write_text(
            'function pickWorkOnly(task) {\n'
            '    // Note: this skips "personal" tasks intentionally.\n'
            '    return task.type === "work";\n'
            '}\n',
            encoding="utf-8",
        )
        assert bp_mod.check_unbalanced_type_work() == []

    def test_tests_directory_is_skipped(self, with_project_root: Path):
        # Test files assert on specific type values intentionally.
        tests_dir = with_project_root / "tests" / "js"
        tests_dir.mkdir(parents=True)
        (tests_dir / "foo.test.js").write_text(
            'test("work only", () => {\n'
            '    expect(t.type === "work").toBe(true);\n'
            '});\n',
            encoding="utf-8",
        )
        assert bp_mod.check_unbalanced_type_work() == []

    def test_non_js_file_is_skipped(self, with_project_root: Path):
        # Python uses TaskType.WORK / TaskType.PERSONAL enum members;
        # the JS check shouldn't scan Python files even if they
        # contain the literal pattern in a docstring.
        (with_project_root / "service.py").write_text(
            'def f(task):\n'
            '    return task.type == "work"  # legitimate in Python\n',
            encoding="utf-8",
        )
        assert bp_mod.check_unbalanced_type_work() == []

    def test_personal_outside_window_still_flagged(self, with_project_root: Path):
        # If "personal" is >20 lines away, the heuristic considers the
        # work check unbalanced. Trade-off: long-block if/else with the
        # personal branch >20 lines from the work line will false-
        # positive. Operator fixes by either shortening the block,
        # commenting "personal" near the work check, or restructuring.
        static_dir = with_project_root / "static"
        static_dir.mkdir()
        lines = ['function f(task) {']
        lines.append('    if (task.type === "work") {')
        # 25 lines of unrelated code between work and personal.
        lines.extend([f'        // line {n}' for n in range(25)])
        lines.append('    } else if (task.type === "personal") {')
        lines.append('        return true;')
        lines.append('    }')
        lines.append('}')
        (static_dir / "app.js").write_text("\n".join(lines), encoding="utf-8")
        # The match at line 2 is 28 lines away from the "personal"
        # match — outside the ±20 window. Flagged.
        findings = bp_mod.check_unbalanced_type_work()
        assert len(findings) == 1


class TestStripJsLineComment:
    """The helper used by check_unbalanced_type_work to defang trailing
    `// comment` text that would otherwise hide the regex match."""

    def test_no_comment_returns_line_unchanged(self):
        assert bp_mod._strip_js_line_comment('foo();') == 'foo();'

    def test_trailing_line_comment_stripped(self):
        assert bp_mod._strip_js_line_comment('foo();  // bar') == 'foo();  '

    def test_comment_inside_double_quote_string_preserved(self):
        # The `//` is inside a string literal, not a comment.
        assert bp_mod._strip_js_line_comment(
            'url = "https://example.com";'
        ) == 'url = "https://example.com";'

    def test_comment_inside_single_quote_string_preserved(self):
        assert bp_mod._strip_js_line_comment(
            "url = 'https://x';"
        ) == "url = 'https://x';"

    def test_no_slashslash_at_all(self):
        assert bp_mod._strip_js_line_comment('var x = 1;') == 'var x = 1;'


# ---------------------------------------------------------------------------
# Driver-level integration
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def test_main_clean_returns_zero(self, with_project_root: Path, capsys):
        # Fresh tmp_path → no fixtures → all checks clean → exit 0.
        # Also stub out the string-match check, which would otherwise
        # try to run the real gate 8d script (not present under tmp_path).
        import scripts.check_bug_patterns as mod
        mod.CHECKS_BACKUP = list(mod.CHECKS)
        mod.CHECKS = [
            (name, fn) for name, fn in mod.CHECKS
            if name != "string-match-only-prod-tests"
        ]
        try:
            rc = mod.main()
        finally:
            mod.CHECKS = mod.CHECKS_BACKUP
        assert rc == 0
        out = capsys.readouterr().out
        assert "CLEAN" in out

    def test_main_with_findings_returns_one(self, with_project_root: Path, capsys, monkeypatch):
        # Plant a bare-1fr offender so check (a) reports one finding.
        css_dir = with_project_root / "static"
        css_dir.mkdir()
        (css_dir / "style.css").write_text(
            ".bad { grid-template-columns: 1fr; }\n",
            encoding="utf-8",
        )
        # Stub the SendGrid call so the test never hits the network.
        sent = []
        monkeypatch.setattr(bp_mod, "send_findings_email",
                            lambda findings: sent.append(findings))
        import scripts.check_bug_patterns as mod
        mod.CHECKS_BACKUP = list(mod.CHECKS)
        mod.CHECKS = [
            (name, fn) for name, fn in mod.CHECKS
            if name != "string-match-only-prod-tests"
        ]
        try:
            rc = mod.main()
        finally:
            mod.CHECKS = mod.CHECKS_BACKUP
        assert rc == 1
        assert len(sent) == 1
        assert sent[0][0].check_id == "bare-1fr-grids"


# ---------------------------------------------------------------------------
# Helper-internals (track-parse) — covered via the same fixture-driven
# pattern as the public checks.
# ---------------------------------------------------------------------------


class TestTrackUsesBare1fr:
    """Direct cover of the inner helper — it's the load-bearing piece
    behind check (a) and worth its own targeted assertions."""

    def test_plain_1fr(self):
        assert bp_mod._track_uses_bare_1fr("1fr")

    def test_repeat_1fr(self):
        assert bp_mod._track_uses_bare_1fr("repeat(7, 1fr)")

    def test_minmax_zero_1fr(self):
        assert not bp_mod._track_uses_bare_1fr("minmax(0, 1fr)")

    def test_minmax_zero_repeat(self):
        assert not bp_mod._track_uses_bare_1fr("repeat(7, minmax(0, 1fr))")

    def test_minmax_nonzero(self):
        assert not bp_mod._track_uses_bare_1fr("minmax(120px, 1fr)")

    def test_fixed_only(self):
        assert not bp_mod._track_uses_bare_1fr("220px 240px")

    def test_no_1fr(self):
        assert not bp_mod._track_uses_bare_1fr("auto auto")

    def test_mixed_track_with_bare_1fr(self):
        # First track bare, second wrapped — overall the rule has a
        # bare-1fr offender and SHOULD be flagged.
        assert bp_mod._track_uses_bare_1fr("1fr minmax(0, 1fr)")

    # importlib import-cycle guard
    def test_module_loads_cleanly(self):
        # If the module ever picks up a circular import, this fails.
        importlib.reload(bp_mod)
