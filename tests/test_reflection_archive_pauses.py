"""#364: a reflection's archive proposal says which repeating tasks it pauses.

Spec: docs/design/364-reflection-archive-pauses.md. A reflection archives
a project or goal only through a ``delete`` proposal, and that pauses the
running templates on it (#353 / #368). ``archive_pauses`` names them, and
``_serialize`` sends it with every reflection, worked out when it is
served, so a review re-opened days later (#495) is still right.
"""
from __future__ import annotations

from models import (
    Goal,
    GoalCategory,
    GoalPriority,
    Project,
    RecurringFrequency,
    RecurringTask,
    ReflectionInputMode,
    TaskType,
    db,
)
from reflection_service import archive_pauses, save_reflection


def _project(name="p") -> Project:
    p = Project(name=name)
    db.session.add(p)
    db.session.commit()
    return p


def _goal(title="g") -> Goal:
    g = Goal(title=title, category=GoalCategory.WORK, priority=GoalPriority.SHOULD)
    db.session.add(g)
    db.session.commit()
    return g


def _template(title, *, project=None, goal=None, active=True) -> RecurringTask:
    rt = RecurringTask(title=title, frequency=RecurringFrequency.DAILY,
                       type=TaskType.WORK, is_active=active,
                       project_id=project.id if project else None,
                       goal_id=goal.id if goal else None)
    db.session.add(rt)
    db.session.commit()
    return rt


def _delete(entity, row) -> dict:
    return {"op": "delete", "entity": entity, "bucket": "explicit",
            "id": str(row.id), "target": "x", "reason": "",
            "changes": [], "fields": {}, "payload": {}}


class TestArchivePauses:
    def test_project_delete_names_its_running_templates(self, app):
        p = _project()
        _template("Water plants", project=p)
        _template("Backup", project=p)
        _template("Elsewhere", project=_project("other"))
        got = archive_pauses({"explicit": [_delete("project", p)], "suggested": []})
        assert got == {f"project:{p.id}": ["Backup", "Water plants"]}

    def test_goal_delete_names_its_running_templates(self, app):
        g = _goal()
        _template("Weekly review", goal=g)
        got = archive_pauses({"explicit": [], "suggested": [_delete("goal", g)]})
        assert got == {f"goal:{g.id}": ["Weekly review"]}

    def test_a_template_the_user_paused_is_not_named(self, app):
        p = _project()
        _template("Paused already", project=p, active=False)
        assert archive_pauses({"explicit": [_delete("project", p)]}) == {}

    def test_other_actions_get_nothing(self, app):
        p = _project()
        _template("Water plants", project=p)
        update = dict(_delete("project", p), op="update",
                      fields={"name": "q"}, payload={"name": "q"})
        create = {"op": "create", "entity": "project", "target": "n",
                  "fields": {"name": "n"}, "payload": {"name": "n"}}
        task_delete = dict(_delete("project", p), entity="task")
        assert archive_pauses({"explicit": [update, create, task_delete]}) == {}

    def test_empty_and_malformed_input(self, app):
        assert archive_pauses(None) == {}
        assert archive_pauses({}) == {}
        assert archive_pauses({"explicit": ["junk", {"op": "delete",
                                                      "entity": "goal",
                                                      "id": "not-a-uuid"}]}) == {}


class TestServedWithTheReflection:
    def test_get_carries_the_map_and_it_empties_once_applied(self, authed_client, app):
        p = _project()
        rt = _template("Water plants", project=p)
        action = _delete("project", p)
        r = save_reflection(transcript="x", input_mode=ReflectionInputMode.TYPED,
                            proposed={"explicit": [action], "suggested": []})
        rid = str(r.id)

        got = authed_client.get(f"/api/reflection/{rid}").get_json()
        assert got["archive_pauses"] == {f"project:{p.id}": ["Water plants"]}
        # The action itself is unchanged: its identity is its JSON (#437).
        assert got["proposed_actions"]["explicit"] == [action]

        resp = authed_client.post(f"/api/reflection/{rid}/confirm",
                                  json={"actions": [action]})
        assert resp.status_code == 200
        assert db.session.get(RecurringTask, rt.id).is_active is False
        after = authed_client.get(f"/api/reflection/{rid}").get_json()
        assert after["archive_pauses"] == {}

    def test_a_reflection_with_no_archive_has_an_empty_map(self, authed_client, app):
        r = save_reflection(transcript="x", input_mode=ReflectionInputMode.TYPED,
                            proposed={"explicit": [], "suggested": []})
        got = authed_client.get(f"/api/reflection/{r.id}").get_json()
        assert got["archive_pauses"] == {}
