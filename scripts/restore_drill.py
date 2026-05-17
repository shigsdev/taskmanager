"""Monthly automated restore drill (#154.7).

Pipeline:
    Pull latest .dump.fernet from BACKUP_REPO_URL
        ↓
    Fernet.decrypt(bytes, key)
        ↓
    pg_restore into a scratch Postgres in the GH Actions runner
    (services: postgres in the workflow file)
        ↓
    Validate: row counts in scratch ≈ live row counts (±5%)
        ↓
    Email PASS / FAIL report

A backup you've never restored is a 50/50 backup. This drill catches
dump corruption, key drift, pg_restore version skew, and Fernet
ciphertext mangling BEFORE the day you actually need to restore.

Required env vars (GitHub Actions secrets + workflow-set):
    BACKUP_REPO_URL          source of dumps
    BACKUP_FERNET_KEY        decryption key
    DATABASE_URL             LIVE Postgres — for the row-count comparison
    SCRATCH_DATABASE_URL     scratch Postgres in the runner (`localhost`)
    SENDGRID_API_KEY / DIGEST_FROM_EMAIL / DIGEST_TO_EMAIL  email report

Pass criteria:
    * pg_restore exited 0 (or with only acceptable warnings)
    * scratch row count for tasks/goals/projects within ±5% of live
    * scratch contains at least 1 row in `tasks` (sanity)
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOLERANCE = 0.05  # 5%

# Same pattern as backup_to_github.py — pass absolute pg_restore path
# via env to dodge $GITHUB_PATH ordering surprises. Workflow sets this
# to /usr/lib/postgresql/18/bin/pg_restore so the runner uses the v18
# binary it installed from PGDG, not the v16 default.
PG_RESTORE_BIN = os.environ.get("PG_RESTORE_BIN", "pg_restore")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.stderr.write(f"FATAL: {name} not set\n")
        sys.exit(1)
    return val


def _live_counts(database_url: str) -> dict:
    """Row counts on the LIVE database (the comparison baseline)."""
    import psycopg

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM tasks), "
            "(SELECT count(*) FROM goals), "
            "(SELECT count(*) FROM projects)"
        )
        row = cur.fetchone()
        return {"tasks": row[0], "goals": row[1], "projects": row[2]}


def _scratch_counts(database_url: str) -> dict:
    """Row counts on the SCRATCH database after pg_restore."""
    return _live_counts(database_url)  # same query shape


def _within_tolerance(scratch: int, live: int, tol: float = TOLERANCE) -> bool:
    """True if scratch is within ±tol of live (or live==0 and scratch==0)."""
    if live == 0:
        return scratch == 0
    return abs(scratch - live) / live <= tol


def fetch_latest_backup(backup_repo: str, dest_dir: Path) -> Path:
    """Clone backup repo, find newest *.dump.fernet, return its path."""
    sys.stdout.write(f"[drill] cloning {backup_repo}\n")
    subprocess.run(
        ["git", "clone", "--depth", "1", backup_repo, str(dest_dir)],
        check=True, capture_output=True, text=True,
    )
    candidates = sorted(dest_dir.glob("*.dump.fernet"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        sys.stderr.write("FATAL: no *.dump.fernet found in backup repo\n")
        sys.exit(2)
    latest = candidates[-1]
    sys.stdout.write(f"[drill] using {latest.name}\n")
    return latest


def decrypt(enc_path: Path, key: str, out_path: Path) -> None:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        f = Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception as e:
        sys.stderr.write(f"FATAL: invalid Fernet key: {e}\n")
        sys.exit(3)
    try:
        plaintext = f.decrypt(enc_path.read_bytes())
    except InvalidToken:
        sys.stderr.write("FATAL: Fernet decryption failed — wrong key?\n")
        sys.exit(3)
    out_path.write_bytes(plaintext)
    sys.stdout.write(f"[drill] decrypted → {out_path.name} ({len(plaintext)} bytes)\n")


def restore(dump_path: Path, scratch_url: str) -> dict:
    """pg_restore into scratch. Returns {"elapsed_sec": N}.

    --clean drops existing objects first; --no-owner / --no-privileges
    skip the (irrelevant) ownership/grant SQL. We tolerate a non-zero
    exit with warnings in stderr — pg_restore is famously chatty about
    extensions and roles that don't exist on the scratch side.
    """
    started = datetime.datetime.now(datetime.UTC)
    # PG_RESTORE_BIN is an env var the trusted workflow YAML sets to a
    # fixed absolute path (/usr/lib/postgresql/18/bin/pg_restore), with
    # a hardcoded "pg_restore" literal fallback. Not user-controlled.
    # No shell=True. Bare trailing nosemgrep (the working suppression
    # pattern in this codebase — semgrep wants it on the matched line).
    _restore_cmd = [
        PG_RESTORE_BIN, "--clean", "--if-exists", "--no-owner",
        "--no-privileges", "--dbname", scratch_url, str(dump_path),
    ]
    # PG_RESTORE_BIN: trusted fixed env path from the workflow YAML,
    # hardcoded "pg_restore" fallback, no shell=True. Bare nosemgrep —
    # `nosemgrep: <text>` would be parsed as a rule-id list.
    proc = subprocess.run(  # noqa: S603
        _restore_cmd,  # nosemgrep
        capture_output=True, text=True, check=False,
    )
    elapsed = (datetime.datetime.now(datetime.UTC) - started).total_seconds()
    if proc.returncode != 0:
        # pg_restore returns 1 even on warnings. Fail only if there are
        # ERROR-level lines (other than the harmless ones).
        errors = [
            line for line in (proc.stderr or "").splitlines()
            if line.startswith("pg_restore: error:")
            and "does not exist" not in line  # role/grant warnings
        ]
        if errors:
            sys.stderr.write("FATAL: pg_restore reported errors:\n")
            sys.stderr.write("\n".join(errors[:10]) + "\n")
            sys.exit(4)
        sys.stdout.write("[drill] pg_restore exit=1 but only warnings — OK\n")
    sys.stdout.write(f"[drill] restored in {elapsed:.1f}s\n")
    return {"elapsed_sec": elapsed}


def send_drill_email(*, success: bool, live: dict, scratch: dict, error: str | None = None) -> None:
    sg_key = os.environ.get("SENDGRID_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (sg_key and from_addr and to_addr):
        sys.stderr.write("[drill] SendGrid not configured; skipping email\n")
        return
    today = datetime.date.today().isoformat()
    if success:
        subject = f"[Taskmanager backup] ✓ Restore drill PASSED — {today}"
        body_lines = [
            f"Monthly restore drill PASSED on {today}.",
            "",
            "Row counts (live vs. scratch):",
            f"  tasks:    live={live.get('tasks')}, scratch={scratch.get('tasks')}",
            f"  goals:    live={live.get('goals')}, scratch={scratch.get('goals')}",
            f"  projects: live={live.get('projects')}, scratch={scratch.get('projects')}",
            f"  Tolerance: ±{int(TOLERANCE * 100)}% (passed)",
            "",
            "The backups remain restorable. Next drill in ~30 days.",
        ]
    else:
        subject = f"[Taskmanager backup] ✗ Restore drill FAILED — {today}"
        body_lines = [
            f"Monthly restore drill FAILED on {today}.",
            "",
            f"Error: {error or '(unknown)'}",
            "",
            "If counts diverge: check whether the dump is missing rows or",
            "the live DB has been backfilled since the dump was taken.",
            "If the decryption failed: rotate BACKUP_FERNET_KEY immediately —",
            "the backup repo is not readable with the current key.",
        ]
    body = "\n".join(body_lines)

    import urllib.error
    import urllib.request

    payload = {
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": from_addr},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {sg_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # URL is the constant SendGrid endpoint, not user input.
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310  # nosemgrep
            sys.stdout.write(f"[drill] email sent: HTTP {resp.status}\n")
    except urllib.error.URLError as e:
        sys.stderr.write(f"[drill] email send failed: {e}\n")


def main() -> int:
    backup_repo = _require_env("BACKUP_REPO_URL")
    fernet_key = _require_env("BACKUP_FERNET_KEY")
    live_url = _require_env("DATABASE_URL")
    scratch_url = _require_env("SCRATCH_DATABASE_URL")

    sys.stdout.write("[drill] starting monthly restore drill\n")
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            repo_dir = tdp / "backups"
            enc_path = fetch_latest_backup(backup_repo, repo_dir)
            dump_path = tdp / "decrypted.dump"
            decrypt(enc_path, fernet_key, dump_path)
            restore(dump_path, scratch_url)

        live = _live_counts(live_url)
        scratch = _scratch_counts(scratch_url)
        sys.stdout.write(f"[drill] live: {live}\n[drill] scratch: {scratch}\n")

        ok = (
            scratch["tasks"] >= 1
            and _within_tolerance(scratch["tasks"], live["tasks"])
            and _within_tolerance(scratch["goals"], live["goals"])
            and _within_tolerance(scratch["projects"], live["projects"])
        )
        if ok:
            send_drill_email(success=True, live=live, scratch=scratch)
            sys.stdout.write("[drill] PASS\n")
            return 0
        send_drill_email(
            success=False, live=live, scratch=scratch,
            error=(
                "Row count mismatch beyond tolerance. "
                f"live={live} scratch={scratch}"
            ),
        )
        sys.stderr.write("FATAL: row count mismatch\n")
        return 5
    except SystemExit:
        send_drill_email(
            success=False, live={}, scratch={},
            error="See GitHub Actions run for FATAL line.",
        )
        raise
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"FATAL: unhandled: {e}\n")
        send_drill_email(success=False, live={}, scratch={}, error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
