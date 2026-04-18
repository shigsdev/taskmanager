"""Post-deploy validation script.

Usage:
    python scripts/validate_deploy.py [--sha <expected>] [--url <base_url>]
                                      [--auth-check] [--cookie-file <path>]

Default behavior (no flags):
    Polls the /healthz endpoint until the deployed SHA matches the expected
    SHA (default: HEAD of the local repo), then prints a Deploy Validation
    Report.

With --auth-check:
    Also reads a Flask session cookie from ~/.taskmanager-session-cookie
    (or --cookie-file) and hits /api/auth/status to verify the cookie is
    still valid. On 401 (cookie expired), prints copy-pasteable refresh
    instructions and exits 2, distinguishing "cookie stale" from "deploy
    broken".

Exit codes:
    0  DEPLOY GREEN       — SHA matches, all checks pass, auth ok (if checked)
    1  DEPLOY RED         — SHA mismatch, failed checks, or timeout
    2  COOKIE EXPIRED     — auth preflight returned 401; refresh and re-run
    3  Usage error        — bad args, can't determine SHA, cookie file missing
"""

import argparse
import json
import subprocess
import sys
import time
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
    print()
    print("Checks:")
    for name, value in sorted(checks.items()):
        print(f"  {name:<16}{value}")
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
             "On 401, prints refresh instructions and exits 2.",
    )
    parser.add_argument(
        "--cookie-file",
        default=str(DEFAULT_COOKIE_FILE),
        help=f"Path to the session cookie file (default: {DEFAULT_COOKIE_FILE})",
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

    # Optional auth preflight (opt-in via --auth-check)
    auth_status_label = None
    if args.auth_check:
        print()
        cookie_path = Path(args.cookie_file).expanduser()
        auth_result = do_auth_preflight(base_url, cookie_path)
        if auth_result == EXIT_GREEN:
            auth_status_label = "PASS"
        elif auth_result == EXIT_COOKIE_EXPIRED:
            # Already printed refresh instructions; just return.
            return EXIT_COOKIE_EXPIRED
        elif auth_result == EXIT_USAGE:
            # Already printed cookie-missing instructions; just return.
            return EXIT_USAGE
        else:
            auth_status_label = "FAIL"
            green = False

    print_report(expected, last_data, green=green, auth_status=auth_status_label)
    return EXIT_GREEN if green else EXIT_RED


if __name__ == "__main__":
    sys.exit(main())
