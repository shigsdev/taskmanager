"""Email digest generation and sending.

Builds a daily digest and sends it as a multipart message (HTML + a
plain-text fallback). Transport is config-driven (ADR-035): the Brevo
transactional HTTP API when ``BREVO_API_KEY`` is set (the Railway path —
Railway blocks outbound SMTP on non-Pro plans), otherwise authenticated
SMTP. The digest includes:
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
- Email addresses and the SMTP password are never logged
- The SMTP send is server-side only
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

# --- Last-send outcome record (#286 digest-failure alert) ------------
# Persisted in the AppSetting key/value store so a SILENT scheduled-send
# failure (e.g. SendGrid "Maximum credits exceeded" → HTTP 401, the
# 2026-06-07 incident) becomes a VISIBLE /healthz signal instead of just
# an ERROR row nobody scans daily. AppSetting.value is String(500), so
# the payload is capped well under that.
LAST_SEND_KEY = "digest_last_send"


def record_send_result(*, status: str, error: str | None = None) -> None:
    """Upsert the outcome of the most recent digest send attempt.

    ``status`` is "ok" | "fail" | "skip". Never raises — recording must
    not crash the scheduler thread, so any DB error is logged + swallowed.
    """
    import json
    from datetime import UTC, datetime

    from logging_service import scrub_sensitive
    from models import AppSetting

    payload = {"status": status, "at": datetime.now(UTC).isoformat()}
    if error:
        # #288: scrub BEFORE storing — this record is republished verbatim
        # on the unauthenticated /healthz (check_digest_last_send), so it
        # must never carry an email/key fragment even if a future failure
        # mode embeds one in the exception text. Same scrubber as app_logs.
        # Cap so status + at + json overhead stay under the 500-char column.
        payload["error"] = (scrub_sensitive(error) or "")[:300]
    value = json.dumps(payload)[:500]
    try:
        row = (
            db.session.query(AppSetting)
            .filter_by(key=LAST_SEND_KEY)
            .one_or_none()
        )
        if row is None:
            db.session.add(AppSetting(key=LAST_SEND_KEY, value=value))
        else:
            row.value = value
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to record digest send result")


def get_last_send_result() -> dict | None:
    """Return the last recorded send outcome dict, or None if never set."""
    import json

    from models import AppSetting

    row = (
        db.session.query(AppSetting).filter_by(key=LAST_SEND_KEY).one_or_none()
    )
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return None


def _safe_app_url(raw: str) -> str:
    """Return ``raw`` only if it looks like an https URL; else empty.

    Defense-in-depth for the email template's CTA button — see callsite
    comment in _build_digest_data. Local development uses APP_URL=
    "http://localhost:..." which is fine for the plain-text ``Open app:``
    line; the HTML template's CTA button only renders when this returns
    a non-empty value, so https-only is intentional (we don't want a
    "Click here to open Task Manager" button in a mailbox that points to
    an unencrypted URL anyway).
    """
    if not raw:
        return ""
    if raw.startswith("https://"):
        return raw
    return ""


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

    PR63 audit fix #128: ``target_date or date.today()`` resolved to
    server UTC, drifting late-evening (8pm+ ET) digest previews to
    "tomorrow's" data. Now uses ``local_today_date`` (DIGEST_TZ) so
    the ad-hoc /api/digest/preview returns same-wall-clock content
    as the cron-fired digest.
    """
    from utils import local_today_date
    today = target_date or local_today_date()
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

    today_iso = today.isoformat()

    def _task_view(t: Task) -> dict[str, Any]:
        # PR62 audit fix #14: filter out inactive projects + DONE goals at
        # the per-task line level too. The goal-section already filters,
        # but a per-task overdue line would still expose the dead label.
        proj_name = (
            _sanitize(t.project.name)
            if t.project_id and t.project and t.project.is_active
            else None
        )
        goal_title = (
            _sanitize(t.goal.title)
            if t.goal_id and t.goal and t.goal.status != GoalStatus.DONE
            else None
        )
        return {
            "title": _sanitize(t.title),
            "project": proj_name,
            "goal": goal_title,
            "due_today": t.due_date == today,
            "due_date_iso": t.due_date.isoformat() if t.due_date else None,
            "due_date_pretty": t.due_date.strftime("%b %d") if t.due_date else None,
            "today_iso": today_iso,  # for plain-text overdue-vs-future disambiguation
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
        # PR62 audit fix #22: scheme-allowlist APP_URL before it lands in
        # an <a href> in the email. Operator-controlled today (env var),
        # but the email template trusts whatever lands in this field.
        # If APP_URL ever becomes user-mutable (settings table, query
        # string, etc.) the email's CTA button becomes an XSS sink.
        # Defense-in-depth: only allow https:// values; anything else
        # silently degrades to no CTA (existing template branch handles
        # the empty case).
        "app_url": _safe_app_url(os.environ.get("APP_URL", "")),
    }


def build_digest(*, target_date: date | None = None) -> str:
    """Build the plain-text digest body (multipart fallback).

    Order (#212, user-flagged 2026-05-23):
        Today → Also due today → Goals → Stats → ⚠ Overdue → Footer.

    Today's tasks lead because that's what the user is about to act on
    when they open the email. Overdue moved to the END (warning-style,
    only emitted when there IS overdue) so the morning starts forward-
    looking instead of relitigating the past. Older versions surfaced
    Overdue first; the user prefers the focus-forward order.
    """
    data = _build_digest_data(target_date)
    lines = [f"TASK DIGEST — {data['day_str']}", ""]

    lines.append(f"TODAY'S TASKS ({len(data['today'])})")
    if data["today"]:
        for t in data["today"]:
            lines.append(_format_task_line(t))
    else:
        lines.append("  (none)")
    lines.append("")

    if data["due_today"]:
        lines.append(f"ALSO DUE TODAY (from other sections) ({len(data['due_today'])})")
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

    # #212: Overdue moved to the END as a warning-style trailer, and
    # ONLY emitted when there IS overdue — an empty overdue block here
    # would be pure visual noise (the whole point of the reorder).
    if data["overdue"]:
        lines.append(f"⚠ OVERDUE ({len(data['overdue'])})")
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
    """Format a single task as a plain-text digest line.

    PR62 audit fix #5: previously this branched on `view["due_date_iso"]`
    being set, which mislabeled future-dated Today-tier tasks as
    "overdue". A user could move a task into Today while keeping its
    planned future due_date — the digest would then claim the task was
    overdue. Now we explicitly compare due_date_iso to today_iso.
    """
    parts = [f"[ ] {view['title']}"]
    if view["project"]:
        parts.append(f"({view['project']})")
    if view["goal"]:
        parts.append(f"[Goal: {view['goal']}]")
    if view["due_today"]:
        parts.append("(due today)")
    elif view["due_date_iso"]:
        # Compare directly to today's iso to disambiguate overdue from future.
        today_iso = view.get("today_iso")
        if today_iso and view["due_date_iso"] < today_iso:
            parts.append(f"(overdue: {view['due_date_iso']})")
        else:
            parts.append(f"(due {view['due_date_pretty']})")
    return " ".join(parts)


def send_digest(
    *,
    to_email: str,
    subject: str | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
    target_date: date | None = None,
) -> bool:
    """Send the digest email as multipart (HTML + text).

    Transport is chosen by config (ADR-035):
      * ``BREVO_API_KEY`` set → Brevo transactional HTTP API (over HTTPS).
        This is the path used on Railway, whose network blocks outbound
        SMTP on non-Pro plans.
      * else ``SMTP_USERNAME`` + ``SMTP_PASSWORD`` set → authenticated SMTP.

    Args:
        to_email: Recipient email address.
        subject: Email subject (auto-generated if not provided).
        body_text: Plain-text body (auto-built if not provided).
        body_html: HTML body (auto-built if not provided).
        target_date: Date for digest content (defaults to today).

    Returns:
        True if the email was sent successfully, False if no transport is
        configured (neither ``BREVO_API_KEY`` nor SMTP credentials).
        Raises EgressError on send failures (#50, ADR-031, ADR-035) so the
        global error handler can surface a useful message.
    """
    from utils import local_today_date
    today = target_date or local_today_date()
    if subject is None:
        subject = f"Task Digest — {today.strftime('%A, %B %d')}"
    if body_text is None:
        body_text = build_digest(target_date=today)
    if body_html is None:
        body_html = build_digest_html(target_date=today)

    # Preferred: Brevo transactional HTTP API (HTTPS — works on Railway,
    # which blocks outbound SMTP on non-Pro plans).
    brevo_key = os.environ.get("BREVO_API_KEY")
    if brevo_key:
        from_email = os.environ.get("DIGEST_FROM_EMAIL")
        if not from_email:
            logger.warning(
                "DIGEST_FROM_EMAIL not set — required for the Brevo API send"
            )
            return False
        return _brevo_api_send(
            api_key=brevo_key,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    # Fallback: authenticated SMTP (Gmail default). Note Railway blocks
    # outbound SMTP on non-Pro plans — prefer BREVO_API_KEY there.
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    # From defaults to the authenticated account — Gmail requires the
    # From address to be the SMTP user (or a verified alias), so falling
    # back to the username avoids a silent DMARC/relay rejection.
    from_email = os.environ.get("DIGEST_FROM_EMAIL") or username

    if not username or not password:
        logger.warning(
            "No email transport configured (BREVO_API_KEY or "
            "SMTP_USERNAME/SMTP_PASSWORD) — digest not sent"
        )
        return False

    return _smtp_send(
        host=host,
        port=port,
        username=username,
        password=password,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


def _brevo_api_send(
    *,
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> bool:
    """Send a multipart email via the Brevo transactional HTTP API.

    Uses ``egress.safe_call_api`` (ADR-023) — the key travels in the
    ``api-key`` header, never a URL query string (ADR-007). This is the
    Railway-friendly path: it's plain HTTPS, so it isn't affected by
    Railway's outbound-SMTP block (ADR-035). ``safe_call_api`` raises
    ``EgressError`` (with the Brevo HTTP status, never the key) on any
    non-2xx or network error, which propagates per ADR-031.
    """
    from egress import safe_call_api

    safe_call_api(
        url="https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "accept": "application/json"},
        json={
            "sender": {"email": from_email, "name": "Task Digest"},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": body_html,
            "textContent": body_text,
        },
        vendor="Brevo",
        timeout_sec=30,
    )
    return True


def _smtp_send(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> bool:
    """Send a multipart email over SMTP+STARTTLS. Separated for testability.

    Attaches BOTH text/plain and text/html parts as multipart/alternative;
    the receiving client picks whichever it can render (HTML by default,
    plain text in clients that strip HTML).

    Uses stdlib ``smtplib`` rather than ``egress.safe_call_api`` (ADR-035):
    the egress wrapper guards HTTP(S) calls (SSRF pin, header scrubbing),
    but SMTP is a different protocol/port to a fixed, operator-configured
    relay — not a user-controllable URL — so the egress protections don't
    apply. Raises ``EgressError`` on any SMTP failure so it propagates the
    same way as every other external send (ADR-031). The exception message
    NEVER includes the password (CLAUDE.md log-hygiene).
    """
    import smtplib
    from email.message import EmailMessage

    from egress import EgressError

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
    except Exception as e:
        # Surface the SMTP status code (e.g. 535 auth failed) when present,
        # but never the password or a raw repr that could echo credentials.
        code = getattr(e, "smtp_code", None)
        raise EgressError(
            f"SMTP send failed: {type(e).__name__}"
            + (f" (code {code})" if code else "")
        ) from e

    return True
