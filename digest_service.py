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
from datetime import date

from sqlalchemy import select
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

    # This Week count
    lines.append(f"THIS WEEK REMAINING: {len(week_tasks)} tasks")
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

    try:
        return _sendgrid_send(api_key, from_email, to_email, subject, body)
    except Exception:
        logger.exception("Failed to send digest email")
        return False


def _sendgrid_send(
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
) -> bool:
    """Send email via SendGrid API. Separated for testability."""
    import sendgrid
    from sendgrid.helpers.mail import Content, Mail, To

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(
        from_email=from_email,
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", body),
    )
    response = sg.send(message)
    return response.status_code in (200, 201, 202)
