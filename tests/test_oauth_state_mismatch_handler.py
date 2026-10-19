"""PR58 #121: OAuth MismatchingStateError → graceful redirect, not 500.

Background: Flask-Dance raises MismatchingStateError when the OAuth
callback's `state` doesn't match the session-stored state. Common
causes documented in errors.py.

Before PR58 the user got an "Internal Server Error" page with no
recovery path. Now they get a redirect to /login + a message there so
the next click re-runs OAuth cleanly.

#507: these ran on a stub app whose page was named ``login``. The real
page is ``login_page``, so ``url_for("login")`` always failed and only
the literal fallback worked — and nothing rendered the message. Every
test now drives the REAL callback (``/login/google/authorized``) on the
real app: oauthlib refuses the mismatched state before any network call.
"""
from __future__ import annotations

import logging

import pytest

CALLBACK = "/login/google/authorized?code=abc&state=from-another-attempt"
MESSAGE = "That sign-in didn&#39;t finish. Please sign in again."


@pytest.fixture
def mismatched_client(client):
    """A client whose session holds a DIFFERENT OAuth state than the one
    the callback carries — what a second tab, a cleared cookie or an
    old bookmark leaves behind."""
    with client.session_transaction() as sess:
        sess["google_oauth_state"] = "the-state-this-browser-started"
    return client


def test_oauth_state_mismatch_redirects_to_login_not_500(mismatched_client):
    resp = mismatched_client.get(CALLBACK)
    # Was 500, now 302 → /login. (302 because handler uses redirect().)
    assert resp.status_code == 302, (
        f"expected 302 redirect to /login, got {resp.status_code}"
    )
    assert resp.headers["Location"].endswith("/login")


def test_redirect_is_built_from_the_real_page_name(mismatched_client, monkeypatch):
    """The handler must find /login by its real endpoint, not lean on
    the literal fallback: break the fallback and it still lands there."""
    import flask

    calls = []
    original = flask.url_for

    def spy(endpoint, **kw):
        calls.append(endpoint)
        return original(endpoint, **kw)

    monkeypatch.setattr(flask, "url_for", spy)
    resp = mismatched_client.get(CALLBACK)
    assert resp.status_code == 302
    assert "login_page" in calls
    assert "login" not in calls


def test_login_page_says_why_after_the_redirect(mismatched_client):
    resp = mismatched_client.get(CALLBACK, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert MESSAGE in body
    assert 'role="alert"' in body


def test_message_shows_once(mismatched_client):
    mismatched_client.get(CALLBACK, follow_redirects=True)
    again = mismatched_client.get("/login").get_data(as_text=True)
    assert MESSAGE not in again


def test_plain_login_page_has_no_message(client):
    """The quiet case: an ordinary visit to /login shows no alert."""
    body = client.get("/login").get_data(as_text=True)
    assert MESSAGE not in body
    assert 'role="alert"' not in body


def test_oauth_state_mismatch_does_not_leak_traceback(mismatched_client):
    """Defense-in-depth: neither the redirect nor the page it lands on
    may contain the raw exception or traceback."""
    for resp in (
        mismatched_client.get(CALLBACK),
        mismatched_client.get("/login"),
    ):
        body = resp.get_data(as_text=True)
        assert "MismatchingStateError" not in body
        assert "Traceback" not in body
        assert "oauthlib" not in body


def test_mismatch_is_logged_as_a_warning_not_an_error(mismatched_client, caplog):
    """A stale sign-in is the user's browser, not an app fault: it must
    not raise an ERROR row (validate_deploy's log scan would call that
    deploy RED)."""
    with caplog.at_level(logging.WARNING, logger="errors"):
        mismatched_client.get(CALLBACK)
    rows = [r for r in caplog.records if r.name == "errors"]
    assert any("state mismatch" in r.getMessage() for r in rows)
    assert all(r.levelno < logging.ERROR for r in rows)
