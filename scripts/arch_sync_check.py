#!/usr/bin/env python3
"""Verify that ARCHITECTURE.md mentions every scheduler job, top-level
route, and ``/api/...`` endpoint the code defines.

Exists because the ARCHITECTURE.md catchups keep drifting (three times
in the 2026-04-20 / 04-21 sprint). CLAUDE.md's cascade-check table
says "new route → update ARCHITECTURE, do NOT mark [⏭️] N/A" but
written rules are easy to skip under momentum. This script checks
the claim mechanically from ``run_all_gates.sh``.

Heuristic, not perfect: a string match on the identifier. A route
name mentioned in a comment counts as documented. Fine — the goal is
"did someone at least think about whether to document it", not a
semantic parse of the doc. False positives (the diff says something's
missing when it's actually covered under a different heading) are
self-correcting: add the name anywhere in the doc and the check
passes.

Failure output lists every missing name one per line so a future
agent can grep and fix. Exit 0 on success, 1 on drift.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARCH = REPO / "ARCHITECTURE.md"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _scheduler_job_ids() -> list[str]:
    """Scrape every ``scheduler.add_job(..., id="...")`` from app.py."""
    text = _read(REPO / "app.py")
    # add_job(...) can span multiple lines; match the id= kwarg anywhere
    # in the call. Cheap and sufficient — we only have a handful.
    return re.findall(r'id=["\']([^"\']+)["\']', text)


def _flask_routes() -> list[str]:
    """Scrape ``@app.route("/<path>")`` from app.py (top-level routes)."""
    text = _read(REPO / "app.py")
    return re.findall(
        r'@app\.route\(["\'](/[\w<>:/-]+)["\']', text,
    )


def _api_endpoints() -> list[str]:
    """Scrape ``@bp.get/post/patch/delete/put("/...")`` from
    every ``*_api.py`` module. Emits the full path including the
    blueprint's url_prefix when detectable."""
    endpoints: list[str] = []
    for api_file in REPO.glob("*_api.py"):
        text = _read(api_file)
        # Extract the blueprint url_prefix, if any, from the Blueprint(...) call.
        prefix_match = re.search(
            r'url_prefix\s*=\s*["\']([^"\']*)["\']', text,
        )
        prefix = prefix_match.group(1) if prefix_match else ""
        # Match @bp.<verb>("/...") — the trailing path can be empty ("")
        # which Flask treats as the bare prefix (e.g. GET /api/tasks).
        for path in re.findall(
            r'@bp\.(?:get|post|patch|delete|put)\(["\']([^"\']*)["\']',
            text,
        ):
            full = prefix.rstrip("/") + "/" + path.lstrip("/")
            full = full.rstrip("/") or prefix or path
            endpoints.append(full)
    return endpoints


def _missing_from_arch(names: list[str], arch_text: str) -> list[str]:
    """Return names that don't appear anywhere in ARCHITECTURE.md."""
    missing = []
    for name in sorted(set(names)):
        if not name:
            continue
        if name in arch_text:
            continue
        missing.append(name)
    return missing


def main() -> int:
    arch = _read(ARCH)
    if not arch:
        print("ARCHITECTURE.md not found or empty", file=sys.stderr)
        return 1

    job_ids = _scheduler_job_ids()
    routes = _flask_routes()
    endpoints = _api_endpoints()

    missing_jobs = _missing_from_arch(job_ids, arch)
    missing_routes = _missing_from_arch(routes, arch)
    missing_endpoints = _missing_from_arch(endpoints, arch)

    drift = bool(missing_jobs or missing_routes or missing_endpoints)

    if drift:
        print(
            "ARCHITECTURE.md drift detected — add these to the diagram "
            "or Components / Data Flows sections:",
            file=sys.stderr,
        )
        for j in missing_jobs:
            print(f"  scheduler job: {j}", file=sys.stderr)
        for r in missing_routes:
            print(f"  Flask route:   {r}", file=sys.stderr)
        for e in missing_endpoints:
            print(f"  API endpoint:  {e}", file=sys.stderr)
        print(
            "\nSee CLAUDE.md cascade check for the rule. "
            "If the name is intentionally abstracted (e.g. /tier/<name> "
            "covers multiple renderings), add a one-line comment in "
            "ARCHITECTURE.md referencing the identifier so this check "
            "passes.",
            file=sys.stderr,
        )
        return 1

    total = len(set(job_ids)) + len(set(routes)) + len(set(endpoints))
    print(
        f"arch_sync_check OK: {total} names checked "
        f"({len(set(job_ids))} jobs, {len(set(routes))} routes, "
        f"{len(set(endpoints))} endpoints).",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
