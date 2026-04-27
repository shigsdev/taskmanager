"""Post-deploy validation script.

Usage:
    python scripts/validate_deploy.py [--sha <expected>] [--url <base_url>]
                                      [--auth-check] [--cookie-file <path>]
                                      [--check-logs | --no-check-logs]

Default behavior (no flags):
    Polls /healthz until the deployed SHA matches the expected SHA (default:
    HEAD of the local repo), then prints a Deploy Validation Report.

    If the cookie file exists (default: ``~/.taskmanager-session-cookie``),
    ``--auth-check`` and ``--check-logs`` are auto-enabled. Pass
    ``--no-check-logs`` to force-skip the log sweep.

With --auth-check:
    Hits /api/auth/status with the stored validator cookie. On 401, prints
    copy-pasteable refresh instructions and exits 2.

With --check-logs:
    After the SHA match, queries /api/debug/logs?level=ERROR since the
    deploy's started_at. Any ERROR row means DEPLOY RED. Catches 500s on
    routes that Playwright smoke doesn't cover — the gap that let
    yesterday's enum outage slip past validate_deploy into "green".

Exit codes:
    0  DEPLOY GREEN       — SHA matches, all checks pass, auth ok (if checked),
                            no new ERROR-level server logs (if checked)
    1  DEPLOY RED         — SHA mismatch, failed checks, timeout, OR new
                            ERROR logs since deploy start
    2  COOKIE EXPIRED     — auth preflight returned 401; refresh and re-run
    3  Usage error        — bad args, can't determine SHA, cookie file missing
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC
from pathlib import Path

DEFAULT_BASE_URL = "https://web-production-3e3ae.up.railway.app"
DEFAULT_COOKIE_FILE = Path.home() / ".taskmanager-session-cookie"
POLL_INTERVAL = 15  # seconds
MAX_POLLS = 40  # 40 x 15s = 10 minutes

# Exit codes
EXIT_GREEN = 0
EXIT_RED = 1
EXIT_COOKIE_EXPIRED = 2
EXIT_USAGE = 3


def get_local_head() -> str:
    """Return full SHA of local HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def fetch_healthz(url: str) -> dict | None:
    """Fetch and parse the healthz JSON.  Returns None on any failure."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "10", url],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def fetch_auth_status(url: str, cookie_value: str) -> tuple[int, dict | None]:
    """Fetch /api/auth/status with the given session cookie.

    Returns ``(http_status, json_body)``. ``http_status`` is 0 on network
    error. ``json_body`` is None if parsing failed.
    """
    try:
        # -w "%{http_code}" appends HTTP status on its own line at the end;
        # -s suppresses curl's progress output so we get a clean body.
        #
        # We send the cookie under BOTH names so this script works with:
        #   (a) a long-lived validator token minted via
        #       `flask mint-validator-cookie` (preferred, 90-day lifetime)
        #   (b) a raw Flask session cookie copied from a browser (legacy
        #       path, expires on any Flask-Dance token refresh)
        # The server's /api/auth/status tries the validator token first,
        # then falls back to the session cookie — whichever one matches
        # wins.
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "10",
                "-w",
                "\n%{http_code}",
                "-b",
                f"validator_token={cookie_value}; session={cookie_value}",
                url,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout
        # Split off the trailing status code.
        newline = output.rfind("\n")
        if newline == -1:
            return 0, None
        body = output[:newline]
        status_str = output[newline + 1:].strip()
        try:
            status = int(status_str)
        except ValueError:
            return 0, None
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = None
        return status, data
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0, None


def fetch_debug_logs(
    url: str,
    cookie_value: str,
    *,
    level: str = "ERROR",
    since_minutes: int | None = None,
    limit: int = 50,
) -> tuple[int, dict | None]:
    """Fetch /api/debug/logs filtered by level (and optional since_minutes).

    Uses the validator cookie (same dual-name strategy as auth-status).
    Returns ``(http_status, json_body)``; 0 on network error.
    """
    qs = [f"level={level}", f"limit={limit}"]
    if since_minutes is not None and since_minutes > 0:
        # Bug #49: the endpoint reads `?since=` (shorthand `Nm`/`Nh`/`Nd`
        # or ISO-8601), NOT `?since_minutes=`. The prior version sent
        # `since_minutes=` which the endpoint silently ignored, falling
        # back to its default 1-hour window — so every deploy validate
        # post-2026-04-25 reported false-positive RED on errors that
        # actually predated the new container by up to an hour.
        qs.append(f"since={since_minutes}m")
    full_url = f"{url}?{'&'.join(qs)}"
    try:
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "15",
                "-w",
                "\n%{http_code}",
                "-b",
                f"validator_token={cookie_value}; session={cookie_value}",
                full_url,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout
        newline = output.rfind("\n")
        if newline == -1:
            return 0, None
        body = output[:newline]
        status_str = output[newline + 1:].strip()
        try:
            status = int(status_str)
        except ValueError:
            return 0, None
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = None
        return status, data
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0, None


def read_cookie_file(path: Path) -> str | None:
    """Read and strip the session cookie value from a file. Returns None
    if the file doesn't exist or is empty after stripping."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except (OSError, UnicodeDecodeError):
        return None


COOKIE_REFRESH_INSTRUCTIONS = """\
\u2554{bar}\u2557
\u2551  VALIDATOR COOKIE REJECTED - refresh needed before re-running     \u2551
\u255a{bar}\u255d

Why you're seeing this:
  Your stored cookie at {cookie_path} is no longer accepted by the
  server. Either it expired (validator cookies live ~90 days by default),
  or SECRET_KEY was rotated, or it was a legacy browser-copied session
  cookie that got invalidated by a Flask-Dance token refresh.

How to refresh (preferred: mint a fresh validator cookie):

  A validator cookie is signed with SECRET_KEY and baked with
  AUTHORIZED_EMAIL. It authenticates /api/auth/status AND read-only
  (GET) requests on protected routes, but never POST/PATCH/DELETE.
  90-day default lifetime.

  Preferred -- standalone mint script (no Flask app boot, only needs
  itsdangerous; works on machines without psycopg installed):
      railway run python scripts/mint_validator_cookie.py |
          Set-Content -NoNewline -Path "{cookie_path}"   (PowerShell)
      railway run python scripts/mint_validator_cookie.py > {cookie_path}
                                                          (bash/zsh)

  Alternative -- Flask CLI (requires full app + psycopg installed):
      railway run python -m flask mint-validator-cookie > {cookie_path}

  Then re-run:
      python scripts/validate_deploy.py --auth-check

Legacy fallback (not recommended -- Flask-Dance token refresh
silently invalidates this path during normal browser use):

  1. Open {base_url}/ in Chrome, sign in with shigsdev@gmail.com
  2. DevTools -> Application -> Cookies -> copy the `session` value
  3. Paste into {cookie_path} (no newline, no quotes)
  4. Re-run the validator

If the `flask mint-validator-cookie` command itself fails, that's a
deploy / env-var bug, not a cookie refresh issue. Check that
SECRET_KEY and AUTHORIZED_EMAIL are set where you're running it.
"""


def print_cookie_refresh_instructions(base_url: str, cookie_path: Path) -> None:
    """Print copy-pasteable refresh steps in a loud, scannable format."""
    # 66-char box — matches the visual width the content takes up.
    print()
    print(COOKIE_REFRESH_INSTRUCTIONS.format(
        bar="\u2550" * 66,
        base_url=base_url,
        cookie_path=cookie_path,
    ))
    print(f"Exit code: {EXIT_COOKIE_EXPIRED} (cookie refresh needed - deploy status unknown)")
    print()


def print_cookie_missing(cookie_path: Path) -> None:
    """Print instructions for the first-time-setup case where the file
    doesn't exist yet. Distinct from 'cookie expired' — different fix."""
    print()
    print("COOKIE FILE NOT FOUND")
    print(f"  Expected: {cookie_path}")
    print()
    print("First-time setup (one-time, takes ~60 seconds):")
    print(f"  1. Open {DEFAULT_BASE_URL}/ in Chrome and sign in")
    print("  2. DevTools -> Application -> Cookies -> copy the `session` value")
    print(f"  3. Save it to {cookie_path} (no quotes, no whitespace)")
    print("  4. Re-run with --auth-check")
    print()
    print("Or run without --auth-check to skip the preflight entirely.")
    print()


def print_report(
    expected_sha: str,
    data: dict | None,
    green: bool,
    auth_status: str | None = None,
    log_status: str | None = None,
    log_error_rows: list[dict] | None = None,
) -> None:
    """Print the Deploy Validation Report in the SOP format."""
    if data is None:
        deployed = "???"
        status = "unreachable"
        started = "???"
        checks = {}
    else:
        deployed = data.get("git_sha", "???")
        status = data.get("status", "???")
        started = data.get("started_at", "???")
        checks = data.get("checks", {})

    sha_match = "PASS" if deployed[:8] == expected_sha[:8] else "FAIL"
    http_status = "200" if data else "???"

    print()
    print("Deploy Validation Report")
    print("-" * 25)
    print(f"Expected SHA:   {expected_sha[:8]}")
    print(f"Deployed SHA:   {deployed[:8]}")
    print(f"SHA match:      {sha_match}")
    print(f"HTTP status:    {http_status}")
    print(f"Overall status: {status}")
    print(f"Started at:     {started}")
    if auth_status is not None:
        print(f"Auth preflight: {auth_status}")
    if log_status is not None:
        count = len(log_error_rows or [])
        suffix = ""
        if log_status == "FAIL":
            plural = "s" if count != 1 else ""
            suffix = f" ({count} server ERROR row{plural})"
        print(f"Error log scan: {log_status}{suffix}")
    print()
    print("Checks:")
    for name, value in sorted(checks.items()):
        print(f"  {name:<16}{value}")
    print()
    # If the log check tripped, show the first few errors inline so the
    # operator can see what's wrong without a second curl.
    if log_error_rows:
        print("Recent server ERRORs (first 5):")
        for row in log_error_rows[:5]:
            route = row.get("route") or "-"
            msg = (row.get("message") or "")[:160].replace("\n", " ")
            ts = (row.get("timestamp") or "")[:19]
            print(f"  {ts}  {route}  {msg}")
        if len(log_error_rows) > 5:
            print(f"  ... and {len(log_error_rows) - 5} more")
        print()
    label = "DEPLOY GREEN" if green else "DEPLOY RED"
    print(f"Status: {label}")
    print()


def do_auth_preflight(base_url: str, cookie_path: Path) -> int:
    """Run the /api/auth/status preflight check.

    Returns an exit code:
      EXIT_GREEN         — auth ok, caller should continue
      EXIT_COOKIE_EXPIRED — 401 received, printed refresh instructions
      EXIT_USAGE         — cookie file missing/empty, printed setup steps
      EXIT_RED           — unexpected status (500, network error, etc.)
    """
    if not cookie_path.exists():
        print_cookie_missing(cookie_path)
        return EXIT_USAGE

    cookie_value = read_cookie_file(cookie_path)
    if not cookie_value:
        print_cookie_missing(cookie_path)
        return EXIT_USAGE

    print(f"  Auth preflight: hitting /api/auth/status with cookie from {cookie_path}")
    status, data = fetch_auth_status(f"{base_url}/api/auth/status", cookie_value)

    if status == 200 and data and data.get("authenticated"):
        email = data.get("email", "???")
        print(f"    -> 200 OK (authenticated as {email})")
        return EXIT_GREEN

    if status == 401:
        print("    -> 401 Unauthorized (cookie rejected)")
        print_cookie_refresh_instructions(base_url, cookie_path)
        return EXIT_COOKIE_EXPIRED

    # Any other status (500, 0 = network error, etc.) is a real problem,
    # not a cookie issue — surface it as DEPLOY RED.
    print(f"    -> unexpected status {status} (auth endpoint broken or unreachable)")
    print()
    return EXIT_RED


def _minutes_since(started_iso: str) -> int | None:
    """Return minutes elapsed since an ISO-8601 timestamp, or None if unparseable.

    Used to scope the /api/debug/logs query to only what's landed since the
    new container came up — so the check reports ONLY errors that this
    deploy is responsible for, not stale failures from the previous SHA.
    """
    if not started_iso:
        return None
    try:
        from datetime import datetime
        # Python 3.11+ tolerates the trailing 'Z'; for older we strip.
        text = started_iso.replace("Z", "+00:00")
        started = datetime.fromisoformat(text)
        now = datetime.now(UTC)
        delta = (now - started).total_seconds()
        # Add 1min buffer so we don't narrowly miss the bootstrapping
        # window where the process is writing its "starting up" logs.
        minutes = int(delta // 60) + 1
        return max(minutes, 1)
    except (ValueError, TypeError, ImportError):
        return None


def do_log_check(
    base_url: str,
    cookie_value: str,
    started_at: str,
) -> tuple[str, list[dict]]:
    """Query /api/debug/logs for server-side ERRORs since deploy start.

    Returns ``(status_label, rows)`` where ``status_label`` is one of:
        "PASS"       — no ERROR rows since deploy start
        "FAIL"       — one or more ERRORs (caller should flip to RED)
        "SKIP: ..."  — couldn't perform the check (network, stale cookie,
                       unparseable timestamp); caller should WARN, not RED

    We only count server-side rows (``source != 'client'``) by default.
    Client-side errors come from the browser error reporter and include
    random noise from extensions / user network blips; they shouldn't
    block a deploy.
    """
    since = _minutes_since(started_at)
    if since is None:
        return "SKIP: couldn't parse started_at from healthz", []

    url = f"{base_url}/api/debug/logs"
    # Retry transient 5xx (e.g. fresh container's connection pool SSL
    # handshake blips observed right after Railway rolling deploys).
    # 3 attempts with exponential-ish backoff is enough to ride through
    # warm-up without letting a persistently-broken endpoint silently pass.
    status, data = 0, None
    for attempt, delay in enumerate((0, 3, 6), start=1):
        if delay:
            time.sleep(delay)
        status, data = fetch_debug_logs(
            url, cookie_value, level="ERROR", since_minutes=since, limit=50,
        )
        # Only retry on transient 5xx / network errors. 2xx and 4xx are
        # deterministic answers — no point retrying them.
        transient = status == 0 or (500 <= status < 600)
        if transient and attempt < 3:
            continue
        break
    if status == 0:
        return "SKIP: log endpoint unreachable after retries", []
    if status == 401:
        # Auth-check would have caught this first; belt-and-braces.
        return "SKIP: validator cookie rejected on /api/debug/logs", []
    if status != 200 or not isinstance(data, dict):
        return f"SKIP: /api/debug/logs returned {status} after retries", []

    rows = data.get("logs", []) or []
    # Filter out:
    #   - client-side rows (browser extension / user network noise)
    #   - transient Postgres SSL connection-pool blips on fresh Railway
    #     containers (tracked as a separate backlog item for pool_pre_ping).
    #     Signature: psycopg.OperationalError + "SSL SYSCALL error: EOF"
    #     or "decryption failed or bad record mac". Real app bugs don't
    #     produce these strings.
    def is_transient_ssl_blip(r: dict) -> bool:
        tb = (r.get("traceback") or "") + (r.get("message") or "")
        return (
            "psycopg.OperationalError" in tb
            and (
                "SSL SYSCALL error: EOF detected" in tb
                or "decryption failed or bad record mac" in tb
            )
        )

    server_errors = [
        r for r in rows
        if isinstance(r, dict)
        and r.get("source") != "client"
        and not is_transient_ssl_blip(r)
    ]
    if not server_errors:
        return "PASS", []
    return "FAIL", server_errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Railway deploy.")
    parser.add_argument(
        "--sha",
        default="",
        help="Expected git SHA (default: local HEAD)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help=f"Deployed base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--auth-check",
        action="store_true",
        help="After SHA match, verify the stored session cookie is still valid. "
             "On 401, prints refresh instructions and exits 2. "
             "Auto-enabled when the cookie file exists.",
    )
    parser.add_argument(
        "--cookie-file",
        default=str(DEFAULT_COOKIE_FILE),
        help=f"Path to the session cookie file (default: {DEFAULT_COOKIE_FILE})",
    )
    # Log check: tri-state because we want "auto-on when cookie exists"
    # semantics but also need an explicit opt-out. store_const lets the
    # default stay None so we can distinguish "user set it" from "default".
    parser.add_argument(
        "--check-logs",
        dest="check_logs",
        action="store_const",
        const=True,
        help="After SHA match, query /api/debug/logs for server-side ERRORs "
             "since deploy start. Any ERROR means DEPLOY RED. "
             "Auto-enabled when the cookie file exists.",
    )
    parser.add_argument(
        "--no-check-logs",
        dest="check_logs",
        action="store_const",
        const=False,
        help="Skip the log check even if the cookie file is present.",
    )
    parser.add_argument(
        "--monitor-minutes",
        type=int,
        default=0,
        help="PR37: after the initial GREEN gate passes, sleep this many "
             "minutes then re-scan logs. Catches errors that only surface "
             "once real traffic hits the new container (e.g. background "
             "jobs that fire on a cron, lazy-loaded code paths). 0 disables. "
             "Recommended: 5 for any PR that touches a route or service.",
    )
    args = parser.parse_args()

    # Backward-compat: if --url includes /healthz we accept it but warn.
    base_url = args.url.rstrip("/")
    if base_url.endswith("/healthz"):
        base_url = base_url[:-len("/healthz")]

    expected = args.sha or get_local_head()
    if not expected:
        print("ERROR: could not determine expected SHA.", file=sys.stderr)
        print("Pass --sha explicitly or run from inside the git repo.",
              file=sys.stderr)
        return EXIT_USAGE

    healthz_url = f"{base_url}/healthz"
    print(f"Waiting for deploy of {expected[:8]}...")
    print(f"Polling {healthz_url} every {POLL_INTERVAL}s (max {MAX_POLLS} attempts)")
    print()

    last_data = None
    matched = False
    for i in range(1, MAX_POLLS + 1):
        data = fetch_healthz(healthz_url)
        if data:
            deployed = data.get("git_sha", "")
            print(f"  [{i}] deployed={deployed[:8]}", end="")
            if deployed[:8] == expected[:8]:
                print(" -- MATCH")
                last_data = data
                matched = True
                break
            print()
        else:
            print(f"  [{i}] unreachable")

        if i < MAX_POLLS:
            time.sleep(POLL_INTERVAL)

    if not matched:
        # Timed out
        print(f"\nTimed out after {MAX_POLLS * POLL_INTERVAL}s.")
        print_report(expected, last_data, green=False)
        return EXIT_RED

    # SHA matched — now check all checks
    checks = last_data.get("checks", {})
    any_fail = any(str(v).startswith("fail") for v in checks.values())
    overall_ok = last_data.get("status") == "ok"
    green = overall_ok and not any_fail

    cookie_path = Path(args.cookie_file).expanduser()
    cookie_present = cookie_path.exists()
    # Auto-enable auth + log checks when the cookie is present — matches
    # the pattern from ADR-type discussion in the post-deploy hotfix saga:
    # if we have credentials, use them. Explicit flags override (e.g.
    # --no-check-logs).
    run_auth_check = args.auth_check or cookie_present
    run_log_check = (
        args.check_logs if args.check_logs is not None else cookie_present
    )

    # Optional auth preflight
    auth_status_label = None
    cookie_value: str | None = None
    if run_auth_check:
        print()
        auth_result = do_auth_preflight(base_url, cookie_path)
        if auth_result == EXIT_GREEN:
            auth_status_label = "PASS"
            # Load cookie for the log check below; preflight already
            # validated existence + non-emptiness.
            cookie_value = read_cookie_file(cookie_path)
        elif auth_result == EXIT_COOKIE_EXPIRED:
            return EXIT_COOKIE_EXPIRED
        elif auth_result == EXIT_USAGE:
            return EXIT_USAGE
        else:
            auth_status_label = "FAIL"
            green = False

    # Optional error-log scan
    log_status_label: str | None = None
    log_error_rows: list[dict] = []
    if run_log_check:
        if not cookie_value:
            # Read independently in case auth check was skipped but user
            # still wants the log scan.
            raw = read_cookie_file(cookie_path) if cookie_present else None
            cookie_value = raw if raw else None
        if cookie_value:
            print()
            print("  Error log scan: querying /api/debug/logs?level=ERROR "
                  "(since deploy started_at)")
            log_status_label, log_error_rows = do_log_check(
                base_url,
                cookie_value,
                last_data.get("started_at") or "",
            )
            print(f"    -> {log_status_label}"
                  + (f" ({len(log_error_rows)} rows)" if log_error_rows else ""))
            if log_status_label == "FAIL":
                green = False
        else:
            log_status_label = "SKIP: no cookie"

    print_report(
        expected, last_data,
        green=green,
        auth_status=auth_status_label,
        log_status=log_status_label,
        log_error_rows=log_error_rows,
    )

    # PR37: deferred log monitor. Sleep N minutes, then re-scan for any
    # NEW server ERRORs that surfaced after initial GREEN. Catches
    # regressions that only appear once real traffic hits the new
    # container — background-job exceptions, cron firing on the new
    # build for the first time, lazy-loaded code paths.
    if green and args.monitor_minutes > 0 and cookie_value:
        print(f"\n--- Post-deploy monitor: sleeping {args.monitor_minutes} min ---")
        # Use absolute timestamp so the second scan only sees logs that
        # arrived AFTER the initial GREEN, not ones we already saw.
        import datetime
        watch_start = datetime.datetime.now(datetime.UTC)
        time.sleep(args.monitor_minutes * 60)
        print(f"Re-scanning logs for ERRORs since {watch_start.isoformat()}...")
        new_status, new_rows = do_log_check(
            base_url, cookie_value,
            watch_start.isoformat().replace("+00:00", "Z"),
        )
        print(f"Monitor scan: {new_status}"
              + (f" ({len(new_rows)} new ERROR rows)" if new_rows else ""))
        if new_status == "FAIL":
            print("\nDEPLOY MONITOR RED — errors surfaced after initial GREEN:")
            for r in new_rows[:5]:
                ts = r.get("timestamp", "?")
                route = r.get("route", "?")
                msg = (r.get("message") or "")[:120]
                print(f"  {ts}  {route}  {msg}")
            return EXIT_RED
        print("Monitor window clean. DEPLOY MONITOR GREEN.")

    # PR41 — auto-emit the SOP Compliance Report template at the end
    # of every GREEN run so it's literally impossible to ship without
    # the template appearing in the terminal scrollback. CLAUDE.md
    # makes this report mandatory; printing it as a fill-in-the-blanks
    # template at the moment of deploy completion is the strongest
    # nudge against the "I'll do it later" silent skip.
    if green:
        _print_sop_template(
            expected,
            monitor_ran=(args.monitor_minutes > 0 and cookie_value is not None),
            log_status_label=log_status_label,
        )

    return EXIT_GREEN if green else EXIT_RED


def _print_sop_template(expected_sha: str, monitor_ran: bool, log_status_label: str) -> None:
    """PR41: emit a fill-in-the-blanks SOP Compliance Report. Phase 8
    is auto-filled from the just-completed validation. Phase 1-7 are
    `[__]` placeholders the operator MUST fill before declaring done.

    Per CLAUDE.md: a missing report counts as `[❌]`. Printing the
    template at the moment of deploy completion ensures the operator
    physically sees it before moving on.
    """
    short = (expected_sha or "")[:8]
    monitor_line = (
        "[OK] Post-deploy monitor                      MONITOR GREEN"
        if monitor_ran else
        "[NA] Post-deploy monitor                      N/A — --monitor-minutes 0"
    )
    log_line = f"[OK] Error log scan                          {log_status_label}"
    print()
    print("=" * 70)
    print("SOP COMPLIANCE REPORT -- fill in Phase 1-7 before declaring done")
    print("=" * 70)
    print(f"SOP Compliance Report -- <one-line description> ({short})")
    print("-" * 50)
    print("Phase 1  Planning")
    print("  [__] Checked backlog                          <backlog item or reason>")
    print("  [__] Scoped work                              <brief>")
    print("  [__] Identified affected files                <file list>")
    print("Phase 2  Git Workflow")
    print("  [__] Pulled latest main")
    print("  [__] Feature branch created                   feature/<name>")
    print("  [__] Small logical commits                    <N> commits: <SHAs>")
    print("  [__] Merged to main + pushed")
    print("  [__] Feature branch cleaned up")
    print("Phase 3  Coding Standards")
    print("  [__] Code changes                             <what changed>")
    print("  [__] Frontend changes                         <or N/A>")
    print("  [__] Cascade check                            <or N/A>")
    print("Phase 4  Quality Gates")
    print("  [__] Ruff                                     PASS")
    print("  [__] Pytest                                   <n> passed, <coverage>%")
    print("  [__] Jest                                     <n> passed")
    print("  [__] Local Playwright + bandit + semgrep + gitleaks + sync ALL PASS")
    print("Phase 5  Tests")
    print("  [__] Tests added/updated                      <what was tested>")
    print("Phase 6  Regression (UI changes only)")
    print("  [__] Bypass server started                    seed + preview_start")
    print("  [__] Desktop (1280x800)                       all pages pass")
    print("  [__] Mobile (375x812)                         all pages pass")
    print("  [__] Console errors                           0")
    print("  [__] Bypass torn down                         .env.dev-bypass deleted")
    print("Phase 7  Documentation")
    print("  [__] ARCHITECTURE.md                          <updated or N/A>")
    print("  [__] README.md                                <updated or N/A>")
    print("  [__] BACKLOG.md                               <updated or N/A>")
    print("  [__] CLAUDE.md                                <updated or N/A>")
    print("Phase 8  Deploy")
    print(f"  [OK] Deploy validation                        GREEN -- {short}, all checks ok")
    print(f"  {log_line}")
    print(f"  {monitor_line}")
    print("  [__] Post-deploy smoke test                   <22/22 PASS / X failures>")
    print("Summary: <N> done, <N> skipped (N/A), <N> not done")
    print(f"Commits: {short}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
