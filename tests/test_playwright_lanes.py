"""Tests for scripts/playwright_lanes.py (#521).

The gate's default of 8 Playwright lanes was benchmarked on a 32 GB /
32-core machine (#402). On an 8 GB / 8-core Mac the same 8 lanes swapped
and each full run failed a different handful of tests. The default now
comes from the machine: 2 GB of RAM per lane, no more lanes than CPUs,
capped at the ports the gate owns: 12, or 8 on Windows (#531).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from scripts import playwright_lanes as pl

GIB = 1024 ** 3


class TestLaneCount:
    @pytest.mark.parametrize(("cpus", "ram_gib", "expected"), [
        (32, 32, 8),    # the #402 benchmark machine keeps its 8
        (8, 8, 4),      # the 8 GB Mac that failed at 8 (#521)
        (4, 16, 4),     # few cores: CPU-bound
        (12, 12, 6),
        (8, 3, 1),      # tiny box still runs, serially
    ])
    def test_sized_by_ram_and_cpus(self, cpus, ram_gib, expected):
        assert pl.lane_count(cpus, ram_gib * GIB, pl.WINDOWS_LANE_MAX) == expected

    def test_never_more_than_the_ports_the_gate_owns(self):
        assert pl.lane_count(64, 256 * GIB) == pl.LANE_MAX == 12

    def test_nothing_known_keeps_the_old_default(self):
        assert pl.lane_count(None, None) == 8
        assert pl.lane_count(None, None, lane_max=4) == 4

    def test_unknown_ram_falls_back_to_cpus(self):
        assert pl.lane_count(6, None) == 6


class TestPlatformCap:
    """#531: 12 lanes on macOS / Linux, 8 on Windows (port pool, #403)."""

    def test_the_12_core_mac_gets_12(self):
        assert pl.lane_count(12, 32 * GIB, pl.lane_max_for("darwin")) == 12

    def test_the_windows_box_keeps_8(self):
        # 32 GB / 32 cores: RAM and CPUs allow 16; Windows' ports don't.
        assert pl.lane_count(32, 32 * GIB, pl.lane_max_for("win32")) == 8

    @pytest.mark.parametrize("platform", ["win32", "cygwin", "msys"])
    def test_every_windows_python_is_capped(self, platform):
        assert pl.lane_max_for(platform) == pl.WINDOWS_LANE_MAX == 8

    @pytest.mark.parametrize("platform", ["darwin", "linux"])
    def test_unix_gets_the_full_cap(self, platform):
        assert pl.lane_max_for(platform) == pl.LANE_MAX

    def test_gate_script_agrees(self):
        """The gate's LANE_MAX and its sanity regex must accept every count
        this script can print, and no more."""
        gate = (pathlib.Path(__file__).resolve().parents[1]
                / "scripts" / "run_all_gates.sh").read_text()
        assert re.search(r"^LANE_MAX=(\d+)$", gate, re.M).group(1) == str(pl.LANE_MAX)
        regex = re.search(r'\[\[ "\$PLAYWRIGHT_WORKERS" =~ (\S+) \]\]', gate).group(1)
        accepted = {n for n in range(0, 20) if re.fullmatch(regex, str(n))}
        assert accepted == set(range(1, pl.LANE_MAX + 1))


class TestDetection:
    def test_this_machine_reports_ram(self):
        ram = pl.total_ram_bytes()
        assert ram is None or ram > GIB  # None only where detection is unsupported

    def test_main_prints_one_lane_count(self, capsys):
        assert pl.main([]) == 0
        out = capsys.readouterr().out
        assert out.strip().isdigit()
        assert 1 <= int(out) <= pl.LANE_MAX
        assert out == out.strip()  # no newline: the gate reads it with $( )
