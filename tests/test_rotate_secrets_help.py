"""#518: Help → Rotate every secret (after a leak).

The section is a checklist, so the tests hold it to the code: every secret
the app or the backup workflows read is on it, what it says the app doesn't
use really isn't used, and the commands it gives to make keys really make
working keys.
"""
from __future__ import annotations

import html
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET_NAME = re.compile(r'"([A-Z][A-Z0-9_]*(?:_KEY|_SECRET|_TOKEN|_PASSWORD))"')


def _section(authed_client) -> str:
    page = authed_client.get("/docs").get_data(as_text=True)
    start = page.index('<section id="rotate-secrets"')
    return page[start:page.index("</section>", start)]


def _copy_value(section: str, field: str) -> str:
    m = re.search(rf'id="{field}"[^>]*value="([^"]*)"', section)
    assert m, field
    return html.unescape(m.group(1))


def _app_sources() -> list[pathlib.Path]:
    return sorted(ROOT.glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))


def _secrets_the_code_reads() -> set[str]:
    names: set[str] = set()
    for path in _app_sources():
        names |= set(SECRET_NAME.findall(path.read_text(encoding="utf-8")))
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        names |= set(re.findall(r"secrets\.([A-Z_]+)", wf.read_text(encoding="utf-8")))
    names.discard("GITHUB_TOKEN")  # GitHub's own, made fresh for every run
    return names


class TestSection:
    def test_listed_and_linked(self, authed_client):
        page = authed_client.get("/docs").get_data(as_text=True)
        assert 'href="#rotate-secrets"' in page
        assert page.count('id="rotate-secrets"') == 1
        # The Backups section's own key-rotation note points here.
        backups = page[page.index('id="backups"'):page.index('id="rotate-secrets"')]
        assert 'href="#rotate-secrets"' in backups

    def test_steps_numbered_in_order(self, authed_client):
        nums = re.findall(r'<span class="docs-step-num">(\d+)</span>', _section(authed_client))
        assert nums == [str(n) for n in range(1, 20)]

    def test_claude_connector_token_step(self, authed_client):
        # #522: a new SECRET_KEY kills the MCP token too; the last step
        # makes a new one and points at the connector section.
        section = _section(authed_client)
        last = section[section.index('docs-step-num">19<'):]
        assert "Claude" in last
        assert 'href="#claude-connector"' in last

    def test_every_secret_the_code_reads_is_covered(self, authed_client):
        # A new secret in the code (or a workflow) must get a step here.
        section = _section(authed_client)
        names = _secrets_the_code_reads()
        assert {"SECRET_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL"} <= names  # the scan works
        missing = sorted(n for n in names if f"<code>{n}</code>" not in section)
        assert missing == []

    def test_every_copy_field_has_a_button(self, authed_client):
        section = _section(authed_client)
        fields = re.findall(r'<input type="text" id="(docsRot\w+)" readonly', section)
        assert len(fields) == len(set(fields)) >= 10
        for f in fields:
            assert f'data-copy-for="{f}"' in section
        assert "docs_copy.js" in authed_client.get("/docs").get_data(as_text=True)

    def test_links_resolve(self, authed_client):
        section = _section(authed_client)
        for path in ("/calendar", "/utilities", "/voice-memo", "/scan", "/settings"):
            assert f'href="{path}"' in section
        assert "${{…}}" in section and "${{Postgres.DATABASE_URL}}" in section


class TestClaims:
    @pytest.mark.parametrize("name", ["BACKUP_FERNET_KEY", "BACKUP_REPO_DEPLOY_KEY"])
    def test_app_never_reads_the_backup_secrets(self, name):
        # Step 2 / 3 say to delete these from Railway: only the GitHub
        # workflow scripts may read them.
        readers = [p.name for p in sorted(ROOT.glob("*.py"))
                   if f'"{name}"' in p.read_text(encoding="utf-8")]
        assert readers == []

    def test_only_the_health_check_encrypts(self):
        # Step 5 says swapping ENCRYPTION_KEY loses nothing: no app module
        # but the health check's self-test calls crypto.encrypt / decrypt.
        users = [p.name for p in sorted(ROOT.glob("*.py"))
                 if p.name != "crypto.py"
                 and re.search(r"from crypto import|import crypto\b",
                               p.read_text(encoding="utf-8"))]
        assert users == ["health.py"]

    def test_scripts_it_names_exist(self, authed_client):
        section = _section(authed_client)
        for field in ("docsRotDbScript", "docsRotMint"):
            script = re.search(r"scripts\\(\w+\.py)", _copy_value(section, field)).group(1)
            assert (ROOT / "scripts" / script).is_file()


def _python_code(command: str) -> str:
    return re.search(r'python -c "([^"]+)"', command).group(1)


class TestCommands:
    def test_session_key_command_makes_a_long_key(self, authed_client):
        code = _python_code(_copy_value(_section(authed_client), "docsRotSecretKey"))
        out = subprocess.run(  # noqa: S603 — our interpreter, the page's own code
            [sys.executable, "-c", code], capture_output=True,
            stdin=subprocess.DEVNULL, text=True, check=True,
        ).stdout.strip()
        assert len(out) >= 60 and out.isascii()

    def test_encryption_key_command_makes_a_working_fernet_key(self, authed_client):
        from cryptography.fernet import Fernet

        section = _section(authed_client)
        code = _python_code(_copy_value(section, "docsRotFernet"))
        key = subprocess.run(  # noqa: S603 — our interpreter, the page's own code
            [sys.executable, "-c", code], capture_output=True,
            stdin=subprocess.DEVNULL, text=True, check=True,
        ).stdout.strip()
        f = Fernet(key.encode())
        assert f.decrypt(f.encrypt(b"x")) == b"x"
        # Step 3 uses the same key maker, then sets the secret with it.
        backup = _copy_value(section, "docsRotBackupFernet")
        assert _python_code(backup) == code
        assert "gh secret set BACKUP_FERNET_KEY --body $k" in backup

    def test_gh_commands_always_pass_body(self, authed_client):
        # Every command it hands you to paste; the prose may name the
        # interactive form, to warn against it.
        section = _section(authed_client)
        fields = re.findall(r'<input type="text" id="(docsRot\w+)" readonly', section)
        sets = [v for v in (_copy_value(section, f) for f in fields) if "gh secret set" in v]
        assert len(sets) == 4
        assert all("--body" in s for s in sets)
