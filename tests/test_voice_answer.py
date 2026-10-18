"""#500: the rules that turn what you said to Siri into one action.

Spec: docs/design/500-siri-add-and-edit-by-voice.md §2-3. Pure functions,
no app: ``today`` is fixed to Wednesday 2026-10-21 (this week runs Mon
Oct 19 - Sun Oct 25, next week Mon Oct 26 - Sun Nov 1).
"""
from __future__ import annotations

from datetime import date

import pytest

from voice_answer import interpret_answer, parse_new_task, parse_spoken_date, spoken_date

TODAY = date(2026, 10, 21)  # a Wednesday


class TestParseSpokenDate:
    @pytest.mark.parametrize("said,expected", [
        ("today", date(2026, 10, 21)),
        ("tomorrow", date(2026, 10, 22)),
        ("the day after tomorrow", date(2026, 10, 23)),
        ("Friday", date(2026, 10, 23)),
        ("on friday", date(2026, 10, 23)),
        ("this Friday", date(2026, 10, 23)),
        ("monday", date(2026, 10, 26)),
        ("wednesday", date(2026, 10, 28)),          # never today itself
        ("next Friday", date(2026, 10, 30)),        # Friday of next week
        ("next monday", date(2026, 10, 26)),
        ("next sunday", date(2026, 11, 1)),
        ("October 25", date(2026, 10, 25)),
        ("Oct 25th", date(2026, 10, 25)),
        ("25 October", date(2026, 10, 25)),
        ("october 1", date(2027, 10, 1)),           # already past: next year
        ("Sept 3rd", date(2027, 9, 3)),
        ("December 25, 2026", date(2026, 12, 25)),
        ("december 25 2027", date(2027, 12, 25)),
        ("the 25th", date(2026, 10, 25)),
        ("the 20th", date(2026, 11, 20)),           # already past: next month
        ("10/25", date(2026, 10, 25)),
        ("1/5", date(2027, 1, 5)),
        ("in 3 days", date(2026, 10, 24)),
        ("in a week", date(2026, 10, 28)),
        ("in two weeks", date(2026, 11, 4)),
        ("in one day", date(2026, 10, 22)),
        ("Friday.", date(2026, 10, 23)),            # dictation adds a period
    ])
    def test_reads(self, said, expected):
        assert parse_spoken_date(said, TODAY) == expected

    @pytest.mark.parametrize("said", [
        "", "someday", "soon", "february 30", "13/40", "the 32nd",
        "next week", "in many days", "friday the", "octember 3",
    ])
    def test_unreadable_is_none(self, said):
        assert parse_spoken_date(said, TODAY) is None


class TestInterpretAnswer:
    @pytest.mark.parametrize("said", [
        "complete", "Complete.", "done", "Done!", "mark complete",
        "Mark it complete", "completed", "mark it done",
    ])
    def test_complete(self, said):
        assert interpret_answer(said, TODAY) == {"action": "complete"}

    @pytest.mark.parametrize("said", ["cancel", "Cancel it.", "cancel the task"])
    def test_cancel(self, said):
        assert interpret_answer(said, TODAY) == {"action": "cancel"}

    @pytest.mark.parametrize("said,tier", [
        ("today", "today"), ("Tomorrow.", "tomorrow"), ("next week", "next_week"),
        ("Backlog", "backlog"), ("move to tomorrow", "tomorrow"),
        ("Move it to next week.", "next_week"), ("move it to the backlog", "backlog"),
    ])
    def test_move(self, said, tier):
        assert interpret_answer(said, TODAY) == {"action": "move", "tier": tier}

    @pytest.mark.parametrize("said", ["skip", "Skip.", "next", "pass", "skip it"])
    def test_skip(self, said):
        assert interpret_answer(said, TODAY) == {"action": "skip"}

    @pytest.mark.parametrize("said,title", [
        ("Rename to call the dentist.", "Call the dentist"),
        ("rename it to Buy oat milk", "Buy oat milk"),
        ("rename Pay the water bill", "Pay the water bill"),
        ("Call it groceries", "Groceries"),
        ("change the name to Book flights for March", "Book flights for March"),
        ("rename to finish tomorrow's report", "Finish tomorrow's report"),
    ])
    def test_rename_keeps_what_was_said(self, said, title):
        assert interpret_answer(said, TODAY) == {"action": "rename", "title": title}

    @pytest.mark.parametrize("said,due", [
        ("Due Friday.", date(2026, 10, 23)),
        ("due next friday", date(2026, 10, 30)),
        ("set the due date to October 25", date(2026, 10, 25)),
        ("Due date tomorrow", date(2026, 10, 22)),
    ])
    def test_due(self, said, due):
        assert interpret_answer(said, TODAY) == {"action": "due", "due_date": due}

    @pytest.mark.parametrize("said", [
        "No due date", "remove the due date", "Clear the due date.", "no date",
    ])
    def test_clear_due(self, said):
        assert interpret_answer(said, TODAY) == {"action": "clear_due"}

    def test_unreadable_date(self):
        assert interpret_answer("due someday", TODAY) == {"action": "bad_date"}

    @pytest.mark.parametrize("said", [
        "", "   ", "complete it tomorrow", "hmm", "rename to", "rename",
        "due", "please complete", "tomorrow and cancel",
    ])
    def test_anything_else_is_unknown(self, said):
        assert interpret_answer(said, TODAY) == {"action": "unknown"}

    def test_none_is_unknown(self):
        assert interpret_answer(None, TODAY) == {"action": "unknown"}


class TestParseNewTask:
    @pytest.mark.parametrize("said,expected", [
        ("Personal buy milk.", {"type": "personal", "title": "Buy milk", "due_date": None}),
        ("work call Sam", {"type": "work", "title": "Call Sam", "due_date": None}),
        ("Work task call Sam due Friday",
         {"type": "work", "title": "Call Sam", "due_date": date(2026, 10, 23)}),
        ("personal task: book the vet",
         {"type": "personal", "title": "Book the vet", "due_date": None}),
        ("Buy milk", {"type": "personal", "title": "Buy milk", "due_date": None}),
        ("Order a cake due October 30th.",
         {"type": "personal", "title": "Order a cake", "due_date": date(2026, 10, 30)}),
        ("Pick up the due diligence report",
         {"type": "personal", "title": "Pick up the due diligence report", "due_date": None}),
        ("Workout plan for winter",
         {"type": "personal", "title": "Workout plan for winter", "due_date": None}),
    ])
    def test_reads(self, said, expected):
        assert parse_new_task(said, TODAY) == expected

    @pytest.mark.parametrize("said", ["", "  ", "work", "Personal task.", "work task", None,
                                      "due friday"])
    def test_no_title_is_none(self, said):
        assert parse_new_task(said, TODAY) is None


def test_spoken_date():
    assert spoken_date(date(2026, 10, 23)) == "Friday, October 23"
    assert spoken_date(date(2027, 1, 5)) == "Tuesday, January 5"


class TestLongInput:
    """Security review 2026-10-18: a long text full of "due" made
    parse_new_task try a date at every one (quadratic). Only a short tail can
    be a date, so only short tails are tried."""

    def test_many_dues_parse_fast(self):
        import time
        start = time.perf_counter()
        parse_new_task("x " + "due " * 20000, TODAY)
        assert time.perf_counter() - start < 0.5

    def test_long_phrase_is_not_a_date(self):
        assert parse_spoken_date("friday " + "x" * 100, TODAY) is None

    def test_short_tail_still_reads(self):
        assert parse_new_task("plan the due diligence trip due next friday", TODAY) == {
            "type": "personal", "title": "Plan the due diligence trip",
            "due_date": date(2026, 10, 30)}
