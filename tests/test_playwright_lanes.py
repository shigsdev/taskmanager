"""Tests for scripts/playwright_lanes.py (#521).

The gate's default of 8 Playwright lanes was benchmarked on a 32 GB /
32-core machine (#402). On an 8 GB / 8-core Mac the same 8 lanes swapped
and each full run failed a different handful of tests. The default now
comes from the machine: 2 GB of RAM per lane, no more lanes than CPUs,
capped at the 8 ports the gate owns.
"""
from __future__ import annotations

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
        assert pl.lane_count(cpus, ram_gib * GIB) == expected

    def test_never_more_than_the_ports_the_gate_owns(self):
        assert pl.lane_count(64, 256 * GIB) == pl.LANE_MAX == 8

    def test_unknown_ram_falls_back_to_cpus(self):
        assert pl.lane_count(6, None) == 6

    def test_nothing_known_keeps_the_old_default(self):
        assert pl.lane_count(None, None) == 8


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
