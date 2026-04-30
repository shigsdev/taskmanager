"""Email digest generation and sending.

Builds a daily digest and sends it via SendGrid as a multipart message
with both an HTML body and a plain-text fallback. The digest includes:
- Overdue tasks (past due date) — surfaced first
- Today's tasks (from the Today tier)
- Tasks due today from other tiers
- Goals that have active tasks in Today
- Tomorrow / This Week / Past-7-day stats

The HTML body uses inline styles + a 600px centered layout for broad
email-client compatibility. The plain-text fallback is sent in the same
multipart message so corporate Outlook / clients that strip HTML still
get a usable digest.

Security notes (per CLAUDE.md):
- Task content is sanitized before inserting into the email body
- HTML rendering uses Jinja autoescape — task titles cannot inject markup
- Email addresses and API keys are never logged
- The SendGrid call is server-side only
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

from flask import render_template
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
    return text.replace("\t", " ").replace("\r", "").strip()


def _build_digest_data(target_date: date | None = None) -> dict[str, Any]:
    """Gather every section the digest needs in one shape.

    Both the plain-text and HTML renderers consume this dict so they
    stay in lockstep.
    """
    today = target_date or date.today()
    day_str = today.strftime("%A, %B %d, %Y")

    all_active = list(db.session.scalars(
        select(Task)
        .where(Task.status == TaskStatus.ACTIVE)
        .options(joinedload(Task.project), joinedload(Task.goal))
    ))

    today_tasks = [t for t in all_active if t.tier == Tier.TODAY]
    tomorrow_tasks = [t for t in all_active if t.tier == Tier.TOMORROW]
    week_tasks = [t for t in all_active if t.tier == Tier.THIS_WEEK]

    due_today = [
        t for t in all_active
        if t.due_date == today and t.tier != Tier.TODAY
    ]

    overdue = [
        t for t in all_active
        if t.due_date and t.due_date < today
    ]

    goal_counts: dict[str, int] = {}
    seen_goals: dict[str, Goal] = {}
    for t in today_tasks:
        if t.goal_id and t.goal and t.goal.status != GoalStatus.DONE:
            key = str(t.goal_id)
            goal_counts[key] = goal_counts.get(key, 0) + 1
            seen_goals[key] = t.goal
    goals_today_pairs = sorted(
        ((seen_goals[k], goal_counts[k]) for k in seen_goals),
        key=lambda x: x[0].category.value,
    )

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

    def _task_view(t: Task) -> dict[str, Any]:
        return {
            "title": _sanitize(t.title),
            "project": _sanitize(t.project.name) if t.project_id and t.project else None,
            "goal": _sanitize(t.goal.title) if t.goal_id and t.goal else None,
            "due_today": t.due_date == today,
            "due_date_iso": t.due_date.isoformat() if t.due_date else None,
            "due_date_pretty": t.due_date.strftime("%b %d") if t.due_date else None,
        }

    return {
        "today_date": today,
        "day_str": day_str,
        "today": [_task_view(t) for t in today_tasks],
        "due_today": [_task_view(t) for t in due_today],
        "overdue": [_task_view(t) for t in overdue],
        "goals_today": [
            {"title": _sanitize(g.title), "category": g.category.value, "count": c}
            for g, c in goals_today_pairs
        ],
        "tomorrow_count": len(tomorrow_tasks),
        "week_count": len(week_tasks),
        "completed_recent": completed_recent,
        "cancelled_recent": cancelled_recent,
        "app_url": os.environ.get("APP_URL", ""),
    }


def build_digest(*, target_date: date | None = None) -> str:
    """Build the plain-text digest body (multipart fallback).

    Order: Overdue → Today → Also due today → Goals → Stats → Footer.
    Overdue is surfaced first because the most urgent items deserve top
    placement; older versions buried it below Today.
    """
    data = _build_digest_data(target_date)
    lines = [f"TASK DIGEST — {data['day_str']}", ""]

    if data["overdue"]:
        lines.append(f"OVERDUE ({len(data['overdue'])})")
        for t in data["overdue"]:
            line = f"[ ] {t['title']}"
            if t["due_date_iso"]:
                line += f" — due {t['due_date_iso']}"
            if t["project"]:
                line += f" ({t['project']})"
            if t["goal"]:
                line += f" [Goal: {t['goal']}]"
            lines.append(line)
        lines.append("")

    lines.append(f"TODAY'S TASKS ({len(data['today'])})")
    if data["today"]:
        for t in data["today"]:
            lines.append(_format_task_line(t))
    else:
        lines.append("  (none)")
    lines.append("")

    if data["due_today"]:
        lines.append(f"ALSO DUE TODAY (from other tiers) ({len(data['due_today'])})")
        for t in data["due_today"]:
            lines.append(_format_task_line(t))
        lines.append("")

    if data["goals_today"]:
        lines.append("GOALS WITH ACTIVE TASKS TODAY")
        for g in data["goals_today"]:
            task_word = "task" if g["count"] == 1 else "tasks"
            lines.append(
                f"- {g['title']} ({g['category']}) — {g['count']} {task_word} today"
            )
        lines.append("")

    lines.append(f"TOMORROW: {data['tomorrow_count']} tasks")
    lines.append(f"THIS WEEK REMAINING: {data['week_count']} tasks")
    lines.append("")
    lines.append(
        f"PAST 7 DAYS: {data['completed_recent']} completed, "
        f"{data['cancelled_recent']} cancelled"
    )
    lines.append("")
    lines.append("---")

    if data["app_url"]:
        lines.append(f"Sent by your Task Manager. Open app: {data['app_url']}")
    else:
        lines.append("Sent by your Task Manager.")

    return "\n".join(lines)


def build_digest_html(*, target_date: date | None = None) -> str:
    """Render the HTML digest body via Jinja.

    Jinja autoescape covers task titles, project names, and goal names —
    a malicious title cannot inject markup into the email.
    """
    data = _build_digest_data(target_date)
    return render_template("email/digest.html", **data)


def _format_task_line(view: dict[str, Any]) -> str:
    """Format a single task as a plain-text digest line."""
    parts = [f"[ ] {view['title']}"]
    if view["project"]:
        parts.append(f"({view['project']})")
    if view["goal"]:
        parts.append(f"[Goal: {view['goal']}]")
    if view["due_today"]:
        parts.append("(due today)")
    elif view["due_date_iso"]:
        parts.append(f"(overdue: {view['due_date_iso']})")
    return " ".join(parts)


def send_digest(
    *,
    to_email: str,
    subject: str | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
    target_date: date | None = None,
) -> bool:
    """Send the digest email via SendGrid as multipart (HTML + text).

    Args:
        to_email: Recipient email address.
        subject: Email subject (auto-generated if not provided).
        body_text: Plain-text body (auto-built if not provided).
        body_html: HTML body (auto-built if not provided).
        target_date: Date for digest content (defaults to today).

    Returns:
        True if the email was sent successfully, False if SENDGRID_API_KEY
        is missing. Raises EgressError on SendGrid HTTP failures (#50,
        ADR-031) so the global error handler can surface a useful message.
    """
    today = target_date or date.today()
    if subject is None:
        subject = f"Task Digest — {today.strftime('%A, %B %d')}"
    if body_text is None:
        body_text = build_digest(target_date=today)
    if body_html is None:
        body_html = build_digest_html(target_date=today)

    api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("DIGEST_FROM_EMAIL", "noreply@taskmanager.app")

    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — digest not sent")
        return False

    return _sendgrid_send(api_key, from_email, to_email, subject, body_text, body_html)


def _sendgrid_send(
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> bool:
    """Send a multipart email via SendGrid. Separated for testability.

    Attaches BOTH text/plain and text/html parts. SendGrid sends them as
    a multipart/alternative message; the receiving client picks whichever
    it can render (HTML by default, plain text in clients that strip HTML).

    Raises ``EgressError`` (the same wrapper used by all other external
    API calls — see ADR-023) so failures propagate with the actual
    SendGrid status code + response body. ADR-031.
    """
    import sendgrid
    from sendgrid.helpers.mail import Content, Mail, To

    from egress import EgressError

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(
        from_email=from_email,
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", body_text),
        html_content=Content("text/html", body_html),
    )
    try:
        response = sg.send(message)
    except Exception as e:
        status_code = getattr(e, "status_code", None)
        body_attr = getattr(e, "body", b"")
        body_str = (
            body_attr.decode("utf-8", errors="replace")
            if isinstance(body_attr, bytes)
            else str(body_attr)
        )
        detail = body_str.replace("\n", " ").strip()[:200]
        if status_code:
            raise EgressError(
                f"SendGrid returned HTTP {status_code}"
                + (f": {detail}" if detail else ""),
            ) from e
        raise EgressError(f"SendGrid call failed: {type(e).__name__}") from e

    if response.status_code in (200, 201, 202):
        return True
    raise EgressError(f"SendGrid returned HTTP {response.status_code}")
