"""JSON API for tasks. All routes require single-user auth."""
from __future__ import annotations

import html.parser
import uuid

from flask import Blueprint, g, jsonify, request

from auth import login_required
from models import Task, TaskStatus, TaskType, Tier
from rate_limit import OUTBOUND_FETCH, limiter
from task_service import (
    ValidationError,
    bulk_update_tasks,
    cancel_parent_task,
    complete_parent_task,
    create_task,
    delete_task,
    get_task,
    list_subtasks,
    list_tasks,
    resolve_project_hint,
    serialize_task,
    update_task,
)

# Re-export of the canonical repeat-payload helper (#200) so any internal
# caller / test patching ``tasks_api._serialize_repeat`` stays unaffected.
from task_service import _serialize_repeat as _serialize_repeat  # noqa: F401
from utils import enum_or_400 as _enum_or_400
from utils import validate_json_body

bp = Blueprint("tasks_api", __name__, url_prefix="/api/tasks")


def _serialize(task: Task) -> dict:
    """Thin wrapper over the canonical serializer (#200).

    Kept as a 1-liner so this module's call sites and any test patching
    ``tasks_api._serialize`` stay unaffected by the consolidation.
    """
    return serialize_task(task, view="full")


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
@validate_json_body
def create(email: str):  # noqa: ARG001
    data = g.json_body
    # #207: capture-bar "@project" hint. parse_capture.js lifts the raw
    # @token into `project_hint`; resolve it here to a project_id by
    # case-insensitive substring match. An explicit `project_id` in the
    # payload always wins — the hint only fills an empty slot.
    project_warning = None
    hint = data.pop("project_hint", None)
    if hint and not data.get("project_id"):
        resolved_id, project_warning = resolve_project_hint(hint)
        if resolved_id is not None:
            data["project_id"] = resolved_id
    try:
        task = create_task(data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    body = _serialize(task)
    if project_warning:
        body["warning"] = project_warning
    return jsonify(body), 201


@bp.get("/<uuid:task_id>")
@login_required
def show(email: str, task_id: uuid.UUID):  # noqa: ARG001
    task = get_task(task_id)
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(task))


@bp.patch("/<uuid:task_id>")
@login_required
@validate_json_body
def patch(email: str, task_id: uuid.UUID):  # noqa: ARG001
    data = g.json_body
    try:
        task = update_task(task_id, data)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(task))


@bp.get("/<uuid:task_id>/subtasks")
@login_required
def subtasks(email: str, task_id: uuid.UUID):  # noqa: ARG001
    task = get_task(task_id)
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify([_serialize(s) for s in list_subtasks(task_id)])


@bp.post("/<uuid:task_id>/complete")
@login_required
def complete(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Complete a task. For parent tasks with open subtasks, pass
    ``{"complete_subtasks": true}`` to archive them too, or omit to
    get a 422 with the count of open subtasks.
    """
    data = request.get_json(silent=True) or {}
    complete_subs = bool(data.get("complete_subtasks"))
    try:
        task = complete_parent_task(task_id, complete_subtasks=complete_subs)
    except ValidationError as e:
        return jsonify({"error": str(e), "field": e.field}), 422
    if task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(task))


@bp.post("/<uuid:task_id>/cancel")
@login_required
def cancel(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """Cancel a task. #176 mirror of /complete: for parent tasks with
    open subtasks, pass ``{"cancel_subtasks": true}`` to cancel them
    too, or omit to get a 422 with the count of open subtasks. An
    optional ``{"cancellation_reason": "..."}`` is stored on the parent.
    """
    data = request.get_json(silent=True) or {}
    cancel_subs = bool(data.get("cancel_subtasks"))
    reason = data.get("cancellation_reason")
    try:
        task = cancel_parent_task(
            task_id, cancel_subtasks=cancel_subs, reason=reason
        )
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


@bp.post("/<uuid:task_id>/duplicate")
@login_required
def duplicate(email: str, task_id: uuid.UUID):  # noqa: ARG001
    """#143 (2026-05-04): clone a task to TOMORROW so the user can keep
    working on it the next day. See ``task_service.duplicate_task`` for
    the field-by-field clone semantics. Returns 201 + the new task on
    success, 404 if the source task doesn't exist or has been deleted.
    """
    from task_service import duplicate_task
    new_task = duplicate_task(task_id)
    if new_task is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(new_task)), 201


@bp.patch("/bulk")
@login_required
@validate_json_body
def bulk_update(email: str):  # noqa: ARG001
    """Apply the same ``updates`` to multiple tasks in one call.

    Expects JSON::

        {
          "task_ids": ["<uuid>", "<uuid>", ...],
          "updates": {  // any subset of the per-task PATCH fields
            "type": "work",
            "tier": "today",
            "goal_id": "...",
            "project_id": null,
            "status": "archived"  // for bulk-complete
          }
        }

    Returns ``{"updated": N, "not_found": [ids], "errors": [...]}``.

    Per-task semantics: each task is processed via ``update_task``,
    so cascade rules (subtask goal/project inheritance) apply.
    Errors on one task don't roll back others — bulk ops are
    best-effort. See :func:`task_service.bulk_update_tasks`.
    """
    data = g.json_body

    task_ids_raw = data.get("task_ids")
    updates = data.get("updates")
    if not isinstance(task_ids_raw, list) or not task_ids_raw:
        return jsonify({"error": "task_ids must be a non-empty list"}), 422
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "updates must be a non-empty dict"}), 422

    # Cap at a sane batch size — protects the DB / Whisper-style
    # accidental "select all 5000 tasks." 200 is generous for any
    # realistic single-user board.
    if len(task_ids_raw) > 200:
        return jsonify({
            "error": f"too many task_ids ({len(task_ids_raw)}); max 200 per call",
        }), 422

    parsed_ids: list[uuid.UUID] = []
    for raw in task_ids_raw:
        try:
            parsed_ids.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            return jsonify({"error": f"invalid task_id: {raw!r}"}), 422

    result = bulk_update_tasks(parsed_ids, updates)
    return jsonify(result)


@bp.post("/reorder")
@login_required
@validate_json_body
def reorder(email: str):  # noqa: ARG001
    """Bulk-update sort_order for tasks within a tier.

    Expects JSON: {"tier": "today", "task_ids": ["id1", "id2", ...]}
    The order of task_ids determines the new sort_order values.
    """
    data = g.json_body

    tier_val = data.get("tier")
    task_ids = data.get("task_ids")

    if not tier_val or not isinstance(task_ids, list):
        return jsonify({"error": "tier and task_ids required"}), 422

    # #187 (2026-05-21): cap the payload, mirroring bulk_update's 200-id
    # limit. reorder does N independent get_task() + SET per id, so an
    # unbounded list eats a worker; MAX_CONTENT_LENGTH alone would allow
    # ~600k UUIDs through.
    if len(task_ids) > 200:
        return jsonify({
            "error": f"too many task_ids ({len(task_ids)}); max 200 per call",
        }), 422

    try:
        Tier(tier_val)
    except ValueError:
        return jsonify({"error": f"invalid tier: {tier_val}"}), 400

    from models import db as _db

    reordered = 0
    for i, tid in enumerate(task_ids):
        try:
            task = get_task(uuid.UUID(tid))
        except (ValueError, AttributeError):
            continue
        if task:
            task.sort_order = i
            reordered += 1
    _db.session.commit()

    return jsonify({"reordered": reordered})


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
@limiter.limit(OUTBOUND_FETCH)  # #184: each call holds a worker on an outbound fetch
@validate_json_body
def url_preview(email: str):  # noqa: ARG001
    """Fetch the <title> of a URL server-side and return it.

    The browser never talks to external sites — all fetching is done here.
    """
    data = g.json_body

    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "invalid url"}), 400

    # All SSRF defenses (DNS rebinding, redirect disable, IP allowlist)
    # live in egress — see docs/adr/006-ssrf-defense.md. PR63 audit fix
    # #125: the route used to duplicate the IP-allowlist resolution loop
    # to distinguish "private IP → loud 400" from "other failure → null
    # title". Now both paths share `egress.is_user_url_allowed` for a
    # single canonical resolution, eliminating the cosmetic TOCTOU
    # window that existed between the two independent resolutions.
    from egress import is_user_url_allowed, safe_fetch_user_url

    if not is_user_url_allowed(url):
        return jsonify({"error": "url not allowed"}), 400

    raw = safe_fetch_user_url(url)
    if raw is None:
        return jsonify({"title": None, "url": url})

    parser = _TitleParser()
    parser.feed(raw)
    return jsonify({"title": parser.title, "url": url})
