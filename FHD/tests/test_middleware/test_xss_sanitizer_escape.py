"""The production middleware stack must preserve business request bytes."""

from __future__ import annotations

import json

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


@pytest.fixture
def fidelity_client(monkeypatch):
    from app import fastapi_routes
    from app.fastapi_app import factory

    # Exercise the production middleware wiring without unrelated business
    # routers, Mod bootstrap or background schedulers for this boundary test.
    monkeypatch.setenv("XCAGI_DESKTOP_FAST_START", "1")
    monkeypatch.setattr(factory, "_app_singleton", None)
    monkeypatch.setattr(fastapi_routes, "register_bootstrap_routes", lambda _app: None)
    app = factory.create_fastapi_app()

    async def echo(request: Request):
        return {"body_hex": (await request.body()).hex()}

    async def parsed(payload: dict):
        return payload

    # Insert the observation routes before the production SPA catch-all.
    routes = [
        APIRoute("/api/_input_fidelity/raw", echo, methods=["POST", "PUT", "PATCH"]),
        APIRoute("/api/_input_fidelity/json", parsed, methods=["POST"]),
    ]
    monkeypatch.setattr(app.router, "routes", routes + app.router.routes)
    # The HTTP boundary needs no background schedulers or startup jobs.
    client = TestClient(app)
    client.cookies.set("csrf_token", "input-fidelity-test")
    client.headers["x-csrf-token"] = "input-fidelity-test"
    try:
        yield client
    finally:
        client.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("content_type", ["application/json", "application/problem+json"])
def test_original_json_bytes_reach_handler(fidelity_client, method, content_type):
    body = b' { "remark": "synthetic<A&B>", "amount": 1.2300, "escaped": "\\u4e2d" }\n'
    response = fidelity_client.request(
        method,
        "/api/_input_fidelity/raw",
        content=body,
        headers={"Content-Type": content_type},
    )
    assert response.status_code == 200, response.text
    assert bytes.fromhex(response.json()["body_hex"]) == body
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in response.headers["content-security-policy"]


def test_nested_business_strings_and_keys_round_trip(fidelity_client):
    payload = {
        "remark": "synthetic<A&B>",
        "password_shape": "test-only<&>\"'",
        "prompt": "if x < 3 and y > 0:\n    print('A&B')",
        "nested": [{"label<&>": "中<&>"}, "&lt;already-text&gt;", None, 10, True],
    }
    response = fidelity_client.post("/api/_input_fidelity/json", json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == payload


@pytest.mark.parametrize("body", [b"{not json", b'"bad\xff"', b"", b"not json"])
def test_raw_body_is_unchanged_even_when_not_json(fidelity_client, body):
    response = fidelity_client.post(
        "/api/_input_fidelity/raw",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert bytes.fromhex(response.json()["body_hex"]) == body


def test_json_validation_and_csrf_remain_enforced(fidelity_client):
    response = fidelity_client.post(
        "/api/_input_fidelity/json",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    del fidelity_client.headers["x-csrf-token"]
    response = fidelity_client.post("/api/_input_fidelity/json", json={"remark": "A&B"})
    assert response.status_code == 403


def test_unicode_and_whitespace_reach_handler_unchanged(fidelity_client):
    body = b" " * 1024 + json.dumps({"remark": "中<&>"}, ensure_ascii=False).encode()
    response = fidelity_client.post(
        "/api/_input_fidelity/raw",
        content=iter([body[:1024], body[1024:]]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert bytes.fromhex(response.json()["body_hex"]) == body
