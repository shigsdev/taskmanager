"""Unit tests for scripts/validate_deploy.py.

Every ship's "done" rests on this script's exit code, so the decision
itself is tested here, not only by real deploys: the helpers (minute
math, the log-scan classifier, the cookie file, the auth preflight) and
main()'s green / red call — SHA match, a ``fail:`` check, ``warn:``
allowed, the poll timeout, and the exit codes 2 / 3 the SOP acts on.
/healthz and the cookie endpoints are stubbed; no network.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ is not a package — import the module by path.
_SCRIPT = Path(__file__).parent.parent / "scripts" / "validate_deploy.py"
spec = importlib.util.spec_from_file_location("validate_deploy", _SCRIPT)
vd = importlib.util.module_from_spec(spec)
sys.modules["validate_deploy"] = vd
spec.loader.exec_module(vd)


# --- _minutes_since ----------------------------------------------------------


class TestMinutesSince:
    def test_returns_none_for_empty(self):
        assert vd._minutes_since("") is None
        assert vd._minutes_since(None) is None  # type: ignore[arg-type]

    def test_returns_none_for_garbage(self):
        assert vd._minutes_since("not a timestamp") is None

    def test_parses_iso_with_z(self):
        past = datetime.now(UTC) - timedelta(minutes=5)
        iso = past.isoformat().replace("+00:00", "Z")
        minutes = vd._minutes_since(iso)
        # ~5 + 1 buffer; allow +/- 1 for scheduler jitter
        assert minutes in (5, 6, 7)

    def test_parses_iso_with_plus_offset(self):
        past = datetime.now(UTC) - timedelta(minutes=10)
        iso = past.isoformat()  # already +00:00
        minutes = vd._minutes_since(iso)
        assert minutes in (10, 11, 12)

    def test_clamps_to_minimum_one(self):
        # started_at in the same second → delta < 60s → (0 // 60) + 1 = 1
        just_now = datetime.now(UTC).isoformat()
        assert vd._minutes_since(just_now) == 1


# --- do_log_check ------------------------------------------------------------


class TestFetchDebugLogsUrl:
    """Bug #49 regression: the URL the script constructs for the
    /api/debug/logs query must use the param name the endpoint actually
    reads (`since=Nm` shorthand, NOT `since_minutes=N`). Prior version
    sent `since_minutes=` which the endpoint silently ignored, falling
    back to its 1-hour default — every deploy validate erroneously
    flagged errors up to an hour pre-deploy as RED."""

    def test_uses_since_shorthand_not_since_minutes(self):
        """Pass since_minutes=5 → URL must contain `since=5m`, NOT
        `since_minutes=5`. Prevents the false-positive DEPLOY RED that
        bit us 4× in 2026-04-24/25."""
        from unittest.mock import MagicMock, patch
        captured_url = {}

        def _fake_run(cmd, *args, **kwargs):
            # Last positional arg in the curl invocation is the URL
            captured_url["url"] = cmd[-1]
            res = MagicMock()
            res.stdout = '{"logs":[],"count":0}\n200'
            res.returncode = 0
            return res

        with patch.object(vd.subprocess, "run", side_effect=_fake_run):
            vd.fetch_debug_logs(
                "https://example.com/api/debug/logs",
                "cookie",
                level="ERROR",
                since_minutes=5,
                limit=50,
            )
        url = captured_url.get("url", "")
        assert "since=5m" in url, (
            f"URL must use `since=5m` (the param the endpoint reads); "
            f"saw {url!r}"
        )
        # Belt-and-braces: ensure we did NOT send the broken param name.
        assert "since_minutes=" not in url, (
            f"Bug #49 regression: URL contained the unrecognized "
            f"`since_minutes=` param; saw {url!r}"
        )

    def test_omits_since_when_no_since_minutes(self):
        """If since_minutes is None or 0, the URL must not include any
        since= param — let the endpoint use its 1h default."""
        from unittest.mock import MagicMock, patch
        captured_url = {}

        def _fake_run(cmd, *args, **kwargs):
            captured_url["url"] = cmd[-1]
            res = MagicMock()
            res.stdout = '{"logs":[],"count":0}\n200'
            res.returncode = 0
            return res

        with patch.object(vd.subprocess, "run", side_effect=_fake_run):
            vd.fetch_debug_logs(
                "https://example.com/api/debug/logs",
                "cookie",
                level="ERROR",
                since_minutes=None,
                limit=50,
            )
        url = captured_url.get("url", "")
        assert "since" not in url


class TestDoLogCheck:
    """Classifier over fetch_debug_logs output.

    The function must:
      1. Return SKIP if started_at is unparseable (no deploy window).
      2. Return SKIP if the endpoint is unreachable (can't fail closed
         on network issues — this is a repair gate, not a blocker).
      3. Return SKIP on 401 (auth-check would have caught it first).
      4. Return SKIP on any non-200.
      5. Return PASS if the response has no server-side errors.
      6. Return FAIL if there's at least one server-side error.
      7. Ignore client-side rows (source='client').
    """

    def _ok_recent_timestamp(self):
        return (datetime.now(UTC) - timedelta(minutes=2)).isoformat()

    def test_skip_on_unparseable_started_at(self):
        status, rows = vd.do_log_check("https://x", "cookie", "nope")
        assert status.startswith("SKIP")
        assert rows == []

    def test_skip_on_network_error(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(0, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")
        assert rows == []

    def test_skip_on_401(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(401, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")

    def test_skip_on_500(self):
        with patch.object(vd, "fetch_debug_logs", return_value=(500, None)):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")

    def test_pass_on_empty_logs(self):
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [], "count": 0}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert rows == []

    def test_fail_on_one_server_error(self):
        error_row = {
            "level": "ERROR",
            "source": "server",
            "route": "/api/tasks",
            "message": "psycopg error",
            "timestamp": "2026-04-20T12:00:00+00:00",
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [error_row], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "FAIL"
        assert len(rows) == 1

    def test_ignores_client_side_errors(self):
        client_row = {
            "level": "ERROR",
            "source": "client",
            "message": "TypeError: undefined",
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [client_row], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert rows == []

    def test_mixes_server_and_client_only_counts_server(self):
        rows_in = [
            {"level": "ERROR", "source": "client", "message": "browser"},
            {"level": "ERROR", "source": "server", "message": "real failure",
             "route": "/api/goals"},
        ]
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": rows_in, "count": 2}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "FAIL"
        assert len(rows) == 1
        assert rows[0]["route"] == "/api/goals"

    def test_ignores_transient_ssl_eof_blip(self):
        """Regression: psycopg SSL EOF errors right after container boot
        are Railway connection-pool flakes, not app bugs. They must not
        block a deploy."""
        blip = {
            "level": "ERROR",
            "source": "server",
            "route": "/api/debug/logs",
            "message": "Exception on /api/debug/logs [GET]",
            "traceback": (
                "psycopg.OperationalError: consuming input failed: "
                "SSL SYSCALL error: EOF detected\n"
            ),
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [blip], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert rows == []

    def test_ignores_transient_ssl_decrypt_blip(self):
        blip = {
            "level": "ERROR",
            "source": "server",
            "traceback": (
                "psycopg.OperationalError: SSL error: "
                "decryption failed or bad record mac\n"
            ),
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [blip], "count": 1}),
        ):
            status, _ = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"

    def test_still_fails_on_non_ssl_operational_error(self):
        """A real DB problem (e.g. table missing) should still FAIL."""
        real_error = {
            "level": "ERROR",
            "source": "server",
            "route": "/api/tasks",
            "traceback": (
                "psycopg.errors.UndefinedTable: relation "
                '"tasks" does not exist\n'
            ),
        }
        with patch.object(
            vd, "fetch_debug_logs",
            return_value=(200, {"logs": [real_error], "count": 1}),
        ):
            status, rows = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "FAIL"
        assert len(rows) == 1

    def test_retries_on_5xx(self):
        """Transient 5xx from /api/debug/logs itself should retry before
        giving up (catches the same warm-up flakiness as the filter)."""
        call_count = {"n": 0}

        def flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return 500, None
            return 200, {"logs": [], "count": 0}

        with patch.object(vd, "fetch_debug_logs", side_effect=flaky), \
             patch.object(vd.time, "sleep"):  # skip real sleeps
            status, _ = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status == "PASS"
        assert call_count["n"] == 3

    def test_does_not_retry_on_4xx(self):
        """401/403 are deterministic — no point retrying."""
        call_count = {"n": 0}

        def auth_fail(*args, **kwargs):
            call_count["n"] += 1
            return 401, None

        with patch.object(vd, "fetch_debug_logs", side_effect=auth_fail), \
             patch.object(vd.time, "sleep"):
            status, _ = vd.do_log_check(
                "https://x", "cookie", self._ok_recent_timestamp(),
            )
        assert status.startswith("SKIP")
        assert call_count["n"] == 1

    def test_passes_since_minutes_to_fetcher(self):
        """Regression guard: the window must be scoped to this deploy."""
        captured: dict = {}

        def fake_fetch(*args, **kwargs):
            captured.update(kwargs)
            return 200, {"logs": [], "count": 0}

        with patch.object(vd, "fetch_debug_logs", side_effect=fake_fetch):
            vd.do_log_check("https://x", "cookie", self._ok_recent_timestamp())

        assert "since_minutes" in captured
        assert captured["since_minutes"] >= 1
        assert captured["level"] == "ERROR"


# --- read_cookie_file ---------------------------------------------------------


class TestReadCookieFile:

    def test_strips_a_trailing_windows_newline(self, tmp_path):
        p = tmp_path / "cookie"
        p.write_bytes(b"abc.def.ghi\r\n")
        assert vd.read_cookie_file(p) == "abc.def.ghi"

    def test_missing_or_blank_file_is_none(self, tmp_path):
        assert vd.read_cookie_file(tmp_path / "nope") is None
        blank = tmp_path / "blank"
        blank.write_text("  \n")
        assert vd.read_cookie_file(blank) is None


# --- do_auth_preflight --------------------------------------------------------


class TestDoAuthPreflight:
    """Exit codes the operator acts on: 2 = re-mint the cookie,
    3 = set it up, 1 = the auth endpoint itself is broken."""

    def _run(self, tmp_path, answer, content="tok"):
        p = tmp_path / "cookie"
        if content is not None:
            p.write_text(content)
        with patch.object(vd, "fetch_auth_status", return_value=answer) as f:
            code = vd.do_auth_preflight("https://app.example", p)
        return code, f

    def test_authenticated_200_is_green_and_sends_the_stripped_cookie(self, tmp_path):
        code, f = self._run(
            tmp_path, (200, {"authenticated": True, "email": "me@x"}),
            content="tok\n",
        )
        assert code == vd.EXIT_GREEN
        f.assert_called_once_with("https://app.example/api/auth/status", "tok")

    def test_200_that_is_not_authenticated_is_red(self, tmp_path):
        code, _ = self._run(tmp_path, (200, {"authenticated": False}))
        assert code == vd.EXIT_RED

    def test_401_means_refresh_the_cookie(self, tmp_path, capsys):
        code, _ = self._run(tmp_path, (401, None))
        assert code == vd.EXIT_COOKIE_EXPIRED
        assert "VALIDATOR COOKIE REJECTED" in capsys.readouterr().out

    @pytest.mark.parametrize("status", [0, 500, 503])
    def test_network_error_or_5xx_is_red_not_a_cookie_problem(self, tmp_path, status):
        code, _ = self._run(tmp_path, (status, None))
        assert code == vd.EXIT_RED

    @pytest.mark.parametrize("content", [None, "   "])
    def test_missing_or_empty_cookie_file_is_a_usage_error(self, tmp_path, content):
        code, f = self._run(tmp_path, (200, {"authenticated": True}), content=content)
        assert code == vd.EXIT_USAGE
        f.assert_not_called()


# --- main(): the green / red decision ----------------------------------------


SHA = "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0"
OK_CHECKS = {
    "database": "ok", "env_vars": "ok", "migrations": "ok", "tables": "ok",
    "writable_db": "ok", "encryption": "ok", "digest": "ok",
    "static_assets": "ok",
}


def _healthz(sha=SHA, status="ok", **checks):
    return {
        "git_sha": sha, "status": status,
        "started_at": datetime.now(UTC).isoformat(),
        "checks": {**OK_CHECKS, **checks},
    }


class TestMainDecision:
    """main() turns /healthz (+ the optional cookie checks) into the exit
    code the SOP trusts. No cookie file here unless a test makes one, so
    the auth + log checks stay off by default, as on a fresh machine."""

    def _main(self, tmp_path, answers, *extra, cookie=False):
        cookie_path = tmp_path / "cookie"
        if cookie:
            cookie_path.write_text("tok")
        argv = ["validate_deploy.py", "--sha", SHA,
                "--cookie-file", str(cookie_path), *extra]
        polls = iter(answers)
        with patch.object(vd.sys, "argv", argv), \
                patch.object(vd, "fetch_healthz", lambda url: next(polls)), \
                patch.object(vd.time, "sleep"):
            return vd.main()

    def test_matching_sha_and_ok_checks_is_green(self, tmp_path, capsys):
        assert self._main(tmp_path, [_healthz()]) == vd.EXIT_GREEN
        out = capsys.readouterr().out
        assert "Status: DEPLOY GREEN" in out
        # PR41: a green run prints the SOP template.
        assert "SOP Compliance Report" in out

    def test_waits_through_the_old_sha_and_an_unreachable_poll(self, tmp_path):
        answers = [_healthz(sha="0" * 40), None, _healthz()]
        assert self._main(tmp_path, answers) == vd.EXIT_GREEN

    def test_a_fail_check_is_red_even_when_status_says_ok(self, tmp_path, capsys):
        answers = [_healthz(migrations="fail: at abc expected def")]
        assert self._main(tmp_path, answers) == vd.EXIT_RED
        assert "Status: DEPLOY RED" in capsys.readouterr().out

    def test_warn_and_skipped_checks_stay_green(self, tmp_path):
        answers = [_healthz(digest="warn: last run 26h ago",
                            encryption="skipped: no key in test")]
        assert self._main(tmp_path, answers) == vd.EXIT_GREEN

    def test_overall_status_not_ok_is_red(self, tmp_path):
        assert self._main(tmp_path, [_healthz(status="fail")]) == vd.EXIT_RED

    def test_never_seeing_the_sha_times_out_red(self, tmp_path, capsys):
        answers = [_healthz(sha="0" * 40)] * vd.MAX_POLLS
        assert self._main(tmp_path, answers) == vd.EXIT_RED
        assert "Timed out" in capsys.readouterr().out

    def test_url_with_healthz_suffix_is_accepted(self, tmp_path):
        seen = []
        argv = ["validate_deploy.py", "--sha", SHA, "--cookie-file",
                str(tmp_path / "none"), "--url", "https://app.example/healthz"]

        def fetch(url):
            seen.append(url)
            return _healthz()

        with patch.object(vd.sys, "argv", argv), \
                patch.object(vd, "fetch_healthz", fetch), \
                patch.object(vd.time, "sleep"):
            assert vd.main() == vd.EXIT_GREEN
        assert seen == ["https://app.example/healthz"]

    def test_cookie_present_turns_on_auth_and_log_checks(self, tmp_path):
        with patch.object(vd, "do_auth_preflight", return_value=vd.EXIT_GREEN) as a, \
                patch.object(vd, "do_log_check", return_value=("PASS", [])) as lg:
            assert self._main(tmp_path, [_healthz()], cookie=True) == vd.EXIT_GREEN
        a.assert_called_once()
        lg.assert_called_once()

    def test_an_error_row_since_the_deploy_is_red(self, tmp_path):
        row = {"route": "/api/tasks", "message": "boom", "source": "server"}
        with patch.object(vd, "do_auth_preflight", return_value=vd.EXIT_GREEN), \
                patch.object(vd, "do_log_check", return_value=("FAIL", [row])):
            assert self._main(tmp_path, [_healthz()], cookie=True) == vd.EXIT_RED

    def test_no_check_logs_skips_the_scan(self, tmp_path):
        with patch.object(vd, "do_auth_preflight", return_value=vd.EXIT_GREEN), \
                patch.object(vd, "do_log_check") as lg:
            code = self._main(tmp_path, [_healthz()], "--no-check-logs", cookie=True)
        assert code == vd.EXIT_GREEN
        lg.assert_not_called()

    @pytest.mark.parametrize("auth", [vd.EXIT_COOKIE_EXPIRED, vd.EXIT_USAGE])
    def test_cookie_problems_pass_their_exit_code_through(self, tmp_path, auth):
        with patch.object(vd, "do_auth_preflight", return_value=auth):
            assert self._main(tmp_path, [_healthz()], cookie=True) == auth

    def test_a_broken_auth_endpoint_is_red(self, tmp_path):
        with patch.object(vd, "do_auth_preflight", return_value=vd.EXIT_RED), \
                patch.object(vd, "do_log_check", return_value=("PASS", [])):
            assert self._main(tmp_path, [_healthz()], cookie=True) == vd.EXIT_RED

    def test_monitor_red_when_new_errors_land_after_green(self, tmp_path, capsys):
        row = {"timestamp": "t", "route": "/x", "message": "late boom"}
        scans = iter([("PASS", []), ("FAIL", [row])])
        with patch.object(vd, "do_auth_preflight", return_value=vd.EXIT_GREEN), \
                patch.object(vd, "do_log_check", lambda *a: next(scans)):
            code = self._main(tmp_path, [_healthz()], "--monitor-minutes", "5",
                              cookie=True)
        assert code == vd.EXIT_RED
        assert "DEPLOY MONITOR RED" in capsys.readouterr().out


# --- #508: a push Railway skips is not an outage ------------------------------


class TestDeployWouldSkip:
    """Mirrors the `web` service's Watch Paths (ARCHITECTURE.md → Deploy
    configuration): a push whose every changed file is excluded never
    builds, so /healthz keeps the previous SHA."""

    @pytest.mark.parametrize("files", [
        ["BACKLOG.md"],
        ["tests/test_egress.py", "tests/js/unit/a.test.js", "docs/design/x.md"],
        [".github/workflows/weekly.yml", ".gitignore", ".gitattributes"],
        ["README.md", "CLAUDE.md", "ARCHITECTURE.md", ".pre-commit-config.yaml"],
    ])
    def test_only_excluded_files_skip(self, files):
        assert vd.deploy_would_skip(files) is True

    @pytest.mark.parametrize("files", [
        ["app.py"],
        ["BACKLOG.md", "static/app.js"],
        ["templates/docs.html"],        # not docs/**
        ["status/index.html"],
        ["scripts/validate_deploy.py"],
        [],                             # nothing changed is not a skip
    ])
    def test_any_deployed_file_builds(self, files):
        assert vd.deploy_would_skip(files) is False

    def test_a_slashless_pattern_matches_at_any_depth_like_gitignore(self):
        assert vd.deploy_would_skip(["tests/e2e/README.md"]) is True
        assert vd.deploy_would_skip(["docs/README.md", "README.md"]) is True

    def test_mirror_matches_the_documented_watch_paths(self):
        """The script's copy and ARCHITECTURE.md's table must agree — the
        dashboard is the source, the table is its written record."""
        arch = (Path(__file__).parent.parent / "ARCHITECTURE.md").read_text(
            encoding="utf-8")
        row = next(ln for ln in arch.splitlines() if ln.startswith("| Watch Paths |"))
        documented = [p.strip().strip("`") for p in row.split("|")[2].split(",")]
        assert documented[0] == "**"
        assert [p.lstrip("!") for p in documented[1:]] == list(vd.WATCH_EXCLUDES)


class TestChangedFiles:

    def test_lists_names_from_git_diff(self):
        from unittest.mock import MagicMock
        res = MagicMock(returncode=0, stdout="BACKLOG.md\ntests/test_x.py\n")
        with patch.object(vd.subprocess, "run", return_value=res) as run:
            assert vd.changed_files("aaa", "bbb") == ["BACKLOG.md", "tests/test_x.py"]
        assert run.call_args[0][0][-2:] == ["aaa", "bbb"]

    def test_unknown_sha_or_no_git_is_none(self):
        from unittest.mock import MagicMock
        bad = MagicMock(returncode=128, stdout="")
        with patch.object(vd.subprocess, "run", return_value=bad):
            assert vd.changed_files("zzz", "bbb") is None
        with patch.object(vd.subprocess, "run", side_effect=FileNotFoundError):
            assert vd.changed_files("aaa", "bbb") is None


class TestMainSkippedDeploy:

    OLD = "f" * 40

    def _main(self, tmp_path, answers, files):
        argv = ["validate_deploy.py", "--sha", SHA,
                "--cookie-file", str(tmp_path / "none")]
        polls = iter(answers)
        with patch.object(vd.sys, "argv", argv), \
                patch.object(vd, "fetch_healthz", lambda url: next(polls)), \
                patch.object(vd, "changed_files", return_value=files) as cf, \
                patch.object(vd.time, "sleep"):
            return vd.main(), cf

    def test_docs_only_push_reports_skipped_after_a_short_grace(self, tmp_path, capsys):
        answers = [_healthz(sha=self.OLD)] * vd.MAX_POLLS
        code, cf = self._main(tmp_path, answers, ["BACKLOG.md", "tests/test_x.py"])
        assert code == vd.EXIT_GREEN
        cf.assert_called_once_with(self.OLD, SHA)
        out = capsys.readouterr().out
        assert "DEPLOY SKIPPED" in out
        assert "unreachable" not in out
        assert "BACKLOG.md" in out
        # Gave up after the grace window, not the full 10 minutes.
        assert out.count("deployed=ffffffff") == vd.SKIP_GRACE_POLLS
        # Nothing shipped, so no SOP template is printed for it.
        assert "SOP Compliance Report" not in out

    def test_skipped_but_the_live_app_failing_is_red(self, tmp_path, capsys):
        answers = [_healthz(sha=self.OLD, database="fail: down")] * vd.MAX_POLLS
        code, _ = self._main(tmp_path, answers, ["BACKLOG.md"])
        assert code == vd.EXIT_RED
        assert "DEPLOY RED" in capsys.readouterr().out

    def test_a_build_that_lands_inside_the_grace_window_is_validated(self, tmp_path):
        answers = [_healthz(sha=self.OLD), _healthz(sha=self.OLD), _healthz()]
        code, _ = self._main(tmp_path, answers, ["BACKLOG.md"])
        assert code == vd.EXIT_GREEN

    def test_app_change_that_never_lands_is_red_and_says_stale_not_unreachable(
            self, tmp_path, capsys):
        answers = [_healthz(sha=self.OLD)] * vd.MAX_POLLS
        code, _ = self._main(tmp_path, answers, ["app.py"])
        assert code == vd.EXIT_RED
        out = capsys.readouterr().out
        assert out.count("deployed=ffffffff") == vd.MAX_POLLS
        assert "Deployed SHA:   ffffffff" in out
        assert "Overall status: unreachable" not in out
        assert "DEPLOY SKIPPED" not in out

    def test_git_cannot_tell_falls_back_to_the_full_wait(self, tmp_path, capsys):
        answers = [_healthz(sha=self.OLD)] * vd.MAX_POLLS
        code, _ = self._main(tmp_path, answers, None)
        assert code == vd.EXIT_RED
        assert capsys.readouterr().out.count("deployed=ffffffff") == vd.MAX_POLLS

    def test_never_answering_is_still_unreachable(self, tmp_path, capsys):
        code, cf = self._main(tmp_path, [None] * vd.MAX_POLLS, ["BACKLOG.md"])
        assert code == vd.EXIT_RED
        assert "Overall status: unreachable" in capsys.readouterr().out
        cf.assert_not_called()


def test_a_long_check_name_keeps_a_gap_before_its_value(capsys):
    """digest_last_send (16 chars) used to run into its value."""
    vd.print_report(SHA, _healthz(digest_last_send="ok: last sent x"), green=True)
    out = capsys.readouterr().out
    assert "digest_last_send  ok: last sent x" in out
    assert "  database          ok" in out
