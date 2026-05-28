"""JSON API for the /utilities page (#222, 2026-05-24).

Surfaces one-shot data cleanups as OAuth-gated endpoints so the
single-user owner can trigger them from the UI without needing to
curl `/api/debug/backfill/*` with an admin token. The admin-token
split (debug_api.py) protects writes from a leaked READ token —
that risk doesn't apply here because every endpoint is gated by
`@login_required` which already enforces `AUTHORIZED_EMAIL` (the
ONLY user authorized to mutate this app's data).

Endpoints (two shapes):

Query-driven utilities — GET-count preview + POST-run pair, so
the UI can show "X tasks will be cleaned" before Run:
    GET  /api/utilities/clear-stale-next-week-due-dates/count
    POST /api/utilities/clear-stale-next-week-due-dates

Action-only utilities (#223, 2026-05-24) — POST-only; result is
async / external so there's nothing to preview:
    POST /api/utilities/trigger-backup
         — dispatches `.github/workflows/daily-backup.yml` via
           the GitHub Actions API (workflow_dispatch trigger).
    POST /api/utilities/trigger-restore-drill
         — dispatches `.github/workflows/monthly-restore-drill.yml`.
    Both require GITHUB_DISPATCH_TOKEN env var (fine-grained PAT
    with `Actions: write` permission on the taskmanager repo).

Inline-scan utilities (#236, 2026-05-26) — POST-only; runs the
recurring-audit scripts in-process and returns findings INLINE so
the UI can render the result list immediately (no waiting for
workflow + email):
    POST /api/utilities/run-bug-pattern-scan
         — invokes scripts/check_bug_patterns.CHECKS (the #226
           weekly scan).
    POST /api/utilities/run-security-posture-scan
         — invokes scripts/check_security_posture.CHECKS (the
           #227 monthly audit).
    POST /api/utilities/run-tech-debt-audit
         — invokes scripts/check_tech_debt.CHECKS (the #228 weekly
           audit; the dependency-drift check inside shells out to
           pip + npm so this endpoint is the slowest of the three,
           typically ~2-5s).
    All three return ``{total, per_check, findings}``. Skips the
    SendGrid email path (the UI surface IS the result channel).

Async-scan utility (#229b, 2026-05-27) — POST kicks off a
subprocess and returns immediately, GET polls for status:
    POST /api/utilities/run-coverage-audit
         — spawns `scripts/check_test_coverage.py --json-only` in a
           background thread (pytest+coverage takes ~30s, can't
           block the request). Returns {status: "running",
           started_at, estimated_duration_seconds}. 409 if another
           run is in flight.
    GET  /api/utilities/coverage-audit-status
         — poll for the current state. While running, returns
           {status: "running", started_at, result: null}. When done,
           returns {status: "complete", duration_seconds, result:
           {total, per_check, findings, overall}}. On failure,
           returns {status: "error", error}. Safe to poll every 2s.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

import requests
from flask import Blueprint, jsonify
from sqlalchemy import select

from auth import login_required
from models import Task, TaskStatus, Tier, db
from utils import local_today_date

bp = Blueprint("utilities_api", __name__, url_prefix="/api/utilities")

logger = logging.getLogger(__name__)


# #223 (2026-05-24): GitHub Actions workflow dispatch helper. Used by
# the trigger-backup + trigger-restore-drill endpoints below to fire
# the existing scheduled workflows on-demand from the /utilities UI.
#
# Why inline rather than `egress.safe_call_api`: safe_call_api expects
# a JSON response body, but GitHub's workflow_dispatch endpoint returns
# 204 No Content on success. Same defensive shape (timeout, vendor-
# tagged error, no token in error messages) — just specialised for
# the empty-body return.
#
# The token NEVER appears in logged output, even on failure: errors
# only quote GitHub's response status and the (token-free) response
# `message` field.
def _dispatch_github_workflow(workflow_file: str) -> dict:
    """Trigger a GitHub Actions workflow_dispatch on `workflow_file`.

    Args:
        workflow_file: The YAML filename in `.github/workflows/`
            (e.g. `"daily-backup.yml"`). Both target workflows
            (#154 daily-backup, #154.7 monthly-restore-drill)
            declare `workflow_dispatch: {}` so they're API-eligible.

    Returns:
        {"dispatched": True, "actions_url": <URL>} on success — the
        URL points the user at the GitHub Actions tab so they can
        watch the run + see PASS/FAIL when the workflow finishes
        (typically ~3 min for backup, ~5-8 min for restore drill).

    Raises:
        ValueError: GITHUB_DISPATCH_TOKEN missing OR GitHub API
            returned a non-204 status. Message is safe to surface
            to the user — never includes the token.
    """
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_DISPATCH_TOKEN env var not configured — add a "
            "fine-grained PAT with Actions: write on this repo to "
            "Railway's variables (see docs/security/git-credentials.md "
            "for the rotation/setup procedure).",
        )
    # Hardcoded repo (single-deployment app) but env-overrideable for
    # the rare case where a fork wants to wire its own workflows.
    repo = os.environ.get("GITHUB_REPO", "shigsdev/taskmanager")
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # The `ref` is which branch to run the workflow on. main is the
    # production deploy line; backups/restore drills should always
    # use the latest committed scripts there.
    body = {"ref": "main"}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
    except requests.RequestException as e:
        raise ValueError(
            f"GitHub API network error: {type(e).__name__}",
        ) from e
    if resp.status_code != 204:
        # 401/403 → bad token or insufficient scope (most common
        # misconfig). 422 → workflow file not found or doesn't
        # declare workflow_dispatch. 5xx → GitHub side issue.
        detail = ""
        try:
            err_body = resp.json()
            detail = err_body.get("message") or ""
        except ValueError:
            detail = (resp.text or "")[:200]
        raise ValueError(
            f"GitHub workflow_dispatch returned HTTP {resp.status_code}"
            + (f": {detail}" if detail else ""),
        )
    actions_url = f"https://github.com/{repo}/actions"
    logger.info(
        "utilities: dispatched workflow %s (run will appear at %s)",
        workflow_file, actions_url,
    )
    return {"dispatched": True, "actions_url": actions_url}


@bp.get("/clear-stale-next-week-due-dates/count")
@login_required
def clear_stale_next_week_due_dates_count(email: str):  # noqa: ARG001
    """Preview: how many active NEXT_WEEK tasks have a stale (today
    or earlier) due_date that the backfill would clear? Read-only —
    safe to call repeatedly. The UI uses this to display the count
    before the user clicks Run.
    """
    today = local_today_date()
    count = db.session.scalar(
        select(db.func.count()).select_from(Task).where(
            Task.tier == Tier.NEXT_WEEK,
            Task.due_date.is_not(None),
            Task.due_date <= today,
            Task.status == TaskStatus.ACTIVE,
        )
    )
    return jsonify({"count": count or 0})


@bp.post("/clear-stale-next-week-due-dates")
@login_required
def clear_stale_next_week_due_dates_run(email: str):  # noqa: ARG001
    """#220 follow-up: clear stale today/past due_date on tasks
    stuck in tier=NEXT_WEEK from pre-#220 tier-button punts. Wraps
    `task_service.backfill_clear_stale_next_week_due_dates()` —
    identical logic to the admin-token-gated
    `/api/debug/backfill/clear-stale-next-week-due-dates` endpoint,
    but OAuth-only so the UI can trigger it.

    Returns {updated: N}. Idempotent (re-running after clean = 0).
    """
    from task_service import backfill_clear_stale_next_week_due_dates
    n = backfill_clear_stale_next_week_due_dates()
    logger.info(
        "utilities: clear_stale_next_week_due_dates triggered via UI, updated=%d",
        n,
    )
    return jsonify({"updated": n})


# #223 (2026-05-24): on-demand backup + restore-drill triggers.


@bp.post("/trigger-backup")
@login_required
def trigger_backup(email: str):  # noqa: ARG001
    """Dispatch the `daily-backup.yml` GitHub Actions workflow ad-hoc.

    Use case: encrypted DB snapshot to the backup repo without waiting
    for the 07:30 UTC scheduled run. Useful before risky migrations,
    before/after large data imports, or any time you want a known-good
    point-in-time copy. The workflow itself (#154) handles encryption
    + git push + retention pruning + email status report.

    Returns {dispatched: True, actions_url: ...} on success — the
    workflow runs asynchronously over the next few minutes; check the
    actions URL or your inbox for PASS/FAIL.

    On misconfig (no token / bad token / GitHub error), returns
    HTTP 503 with the failure detail. Token VALUE is never returned.
    """
    try:
        result = _dispatch_github_workflow("daily-backup.yml")
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)


# #236 (2026-05-26): on-demand triggers for the recurring audit
# scripts. Unlike the workflow-dispatch utilities above, these run
# IN-PROCESS — the audit scripts are pure-stdlib + read-only, so
# we can invoke their CHECKS arrays directly and surface the
# findings inline on the page (no waiting for a workflow + email).
#
# Why not workflow_dispatch like #223? Two reasons:
#   1. Latency: the workflow takes ~30s to start + run; running
#      in-process completes in <1s for both audits combined.
#   2. Visibility: a workflow_dispatch shows up as "dispatched, see
#      Actions tab" — the user doesn't see the finding list until
#      the email arrives. Inline scan shows the findings RIGHT NOW.
# Side effect: the SendGrid email path is skipped (no cron, no
# email). That's intentional — the on-demand UI IS the email-substitute.


def _serialise_findings(findings) -> list[dict]:
    """Convert a list of script Finding dataclasses to JSON-safe dicts.

    Both `check_bug_patterns.Finding` and `check_security_posture.Finding`
    are frozen dataclasses; dataclasses.asdict() handles either.
    """
    import dataclasses
    out: list[dict] = []
    for f in findings:
        try:
            out.append(dataclasses.asdict(f))
        except TypeError:
            # Defensive — if a future check returns a non-dataclass
            # Finding, render its repr() so the UI still surfaces it.
            out.append({"detail": repr(f)})
    return out


# #244 (2026-05-27): /utilities-triggered audits dispatch the cron
# workflow to persist BACKLOG.md changes back to GitHub.
#
# Why: the in-process autofile path (#243) modifies BACKLOG.md ON THE
# RAILWAY CONTAINER'S LOCAL FILESYSTEM. Railway containers have no
# git credentials, no push step, and get wiped on every deploy. So
# the autofile rows ARE written but only inside the ephemeral
# container — invisible to the operator who checks origin/main.
#
# Fix: after the in-process audit returns the findings inline, also
# dispatch the matching cron workflow. The workflow runs the audit
# on a GitHub Actions runner (which has commit + push wired in via
# the #242 commit-back step). UI gets the inline results immediately;
# the workflow_dispatch result lands in BACKLOG.md ~2 minutes later.
#
# Why dispatch the workflow rather than directly committing via the
# REST API:
#   - The workflow already has the commit + push logic; reusing it
#     means a single code path. (REST API would need separate locking
#     + race handling against the cron's own commit step.)
#   - The workflow re-runs the audit on a clean checkout — catches
#     "I committed something locally but the audit doesn't see it"
#     class of confusion.
#   - The dispatch is async — Flask returns immediately, no extra
#     latency on the /utilities response.
_AUDIT_NAME_TO_WORKFLOW = {
    "bug-pattern": "weekly-bug-pattern-scan.yml",
    "security": "monthly-security-audit.yml",
    "tech-debt": "weekly-tech-debt-audit.yml",
    "coverage": "weekly-coverage-audit.yml",
}


def _dispatch_audit_workflow_for_autofile(audit_name: str) -> None:
    """#244: best-effort workflow_dispatch so the cron path commits
    the autofile changes back to GitHub. Failures are logged but
    don't propagate (the inline audit result is the load-bearing
    channel; persistence is a value-add).
    """
    workflow_file = _AUDIT_NAME_TO_WORKFLOW.get(audit_name)
    if not workflow_file:
        return
    try:
        _dispatch_github_workflow(workflow_file)
        logger.info(
            "utilities: dispatched %s for autofile persistence",
            workflow_file,
        )
    except (ValueError, RuntimeError) as e:
        # Most common: GITHUB_DISPATCH_TOKEN not set in this env.
        # Logged at INFO not WARNING because for dev/test envs it's
        # expected and not actionable. The inline scan result still
        # rendered correctly; only the BACKLOG.md persistence is
        # affected.
        logger.info(
            "utilities: autofile dispatch skipped for %s: %s: %s",
            audit_name, type(e).__name__, e,
        )


def _run_audit_script_checks(
    checks_module, audit_name: str | None = None,
) -> dict:
    """Invoke every check function in `checks_module.CHECKS` and
    return the aggregate as a JSON-safe dict.

    Used by /run-bug-pattern-scan, /run-security-posture-scan, and
    /run-tech-debt-audit. Catches per-check exceptions so one broken
    check doesn't abort the whole audit — the broken check just shows
    0 findings + an "errored" note in per_check_counts.

    If ``audit_name`` is provided, the finding list is also passed to
    ``backlog_autofile.run_for_audit()`` so /utilities-triggered runs
    end up in BACKLOG.md's ``## Auto-filed by recurring audits``
    section. After that, #244 dispatches the matching cron workflow
    so the BACKLOG.md change gets committed back to GitHub (the
    Railway container can't push). The in-process autofile is still
    useful for the local-dev / smoke-test path where the container
    has git access. (#243, 2026-05-27; #244, 2026-05-27)
    """
    all_findings = []
    per_check = []
    for label, fn in checks_module.CHECKS:
        try:
            findings = fn()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "utilities: %s check %s errored: %s: %s",
                checks_module.__name__, label, type(e).__name__, e,
            )
            per_check.append({"label": label, "count": 0,
                              "errored": f"{type(e).__name__}: {e}"})
            continue
        all_findings.extend(findings)
        per_check.append({"label": label, "count": len(findings)})

    # #243: auto-file the findings so the operator sees them in the
    # backlog even when they ran the audit by clicking Run on the
    # /utilities card. Same upsert path the cron uses — single source
    # of truth for "this finding exists." Best-effort: a broken
    # autofile must not take down the UI response.
    # #244: AFTER the local autofile, dispatch the cron workflow so
    # the BACKLOG.md change gets committed back to GitHub from the
    # GH Actions runner (Railway containers can't push to git).
    if audit_name:
        try:
            from scripts import backlog_autofile
            backlog_autofile.run_for_audit(audit_name, all_findings)
        except (ImportError, FileNotFoundError, ValueError, OSError) as e:
            logger.warning(
                "utilities: autofile for %s failed (continuing): "
                "%s: %s",
                audit_name, type(e).__name__, e,
            )
        _dispatch_audit_workflow_for_autofile(audit_name)

    return {
        "total": len(all_findings),
        "per_check": per_check,
        "findings": _serialise_findings(all_findings),
    }


@bp.post("/run-bug-pattern-scan")
@login_required
def run_bug_pattern_scan(email: str):  # noqa: ARG001
    """#236 — run the #226 weekly bug-pattern scanner in-process and
    return the findings inline. Skips the SendGrid email path (the UI
    surfaces the results directly).

    Returns ``{total, per_check, findings}``. `per_check` is the
    ordered list of `{label, count, errored?}` so the UI can render a
    breakdown even when total is 0. Empty `findings` array = CLEAN.
    """
    from scripts import check_bug_patterns
    # #243 — pass audit_name so the findings get auto-filed to
    # BACKLOG.md's `## Auto-filed by recurring audits` section.
    result = _run_audit_script_checks(
        check_bug_patterns, audit_name="bug-pattern",
    )
    logger.info(
        "utilities: bug-pattern scan triggered via UI, total=%d",
        result["total"],
    )
    return jsonify(result)


@bp.post("/run-security-posture-scan")
@login_required
def run_security_posture_scan(email: str):  # noqa: ARG001
    """#236 — run the #227 monthly security-posture audit in-process
    and return findings inline. Skips the SendGrid email path. The
    operator-maintained source-of-truth files
    (`docs/security/pat-inventory.json`,
    `docs/security/oauth-scopes.json`) are read on every call so the
    UI reflects whatever is committed at the deployed SHA.
    """
    from scripts import check_security_posture
    # #243 — autofile to BACKLOG.md alongside the email channel.
    result = _run_audit_script_checks(
        check_security_posture, audit_name="security",
    )
    logger.info(
        "utilities: security-posture scan triggered via UI, total=%d",
        result["total"],
    )
    return jsonify(result)


# #229b (2026-05-27): coverage-audit on-demand card — async edition.
#
# The other three inline-scan endpoints (#236 bug-pattern + security-
# posture + tech-debt) run their CHECKS arrays in <2 seconds, so a
# synchronous POST that returns the result is fine. The coverage audit
# is different: pytest with coverage takes ~30 seconds against the
# full test suite. Blocking a Flask request that long would hit
# gunicorn's worker timeout AND give the user no progress feedback.
#
# Pattern: ONE single-user job slot tracked in a module-level dict.
# POST spawns scripts/check_test_coverage.py as a subprocess with
# --json-only <tmpfile>. A background thread watches the subprocess
# and updates the state dict when it finishes. GET polls the state.
#
# Trade-offs:
#   - Single slot = no concurrent runs (operator gets 409 if they
#     double-click; harmless because there's only one operator).
#   - Container restart wipes the in-flight state — file in /tmp/
#     vanishes with the container. Polling sees "idle" on the new
#     container; the JS frontend's "audit was interrupted" message
#     handles this case.
#   - No persistence across deploys — last result is ephemeral.
#     Acceptable because the cron's email is the durable record.
#
# #250 (2026-05-28): MOVED FROM module-level dict to a shared FILE
# in /tmp/ because gunicorn runs multiple workers (default 2 from
# `gunicorn.conf.py`'s `WEB_CONCURRENCY=2`), and module-level dicts
# are NOT shared across workers. The original implementation had a
# severe bug: POST landed on worker A (set state="running"), polling
# round-robin'd to worker B (saw state="idle" because worker B's
# module state was never touched), and the frontend's polling-on-idle
# fix (#244) interpreted that as a container restart → "Audit was
# interrupted" message. File-based state is visible to all workers
# in the same container.
#
# Atomicity: writes go through a sibling `.tmp` file + `os.replace()`
# which is atomic on POSIX. Readers see either the old or the new
# file content, never a partial state. The single-worker threading.
# Lock is kept (only inside the kickoff POST handler) to serialise
# the read-check-write sequence of the 409 guard against
# double-click within a single worker; cross-worker the user is the
# only one clicking so a true concurrent double-POST is extremely
# rare, and at worst we get two subprocesses racing for the same
# result file (single-user app, low-cost outcome).
_COVERAGE_JOB_STATE_PATH = Path(
    # nosec B108 / noqa: S108 — Intentional shared-state file under
    # the system temp dir so all gunicorn workers in the same Railway
    # container can read/write the same job-state record. The file
    # contains audit-result JSON (no secrets, no PII) and is gated
    # behind the @login_required `/api/utilities/*` routes which are
    # AUTHORIZED_EMAIL-locked. Predictable path is the WHOLE POINT —
    # mkstemp here would defeat the cross-worker visibility goal.
    os.environ.get("TMPDIR", "/tmp"),  # noqa: S108  # nosec B108 — intentional shared state path; see comment above
) / "taskmanager_coverage_audit_state.json"
_COVERAGE_IDLE_STATE: dict = {
    "status": "idle",          # idle | running | complete | error
    "started_at": None,        # ISO8601
    "finished_at": None,       # ISO8601 (set on complete OR error)
    "duration_seconds": None,  # filled on completion
    "result": None,            # the parsed JSON when status=complete
    "error": None,             # str when status=error
}
_coverage_job_lock = __import__("threading").Lock()


def _read_coverage_job_state() -> dict:
    """Return the current job state from the shared state file, or the
    idle default if the file is missing / malformed.

    Missing file = idle (no run ever started, or container was just
    restarted). Corrupt file = idle (defensive: surface as no-job and
    let the next kickoff overwrite it). Returns a COPY so callers can't
    mutate _COVERAGE_IDLE_STATE.
    """
    try:
        text = _COVERAGE_JOB_STATE_PATH.read_text(encoding="utf-8")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return dict(_COVERAGE_IDLE_STATE)
        # Defensive: ensure all expected keys are present.
        out = dict(_COVERAGE_IDLE_STATE)
        out.update(parsed)
        return out
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_COVERAGE_IDLE_STATE)


def _write_coverage_job_state(state: dict) -> None:
    """Atomic write of the job state to the shared file. Uses a
    sibling `.tmp` file + `os.replace()` so readers never see a
    partial state — they get either the old file or the new file,
    never a half-written one.
    """
    tmp = _COVERAGE_JOB_STATE_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        # `Path.replace` calls `os.replace`, which is atomic across
        # POSIX (and best-effort on Windows). For Railway prod
        # (Linux containers) this is truly atomic.
        tmp.replace(_COVERAGE_JOB_STATE_PATH)
    except OSError as e:
        logger.warning(
            "utilities: coverage state write failed (continuing): "
            "%s: %s",
            type(e).__name__, e,
        )


def _run_coverage_audit_subprocess(json_path: str) -> None:
    """Background-thread target. Runs the audit script, then updates
    the module-level state dict. Catches every exception so the
    thread can't die silently and leave the state stuck at
    "running" — any unexpected failure surfaces as status=error.
    """
    import subprocess
    import sys
    import threading  # noqa: F401 — imported for the lock

    started = datetime.datetime.now(datetime.UTC)
    script_path = (
        Path(__file__).resolve().parent / "scripts" / "check_test_coverage.py"
    )
    # #229b refinement (2026-05-27): redirect stdout/stderr to tempfiles
    # rather than `capture_output=True` (PIPE). On Windows, PIPE-captured
    # output of a long-running pytest run can deadlock or crash before
    # coverage.json lands. Tempfile redirection sidesteps the PIPE
    # buffering issue while still letting us read the last 500 bytes of
    # stderr on failure for diagnostics.
    #
    # Also force PYTHONIOENCODING=utf-8 in the subprocess env — the
    # script's sys.stdout/stderr otherwise default to cp1252 on Windows,
    # which crashes on the non-ASCII characters (→ → arrows etc.)
    # that the script's progress messages use. The script then exits
    # 1 from the encode error and the result file never gets written.
    import tempfile as _tempfile
    stderr_fd, stderr_path = _tempfile.mkstemp(
        prefix="cov-audit-stderr-", suffix=".log",
    )
    os.close(stderr_fd)
    sub_env = os.environ.copy()
    sub_env["PYTHONIOENCODING"] = "utf-8"
    try:
        # Inherit env — DIGEST_*_EMAIL etc. unused in --json-only mode
        # but harmless. Discard stdout (the pytest report is large +
        # uninteresting once coverage.json lands); keep stderr in a
        # tempfile so we can surface the tail of it on failure.
        with open(stderr_path, "w", encoding="utf-8") as stderr_fp:
            proc = subprocess.run(  # noqa: S603
                [
                    sys.executable, str(script_path),
                    "--json-only", json_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=stderr_fp,
                env=sub_env,
                text=True,
                check=False,
                timeout=600,  # generous: pytest+cov on a slow runner
            )
        # Read stderr back so we can include it in error messages.
        try:
            stderr_tail = Path(stderr_path).read_text(
                encoding="utf-8", errors="replace",
            )[-500:]
        except OSError:
            stderr_tail = ""
        if proc.returncode == 2:
            # Internal error in the script (e.g. coverage.json not
            # produced). Surface the last bit of stderr to the UI.
            raise RuntimeError(
                "coverage script exited 2 (internal error): "
                + stderr_tail,
            )
        # 0 = clean, 1 = findings — both produce a result file.
        result_path = Path(json_path)
        if not result_path.exists():
            raise RuntimeError(
                f"coverage script exited but produced no result file "
                f"(rc={proc.returncode}, stderr_tail={stderr_tail!r})",
            )
        if result_path.stat().st_size == 0:
            raise RuntimeError(
                f"coverage script exited but result file is empty "
                f"(rc={proc.returncode}, stderr_tail={stderr_tail!r})",
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (subprocess.TimeoutExpired, RuntimeError, OSError,
            json.JSONDecodeError) as e:
        finished = datetime.datetime.now(datetime.UTC)
        # #250 — write state to the shared file so all gunicorn workers
        # see the new "error" state. Reading first preserves any fields
        # the kickoff set (started_at) before overwriting status/error.
        with _coverage_job_lock:
            cur = _read_coverage_job_state()
            cur.update({
                "status": "error",
                "finished_at": finished.isoformat(),
                "duration_seconds": (finished - started).total_seconds(),
                "result": None,
                "error": f"{type(e).__name__}: {e}",
            })
            _write_coverage_job_state(cur)
        logger.warning(
            "utilities: coverage audit subprocess errored: %s: %s",
            type(e).__name__, e,
        )
        return
    finally:
        # Best-effort cleanup of the stderr tempfile. Logged at INFO so
        # the path is grep-able in Railway logs if a future run errors
        # before this finally fires (the wrapper catches every excn so
        # that's belt-and-braces).
        import contextlib
        logger.info("utilities: coverage audit stderr at %s", stderr_path)
        with contextlib.suppress(OSError):
            Path(stderr_path).unlink(missing_ok=True)

    # #243 (2026-05-27): autofile coverage findings into BACKLOG.md
    # the same way the inline-scan endpoints do. The script's
    # --json-only branch exits before its own autofile branch fires,
    # so we trigger it here using the parsed result. Best-effort: a
    # broken autofile must not flip the job's status to error since
    # the audit data itself is fine.
    # #244 (2026-05-27): also dispatch the cron workflow so the
    # autofile change gets committed back to GitHub (Railway can't
    # push). Same best-effort treatment.
    try:
        from types import SimpleNamespace

        from scripts import backlog_autofile
        adapted = [
            SimpleNamespace(
                check_id=f.get("check_id", ""),
                path=f.get("path", ""),
                detail=f.get("detail", ""),
            )
            for f in (result.get("findings") or [])
        ]
        backlog_autofile.run_for_audit("coverage", adapted)
    except (ImportError, FileNotFoundError, ValueError, OSError) as e:
        logger.warning(
            "utilities: coverage autofile failed (continuing): "
            "%s: %s",
            type(e).__name__, e,
        )
    _dispatch_audit_workflow_for_autofile("coverage")

    finished = datetime.datetime.now(datetime.UTC)
    # #250 — write to shared file (visible across all gunicorn workers).
    with _coverage_job_lock:
        cur = _read_coverage_job_state()
        cur.update({
            "status": "complete",
            "finished_at": finished.isoformat(),
            "duration_seconds": (finished - started).total_seconds(),
            "result": result,
            "error": None,
        })
        _write_coverage_job_state(cur)
    logger.info(
        "utilities: coverage audit complete (total=%d, %.1fs)",
        result.get("total", 0),
        (finished - started).total_seconds(),
    )


@bp.post("/run-coverage-audit")
@login_required
def run_coverage_audit(email: str):  # noqa: ARG001
    """#229b — kick off a coverage-audit subprocess in the background.

    Returns immediately with {status: "running", started_at}. Client
    polls GET /api/utilities/coverage-audit-status until status flips
    to "complete" or "error". The actual result JSON (matching the
    inline-scan shape from #236) lives in the status response when
    complete.

    Returns 409 if a previous run is already in flight. Single-user
    app, so two concurrent runs would just race for the result file
    and the operator gets confusing UX.
    """
    import tempfile
    import threading

    with _coverage_job_lock:
        # #250 — read state from shared file so all gunicorn workers
        # see the SAME source of truth. Without this, worker A could
        # be running while worker B sees idle and starts a SECOND
        # subprocess (race on coverage.json + autofile commits).
        cur = _read_coverage_job_state()
        if cur["status"] == "running":
            return jsonify({
                "error": "A coverage audit is already running",
                "started_at": cur["started_at"],
            }), 409
        # Allocate a tempfile path the subprocess will write to. Use
        # a per-run path so a stale file from a prior run can't
        # mislead the next poll.
        fd, json_path = tempfile.mkstemp(
            prefix="cov-audit-", suffix=".json",
        )
        os.close(fd)  # subprocess will overwrite it
        started_iso = datetime.datetime.now(datetime.UTC).isoformat()
        _write_coverage_job_state({
            "status": "running",
            "started_at": started_iso,
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
        })

    # Spawn the background thread AFTER releasing the lock so the
    # subprocess.run inside doesn't hold up POSTs that might come
    # in to status.
    t = threading.Thread(
        target=_run_coverage_audit_subprocess,
        args=(json_path,),
        daemon=True,
        name="coverage-audit-runner",
    )
    t.start()
    logger.info(
        "utilities: coverage audit started, json_path=%s", json_path,
    )
    return jsonify({
        "status": "running",
        "started_at": started_iso,
        # #251 (2026-05-28) — bumped from 30 to 240 to match observed
        # Railway runtimes (3-5 minutes for the full pytest --cov
        # suite). The UI's pollAsyncJob loop now overrides this with
        # a live elapsed-time counter, so the field is informational.
        "estimated_duration_seconds": 240,
    })


@bp.get("/coverage-audit-status")
@login_required
def coverage_audit_status(email: str):  # noqa: ARG001
    """#229b — poll the current coverage-audit job state.

    Returns the module-level state dict snapshot. While running, the
    `result` field is null and the UI shows a spinner. When complete,
    `result` contains the {total, per_check, findings, overall}
    payload the inline-scan renderer expects. On error, `error`
    contains a short type+message string.

    Idempotent and read-only — safe to poll every 2 seconds.
    """
    # #250 — read from shared file so polling sees the SAME state
    # regardless of which gunicorn worker handles this request.
    # Atomic-rename semantics on the writer side mean we either see
    # the old state or the new state, never a partial one.
    snapshot = _read_coverage_job_state()
    return jsonify(snapshot)


@bp.post("/run-tech-debt-audit")
@login_required
def run_tech_debt_audit(email: str):  # noqa: ARG001
    """#236 — run the #228 weekly tech-debt audit in-process and
    return findings inline. Skips the SendGrid email path.

    Note: the `dependency-drift` check inside this audit shells out
    to `pip list --outdated` and `npm outdated`, both of which can
    take a few seconds on first call. On the Railway host the
    runtime is normally < 5s; if it consistently exceeds 10s,
    consider moving to a background-job pattern.
    """
    from scripts import check_tech_debt
    # #243 — autofile to BACKLOG.md alongside the email channel.
    result = _run_audit_script_checks(
        check_tech_debt, audit_name="tech-debt",
    )
    logger.info(
        "utilities: tech-debt audit triggered via UI, total=%d",
        result["total"],
    )
    return jsonify(result)


@bp.post("/trigger-restore-drill")
@login_required
def trigger_restore_drill(email: str):  # noqa: ARG001
    """Dispatch the `monthly-restore-drill.yml` GitHub Actions workflow
    ad-hoc.

    Use case: verify the most recent backup is actually restorable
    (decryptable + pg_restore-able + row counts ±5% of live). The
    drill (#154.7) catches dump corruption, key drift, pg_restore
    version skew, and Fernet ciphertext mangling BEFORE the day you
    actually need to restore. Normally runs monthly; this lets you
    trigger out-of-cycle (e.g. after rotating BACKUP_FERNET_KEY).

    Returns {dispatched: True, actions_url: ...}. Workflow takes
    ~5-8 minutes to complete; PASS/FAIL email arrives when it finishes.
    """
    try:
        result = _dispatch_github_workflow("monthly-restore-drill.yml")
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)
