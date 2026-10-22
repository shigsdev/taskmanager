"""#519: what the app says about backups matches the backup scripts.

The backup and drill email through Brevo (#298) and keep every backup
(#511), but Help -> Backups still told you to add SENDGRID_API_KEY, quoted
a subject the script never sends, and /utilities said the workflow prunes
anything older than 7 days. The subjects are read from the scripts, so a
reworded subject fails here until the Help follows.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _subject(script: str, mark: str) -> str:
    """The fixed part of a subject the script sends, e.g.
    '[Taskmanager backup] ✓ Daily backup OK'."""
    src = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    pattern = (r'subject = f"(\[Taskmanager backup\] ' + re.escape(mark)
               + r'[^"{]*?) — \{today\}"')
    m = re.search(pattern, src)
    assert m, (script, mark)
    return m.group(1)


def _page(client, path: str) -> str:
    r = client.get(path)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _backups_section(client) -> str:
    page = _page(client, "/docs")
    start = page.index('<section id="backups"')
    return page[start:page.index("</section>", start)]


class TestHelpBackups:
    def test_no_sendgrid_left(self, authed_client):
        section = _backups_section(authed_client)
        assert "sendgrid" not in section.lower()
        assert "<code>BREVO_API_KEY</code>" in section

    def test_quotes_the_subjects_the_scripts_send(self, authed_client):
        section = _backups_section(authed_client)
        backup_ok = _subject("backup_to_github.py", "✓")
        assert backup_ok == "[Taskmanager backup] ✓ Daily backup OK"
        assert backup_ok in section

    def test_quotes_the_log_lines_the_script_prints(self, authed_client):
        section = _backups_section(authed_client)
        src = (ROOT / "scripts" / "backup_to_github.py").read_text(encoding="utf-8")
        for line in ("[backup] email sent: HTTP ", "[backup] email send failed: ",
                     "[backup] Brevo not configured; skipping email"):
            assert line in src
            assert line.strip() in section

    def test_rotation_step_names_both_success_subjects(self, authed_client):
        page = _page(authed_client, "/docs")
        start = page.index('<section id="rotate-secrets"')
        rotate = page[start:page.index("</section>", start)]
        for script in ("backup_to_github.py", "restore_drill.py"):
            assert _subject(script, "✓").removeprefix("[Taskmanager backup] ") in rotate


class TestOtherPages:
    def test_utilities_backup_card_keeps_every_backup(self, authed_client):
        page = _page(authed_client, "/utilities")
        assert "older than 7 days" not in page
        assert "nothing is pruned" in page

    def test_architecture_names_brevo_not_sendgrid(self, authed_client):
        page = _page(authed_client, "/architecture")
        assert "SENDGRID_API_KEY" not in page
