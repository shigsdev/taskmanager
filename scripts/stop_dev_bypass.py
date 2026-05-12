"""Stop any local-dev bypass Flask process bound to port 5111.

Why this exists: ``scripts/run_dev_bypass.py`` is a long-running
Flask dev server. When started via the shell as a background process
(``python scripts/run_dev_bypass.py &``) the process keeps running
until something explicitly kills it. The marker file
``.env.dev-bypass`` only gates whether NEW process starts allow
bypass — deleting it does NOT stop a process that's already running.

Symptoms of orphans:
  - You start a fresh ``run_dev_bypass.py`` and it errors with
    ``OSError: [Errno 98] Address already in use`` on 5111.
  - The Claude Code background-task list shows a stale
    "Start dev bypass" task that won't go away.
  - Browser hits to http://localhost:5111 return data from a
    stale code path (the running process is on an older commit).

Usage (cross-platform):
    python scripts/stop_dev_bypass.py

Exit codes:
    0 — port 5111 is free (either already free, or we killed it)
    1 — couldn't enumerate listening processes (unsupported OS)
    2 — found a process but couldn't kill it (insufficient perms)

Safe to run anytime; idempotent; does nothing when the port is
already free.
"""
from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import time

PORT = 5111


def _pids_on_port_windows(port: int) -> list[int]:
    """Parse ``netstat -ano`` lines for LISTENING entries on the port."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.stderr.write(f"could not run netstat: {e}\n")
        return []
    pids: set[int] = set()
    import contextlib

    needle = f":{port} "
    for line in out.splitlines():
        if needle not in line or "LISTENING" not in line:
            continue
        # netstat output last column = PID
        parts = line.split()
        if not parts:
            continue
        with contextlib.suppress(ValueError):
            pids.add(int(parts[-1]))
    return sorted(pids)


def _pids_on_port_unix(port: int) -> list[int]:
    """Use ``lsof -ti`` on Mac/Linux to find PIDs bound to the port."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        sys.stderr.write(
            "lsof not found; install with `brew install lsof` or "
            "`apt-get install lsof`\n",
        )
        return []
    pids: list[int] = []
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _kill_pid(pid: int) -> bool:
    """Kill a PID cross-platform. Returns True on success."""
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            sys.stderr.write(
                f"could not kill PID {pid}: {e.stderr or e}\n",
            )
            return False
    # Unix: SIGTERM, then SIGKILL after 1s if still alive.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True  # already gone
    except PermissionError:
        sys.stderr.write(f"no permission to kill PID {pid}\n")
        return False
    time.sleep(1.0)
    try:
        os.kill(pid, 0)  # exists?
    except ProcessLookupError:
        return True
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def main() -> int:
    if platform.system() == "Windows":
        pids = _pids_on_port_windows(PORT)
    else:
        pids = _pids_on_port_unix(PORT)

    if not pids:
        sys.stdout.write(f"port {PORT} is already free\n")
        # Also remove the marker file as a courtesy — common pattern
        # is to leave it behind after a manual teardown.
        if os.path.exists(".env.dev-bypass"):
            try:
                os.remove(".env.dev-bypass")
                sys.stdout.write("(also removed .env.dev-bypass)\n")
            except OSError:
                pass
        return 0

    sys.stdout.write(
        f"found {len(pids)} process(es) on port {PORT}: {pids}\n",
    )
    failed = 0
    for pid in pids:
        if _kill_pid(pid):
            sys.stdout.write(f"  killed PID {pid}\n")
        else:
            failed += 1
    # Remove marker file so a future start is a clean state.
    if os.path.exists(".env.dev-bypass"):
        try:
            os.remove(".env.dev-bypass")
            sys.stdout.write("removed .env.dev-bypass\n")
        except OSError:
            pass

    if failed:
        return 2
    # Verify the port is actually free now.
    time.sleep(0.5)
    leftover = (
        _pids_on_port_windows(PORT) if platform.system() == "Windows"
        else _pids_on_port_unix(PORT)
    )
    if leftover:
        sys.stderr.write(f"port {PORT} still busy: {leftover}\n")
        return 2
    sys.stdout.write(f"port {PORT} is now free\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
