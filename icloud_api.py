"""JSON API for the user's iCloud Calendar events (#371) — read-only.

Endpoints:
    GET  /api/icloud/events?start=YYYY-MM-DD&end=YYYY-MM-DD
            — the events in the window (``end`` is the last day shown,
              inclusive, like /api/recurring/previews; at most 70 days)
    POST /api/icloud/refresh
            — forget the 15-minute cache; the next read asks iCloud

Answers:
    200 ``{enabled: false, events: []}`` when ICLOUD_USERNAME /
        ICLOUD_APP_PASSWORD aren't set (the feature is off, nothing shows);
    200 ``{enabled: true, events: [...]}`` (shape: icloud_service.events_from_ics);
    502 ``{enabled: true, error, auth?}`` when iCloud fails. Never 401/403:
        the page's apiFetch reads those as "your session expired, sign in
        again", and it's the Apple password that was refused, not the user.

Nothing here writes to iCloud or to the database. Spec:
docs/design/371-icloud-calendar-pull.md; egress path: ADR-041.
"""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request

import icloud_service
from auth import login_required
from rate_limit import OUTBOUND_FETCH, limiter

bp = Blueprint("icloud_api", __name__, url_prefix="/api/icloud")


@bp.get("/events")
@login_required
def events(email: str):  # noqa: ARG001
    if not icloud_service.configured():
        return jsonify({"enabled": False, "events": []})
    try:
        start = date.fromisoformat(request.args.get("start") or "")
        end = date.fromisoformat(request.args.get("end") or "")
    except ValueError:
        return jsonify({"error": "start and end must be YYYY-MM-DD"}), 400
    if end < start:
        return jsonify({"error": "end must not be before start"}), 400
    if (end - start).days > icloud_service.MAX_WINDOW_DAYS:
        return jsonify({
            "error": f"range cannot exceed {icloud_service.MAX_WINDOW_DAYS} days",
        }), 400
    try:
        evs = icloud_service.fetch_events(start, end + timedelta(days=1))
    except icloud_service.IcloudAuthError as e:
        return jsonify({"enabled": True, "error": str(e), "auth": True}), 502
    except icloud_service.IcloudError as e:
        return jsonify({"enabled": True, "error": str(e)}), 502
    return jsonify({"enabled": True, "events": evs})


@bp.post("/refresh")
@login_required
@limiter.limit(OUTBOUND_FETCH)  # each refresh makes the next read call Apple
def refresh(email: str):  # noqa: ARG001
    icloud_service.refresh()
    return jsonify({"ok": True})
