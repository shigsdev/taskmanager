"""JSON API for tasks. All routes require single-user auth."""
from __future__ import annotations

import html.parser
import urllib.request
import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from models import Task, TaskStatus, TaskType, Tier
from task_service import (
    ValidationError,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)

bp = Blueprint("tasks_api", __name__, url_prefix="/api/tasks")


def _serialize(task: Task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "tier": task.tier.value,
        "type": task.type.value,
        "status": task.status.value,
        "project_id": str(task.project_id) if task.project_id else None,
        "goal_id": str(task.goal_id) if task.goal_id else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "url": task.url,
        "notes": task.notes,
        "checklist": task.checklist or [],
        "sort_order": task.sort_order,
        "last_reviewed": task.last_reviewed.isoformat() if task.last_reviewed else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _enum_or_400(enum_cls, value):
    if value is None:
        return None, None
    try:
        return enum_cls(value), None
    except ValueError:
        return None, (jsonify({"error": f"invalid filter value: {value}"}), 400)


def _uuid_or_400(value, field):
    if value is None:
        return None, None
    try:
        return uuid.UUID(value), None
    except (ValueError, AttributeError):
        return None, (jsonify({"error": f"invalid {field}"}), 400)


@bp.get("")
@login_required
def index(email: str):  # noqa: ARG001 (email injected by login_required)
    tier, err = _enum_or_400(Tier, request.args.get("tier"))
    if err:
        return err
    task_type, err = _enum_or_400(TaskType, request.args.get("type"))
    if err:
        return err

    status_arg = request.args.get("status")
    if status_arg == "all":
        status = None
    elif status_arg:
        status, err = _enum_or_400(TaskStatus, status_arg)
        if err:
            return err
    else:
        status = TaskStatus.ACTIVE

    project_id, err = _uuid_or_400(request.args.get("project_id"), "project_id")
    if err:
        return err
    goal_id, err = _uuid_or_400(request.args.get("goal_id"), "goal_id")
    if err:
        return err

    tasks = list_tasks(
        tier=tier,
        type=task_type,
        status=status,
        project_id=project_id,
        goal_id=goal_id,
    )
    return jsonify([_serialize(t) for t in tasks])


@bp.post("")
@login_required
def create(email: str):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        task = create_task(data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    return jsonify(_serialize(task)), 201


@bp.get("/<uuid:task_id>")
@login_required
def show(email: str, task_id: uuid.UUID):  # noqa: ARG001
    task = get_task(task_id)
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(task))


@bp.patch("/<uuid:task_id>")
@login_required
def patch(email: str, task_id: uuid.UUID):  # noqa: ARG001
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        task = update_task(task_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(task))


@bp.delete("/<uuid:task_id>")
@login_required
def destroy(email: str, task_id: uuid.UUID):  # noqa: ARG001
    if not delete_task(task_id):
        return jsonify({"error": "not found"}), 404
    return "", 204


@bp.post("/reorder")
@login_required
def reorder(email: str):  # noqa: ARG001
    """Bulk-update sort_order for tasks within a tier.

    Expects JSON: {"tier": "today", "task_ids": ["id1", "id2", ...]}
    The order of task_ids determines the new sort_order values.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    tier_val = data.get("tier")
    task_ids = data.get("task_ids")

    if not tier_val or not isinstance(task_ids, list):
        return jsonify({"error": "tier and task_ids required"}), 422

    try:
        Tier(tier_val)
    except ValueError:
        return jsonify({"error": f"invalid tier: {tier_val}"}), 400

    for i, tid in enumerate(task_ids):
        try:
            task = get_task(uuid.UUID(tid))
        except (ValueError, AttributeError):
            continue
        if task:
            update_task(task.id, {"sort_order": i})

    return jsonify({"reordered": len(task_ids)})


class _TitleParser(html.parser.HTMLParser):
    """Minimal HTML parser that extracts the first <title> tag content."""

    def __init__(self):
        super().__init__()
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):  # noqa: ARG002
        if tag == "title" and self.title is None:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and self.title is None:
            self.title = data.strip()


@bp.post("/url-preview")
@login_required
def url_preview(email: str):  # noqa: ARG001
    """Fetch the <title> of a URL server-side and return it.

    The browser never talks to external sites — all fetching is done here.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "invalid url"}), 400

    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            headers={"User-Agent": "Mozilla/5.0 TaskManager/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            # Only read the first 32 KB — enough for any <head> section
            raw = resp.read(32768).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return jsonify({"title": None, "url": url})

    parser = _TitleParser()
    parser.feed(raw)
    return jsonify({"title": parser.title, "url": url})
