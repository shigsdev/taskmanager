"""Gunicorn production configuration.

Railway sets the PORT env var. Workers are calculated based on
available CPUs. Timeouts are generous for image scan uploads
which may take a few seconds on the Vision + Claude pipeline.
"""
import os

# Bind to Railway's PORT (default 8000 for local dev)
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Workers: 2-4 per CPU core, capped for Railway's single-container model
workers = int(os.environ.get("WEB_CONCURRENCY", 2))

# Timeout: 120s covers image scan pipeline (Vision + Claude API calls)
timeout = 120

# Graceful restart timeout
graceful_timeout = 30

# Access logging to stdout (Railway captures it)
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Preload app for faster worker boot
preload_app = True


# #439: the lock handle of the worker that runs the scheduler. Kept for
# the worker's lifetime; the OS releases it when the worker exits.
_scheduler_lock = None


def post_worker_init(worker):  # noqa: ARG001 — gunicorn hook signature
    """Start the digest scheduler in exactly one worker.

    APScheduler uses a background thread which is not fork-safe.
    With preload_app=True the app is created in the master process,
    but background threads die after fork. This hook runs after the
    fork, inside each worker.

    #439: the worker that wins an exclusive file lock runs it. It used
    to be "the worker with age 1", but age is a spawn counter, so when
    worker 1 was killed (e.g. by the timeout) its replacement (age 3)
    never started one and the digest + nightly jobs stopped until the
    next deploy. The lock is released when its holder exits, so the
    replacement takes over; a second live worker never gets it, so
    emails are still sent once.
    """
    global _scheduler_lock
    import scheduler_lock

    handle = scheduler_lock.try_acquire()
    if handle is None:
        return
    _scheduler_lock = handle
    from app import _start_digest_scheduler, create_app
    app = create_app()
    _start_digest_scheduler(app)
