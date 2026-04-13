"""Post-deploy validation script.

Usage:
    python scripts/validate_deploy.py [--sha <expected>] [--url <healthz_url>]

Polls the /healthz endpoint until the deployed SHA matches the expected SHA
(default: HEAD of the local repo), then prints a Deploy Validation Report.

Exit codes:
    0  DEPLOY GREEN — SHA matches, all checks pass
    1  DEPLOY RED   — SHA mismatch, failed checks, or timeout
    2  Usage error  (bad args, can't determine SHA, etc.)
"""

import argparse
import json
import subprocess
import sys
import time

DEFAULT_URL = "https://web-production-3e3ae.up.railway.app/healthz"
POLL_INTERVAL = 15  # seconds
MAX_POLLS = 40  # 40 × 15s = 10 minutes


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


def print_report(
    expected_sha: str,
    data: dict | None,
    green: bool,
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
    print()
    print("Checks:")
    for name, value in sorted(checks.items()):
        print(f"  {name:<16}{value}")
    print()
    label = "DEPLOY GREEN" if green else "DEPLOY RED"
    print(f"Status: {label}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Railway deploy.")
    parser.add_argument(
        "--sha",
        default="",
        help="Expected git SHA (default: local HEAD)",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Healthz URL (default: {DEFAULT_URL})",
    )
    args = parser.parse_args()

    expected = args.sha or get_local_head()
    if not expected:
        print("ERROR: could not determine expected SHA.", file=sys.stderr)
        print("Pass --sha explicitly or run from inside the git repo.",
              file=sys.stderr)
        return 2

    print(f"Waiting for deploy of {expected[:8]}...")
    print(f"Polling {args.url} every {POLL_INTERVAL}s (max {MAX_POLLS} attempts)")
    print()

    last_data = None
    for i in range(1, MAX_POLLS + 1):
        data = fetch_healthz(args.url)
        if data:
            deployed = data.get("git_sha", "")
            print(f"  [{i}] deployed={deployed[:8]}", end="")
            if deployed[:8] == expected[:8]:
                print(" -- MATCH")
                last_data = data
                break
            print()
        else:
            print(f"  [{i}] unreachable")

        if i < MAX_POLLS:
            time.sleep(POLL_INTERVAL)
    else:
        # Timed out
        print(f"\nTimed out after {MAX_POLLS * POLL_INTERVAL}s.")
        print_report(expected, last_data, green=False)
        return 1

    # SHA matched — now check all checks
    checks = last_data.get("checks", {})
    any_fail = any(
        str(v).startswith("fail") for v in checks.values()
    )
    overall_ok = last_data.get("status") == "ok"
    green = overall_ok and not any_fail

    print_report(expected, last_data, green=green)
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
