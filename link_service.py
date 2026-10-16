"""Project and goal links on a write (#475).

A NEW link to a project or goal is refused when it doesn't exist, is
archived, or — for a project — is of the other type than the task or
template. A link that is re-sent unchanged (every editor sends the stored
links on Save) or inherited (a subtask's from its parent, a task's goal from
its project) is not new, so old data keeps saving.

Imports only models + utils so every service can use it (project_service
imports recurring_service, so the checks can't live in either).
"""
from __future__ import annotations

import uuid

from models import Goal, Project, db
from utils import ValidationError
from utils import parse_uuid as _parse_uuid


def project_type_matches(project: Project, item_type) -> bool:
    return project.type.value == item_type.value


def check_project_link(
    project_id: uuid.UUID, *, item_type=None, noun: str = "task",
) -> Project:
    """The project, or a ValidationError the user can act on."""
    project = db.session.get(Project, project_id)
    if project is None:
        raise ValidationError("That project no longer exists — pick another.", "project_id")
    if not project.is_active:
        raise ValidationError(
            f'The project "{project.name}" is archived — unarchive it first.', "project_id",
        )
    if item_type is not None and not project_type_matches(project, item_type):
        raise ValidationError(
            f'"{project.name}" is a {project.type.value} project and this is a '
            f"{item_type.value} {noun} — pick a {item_type.value} project or none.",
            "project_id",
        )
    return project


def check_goal_link(goal_id: uuid.UUID) -> Goal:
    goal = db.session.get(Goal, goal_id)
    if goal is None:
        raise ValidationError("That goal no longer exists — pick another.", "goal_id")
    if not goal.is_active:
        raise ValidationError(
            f'The goal "{goal.title}" is archived — unarchive it first.', "goal_id",
        )
    return goal


def check_link_changes(
    data: dict,
    *,
    item_type,
    old_project_id: uuid.UUID | None = None,
    old_goal_id: uuid.UUID | None = None,
    inherited_project_id: uuid.UUID | None = None,
    inherited_goal_id: uuid.UUID | None = None,
    noun: str = "task",
) -> None:
    """Check the links ``data`` would set on a task or template, before
    anything is written. Only a NEW id is checked: not the stored one, not
    the inherited one, and for the goal not the goal of the project the
    item ends up on (the #77 cascade carries it, archived or not)."""
    project_id = old_project_id
    if "project_id" in data:
        project_id = _parse_uuid(data["project_id"], "project_id")
        if project_id is not None and project_id not in (old_project_id, inherited_project_id):
            check_project_link(project_id, item_type=item_type, noun=noun)
    if "goal_id" in data:
        goal_id = _parse_uuid(data["goal_id"], "goal_id")
        if goal_id is None or goal_id in (old_goal_id, inherited_goal_id):
            return
        project = db.session.get(Project, project_id) if project_id else None
        if project is not None and project.goal_id == goal_id:
            return
        check_goal_link(goal_id)


def unlink_other_type_project(
    item, *, old_type, data: dict, old_goal_id: uuid.UUID | None,
) -> None:
    """After a type change, take ``item`` off a project of the other type,
    as picking "(no project)" would (#427): the goal goes only if it is
    that project's goal and this write didn't set the goal itself."""
    if item.type == old_type or item.project_id is None:
        return
    project = db.session.get(Project, item.project_id)
    if project is None or project_type_matches(project, item.type):
        return
    item.project_id = None
    goal_set_here = (
        "goal_id" in data and _parse_uuid(data["goal_id"], "goal_id") != old_goal_id
    )
    if not goal_set_here and project.goal_id is not None and item.goal_id == project.goal_id:
        item.goal_id = None


# --- #481: batches -----------------------------------------------------------
#
# A batch (import, scan, voice memo, reflection) keeps its rows: a link that
# doesn't fit is dropped from that row only and the reason is reported,
# instead of refusing (a single write) or failing the whole batch (a dangling
# id at commit on Postgres). #447's "fit what comes in a batch".

_BATCH_NOTES_SHOWN = 3


def fit_batch_links(
    project_id: uuid.UUID | None,
    goal_id: uuid.UUID | None,
    *,
    item_type,
    noun: str = "task",
) -> tuple[uuid.UUID | None, uuid.UUID | None, list[str]]:
    """The links a new batch row may keep, and why any were dropped."""
    reasons: list[str] = []
    if project_id is not None:
        project = db.session.get(Project, project_id)
        if project is None:
            reasons.append("its project no longer exists")
        elif not project.is_active:
            reasons.append(f'the project "{project.name}" is archived')
        elif item_type is not None and not project_type_matches(project, item_type):
            reasons.append(
                f'"{project.name}" is a {project.type.value} project and this is a '
                f"{item_type.value} {noun}"
            )
        if reasons:
            project_id = None
    if goal_id is not None:
        goal = db.session.get(Goal, goal_id)
        if goal is None:
            reasons.append("its goal no longer exists")
            goal_id = None
        elif not goal.is_active:
            reasons.append(f'the goal "{goal.title}" is archived')
            goal_id = None
    return project_id, goal_id, reasons


def batch_link_note(title: str, reasons: list[str]) -> str:
    """One row's note: ``"<title>" — <reason>; <reason>``."""
    return f'"{title}" — ' + "; ".join(reasons)


def batch_link_warning(notes: list[str]) -> str | None:
    """The sentence a batch answer carries, or None when nothing dropped."""
    if not notes:
        return None
    shown = "; ".join(notes[:_BATCH_NOTES_SHOWN])
    more = len(notes) - _BATCH_NOTES_SHOWN
    if more > 0:
        shown += f"; and {more} more"
    return f"Added without a link: {shown}."
