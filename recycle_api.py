"""JSON API for the recycle bin.

Endpoints:
    GET  /api/recycle-bin                    — list batches in the bin
    GET  /api/recycle-bin/summary            — aggregate counts for the bin
    POST /api/recycle-bin/undo/<batch_id>    — soft-delete a batch
    POST /api/recycle-bin/restore/<batch_id> — un-soft-delete a batch
    POST /api/recycle-bin/purge/<batch_id>   — hard-delete a batch
    POST /api/recycle-bin/empty              — hard-delete every batch

Destructive operations (purge, empty) require a typed confirmation token
in the JSON request body: ``{"confirmation": "DELETE"}``. This prevents
accidental one-click data loss.
"""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from auth import login_required
from recycle_service import (
    BatchNotFoundError,
    BatchStateError,
    ConfirmationError,
    bin_summary,
    empty_bin,
    list_bin,
    purge_batch,
    restore_batch,
    undo_batch,
)

bp = Blueprint("recycle_api", __name__, url_prefix="/api/recycle-bin")


def _parse_batch_id(raw: str):
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None


@bp.get("")
@login_required
def list_entries(email: str):  # noqa: ARG001
    """Return all batches currently in the recycle bin."""
    return jsonify({"batches": list_bin()})


@bp.get("/summary")
@login_required
def summary(email: str):  # noqa: ARG001
    """Return aggregate counts for everything currently in the bin."""
    return jsonify(bin_summary())


@bp.post("/undo/<batch_id>")
@login_required
def undo(email: str, batch_id: str):  # noqa: ARG001
    """Soft-delete a batch (move it to the recycle bin)."""
    bid = _parse_batch_id(batch_id)
    if bid is None:
        return jsonify({"error": "invalid batch_id"}), 400

    try:
        result = undo_batch(bid)
    except BatchNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except BatchStateError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(result)


@bp.post("/restore/<batch_id>")
@login_required
def restore(email: str, batch_id: str):  # noqa: ARG001
    """Un-soft-delete a batch (remove it from the recycle bin)."""
    bid = _parse_batch_id(batch_id)
    if bid is None:
        return jsonify({"error": "invalid batch_id"}), 400

    try:
        result = restore_batch(bid)
    except BatchNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except BatchStateError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(result)


@bp.post("/purge/<batch_id>")
@login_required
def purge(email: str, batch_id: str):  # noqa: ARG001
    """Hard-delete a batch. Requires ``{"confirmation": "DELETE"}``."""
    bid = _parse_batch_id(batch_id)
    if bid is None:
        return jsonify({"error": "invalid batch_id"}), 400

    data = request.get_json(silent=True) or {}
    confirmation = data.get("confirmation") if isinstance(data, dict) else None

    try:
        result = purge_batch(bid, confirmation)
    except ConfirmationError as e:
        return jsonify({"error": str(e)}), 400
    except BatchNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except BatchStateError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(result)


@bp.post("/empty")
@login_required
def empty(email: str):  # noqa: ARG001
    """Hard-delete every batch in the bin. Requires typed confirmation."""
    data = request.get_json(silent=True) or {}
    confirmation = data.get("confirmation") if isinstance(data, dict) else None

    try:
        result = empty_bin(confirmation)
    except ConfirmationError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(result)
