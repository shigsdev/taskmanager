"""Guard tests for scripts/arch_sync_check.py (#264).

#167 relocated the nightly-cron table out of app.py (`_NIGHTLY_CRONS`)
into cron_jobs.py (`JOB_ORDER`). The arch-sync gate scraped job ids from
app.py ONLY, so the move silently dropped the four nightly crons from
enforcement — the scraper went from 6 ids to 2 without ever failing,
because shrinking the scrape input can't make `_missing_from_arch` go
red. #264 re-points the scraper at both files; these tests assert the
scrape input can't silently shrink again. #512 adds a check of the
scrape against the app's real route list (app.url_map): it may miss
only the named few (#516 fixes those) and may never invent a path.
"""
from __future__ import annotations

import importlib.util
import pathlib

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load_arch_sync():
    spec = importlib.util.spec_from_file_location(
        "arch_sync_check", SCRIPTS_DIR / "arch_sync_check.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scraper_finds_all_cron_jobs_module_ids():
    """Every job id declared in cron_jobs.JOB_ORDER must be surfaced by
    the scraper. Auto-syncs with the source of truth — add a 5th nightly
    cron to JOB_ORDER and this test requires the scraper to find it,
    guarding the exact #167 relocation class going forward."""
    import cron_jobs
    found = set(_load_arch_sync()._scheduler_job_ids())
    missing = cron_jobs.VALID_JOB_IDS - found
    assert not missing, (
        f"arch_sync_check._scheduler_job_ids() dropped JOB_ORDER ids "
        f"{sorted(missing)} — did the table move out of a scraped file? "
        f"(found: {sorted(found)})"
    )


def test_scraper_finds_app_py_add_job_ids():
    """The two directly-registered add_job(id=) scheduler jobs in app.py
    must also be surfaced, so the full scheduler surface (6 jobs today)
    stays enforced against ARCHITECTURE.md."""
    found = set(_load_arch_sync()._scheduler_job_ids())
    assert {"daily_digest", "scheduler_heartbeat"} <= found, (
        f"app.py add_job ids missing from scraper (found: {sorted(found)})"
    )


# --- #512: the scrape against the app's real route list -----------------------

# Routes the scraper cannot see today. #516 replaces the regex scrape with
# app.url_map; until then this set may only SHRINK — a new route the
# scrape misses fails below instead of slipping past the gate.
KNOWN_UNSCRAPED = {
    "/",                          # the regex needs a character after "/"
    "/sw.js",                     # ...and no "." in a path
    "/login/google",              # Flask-Dance's blueprint, url_prefix in app.py
    "/login/google/authorized",
    "/static/<path:filename>",    # Flask's own
}


def test_the_scrape_sees_every_real_route_but_the_known_few(app):
    mod = _load_arch_sync()
    scraped = set(mod._flask_routes()) | set(mod._api_endpoints())
    real = {r.rule.rstrip("/") or "/" for r in app.url_map.iter_rules()}
    unseen = real - scraped - KNOWN_UNSCRAPED
    assert not unseen, (
        f"routes the arch-sync gate can't see (so ARCHITECTURE.md can "
        f"miss them silently): {sorted(unseen)}"
    )
    assert real >= KNOWN_UNSCRAPED, "a known-unscraped route is gone — drop it here"


def test_every_scraped_route_is_real(app):
    """The scrape must not invent paths (a bad prefix join would make the
    gate demand documentation for routes that don't exist)."""
    mod = _load_arch_sync()
    real = {r.rule.rstrip("/") or "/" for r in app.url_map.iter_rules()}
    invented = (set(mod._flask_routes()) | set(mod._api_endpoints())) - real
    assert not invented, sorted(invented)
