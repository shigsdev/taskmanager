"""#204 option E: /healthz answers the off-Railway status page's browser.

The status page (status/, GitHub Pages) fetches /healthz cross-origin, so
the response must carry ``Access-Control-Allow-Origin`` for exactly that
origin -- on a 503 too, since "down" is the answer the page most needs to
read. Any other origin gets no CORS header (the browser then refuses to
hand the body to that page). /healthz was already public; this only lets
one more page read it.
"""
from __future__ import annotations

import pytest

STATUS_ORIGIN = "https://shigsdev.github.io"


def test_status_page_origin_is_allowed(client):
    resp = client.get("/healthz", headers={"Origin": STATUS_ORIGIN})
    assert resp.headers.get("Access-Control-Allow-Origin") == STATUS_ORIGIN
    assert "Origin" in resp.headers.get("Vary", "")
    assert "git_sha" in resp.get_json()


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "https://shigsdev.github.io.evil.example",
    "http://shigsdev.github.io",
    "null",
])
def test_other_origins_get_no_cors_header(client, origin):
    resp = client.get("/healthz", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" not in resp.headers


def test_no_origin_is_unchanged(client):
    resp = client.get("/healthz")
    assert "Access-Control-Allow-Origin" not in resp.headers
    assert resp.status_code in (200, 503)


def test_a_503_still_carries_the_header(client, monkeypatch):
    import health

    def failing(app, db):
        return {"status": "fail", "critical_failed": ["database"], "git_sha": "dev",
                "started_at": None, "digest_scheduled_at": None,
                "checks": {"database": "fail: down"}}

    monkeypatch.setattr(health, "run_health_checks", failing)
    resp = client.get("/healthz", headers={"Origin": STATUS_ORIGIN})
    assert resp.status_code == 503
    assert resp.headers.get("Access-Control-Allow-Origin") == STATUS_ORIGIN
