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


def post_worker_init(worker):
    """Start the digest scheduler in the first worker only.

    APScheduler uses a background thread which is not fork-safe.
    With preload_app=True the app is created in the master process,
    but background threads die after fork. This hook runs after the
    fork, inside each worker. We only start the scheduler in worker
    with the lowest age (first to boot) to avoid duplicate emails.
    """
    # worker.age starts at 1 and increments for each spawned worker
    if worker.age == 1:
        from app import _start_digest_scheduler, create_app
        app = create_app()
        _start_digest_scheduler(app)
