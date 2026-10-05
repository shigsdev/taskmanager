"""#386 — a task created with a due date must not land in Inbox.

Spec: docs/design/386-dated-tasks-skip-inbox.md. Three write paths:

1. ``POST /api/tasks`` / ``create_task`` — an Inbox tier (explicit or the
   default) with a due date routes by the date; an explicit non-Inbox
   tier still wins (the #74 "caller explicit about both" rule).
2. ``update_task`` — an explicit ``tier: "inbox"`` routes only when the
   date changed in the same write (decision 1), so a deliberate move of
   an already-dated task into Inbox sticks.
3. Reviewed candidates (reflection / scan / voice via
   ``create_tasks_from_candidates``, files via ``create_tasks_from_import``)
   — the date always wins, Freezer included (decision 2 + follow-up).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from models import Task, TaskType, Tier, db


def _today() -> date:
    from task_service import _local_today_date
    return _local_today_date()


def _natural(d: date) -> Tier:
    from task_service import _tier_for_due_date
    return _tier_for_due_date(d)


def _make_task(**overrides) -> Task:
    fields = {"title": "Seed", "type": TaskType.WORK}
    fields.update(overrides)
    task = Task(**fields)
    db.session.add(task)
    db.session.commit()
    return task


# --- 1. POST /api/tasks ------------------------------------------------------


class TestCreateViaApi:

    def test_explicit_inbox_with_date_routes_by_date(self, authed_client):
        """The task panel always sends tier — a New Task saved with a date
        while the dropdown still says Inbox used to stay in Inbox."""
        due = _today() + timedelta(days=3)
        resp = authed_client.post("/api/tasks", json={
            "title": "Turnover ownership", "type": "work",
            "tier": "inbox", "due_date": due.isoformat(),
        })
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == _natural(due).value
        assert resp.get_json()["tier"] != "inbox"

    def test_inbox_without_date_stays_in_inbox(self, authed_client):
        """The quiet case — an undated capture is still untriaged."""
        resp = authed_client.post("/api/tasks", json={
            "title": "Someday thought", "type": "work", "tier": "inbox",
        })
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "inbox"

    def test_explicit_non_inbox_tier_still_wins(self, authed_client):
        """#74's explicit combo is unchanged on the API path."""
        due = _today() + timedelta(days=30)
        resp = authed_client.post("/api/tasks", json={
            "title": "Plan early", "type": "work",
            "tier": "this_week", "due_date": due.isoformat(),
        })
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "this_week"

    def test_freezer_with_date_stays_frozen(self, authed_client):
        due = _today() + timedelta(days=2)
        resp = authed_client.post("/api/tasks", json={
            "title": "Parked", "type": "personal",
            "tier": "freezer", "due_date": due.isoformat(),
        })
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "freezer"


# --- 2. update_task ----------------------------------------------------------


class TestUpdateInboxRouting:

    def test_inbox_task_new_date_with_tier_inbox_in_payload_routes(self, app):
        """What the panel sends when the iPhone picker never fired
        "change": tier is still inbox, but the date is new."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(tier=Tier.INBOX, due_date=None)
            due = _today() + timedelta(days=1)
            updated = update_task(t.id, {
                "tier": "inbox", "due_date": due.isoformat(),
            })
            assert updated.tier == _natural(due)

    def test_changed_date_on_dated_inbox_task_routes(self, app):
        from task_service import update_task
        with app.app_context():
            t = _make_task(
                tier=Tier.INBOX, due_date=_today() + timedelta(days=40)
            )
            updated = update_task(t.id, {
                "tier": "inbox", "due_date": _today().isoformat(),
            })
            assert updated.tier == Tier.TODAY

    def test_deliberate_move_into_inbox_keeps_inbox(self, app):
        """Decision 1: date unchanged → the explicit Inbox sticks (panel
        dropdown re-picked to Inbox with the date untouched)."""
        from task_service import update_task
        with app.app_context():
            due = _today() + timedelta(days=2)
            t = _make_task(tier=_natural(due), due_date=due)
            updated = update_task(t.id, {
                "tier": "inbox", "due_date": due.isoformat(),
            })
            assert updated.tier == Tier.INBOX
            assert updated.due_date == due

    def test_tier_only_move_into_inbox_keeps_inbox(self, app):
        """Bulk "Inbox" / calendar drag send tier alone."""
        from task_service import update_task
        with app.app_context():
            due = _today() + timedelta(days=2)
            t = _make_task(tier=_natural(due), due_date=due)
            updated = update_task(t.id, {"tier": "inbox"})
            assert updated.tier == Tier.INBOX

    def test_explicit_non_inbox_tier_with_new_date_still_wins(self, app):
        from task_service import update_task
        with app.app_context():
            t = _make_task(tier=Tier.INBOX, due_date=None)
            updated = update_task(t.id, {
                "tier": "next_week",
                "due_date": (_today() + timedelta(days=30)).isoformat(),
            })
            assert updated.tier == Tier.NEXT_WEEK

    def test_clearing_the_date_leaves_inbox_alone(self, app):
        from task_service import update_task
        with app.app_context():
            t = _make_task(
                tier=Tier.INBOX, due_date=_today() + timedelta(days=5)
            )
            updated = update_task(t.id, {"tier": "inbox", "due_date": ""})
            assert updated.tier == Tier.INBOX
            assert updated.due_date is None


# --- 3. Reviewed candidates: the date always wins ---------------------------


_CANDIDATE_SOURCES = ["reflection", "voice", "scan"]


def _candidates(tier, due):
    c = {"title": "From review", "type": "work", "included": True}
    if tier is not None:
        c["tier"] = tier
    if due is not None:
        c["due_date"] = due.isoformat()
    return [c]


class TestCandidatesDateWins:

    @pytest.mark.parametrize("source", _CANDIDATE_SOURCES)
    @pytest.mark.parametrize("tier", [None, "inbox"])
    def test_inbox_or_missing_tier_with_date_routes(self, app, source, tier):
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            due = _today() + timedelta(days=4)
            [t] = create_tasks_from_candidates(
                _candidates(tier, due), source_prefix=source
            )
            assert t.tier == _natural(due)

    @pytest.mark.parametrize("source", _CANDIDATE_SOURCES)
    def test_proposed_section_loses_to_date(self, app, source):
        """Decision 2: "This Week" proposed for a date next month."""
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            due = _today() + timedelta(days=30)
            [t] = create_tasks_from_candidates(
                _candidates("this_week", due), source_prefix=source
            )
            assert t.tier == Tier.BACKLOG

    def test_freezer_loses_to_date_on_candidates(self, app):
        """Decision 2 follow-up: no Freezer exception on these paths."""
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            [t] = create_tasks_from_candidates(
                _candidates("freezer", _today()), source_prefix="voice"
            )
            assert t.tier == Tier.TODAY

    @pytest.mark.parametrize("tier,expected", [
        (None, Tier.INBOX), ("inbox", Tier.INBOX), ("backlog", Tier.BACKLOG),
        ("freezer", Tier.FREEZER),
    ])
    def test_undated_candidate_keeps_its_section(self, app, tier, expected):
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            [t] = create_tasks_from_candidates(
                _candidates(tier, None), source_prefix="reflection"
            )
            assert t.tier == expected

    def test_reflection_apply_routes_a_dated_proposal(self, app):
        """The screenshot path end to end: reflection_service builds
        candidates with ``tier = f.get("tier") or "inbox"``."""
        from models import ReflectionInputMode
        from reflection_service import apply_selected_actions, save_reflection
        with app.app_context():
            due = _today() + timedelta(days=6)
            reflection = save_reflection(
                transcript="transition plan",
                input_mode=ReflectionInputMode.TYPED,
                proposed={"explicit": [], "suggested": []},
            )
            summary = apply_selected_actions(reflection, [{
                "op": "create", "entity": "task",
                "payload": {"title": "DTCC Training",
                            "due_date": due.isoformat()},
            }])
            assert summary["created"]["task"] == 1
            t = db.session.scalars(
                db.select(Task).where(Task.title == "DTCC Training")
            ).one()
            assert t.tier == _natural(due)


class TestImportDateWins:

    def test_import_rows_follow_the_date(self, app):
        from import_service import create_tasks_from_import
        with app.app_context():
            soon = _today() + timedelta(days=1)
            later = _today() + timedelta(days=45)
            rows = [
                {"title": "dated inbox", "tier": "inbox",
                 "due_date": soon.isoformat()},
                {"title": "dated this week", "tier": "this_week",
                 "due_date": later.isoformat()},
                {"title": "dated freezer", "tier": "freezer",
                 "due_date": soon.isoformat()},
                {"title": "undated backlog", "tier": "backlog"},
            ]
            tasks = {t.title: t for t in create_tasks_from_import(rows, source="test")}
            assert tasks["dated inbox"].tier == _natural(soon)
            assert tasks["dated this week"].tier == Tier.BACKLOG
            assert tasks["dated freezer"].tier == _natural(soon)
            assert tasks["undated backlog"].tier == Tier.BACKLOG


# --- 4. Overdue dates file to TODAY on the #386 paths (user decision) -------


class TestOverdueFilesToToday:
    """Without this, ``_tier_for_due_date`` maps a past date to This Week
    or Backlog, so an overdue task would be filed out of sight."""

    def test_candidate_with_past_date_lands_in_today(self, app):
        from scan_service import create_tasks_from_candidates
        with app.app_context():
            [t] = create_tasks_from_candidates(
                _candidates("backlog", _today() - timedelta(days=30)),
                source_prefix="reflection",
            )
            assert t.tier == Tier.TODAY

    def test_import_row_with_past_date_lands_in_today(self, app):
        from import_service import create_tasks_from_import
        with app.app_context():
            [t] = create_tasks_from_import(
                [{"title": "late", "tier": "inbox",
                  "due_date": (_today() - timedelta(days=1)).isoformat()}],
                source="test",
            )
            assert t.tier == Tier.TODAY

    def test_api_create_inbox_with_past_date_lands_in_today(self, authed_client):
        resp = authed_client.post("/api/tasks", json={
            "title": "Overdue already", "type": "work", "tier": "inbox",
            "due_date": (_today() - timedelta(days=10)).isoformat(),
        })
        assert resp.status_code == 201
        assert resp.get_json()["tier"] == "today"

    @pytest.mark.parametrize("payload_has_tier", [True, False])
    def test_inbox_task_given_past_date_lands_in_today(self, app, payload_has_tier):
        from task_service import update_task
        with app.app_context():
            t = _make_task(tier=Tier.INBOX, due_date=None)
            data = {"due_date": (_today() - timedelta(days=3)).isoformat()}
            if payload_has_tier:
                data["tier"] = "inbox"
            updated = update_task(t.id, data)
            assert updated.tier == Tier.TODAY

    def test_non_inbox_task_keeps_74_mapping_for_past_date(self, app):
        """Scope guard: only the #386 paths change. A Backlog task given a
        date last month still follows #74's mapping (Backlog)."""
        from task_service import update_task
        with app.app_context():
            t = _make_task(tier=Tier.THIS_WEEK, due_date=None)
            updated = update_task(t.id, {
                "due_date": (_today() - timedelta(days=30)).isoformat(),
            })
            assert updated.tier == Tier.BACKLOG
