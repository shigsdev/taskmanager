"""Drift guard: every front-end goal-category picker must cover the
GoalCategory enum (#277).

#68 (2026-04-25) added `BAU = "bau"` to the GoalCategory enum, but
several JS pickers that hard-code the category list were never updated.
The most visible consequence (#277, 2026-05-30): the /goals page groups
goals by iterating `GOALS_CATEGORIES` in goals.js — a category missing
from that list renders NO section, so BAU goals silently vanished from
the page even though the rows were intact in the DB. The scan + import
category pickers had the same omission (you couldn't tag a goal BAU when
scanning or importing).

These lists live in plain JS (no shared enum across the Python/JS
boundary), so nothing mechanically tied them to the enum. This test
scrapes each picker file for the quoted category-value literals and
asserts the full enum is present — turning the next enum addition that
forgets a picker into a red test instead of a user-reported disappearance.
"""
from __future__ import annotations

import pathlib

from models import GoalCategory

STATIC = pathlib.Path(__file__).resolve().parents[1] / "static"

# Every file here renders a user-facing GOAL category picker / grouping.
# (NOT goal_filter_helpers.js or inbox_categorize.js — those map
# categories to the work/personal task-type bipartition, a deliberate
# transform, not a "list all categories" surface.)
GOAL_CATEGORY_PICKER_FILES = [
    "goals.js",        # GOALS_CATEGORIES — drives the /goals section grouping (#277 bug site)
    "scan.js",         # GOAL_CATEGORIES — scan-review category dropdown
    "import.js",       # import-candidate category dropdown
    "voice_memo.js",   # voice-memo review category dropdown
]


def _enum_values() -> set[str]:
    return {c.value for c in GoalCategory}


def test_every_goal_category_picker_covers_the_enum():
    """Each picker file must contain a quoted literal for every
    GoalCategory value. Catches the #68→#277 class of "added an enum
    member, forgot a consumer" drift across all four pickers at once."""
    enum_values = _enum_values()
    failures: list[str] = []
    for fname in GOAL_CATEGORY_PICKER_FILES:
        text = (STATIC / fname).read_text(encoding="utf-8")
        missing = sorted(
            v for v in enum_values
            if f'"{v}"' not in text and f"'{v}'" not in text
        )
        if missing:
            failures.append(f"{fname}: missing {missing}")
    assert not failures, (
        "Goal-category pickers fell behind the GoalCategory enum "
        f"({sorted(enum_values)}). Add the missing value(s) to each "
        f"picker:\n  " + "\n  ".join(failures)
    )


def test_guard_covers_a_known_picker_file():
    """Sanity: the guard list isn't empty and points at real files —
    a guard that scans nothing would pass vacuously."""
    assert GOAL_CATEGORY_PICKER_FILES
    for fname in GOAL_CATEGORY_PICKER_FILES:
        assert (STATIC / fname).is_file(), f"missing picker file {fname}"
