"""#482: changing a project's type retypes its tasks and repeating tasks.

``update_project`` (the panel's Save, and /projects bulk Type ▾) used to
set ``project.type`` alone, so every task and template on the project was
left on the old type — a mismatch #475 refuses everywhere else. User
decision 2026-10-16: they switch type with the project.
"""
from __future__ import annotations

from models import (
    Project,
    ProjectType,
    RecurringFrequency,
    RecurringTask,
    Task,
    TaskStatus,
    TaskType,
    Tier,
    db,
)


def _seed():
    p = Project(name="482 kitchen", type=ProjectType.WORK)
    db.session.add(p)
    db.session.flush()
    open_ = Task(title="482 open", type=TaskType.WORK, tier=Tier.TODAY, project_id=p.id)
    done = Task(title="482 done", type=TaskType.WORK, tier=Tier.TODAY, project_id=p.id,
                status=TaskStatus.ARCHIVED)
    db.session.add_all([open_, done])
    db.session.flush()
    # A subtask with no project of its own still follows its parent.
    sub = Task(title="482 sub", type=TaskType.WORK, tier=Tier.TODAY, parent_id=open_.id)
    other = Task(title="482 elsewhere", type=TaskType.WORK, tier=Tier.TODAY)
    tmpl = RecurringTask(title="482 weekly", type=TaskType.WORK,
                         frequency=RecurringFrequency.WEEKLY,
                         project_id=p.id)
    paused = RecurringTask(title="482 paused", type=TaskType.WORK,
                           frequency=RecurringFrequency.DAILY,
                           project_id=p.id, is_active=False)
    db.session.add_all([sub, other, tmpl, paused])
    db.session.commit()
    return p, [open_, done, sub], other, [tmpl, paused]


def _types(model, rows):
    db.session.expire_all()
    return {db.session.get(model, r.id).type for r in rows}


def test_panel_type_change_retypes_tasks_subtasks_and_templates(app, authed_client):
    with app.app_context():
        p, tasks, other, templates = _seed()
        r = authed_client.patch(f"/api/projects/{p.id}", json={"type": "personal"})
        assert r.status_code == 200, r.get_json()
        assert _types(Task, tasks) == {TaskType.PERSONAL}
        assert _types(RecurringTask, templates) == {TaskType.PERSONAL}
        assert _types(Task, [other]) == {TaskType.WORK}   # not on the project


def test_bulk_type_change_retypes_them_too(app, authed_client):
    with app.app_context():
        p, tasks, _, templates = _seed()
        r = authed_client.patch("/api/projects/bulk", json={
            "project_ids": [str(p.id)], "updates": {"type": "personal"},
        })
        assert r.get_json()["updated"] == 1
        assert _types(Task, tasks) == {TaskType.PERSONAL}
        assert _types(RecurringTask, templates) == {TaskType.PERSONAL}


def test_a_save_that_keeps_the_type_touches_no_task(app, authed_client):
    # The quiet case: the panel re-sends the type on every Save. A task the
    # user retyped by hand onto a mismatch (old data) is left alone.
    with app.app_context():
        p, tasks, _, _ = _seed()
        stray = tasks[0]
        stray.type = TaskType.PERSONAL
        db.session.commit()
        r = authed_client.patch(f"/api/projects/{p.id}", json={"type": "work", "name": "482 k2"})
        assert r.status_code == 200
        assert _types(Task, [stray]) == {TaskType.PERSONAL}


def test_the_goal_links_are_untouched(app, authed_client):
    from models import Goal, GoalCategory, GoalPriority
    with app.app_context():
        p, tasks, _, _ = _seed()
        g = Goal(title="482 goal", category=GoalCategory.WORK, priority=GoalPriority.MUST)
        db.session.add(g)
        db.session.flush()
        tasks[0].goal_id = g.id
        db.session.commit()
        authed_client.patch(f"/api/projects/{p.id}", json={"type": "personal"})
        db.session.expire_all()
        assert db.session.get(Task, tasks[0].id).goal_id == g.id
        assert db.session.get(Task, tasks[0].id).project_id == p.id
