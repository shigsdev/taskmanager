"""#325 Reflection milestone — the runway the weekly reflection points at.

A reflection is more useful when it knows what it is counting down to.
This module stores ONE milestone ("what you're working toward, and by
when") and resolves it for both the /reflection header and the Claude
prompt, so proposals get sequenced against a real deadline instead of
floating free.

The name comes from one of two places (user's choice, #325):

  custom  — a label you type. Fully self-contained.
  goal    — a link to a Goal. The label then FOLLOWS that goal's title,
            and the goal id is handed to Claude so proposals can hang
            off the goal the plan belongs to.

Note the date is always stored here, never read off the goal: the
``goals`` table has no ``target_date`` column — only a free-text
``target_quarter`` ("Q4 2026"), which cannot drive a day-accurate
countdown.

Persistence is the existing ``AppSetting`` key/value store, so this
needs no migration. Single-user app — exactly one milestone.
"""
from __future__ import annotations

import uuid
from datetime import date

from models import AppSetting, Goal, GoalStatus, db
from utils import local_today_date

# AppSetting keys. Namespaced so the store stays readable.
LABEL_KEY = "reflection_milestone_label"
DATE_KEY = "reflection_milestone_date"
GOAL_ID_KEY = "reflection_milestone_goal_id"

_ALL_KEYS = (LABEL_KEY, DATE_KEY, GOAL_ID_KEY)


# --- tiny AppSetting helpers -------------------------------------------------


def _get(key: str) -> str | None:
    row = AppSetting.query.filter_by(key=key).first()
    return row.value if row is not None and row.value != "" else None


def _put(key: str, value: str | None) -> None:
    row = AppSetting.query.filter_by(key=key).first()
    if value is None or value == "":
        if row is not None:
            db.session.delete(row)
        return
    if row is None:
        db.session.add(AppSetting(key=key, value=value[:500]))
    else:
        row.value = value[:500]


# --- pure countdown math -----------------------------------------------------


def countdown(target: date | None, today: date | None = None) -> dict:
    """Days/weeks between ``today`` and ``target``.

    Pure and injectable so the boundary cases are testable: the target
    day ITSELF is 0 days left (not 1, not -1), and a past target reports
    negative days with ``passed=True`` rather than clamping to zero —
    a milestone that has gone by should say so, not quietly read "0
    days left" forever.

    ``weeks_left`` rounds UP, because "6 days left" is meaningfully
    "1 week", not "0 weeks".
    """
    if target is None:
        return {"days_left": None, "weeks_left": None, "passed": False}
    today = today or local_today_date()
    days = (target - today).days
    weeks = -(-days // 7) if days >= 0 else -((-days) // 7)
    return {"days_left": days, "weeks_left": weeks, "passed": days < 0}


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


# --- resolution --------------------------------------------------------------


def get_milestone(today: date | None = None) -> dict:
    """The current milestone, resolved for display + the Claude prompt.

    Shape::

        {configured, source, label, date, goal_id, goal_title,
         days_left, weeks_left, passed, warning}

    ``warning`` is set (and ``source`` degrades to "custom") when a
    LINKED goal has gone away or been completed. Degrading loudly rather
    than silently is the whole point — a countdown that quietly stops
    tracking is worse than no countdown.
    """
    target = _parse_date(_get(DATE_KEY))
    stored_label = _get(LABEL_KEY)
    goal_id_raw = _get(GOAL_ID_KEY)

    source = None
    label = stored_label
    goal_id = None
    goal_title = None
    warning = None

    if goal_id_raw:
        goal = None
        try:
            goal = db.session.get(Goal, uuid.UUID(goal_id_raw))
        except (TypeError, ValueError):
            goal = None
        if goal is None:
            warning = (
                "The linked goal no longer exists — showing the saved name. "
                "Re-link or set a name to clear this."
            )
        elif not goal.is_active:
            warning = (
                f"The linked goal “{goal.title}” was deleted — showing "
                "the saved name. Re-link or set a name to clear this."
            )
        elif goal.status == GoalStatus.DONE:
            # Not an error — finishing the goal is good news — but the
            # countdown shouldn't keep presenting it as live work.
            source = "goal"
            goal_id = str(goal.id)
            goal_title = goal.title
            label = goal.title
            warning = f"“{goal.title}” is marked done."
        else:
            source = "goal"
            goal_id = str(goal.id)
            goal_title = goal.title
            label = goal.title

    if source is None and (stored_label or target):
        source = "custom"

    counts = countdown(target, today)
    return {
        "configured": source is not None,
        "source": source,
        "label": label,
        "date": target.isoformat() if target else None,
        "goal_id": goal_id,
        "goal_title": goal_title,
        "warning": warning,
        **counts,
    }


def set_milestone(
    *,
    label: str | None = None,
    target_date: str | None = None,
    goal_id: str | None = None,
) -> dict:
    """Set (or update) the milestone. Returns the resolved milestone.

    Passing ``goal_id`` links the label to that goal; passing ``label``
    without a goal_id unlinks and uses the typed name. The date is
    always stored here either way.

    Raises ValueError on an unparseable date or an unknown goal — a
    silently-ignored bad value would leave the user staring at a header
    that didn't change.
    """
    if (target_date is not None and target_date != ""
            and _parse_date(target_date) is None):
        raise ValueError("target_date must be YYYY-MM-DD")

    if goal_id:
        try:
            goal = db.session.get(Goal, uuid.UUID(goal_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("goal_id must be a UUID") from exc
        if goal is None:
            raise ValueError("goal not found")
        _put(GOAL_ID_KEY, str(goal.id))
        # Keep the title as a fallback label so a later deletion still
        # renders something meaningful instead of a blank header.
        _put(LABEL_KEY, goal.title)
    else:
        _put(GOAL_ID_KEY, None)
        if label is not None:
            _put(LABEL_KEY, label.strip() or None)

    if target_date is not None:
        _put(DATE_KEY, target_date or None)

    db.session.commit()
    return get_milestone()


def clear_milestone() -> None:
    """Remove the milestone entirely."""
    for key in _ALL_KEYS:
        _put(key, None)
    db.session.commit()


def milestone_prompt_line(today: date | None = None) -> str:
    """One line of runway context for the Claude prompt, or "".

    Deliberately terse: it tells Claude what the deadline is and to
    sequence against it, without lecturing — the model already knows how
    to plan, it just never knew the date existed.
    """
    m = get_milestone(today)
    if not m["configured"] or not m["date"]:
        return ""
    label = m["label"] or "their milestone"
    if m["passed"]:
        return (
            f"The user's milestone “{label}” was {m['date']}, "
            f"{abs(m['days_left'])} day(s) ago."
        )
    line = (
        f"The user is working toward “{label}” on {m['date']} — "
        f"{m['days_left']} day(s) away (~{m['weeks_left']} week(s)). "
        "Sequence and time-box your proposals against that runway; "
        "prefer work that can realistically land before it."
    )
    if m["goal_id"]:
        line += (
            f" That milestone is goal id {m['goal_id']} — attach related "
            "new tasks to that goal unless the user says otherwise."
        )
    return line
