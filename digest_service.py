"""Email digest generation and sending.

Builds a plain-text daily digest and sends it via SendGrid. The digest
includes:
- Today's tasks (from the Today tier)
- Tasks due today (from any tier)
- Overdue tasks (past due date)
- Goals that have active tasks in Today
- This Week remaining count

The digest is plain text (no HTML) for maximum email client compatibility,
especially in corporate Outlook environments.

Security notes (per CLAUDE.md):
- Task content is sanitized before inserting into the email body
- Email addresses and API keys are never logged
- The SendGrid call is server-side only
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from models import Goal, GoalStatus, Task, TaskStatus, Tier, db

logger = logging.getLogger(__name__)


def _sanitize(text: str) -> str:
    """Remove control characters and excessive whitespace from task content.

    This prevents injection of unexpected formatting into the email body.
    We keep newlines within notes but strip everything else.
    """
    if not text:
        return ""
    # Replace tabs and carriage returns, strip leading/trailing whitespace
    return text.replace("\t", " ").replace("\r", "").strip()


def build_digest(*, target_date: date | None = None) -> str:
    """Build the plain-text digest content.

    Args:
        target_date: The date to build the digest for (defaults to today).

    Returns:
        The complete digest as a plain-text string.
    """
    today = target_date or date.today()
    day_str = today.strftime("%A, %B %d, %Y")

    # Gather data — single query with eager-loaded relationships
    all_active = list(db.session.scalars(
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .options(joinedload(Task.project), joinedload(Task.goal))
    ))

    today_tasks = [t for t in all_active if t.tier == Tier.TODAY]
    tomorrow_tasks = [t for t in all_active if t.tier == Tier.TOMORROW]
    week_tasks = [t for t in all_active if t.tier == Tier.THIS_WEEK]

    # Tasks due today from ANY tier (excluding Today — already shown)
    due_today = [
        t for t in all_active
        if t.due_date == today and t.tier != Tier.TODAY
    ]

    # Overdue tasks (past due date)
    overdue = [
        t for t in all_active
        if t.due_date and t.due_date < today
    ]

    # Goals with active tasks in Today (already eager-loaded)
    goals_today: list[tuple[Goal, int]] = []
    goal_counts: dict[str, int] = {}
    for t in today_tasks:
        if t.goal_id and t.goal and t.goal.status != GoalStatus.DONE:
            key = str(t.goal_id)
            goal_counts[key] = goal_counts.get(key, 0) + 1
    seen_goals: dict[str, Goal] = {}
    for t in today_tasks:
        if t.goal_id and t.goal and str(t.goal_id) in goal_counts:
            seen_goals[str(t.goal_id)] = t.goal
    for gid, goal in seen_goals.items():
        goals_today.append((goal, goal_counts[gid]))
    goals_today.sort(key=lambda x: x[0].category.value)

    # Build the text
    lines = [f"TASK DIGEST — {day_str}", ""]

    # Today's tasks
    lines.append("TODAY'S TASKS")
    if today_tasks:
        for t in today_tasks:
            lines.append(_format_task_line(t, today))
    else:
        lines.append("  (none)")
    lines.append("")

    # Due today (from other tiers)
    if due_today:
        lines.append("ALSO DUE TODAY (from other tiers)")
        for t in due_today:
            lines.append(_format_task_line(t, today))
        lines.append("")

    # Overdue
    if overdue:
        lines.append("OVERDUE")
        for t in overdue:
            line = f"[ ] {_sanitize(t.title)}"
            if t.due_date:
                line += f" — due {t.due_date.isoformat()}"
            lines.append(line)
        lines.append("")

    # Goals with active tasks today
    if goals_today:
        lines.append("GOALS WITH ACTIVE TASKS TODAY")
        for goal, count in goals_today:
            task_word = "task" if count == 1 else "tasks"
            lines.append(
                f"- {_sanitize(goal.title)} ({goal.category.value})"
                f" — {count} {task_word} today"
            )
        lines.append("")

    # Tomorrow count (backlog #27) + This Week count
    lines.append(f"TOMORROW: {len(tomorrow_tasks)} tasks")
    lines.append(f"THIS WEEK REMAINING: {len(week_tasks)} tasks")
    lines.append("")

    # Past-7-day completed/cancelled summary (#25). Surfaces honesty:
    # how many tasks did the user finish vs consciously drop in the
    # past week. Counted separately because they're not the same thing.
    week_ago = today - timedelta(days=7)
    completed_recent = db.session.scalar(
        select(func.count()).select_from(Task).where(
            Task.status == TaskStatus.ARCHIVED,
            Task.updated_at >= week_ago,
        )
    ) or 0
    cancelled_recent = db.session.scalar(
        select(func.count()).select_from(Task).where(
            Task.status == TaskStatus.CANCELLED,
            Task.updated_at >= week_ago,
        )
    ) or 0
    lines.append(
        f"PAST 7 DAYS: {completed_recent} completed, "
        f"{cancelled_recent} cancelled"
    )
    lines.append("")
    lines.append("---")

    app_url = os.environ.get("APP_URL", "")
    if app_url:
        lines.append(f"Sent by your Task Manager. Open app: {app_url}")
    else:
        lines.append("Sent by your Task Manager.")

    return "\n".join(lines)


def _format_task_line(task: Task, today: date) -> str:
    """Format a single task as a digest line."""
    parts = [f"[ ] {_sanitize(task.title)}"]

    # Project name (if linked)
    if task.project_id and task.project:
        parts.append(f"({_sanitize(task.project.name)})")

    # Goal name (if linked)
    if task.goal_id and task.goal:
        parts.append(f"[Goal: {_sanitize(task.goal.title)}]")

    # Due date annotation
    if task.due_date:
        if task.due_date == today:
            parts.append("(due today)")
        elif task.due_date < today:
            parts.append(f"(overdue: {task.due_date.isoformat()})")

    return " ".join(parts)


def send_digest(
    *,
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
    target_date: date | None = None,
) -> bool:
    """Send the digest email via SendGrid.

    Args:
        to_email: Recipient email address.
        subject: Email subject (auto-generated if not provided).
        body: Email body (auto-generated via build_digest if not provided).
        target_date: Date for digest content (defaults to today).

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    today = target_date or date.today()
    if subject is None:
        subject = f"Task Digest — {today.strftime('%A, %B %d')}"
    if body is None:
        body = build_digest(target_date=today)

    api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("DIGEST_FROM_EMAIL", "noreply@taskmanager.app")

    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — digest not sent")
        return False

    # Bug #50 (ADR-031): previously this caught Exception → False, which
    # killed all SendGrid error context (the actual cause was usually
    # "from address not verified" returning HTTP 403, but the user saw
    # a hardcoded "check SENDGRID_API_KEY" string). Now we let the
    # exception propagate; the global error handler in errors.py
    # extracts the SendGrid status + response body and surfaces a useful
    # message ("SendGrid returned HTTP 403: ..."). Boolean callers (the
    # daily cron job) still get False on failure — caught at the cron
    # site so we don't crash the scheduler.
    return _sendgrid_send(api_key, from_email, to_email, subject, body)


def _sendgrid_send(
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> bool:
    """Send email via SendGrid API. Separated for testability.

    Raises ``EgressError`` (the same wrapper used by all other external
    API calls — see ADR-023) so failures propagate with the actual
    SendGrid status code + response body. This is what makes the user-
    facing error useful instead of the previous hardcoded "check
    SENDGRID_API_KEY" string. ADR-031.
    """
    import sendgrid
    from sendgrid.helpers.mail import Content, Mail, To

    from egress import EgressError

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(
        from_email=from_email,
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", body),
    )
    try:
        response = sg.send(message)
    except Exception as e:
        # Common SendGrid SDK exceptions (ForbiddenError, BadRequestsError,
        # UnauthorizedError, etc.) all carry the response status + body.
        # Extract whatever useful detail we can.
        status_code = getattr(e, "status_code", None)
        body_attr = getattr(e, "body", b"")
        body_str = (
            body_attr.decode("utf-8", errors="replace")
            if isinstance(body_attr, bytes)
            else str(body_attr)
        )
        # Trim the body to the first useful line — SendGrid's JSON
        # errors look like {"errors":[{"message":"...","field":...}]}.
        # Even raw, the first 200 chars are always actionable.
        detail = body_str.replace("\n", " ").strip()[:200]
        if status_code:
            raise EgressError(
                f"SendGrid returned HTTP {status_code}"
                + (f": {detail}" if detail else ""),
            ) from e
        raise EgressError(f"SendGrid call failed: {type(e).__name__}") from e

    if response.status_code in (200, 201, 202):
        return True
    # Unexpected non-2xx response that didn't raise — surface it.
    raise EgressError(f"SendGrid returned HTTP {response.status_code}")
