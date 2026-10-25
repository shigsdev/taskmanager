"""Print the default number of local Playwright lanes for this machine (#521).

Usage:
    python scripts/playwright_lanes.py

``run_all_gates.sh`` uses this when ``PLAYWRIGHT_WORKERS`` is unset. Each
lane is a Chromium worker plus its own waitress server and DB copy, so the
count is bounded by RAM and CPUs, not just the gate's ports:

- 2 GB of RAM per lane. #402 benchmarked 8 lanes on a 32 GB / 32-core
  machine; on an 8 GB / 8-core Mac the same 8 swapped (~1.5 GB out per
  run), and every full run failed a different 0-7 tests that passed alone:
  hung clicks, recordings that never started, cleanup hooks that timed out
  and leaked state into the next test on the lane.
- No more lanes than CPUs.
- At most ``LANE_MAX`` (ports 5111-5118, see the gate).

Whatever can't be measured is left out of the minimum, so a machine where
nothing is detected keeps the old default of 8. Prints the bare number (no
newline) and exits 0.
"""
from __future__ import annotations

import os
import subprocess
import sys

LANE_MAX = 8
RAM_PER_LANE = 2 * 1024 ** 3


def lane_count(cpus: int | None, ram_bytes: int | None) -> int:
    """Lanes for a machine with ``cpus`` CPUs and ``ram_bytes`` of RAM."""
    limits = [LANE_MAX]
    if cpus:
        limits.append(cpus)
    if ram_bytes:
        limits.append(ram_bytes // RAM_PER_LANE)
    return max(1, min(limits))


def total_ram_bytes() -> int | None:
    """Physical RAM, or None where it can't be read."""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout
            return int(out.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    if sys.platform == "win32":
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MemStatus(dwLength=ctypes.sizeof(_MemStatus))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullTotalPhys)
        return None
    # Linux, and Git Bash / MSYS (its python reads the same /proc).
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    sys.stdout.write(str(lane_count(os.cpu_count(), total_ram_bytes())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
