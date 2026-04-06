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
