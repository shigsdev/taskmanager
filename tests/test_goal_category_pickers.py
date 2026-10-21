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
# (NOT goal_filter_helpers.js or inbox_categorize.js — those map each
# category to the task type it fits — work, personal, or both for BAU
# since #285 — a deliberate transform, not a "list all categories"
# surface.)
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



# --- #512: the server-rendered pickers and the server-side lists --------------


def _select_values(html: str, select_id: str) -> set[str]:
    import re

    block = re.search(rf'<select id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
    assert block, f"no <select id={select_id!r}>"
    return set(re.findall(r'<option value="([^"]*)"', block.group(1))) - {""}


def test_the_goals_page_selects_list_exactly_the_enum():
    """templates/goals.html is server HTML, not one of the JS lists above:
    the filter and the panel's Category select each offer every value
    and nothing else."""
    html = (STATIC.parent / "templates" / "goals.html").read_text(encoding="utf-8")
    for select_id in ("filterCategory", "goalCategory"):
        assert _select_values(html, select_id) == _enum_values(), select_id


def test_voice_and_scan_accept_exactly_the_enum():
    import scan_service

    assert set(scan_service._VOICE_VALID_CATEGORIES) == _enum_values()
    # Every category is on one side or both — none falls through (#285).
    assert _enum_values() >= scan_service._VOICE_WORK_CATEGORIES
    assert scan_service._VOICE_NEUTRAL_CATEGORIES <= scan_service._VOICE_WORK_CATEGORIES


def test_every_claude_prompt_that_names_categories_names_them_all():
    """A prompt that lists the categories but misses one makes Claude
    put those goals somewhere else."""
    import reflection_service

    # (scan's goal prompt has its own test in test_scan.py; import's
    # transcript prompt makes tasks only and names no category.)
    for name, prompt in (
        ("reflection _REFLECT_PROMPT", reflection_service._REFLECT_PROMPT),
    ):
        missing = sorted(v for v in _enum_values() if v not in prompt)
        assert not missing, f"{name} is missing {missing}"
