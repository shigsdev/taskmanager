"""#282 Strength Forge — tracking service (Phase B.1: workout sessions).

Business logic for logging completed workouts and summarizing them.
Thin: validation + canonical CRUD through the ORM. Dates use
``local_today_date()`` (DIGEST_TZ) so "this week" buckets correctly
across the UTC/local boundary (cf. the #181/#240 date-drift fixes).
"""
from __future__ import annotations

from datetime import timedelta

from models import WorkoutSession, db
from utils import local_today_date

# The 5 loggable plans (band A/B + military sessions 1-3). The flare-up
# protocol is tracked separately (Phase B.2), not logged as a session.
VALID_PLAN_TYPES = ("band-a", "band-b", "mil-1", "mil-2", "mil-3")

PLAN_LABELS = {
    "band-a": "Bands · Workout A",
    "band-b": "Bands · Workout B",
    "mil-1": "Military · Push + Core",
    "mil-2": "Military · Pull + Legs",
    "mil-3": "Military · Full-Body Circuit",
}


def log_session(plan_type: str) -> WorkoutSession:
    """Record a completed workout (dated today, local TZ)."""
    if plan_type not in VALID_PLAN_TYPES:
        raise ValueError(f"invalid plan_type: {plan_type!r}")
    session = WorkoutSession(plan_type=plan_type, session_date=local_today_date())
    db.session.add(session)
    db.session.commit()
    return session


def recent_sessions(limit: int = 12) -> list[WorkoutSession]:
    return (
        WorkoutSession.query.order_by(
            WorkoutSession.session_date.desc(), WorkoutSession.created_at.desc()
        )
        .limit(limit)
        .all()
    )


def session_summary() -> dict:
    """Counts for the tracking strip: this-week (Mon-start) and all-time."""
    today = local_today_date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    this_week = WorkoutSession.query.filter(
        WorkoutSession.session_date >= week_start
    ).count()
    total = WorkoutSession.query.count()
    return {
        "this_week": this_week,
        "total": total,
        "week_start": week_start.isoformat(),
    }


def delete_session(session_id) -> bool:
    """Undo a logged session. Returns False if it didn't exist."""
    session = db.session.get(WorkoutSession, session_id)
    if session is None:
        return False
    db.session.delete(session)
    db.session.commit()
    return True


def serialize(session: WorkoutSession) -> dict:
    return {
        "id": str(session.id),
        "plan_type": session.plan_type,
        "label": PLAN_LABELS.get(session.plan_type, session.plan_type),
        "session_date": session.session_date.isoformat(),
    }
