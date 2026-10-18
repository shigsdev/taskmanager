"""#500: turn what the user said to Siri into one action.

Spec: docs/design/500-siri-add-and-edit-by-voice.md §2-3. The Siri Shortcut
sends its dictated text unchanged; these fixed rules (no AI) decide what it
means. Pure functions — ``today`` is passed in — so ``voice_review_api``
stays thin and the rules are tested on their own (tests/test_voice_answer.py).

A command must be the WHOLE answer ("complete it tomorrow" means nothing),
so one answer can never do two things.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_WD = "|".join(_WEEKDAYS)
_MO = "|".join(_MONTHS)
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"

_COMPLETE = {
    "complete", "completed", "done", "finished", "finish", "finish it",
    "mark complete", "mark done", "mark it complete", "mark it done",
    "mark as complete", "mark as done", "mark it as complete", "mark it as done",
}
_CANCEL = {"cancel", "cancel it", "cancel the task", "cancel task", "cancelled"}
_SKIP = {"skip", "skip it", "next", "pass", "leave it"}
_MOVE_TARGETS = {
    "today": "today", "tomorrow": "tomorrow", "next week": "next_week",
    "backlog": "backlog", "the backlog": "backlog",
}
_CLEAR_DUE = {
    "no due date", "no date", "remove the due date", "remove due date",
    "clear the due date", "clear due date", "delete the due date",
}
# Words a rename can't be: "rename to" alone is not a rename to "To".
_NOT_A_TITLE = {"to", "it", "it to"}
# The longest a spoken date runs ("the day after tomorrow", "December 25
# 2027"). Longer text is never tried as one, which keeps parse_new_task
# linear however many "due"s it holds (security review 2026-10-18).
_MAX_DATE_PHRASE = 40


def _norm(text: str) -> str:
    """Lowercase, punctuation that dictation adds turned to spaces (not the
    apostrophe or slash), whitespace collapsed."""
    text = re.sub(r"[.,!?;:\"“”]", " ", text.lower())
    return " ".join(text.split())


def _clean(text: str) -> str:
    """As said, with whitespace collapsed and trailing punctuation dropped."""
    return " ".join(text.split()).rstrip(".!?,;: ")


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_occurrence(today: date, month: int, day: int) -> date | None:
    """This year's month/day, or next year's when it has already passed."""
    this_year = _safe_date(today.year, month, day)
    if this_year is None:
        return None
    if this_year >= today:
        return this_year
    return _safe_date(today.year + 1, month, day)


def parse_spoken_date(text: str | None, today: date) -> date | None:
    """A date as people say it, relative to ``today``; None when unreadable.

    today / tomorrow / the day after tomorrow; a weekday (the next one after
    today, never today itself); "next <weekday>" (that day of next Mon-Sun
    week); "October 25", "25 October", "the 25th", "10/25", with an optional
    year (without one, the next time that date comes round); "in N days /
    weeks".
    """
    if not isinstance(text, str) or len(text) > _MAX_DATE_PHRASE:
        return None
    s = re.sub(r"^(?:on|by|for) ", "", _norm(text))
    if not s:
        return None
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s in ("the day after tomorrow", "day after tomorrow"):
        return today + timedelta(days=2)

    m = re.fullmatch(rf"(?:this )?({_WD})", s)
    if m:
        ahead = (_WEEKDAYS[m.group(1)] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    m = re.fullmatch(rf"next ({_WD})", s)
    if m:
        next_monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return next_monday + timedelta(days=_WEEKDAYS[m.group(1)])

    m = re.fullmatch(r"in (\d{1,3}|[a-z]+) (day|days|week|weeks)", s)
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if n is None:
            return None
        return today + timedelta(days=n * (7 if m.group(2).startswith("week") else 1))

    m = re.fullmatch(rf"({_MO}) {_ORD}(?: (\d{{4}}))?", s)
    if m:
        month, day, year = _MONTHS[m.group(1)], int(m.group(2)), m.group(3)
        return _safe_date(int(year), month, day) if year else _next_occurrence(today, month, day)
    m = re.fullmatch(rf"(?:the )?{_ORD} (?:of )?({_MO})(?: (\d{{4}}))?", s)
    if m:
        day, month, year = int(m.group(1)), _MONTHS[m.group(2)], m.group(3)
        return _safe_date(int(year), month, day) if year else _next_occurrence(today, month, day)

    m = re.fullmatch(r"the (\d{1,2})(?:st|nd|rd|th)", s)
    if m:
        day = int(m.group(1))
        this_month = _safe_date(today.year, today.month, day)
        if this_month is not None and this_month >= today:
            return this_month
        if today.month == 12:
            return _safe_date(today.year + 1, 1, day)
        return _safe_date(today.year, today.month + 1, day)

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", s)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if year:
            return _safe_date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        return _next_occurrence(today, month, day)
    return None


def interpret_answer(text: str | None, today: date) -> dict:
    """What an answer about one task means, as ``{"action": ...}``.

    Actions: complete, cancel, skip, move (+ tier), rename (+ title, first
    letter capitalized), due (+ due_date), clear_due, bad_date (a "due …"
    whose date didn't read), unknown.
    """
    if not isinstance(text, str) or not text.strip():
        return {"action": "unknown"}
    raw = _clean(text)
    s = _norm(text)

    m = re.match(
        r"^(?:rename(?:\s+it)?(?:\s+to)?|call\s+it|change\s+(?:the\s+)?(?:name|title)\s+to)\s+(.+)$",
        raw, re.IGNORECASE,
    )
    if m:
        title = m.group(1).strip()
        if title.lower() in _NOT_A_TITLE:
            return {"action": "unknown"}
        return {"action": "rename", "title": _cap(title)}

    if s in _CLEAR_DUE:
        return {"action": "clear_due"}
    m = re.match(r"^(?:set (?:the )?due date to|due date|due on|due by|due)\s+(.+)$", s)
    if m:
        due = parse_spoken_date(m.group(1), today)
        return {"action": "due", "due_date": due} if due else {"action": "bad_date"}

    if s in _COMPLETE:
        return {"action": "complete"}
    if s in _CANCEL:
        return {"action": "cancel"}
    if s in _SKIP:
        return {"action": "skip"}
    target = re.sub(r"^move(?: it)?(?: to)? ", "", s)
    if target in _MOVE_TARGETS:
        return {"action": "move", "tier": _MOVE_TARGETS[target]}
    return {"action": "unknown"}


def parse_new_task(text: str | None, today: date) -> dict | None:
    """``[work|personal] [task] <title> [due <date>]`` → ``{type, title,
    due_date}``; None when there's no title. No type word → personal. A
    trailing "due …" is a date only when it reads as one; otherwise it
    stays in the title ("the due diligence report")."""
    if not isinstance(text, str):
        return None
    raw = _clean(text)
    task_type = "personal"
    m = re.match(r"^(work|personal)\b(?:\s+task\b)?[\s:,\-]*(.*)$", raw, re.IGNORECASE)
    if m:
        task_type, raw = m.group(1).lower(), m.group(2)

    due = None
    for found in reversed(list(re.finditer(r"(?:^|\s)due\s+", raw, re.IGNORECASE))):
        if len(raw) - found.end() > _MAX_DATE_PHRASE:
            break  # every earlier "due" has a longer tail still
        when = parse_spoken_date(raw[found.end():], today)
        if when is not None:
            due, raw = when, raw[:found.start()]
            break

    title = _clean(raw)
    if not title:
        return None
    return {"type": task_type, "title": _cap(title), "due_date": due}


def spoken_date(d: date) -> str:
    """How Siri says a date: "Friday, October 23"."""
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"
