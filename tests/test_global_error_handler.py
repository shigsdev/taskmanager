"""Tests for the global Flask error handlers (#50, ADR-031).

These verify that ANY exception escaping per-route handlers lands as a
JSON response with a useful (sanitized) message + the request_id, NOT
as Flask's default opaque 500. Without this, bug #52 surfaced as a
"Save failed:" alert with a blank message because the underlying
psycopg `InvalidTextRepresentation` had no JSON shape.
"""
from __future__ import annotations

# --- HTTPException handler --------------------------------------------------


class TestHTTPExceptionHandler:
    """Werkzeug HTTPException covers framework-raised 4xx/5xx (404 for
    unknown routes, 405 for wrong method, 413 for oversize, etc.). The
    handler should preserve the status code and shape the body as JSON
    for /api/ paths only."""

    def test_404_on_api_returns_json(self, client):
        resp = client.get("/api/no-such-endpoint")
        assert resp.status_code == 404
        body = resp.get_json()
        assert body is not None
        assert "error" in body
        assert body.get("status") == 404

    def test_404_on_html_path_keeps_default_html(self, client):
        """HTML paths use Flask's default error page — wrapping every
        HTML 500 in JSON would break the browser experience."""
        resp = client.get("/no-such-page")
        assert resp.status_code == 404
        # Default Flask 404 is HTML; we know it because content-type
        # isn't application/json
        assert "json" not in (resp.content_type or "").lower()


# --- Generic uncaught Exception handler ------------------------------------


class TestUncaughtExceptionHandler:
    """Anything not caught by the per-route handlers (or HTTPException
    handler) lands here. Returns a JSON 500 with sanitized message +
    request_id so the user can correlate with logs."""

    def test_uncaught_runtime_error_returns_json_500(self, app, authed_client):
        """Inject a route that raises RuntimeError, hit it, expect JSON
        with the error message (not opaque 500 HTML)."""
        # Add a transient route that always raises
        @app.route("/api/_test/explode", methods=["GET"])
        def _explode():  # noqa: ARG001
            raise RuntimeError("boom!")

        resp = authed_client.get("/api/_test/explode")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body is not None
        # Sanitized message includes the type + first-line of the error
        assert "boom" in body["error"]
        assert body["type"] == "RuntimeError"
        assert "request_id" in body

    def test_egress_error_returns_502_with_message(self, app, authed_client):
        """EgressError (the wrapper used by all external API calls per
        ADR-023) should map to 502 Bad Gateway and pass the existing
        clean message through unchanged. This is the path that fixes
        the SendGrid case from #47/#50."""
        from egress import EgressError

        @app.route("/api/_test/egress", methods=["GET"])
        def _egress():  # noqa: ARG001
            raise EgressError("SendGrid returned HTTP 403: from address not verified")

        resp = authed_client.get("/api/_test/egress")
        assert resp.status_code == 502
        body = resp.get_json()
        assert body is not None
        # The full EgressError message — vendor + status + detail —
        # should be visible to the user. NO hardcoded misleading message.
        assert "SendGrid" in body["error"]
        assert "403" in body["error"]
        assert "not verified" in body["error"]
        assert body["type"] == "EgressError"

    def test_sqlalchemy_data_error_returns_422(self, app, authed_client):
        """SQLAlchemy DataError (wraps psycopg's InvalidTextRepresentation,
        which is what hit us in #52) should map to 422 with the
        underlying psycopg message — NOT a blank "Save failed:"."""
        from sqlalchemy.exc import DataError

        @app.route("/api/_test/dataerror", methods=["GET"])
        def _data_err():  # noqa: ARG001
            # Simulate the exact #52 failure mode
            class FakeOrig(Exception):
                def __str__(self):
                    return "invalid input value for enum projecttype: \"PERSONAL\""
            raise DataError(
                "INSERT INTO projects ...", {}, FakeOrig(),
            )

        resp = authed_client.get("/api/_test/dataerror")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body is not None
        # The user-facing message must include the actual cause, not a
        # generic "save failed". This is what would have prevented #52
        # from blocking the user with a blank error.
        assert "invalid input value" in body["error"]
        assert "projecttype" in body["error"]
        assert "PERSONAL" in body["error"]

    def test_response_includes_request_id_when_available(self, app, authed_client):
        """Every error response should include the request_id so the
        user can correlate the alert with the matching app_logs row."""
        @app.route("/api/_test/err-with-rid", methods=["GET"])
        def _err():  # noqa: ARG001
            raise ValueError("test")

        resp = authed_client.get("/api/_test/err-with-rid")
        body = resp.get_json()
        assert "request_id" in body
        # request_id field present even if empty (never causes KeyError)
        assert isinstance(body["request_id"], str)


# --- Digest service refactor (raises instead of swallows) ------------------


class TestDigestSendgridErrorPropagation:
    """digest_service.send_digest() previously caught Exception → False,
    killing all SendGrid error context (the user saw the hardcoded
    "check SENDGRID_API_KEY" message regardless). Now it raises
    EgressError with the actual SendGrid status + body, which the
    global handler shapes into a 502 JSON response. ADR-031."""

    def test_sendgrid_exception_raises_egress_error_with_status(self, monkeypatch):
        """When the SendGrid SDK raises (e.g. ForbiddenError), the
        service must wrap it in EgressError and include the HTTP status
        code in the message."""
        from digest_service import _sendgrid_send
        from egress import EgressError

        class _FakeSendGridError(Exception):
            status_code = 403
            body = (
                b'{"errors":[{"message":"'
                b'The from address does not match a verified Sender Identity'
                b'"}]}'
            )

        def _raise_sg_error(*args, **kwargs):
            raise _FakeSendGridError("forbidden")

        monkeypatch.setattr("sendgrid.SendGridAPIClient.send", _raise_sg_error)

        try:
            _sendgrid_send("fake-key", "from@x", "to@x", "Subject", "Body", "<p>Body</p>")
        except EgressError as e:
            msg = str(e)
            assert "SendGrid" in msg
            assert "403" in msg
            # Body should be in the error message — no more "check
            # SENDGRID_API_KEY" hardcoded misdirection
            assert "verified Sender Identity" in msg
        else:
            raise AssertionError("expected EgressError to be raised")

    def test_send_digest_propagates_egress_error(self, app, monkeypatch):
        """send_digest() should NOT catch the EgressError from
        _sendgrid_send any more — it should propagate so the API layer's
        global error handler can shape it. (Previously it caught
        Exception → False, which is exactly the bug.)"""
        from digest_service import send_digest
        from egress import EgressError

        def _raise(*args, **kwargs):
            raise EgressError("SendGrid returned HTTP 403: bad sender")

        monkeypatch.setattr("digest_service._sendgrid_send", _raise)
        monkeypatch.setenv("SENDGRID_API_KEY", "fake-key")

        with app.app_context():
            try:
                send_digest(to_email="user@example.com")
            except EgressError as e:
                assert "SendGrid" in str(e)
                assert "403" in str(e)
            else:
                raise AssertionError("EgressError should have propagated")
