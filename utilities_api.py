"""JSON API for the /utilities page (#222, 2026-05-24).

Surfaces one-shot data cleanups as OAuth-gated endpoints so the
single-user owner can trigger them from the UI without needing to
curl `/api/debug/backfill/*` with an admin token. The admin-token
split (debug_api.py) protects writes from a leaked READ token —
that risk doesn't apply here because every endpoint is gated by
`@login_required` which already enforces `AUTHORIZED_EMAIL` (the
ONLY user authorized to mutate this app's data).

Endpoints (two shapes):

Query-driven utilities — GET-count preview + POST-run pair, so
the UI can show "X tasks will be cleaned" before Run:
    GET  /api/utilities/clear-stale-next-week-due-dates/count
    POST /api/utilities/clear-stale-next-week-due-dates

Action-only utilities (#223, 2026-05-24) — POST-only; result is
async / external so there's nothing to preview:
    POST /api/utilities/trigger-backup
         — dispatches `.github/workflows/daily-backup.yml` via
           the GitHub Actions API (workflow_dispatch trigger).
    POST /api/utilities/trigger-restore-drill
         — dispatches `.github/workflows/monthly-restore-drill.yml`.
    Both require GITHUB_DISPATCH_TOKEN env var (fine-grained PAT
    with `Actions: write` permission on the taskmanager repo).
"""
from __future__ import annotations

import logging
import os

import requests
from flask import Blueprint, jsonify
from sqlalchemy import select

from auth import login_required
from models import Task, TaskStatus, Tier, db
from utils import local_today_date

bp = Blueprint("utilities_api", __name__, url_prefix="/api/utilities")

logger = logging.getLogger(__name__)


# #223 (2026-05-24): GitHub Actions workflow dispatch helper. Used by
# the trigger-backup + trigger-restore-drill endpoints below to fire
# the existing scheduled workflows on-demand from the /utilities UI.
#
# Why inline rather than `egress.safe_call_api`: safe_call_api expects
# a JSON response body, but GitHub's workflow_dispatch endpoint returns
# 204 No Content on success. Same defensive shape (timeout, vendor-
# tagged error, no token in error messages) — just specialised for
# the empty-body return.
#
# The token NEVER appears in logged output, even on failure: errors
# only quote GitHub's response status and the (token-free) response
# `message` field.
def _dispatch_github_workflow(workflow_file: str) -> dict:
    """Trigger a GitHub Actions workflow_dispatch on `workflow_file`.

    Args:
        workflow_file: The YAML filename in `.github/workflows/`
            (e.g. `"daily-backup.yml"`). Both target workflows
            (#154 daily-backup, #154.7 monthly-restore-drill)
            declare `workflow_dispatch: {}` so they're API-eligible.

    Returns:
        {"dispatched": True, "actions_url": <URL>} on success — the
        URL points the user at the GitHub Actions tab so they can
        watch the run + see PASS/FAIL when the workflow finishes
        (typically ~3 min for backup, ~5-8 min for restore drill).

    Raises:
        ValueError: GITHUB_DISPATCH_TOKEN missing OR GitHub API
            returned a non-204 status. Message is safe to surface
            to the user — never includes the token.
    """
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_DISPATCH_TOKEN env var not configured — add a "
            "fine-grained PAT with Actions: write on this repo to "
            "Railway's variables (see docs/security/git-credentials.md "
            "for the rotation/setup procedure).",
        )
    # Hardcoded repo (single-deployment app) but env-overrideable for
    # the rare case where a fork wants to wire its own workflows.
    repo = os.environ.get("GITHUB_REPO", "shigsdev/taskmanager")
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # The `ref` is which branch to run the workflow on. main is the
    # production deploy line; backups/restore drills should always
    # use the latest committed scripts there.
    body = {"ref": "main"}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
    except requests.RequestException as e:
        raise ValueError(
            f"GitHub API network error: {type(e).__name__}",
        ) from e
    if resp.status_code != 204:
        # 401/403 → bad token or insufficient scope (most common
        # misconfig). 422 → workflow file not found or doesn't
        # declare workflow_dispatch. 5xx → GitHub side issue.
        detail = ""
        try:
            err_body = resp.json()
            detail = err_body.get("message") or ""
        except ValueError:
            detail = (resp.text or "")[:200]
        raise ValueError(
            f"GitHub workflow_dispatch returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else ""),
        )
    actions_url = f"https://github.com/{repo}/actions"
    logger.info(
        "utilities: dispatched workflow %s (run will appear at %s)",
        workflow_file, actions_url,
    )
    return {"dispatched": True, "actions_url": actions_url}


@bp.get("/clear-stale-next-week-due-dates/count")
@login_required
def clear_stale_next_week_due_dates_count(email: str):  # noqa: ARG001
    """Preview: how many active NEXT_WEEK tasks have a stale (today
    or earlier) due_date that the backfill would clear? Read-only —
    safe to call repeatedly. The UI uses this to display the count
    before the user clicks Run.
    """
    today = local_today_date()
    count = db.session.scalar(
        select(db.func.count()).select_from(Task).where(
            Task.tier == Tier.NEXT_WEEK,
            Task.due_date.is_not(None),
            Task.due_date <= today,
            Task.status == TaskStatus.ACTIVE,
        )
    )
    return jsonify({"count": count or 0})


@bp.post("/clear-stale-next-week-due-dates")
@login_required
def clear_stale_next_week_due_dates_run(email: str):  # noqa: ARG001
    """#220 follow-up: clear stale today/past due_date on tasks
    stuck in tier=NEXT_WEEK from pre-#220 tier-button punts. Wraps
    `task_service.backfill_clear_stale_next_week_due_dates()` —
    identical logic to the admin-token-gated
    `/api/debug/backfill/clear-stale-next-week-due-dates` endpoint,
    but OAuth-only so the UI can trigger it.

    Returns {updated: N}. Idempotent (re-running after clean = 0).
    """
    from task_service import backfill_clear_stale_next_week_due_dates
    n = backfill_clear_stale_next_week_due_dates()
    logger.info(
        "utilities: clear_stale_next_week_due_dates triggered via UI, updated=%d",
        n,
    )
    return jsonify({"updated": n})


# #223 (2026-05-24): on-demand backup + restore-drill triggers.


@bp.post("/trigger-backup")
@login_required
def trigger_backup(email: str):  # noqa: ARG001
    """Dispatch the `daily-backup.yml` GitHub Actions workflow ad-hoc.

    Use case: encrypted DB snapshot to the backup repo without waiting
    for the 07:30 UTC scheduled run. Useful before risky migrations,
    before/after large data imports, or any time you want a known-good
    point-in-time copy. The workflow itself (#154) handles encryption
    + git push + retention pruning + email status report.

    Returns {dispatched: True, actions_url: ...} on success — the
    workflow runs asynchronously over the next few minutes; check the
    actions URL or your inbox for PASS/FAIL.

    On misconfig (no token / bad token / GitHub error), returns
    HTTP 503 with the failure detail. Token VALUE is never returned.
    """
    try:
        result = _dispatch_github_workflow("daily-backup.yml")
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)


@bp.post("/trigger-restore-drill")
@login_required
def trigger_restore_drill(email: str):  # noqa: ARG001
    """Dispatch the `monthly-restore-drill.yml` GitHub Actions workflow
    ad-hoc.

    Use case: verify the most recent backup is actually restorable
    (decryptable + pg_restore-able + row counts ±5% of live). The
    drill (#154.7) catches dump corruption, key drift, pg_restore
    version skew, and Fernet ciphertext mangling BEFORE the day you
    actually need to restore. Normally runs monthly; this lets you
    trigger out-of-cycle (e.g. after rotating BACKUP_FERNET_KEY).

    Returns {dispatched: True, actions_url: ...}. Workflow takes
    ~5-8 minutes to complete; PASS/FAIL email arrives when it finishes.
    """
    try:
        result = _dispatch_github_workflow("monthly-restore-drill.yml")
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)
