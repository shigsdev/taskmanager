"""Unit tests for the ``validate_json_body`` decorator (#196, PR15).

The decorator centralizes the strict JSON-object-body check that 27
API route handlers previously open-coded:

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

These tests exercise the decorator directly via a throwaway Flask
route — a dict body passes through and is readable on ``g.json_body``;
any non-dict body (list, string, None, missing) short-circuits with a
400 ``{"error": "JSON body required"}``.
"""
from __future__ import annotations

import json

import pytest
from flask import Flask, g, jsonify

from utils import validate_json_body


@pytest.fixture
def decorated_app():
    """A minimal Flask app with one route guarded by the decorator.

    The route echoes back whatever the decorator stashed on ``g`` so a
    test can assert the parsed body survived the wrapper untouched.
    """
    app = Flask(__name__)

    @app.post("/echo")
    @validate_json_body
    def echo():
        # The decorator guarantees g.json_body is a dict here.
        return jsonify({"received": g.json_body}), 200

    return app


# --- happy path --------------------------------------------------------------


def test_dict_body_passes_through_to_g(decorated_app):
    """A JSON object body reaches the route via ``g.json_body``."""
    client = decorated_app.test_client()
    resp = client.post("/echo", json={"name": "value", "n": 1})
    assert resp.status_code == 200
    assert resp.get_json() == {"received": {"name": "value", "n": 1}}


def test_empty_dict_body_is_allowed(decorated_app):
    """An empty ``{}`` is still a dict — the decorator must allow it.

    The decorator only rejects *non-objects*; field-level "this key is
    required" checks stay in the route body.
    """
    client = decorated_app.test_client()
    resp = client.post("/echo", json={})
    assert resp.status_code == 200
    assert resp.get_json() == {"received": {}}


def test_g_json_body_set_inside_request_context(decorated_app):
    """Drive the wrapped callable directly inside a request context.

    Confirms the decorator stashes the parsed dict on ``flask.g`` (not
    just that the route happens to read it).
    """
    with decorated_app.test_request_context(
        "/echo",
        method="POST",
        data=json.dumps({"k": "v"}),
        content_type="application/json",
    ):
        # g.json_body is unset until the wrapper runs.
        assert "json_body" not in g
        resp = decorated_app.view_functions["echo"]()
        assert g.json_body == {"k": "v"}
        body, status = resp
        assert status == 200
        assert body.get_json() == {"received": {"k": "v"}}


# --- rejection path ----------------------------------------------------------


def test_missing_body_returns_400(decorated_app):
    """No body at all → 400 with the standard error shape."""
    client = decorated_app.test_client()
    resp = client.post("/echo")
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


def test_json_list_body_returns_400(decorated_app):
    """A JSON array is valid JSON but not an object → 400."""
    client = decorated_app.test_client()
    resp = client.post("/echo", json=[1, 2, 3])
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


def test_json_string_body_returns_400(decorated_app):
    """A bare JSON string is valid JSON but not an object → 400."""
    client = decorated_app.test_client()
    resp = client.post("/echo", json="just a string")
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


def test_json_null_body_returns_400(decorated_app):
    """A literal JSON ``null`` parses to ``None`` → 400."""
    client = decorated_app.test_client()
    resp = client.post(
        "/echo", data="null", content_type="application/json"
    )
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


def test_malformed_json_returns_400(decorated_app):
    """Unparseable bytes — ``get_json(silent=True)`` yields None → 400."""
    client = decorated_app.test_client()
    resp = client.post(
        "/echo", data="{not valid json", content_type="application/json"
    )
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


def test_non_json_content_type_returns_400(decorated_app):
    """Plain-text body — silent parse fails → 400, not a 500."""
    client = decorated_app.test_client()
    resp = client.post(
        "/echo", data="plain text", content_type="text/plain"
    )
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "JSON body required"}


# --- decorator mechanics -----------------------------------------------------


def test_preserves_wrapped_function_metadata():
    """``@wraps`` keeps the original function's name/docstring.

    Flask routes are registered by ``__name__``; losing it would break
    ``url_for`` and any test that patches a view by name.
    """

    @validate_json_body
    def my_route():
        """Original docstring."""
        return "ok"

    assert my_route.__name__ == "my_route"
    assert my_route.__doc__ == "Original docstring."


def test_passes_through_args_and_kwargs(decorated_app):
    """The wrapper forwards positional + keyword args transparently.

    Real routes receive path params (and ``email`` from
    ``@login_required``) as args/kwargs — the wrapper must not swallow
    them.
    """
    captured = {}

    @validate_json_body
    def route_with_params(path_arg, *, kw_arg):
        captured["path_arg"] = path_arg
        captured["kw_arg"] = kw_arg
        captured["body"] = g.json_body
        return "ok"

    with decorated_app.test_request_context(
        "/x",
        method="POST",
        data=json.dumps({"b": 1}),
        content_type="application/json",
    ):
        result = route_with_params("positional", kw_arg="keyword")

    assert result == "ok"
    assert captured == {
        "path_arg": "positional",
        "kw_arg": "keyword",
        "body": {"b": 1},
    }
