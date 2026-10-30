"""#522: Help → Connect Claude (claude.ai MCP connector).

User-facing setup copy, held to the code: the commands it names exist,
the address is the real route, and it says what the token can't do.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _page(authed_client) -> str:
    return authed_client.get("/docs").get_data(as_text=True)


def _section(authed_client) -> str:
    page = _page(authed_client)
    start = page.index('<section id="claude-connector"')
    return page[start : page.index("</section>", start)]


def test_listed_in_contents(authed_client):
    page = _page(authed_client)
    assert 'href="#claude-connector"' in page
    assert page.count('id="claude-connector"') == 1


def test_connector_settings_match_the_server(authed_client, app):
    section = _section(authed_client)
    assert "https://web-production-3e3ae.up.railway.app/mcp" in section
    assert "No sign-in" in section
    assert "<code>authorization</code>" in section
    assert "Bearer " in section
    assert "/mcp" in {r.rule for r in app.url_map.iter_rules()}


def test_commands_it_names_exist(authed_client, app):
    section = _section(authed_client)
    assert "scripts/mint_mcp_token.py" in section
    assert (ROOT / "scripts" / "mint_mcp_token.py").is_file()
    assert "revoke-mcp-token" in section
    assert "revoke-mcp-token" in app.cli.list_commands(app.app_context())


def test_says_what_it_cannot_do(authed_client):
    section = _section(authed_client)
    assert "cannot delete" in section
    assert "365 days" in section


def test_revoke_command_runs_the_apps_python(authed_client):
    """Over `railway ssh` the container's plain `python` has no Flask
    (found revoking a token in prod, 2026-10-30); the app's lives in
    /opt/venv."""
    section = _section(authed_client)
    assert "cd /app &amp;&amp; /opt/venv/bin/python -m flask revoke-mcp-token" in section
    assert "railway ssh keys add" in section


def test_token_is_copied_right_before_pasting(authed_client):
    """Copying the URL replaced a clipboard token, so every request got 401.
    The token waits in a private file and the full header value is copied
    at the moment it is pasted."""
    section = _section(authed_client)
    assert "umask 077" in section
    assert "~/.taskmanager-mcp-token" in section
    assert "printf &#39;Bearer %s&#39;" in section or "printf 'Bearer %s'" in section
    assert "rm ~/.taskmanager-mcp-token" in section
