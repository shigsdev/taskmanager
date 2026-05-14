"""Daily encrypted backup of the Postgres DB to a private GitHub repo (#154).

Pipeline:
    pg_dump --format=custom $DATABASE_URL    →   bytes
                ↓
        Fernet.encrypt(bytes, key)             ←   key from env
                ↓
        write timestamped file in BACKUP_REPO  →   git add + commit + push
                ↓
        prune any *.dump.fernet older than 7d  →   commit (retention = 7 daily)
                ↓
        compute row counts (tasks/goals/projects) →   email report

Run via GitHub Actions on cron (.github/workflows/daily-backup.yml).
Required env vars (set as GitHub Actions secrets):
    DATABASE_URL          Railway Postgres URL
    BACKUP_FERNET_KEY     base64 Fernet key (44 chars, ends with '=')
    BACKUP_REPO_DEPLOY_KEY  SSH deploy key with write access to backup repo
    BACKUP_REPO_URL       git@github.com:<user>/taskmanager-backups.git
    SENDGRID_API_KEY      reuse the app's existing key
    DIGEST_FROM_EMAIL     reuse
    DIGEST_TO_EMAIL       reuse — backup status email goes here

Threat model: even if the backup repo is compromised, the Fernet
ciphertext is unreadable without BACKUP_FERNET_KEY. The key never
lives in the repo; it lives in GitHub Actions secrets (encrypted,
masked in logs) and a copy in 1Password for restore-time use.

Exit codes:
    0 — backup succeeded; success email sent
    1 — pg_dump failed
    2 — encryption failed
    3 — git push failed
    4 — email send failed (backup itself was OK)
    Any non-zero exit also tries to send a failure email before exiting.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Pinned to the repository root so subprocess git commands work regardless
# of which directory the workflow CWDs into.
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

RETENTION_DAYS = 7  # locked-in #154.2: last 7 daily only
DUMP_FORMAT = "custom"  # locked-in #154.4: pg_dump custom format

# User-reported 2026-05-13: GitHub-hosted Ubuntu runners ship pg_dump
# 16 by default. Railway's managed Postgres is 18.x — pg_dump refuses
# to dump from a newer server. Workflow installs postgresql-client-18
# from PGDG at /usr/lib/postgresql/18/bin and passes the absolute
# path here via PG_DUMP_BIN — bypasses any $PATH-ordering surprises
# from $GITHUB_PATH prepending logic. Falls back to `pg_dump` on PATH
# for local testing where the default binary is the right version.
PG_DUMP_BIN = os.environ.get("PG_DUMP_BIN", "pg_dump")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.stderr.write(f"FATAL: {name} not set\n")
        sys.exit(1)
    return val


def run_pg_dump(database_url: str, out_path: Path) -> dict:
    """Run pg_dump --format=custom and write to out_path. Returns
    {"size_bytes": N, "elapsed_sec": N}."""
    started = datetime.datetime.now(datetime.UTC)
    sys.stdout.write(f"[backup] pg_dump → {out_path.name} (binary={PG_DUMP_BIN})\n")
    proc = subprocess.run(
        [PG_DUMP_BIN, f"--format={DUMP_FORMAT}", "--file", str(out_path), database_url],
        capture_output=True, text=True, check=False,
    )
    elapsed = (datetime.datetime.now(datetime.UTC) - started).total_seconds()
    if proc.returncode != 0:
        sys.stderr.write(f"FATAL: pg_dump failed (exit {proc.returncode}):\n")
        sys.stderr.write(proc.stderr or "(no stderr)\n")
        sys.exit(1)
    size = out_path.stat().st_size
    sys.stdout.write(f"[backup] dump OK — {size} bytes in {elapsed:.1f}s\n")
    return {"size_bytes": size, "elapsed_sec": elapsed}


def encrypt_in_place(path: Path, key: str) -> Path:
    """Encrypt the file at `path` with Fernet. Returns the new
    .fernet path; deletes the plaintext."""
    from cryptography.fernet import Fernet

    try:
        f = Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception as e:
        sys.stderr.write(f"FATAL: invalid Fernet key: {e}\n")
        sys.exit(2)
    plaintext = path.read_bytes()
    ciphertext = f.encrypt(plaintext)
    enc_path = path.with_suffix(path.suffix + ".fernet")
    enc_path.write_bytes(ciphertext)
    path.unlink()  # remove plaintext immediately
    sys.stdout.write(f"[backup] encrypted → {enc_path.name} ({len(ciphertext)} bytes)\n")
    return enc_path


def _query_row_counts(database_url: str) -> dict:
    """Run a tiny query to get task/goal/project counts. Best-effort —
    failures here don't block the backup; just omitted from email."""
    try:
        import psycopg

        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT "
                "(SELECT count(*) FROM tasks WHERE status='ACTIVE'), "
                "(SELECT count(*) FROM goals), "
                "(SELECT count(*) FROM projects)"
            )
            row = cur.fetchone()
            return {
                "active_tasks": row[0],
                "goals": row[1],
                "projects": row[2],
            }
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[backup] row-count query failed (non-fatal): {e}\n")
        return {}


def push_to_backup_repo(enc_path: Path, repo_url: str) -> str:
    """Clone the backup repo into a temp dir, copy the .fernet file in,
    prune old files older than RETENTION_DAYS, commit + push. Returns
    the commit SHA."""
    with tempfile.TemporaryDirectory() as td:
        repo_dir = Path(td) / "backups"
        sys.stdout.write(f"[backup] cloning {repo_url}\n")
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
            check=True, capture_output=True, text=True,
        )
        # Configure committer so the push doesn't fail.
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.email",
             "backup-bot@taskmanager"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.name",
             "Taskmanager Backup Bot"],
            check=True,
        )
        # Copy the new dump in.
        shutil.copy2(enc_path, repo_dir / enc_path.name)
        # Prune old files (retention).
        cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            days=RETENTION_DAYS
        )
        pruned: list[str] = []
        for p in repo_dir.glob("*.dump.fernet"):
            mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.UTC)
            if mtime < cutoff:
                p.unlink()
                pruned.append(p.name)
        # Commit + push.
        subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True)
        msg_lines = [f"backup: {enc_path.name}"]
        if pruned:
            msg_lines.append(f"pruned {len(pruned)} (>{RETENTION_DAYS}d): "
                             + ", ".join(pruned[:5])
                             + ("…" if len(pruned) > 5 else ""))
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m", "\n\n".join(msg_lines)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0 and "nothing to commit" in (proc.stdout + proc.stderr):
            sys.stdout.write("[backup] no changes to commit (file already exists?)\n")
            return ""
        if proc.returncode != 0:
            sys.stderr.write(f"FATAL: git commit failed:\n{proc.stderr}\n")
            sys.exit(3)
        push = subprocess.run(
            ["git", "-C", str(repo_dir), "push"],
            capture_output=True, text=True, check=False,
        )
        if push.returncode != 0:
            sys.stderr.write(f"FATAL: git push failed:\n{push.stderr}\n")
            sys.exit(3)
        sha = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        sys.stdout.write(f"[backup] pushed {sha[:8]}\n")
        return sha


def send_status_email(
    *,
    success: bool,
    dump_meta: dict,
    counts: dict,
    sha: str,
    error: str | None = None,
) -> None:
    """Send a status email via SendGrid. Reuses the app's existing
    DIGEST_* env vars. Failures here are LOGGED but do NOT change the
    overall exit code (the backup itself was the main job)."""
    sg_key = os.environ.get("SENDGRID_API_KEY")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL")
    to_addr = os.environ.get("DIGEST_TO_EMAIL")
    if not (sg_key and from_addr and to_addr):
        sys.stderr.write("[backup] SendGrid not configured; skipping email\n")
        return

    today = datetime.date.today().isoformat()
    if success:
        subject = f"[Taskmanager backup] ✓ Daily backup OK — {today}"
        size_mb = dump_meta.get("size_bytes", 0) / (1024 * 1024)
        body_lines = [
            f"Daily backup ran successfully on {today}.",
            "",
            f"Dump size:    {size_mb:.2f} MB ({dump_meta.get('size_bytes', 0)} bytes)",
            f"Elapsed:      {dump_meta.get('elapsed_sec', 0):.1f} seconds",
            f"Active tasks: {counts.get('active_tasks', '(unknown)')}",
            f"Goals:        {counts.get('goals', '(unknown)')}",
            f"Projects:     {counts.get('projects', '(unknown)')}",
            f"Commit:       {sha}",
            "",
            "Retention policy: last 7 daily backups kept; older pruned automatically.",
        ]
    else:
        subject = f"[Taskmanager backup] ✗ Daily backup FAILED — {today}"
        body_lines = [
            f"Daily backup FAILED on {today}.",
            "",
            f"Error: {error or '(unknown)'}",
            "",
            "Check the GitHub Actions run for full logs.",
        ]
    body = "\n".join(body_lines)

    # Use the SendGrid v3 mail-send endpoint directly (no SDK). Same
    # pattern as digest_service.
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
            sys.stdout.write(f"[backup] email sent: HTTP {resp.status}\n")
    except urllib.error.URLError as e:
        sys.stderr.write(f"[backup] email send failed: {e}\n")


def main() -> int:
    database_url = _require_env("DATABASE_URL")
    fernet_key = _require_env("BACKUP_FERNET_KEY")
    backup_repo = _require_env("BACKUP_REPO_URL")

    stamp = _now_iso()
    sys.stdout.write(f"[backup] starting {stamp}\n")

    try:
        with tempfile.TemporaryDirectory() as td:
            dump_path = Path(td) / f"taskmanager-{stamp}.dump"
            dump_meta = run_pg_dump(database_url, dump_path)
            counts = _query_row_counts(database_url)
            enc_path = encrypt_in_place(dump_path, fernet_key)
            sha = push_to_backup_repo(enc_path, backup_repo)
        send_status_email(
            success=True, dump_meta=dump_meta, counts=counts, sha=sha,
        )
        return 0
    except SystemExit:
        # Already wrote a FATAL line + chose an exit code.
        send_status_email(
            success=False, dump_meta={}, counts={}, sha="",
            error="See GitHub Actions run for the FATAL line.",
        )
        raise
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"FATAL: unhandled exception: {e}\n")
        send_status_email(
            success=False, dump_meta={}, counts={}, sha="",
            error=f"{type(e).__name__}: {e}",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
