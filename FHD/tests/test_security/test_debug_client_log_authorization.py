"""Legacy client debug logs must be session-bound and size-limited."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import debug_client_log as debug_route
from app.infrastructure.auth import dependencies as auth_deps
from app.utils.logging import logging_utils


@pytest.fixture
def client_and_log(tmp_path, monkeypatch):
    log_path = tmp_path / "debug_ndjson.log"
    monkeypatch.setattr(logging_utils, "get_debug_log_path", lambda: str(log_path))
    monkeypatch.setattr(auth_deps, "resolve_session_user", lambda _req: None)
    app = FastAPI()
    app.include_router(debug_route.router)
    with TestClient(app) as client:
        yield client, log_path


def _login(monkeypatch, *, active=True):
    monkeypatch.setattr(
        auth_deps,
        "resolve_session_user",
        lambda _req: SimpleNamespace(id=17, is_active=active),
    )


def test_anonymous_and_spoofed_identity_cannot_write(client_and_log):
    client, log_path = client_and_log
    result = client.post(
        "/api/debug/client-log",
        headers={"X-User-ID": "1"},
        json={"message": "untrusted"},
    )
    assert result.status_code == 401
    assert not log_path.exists()


def test_disabled_session_cannot_write(client_and_log, monkeypatch):
    client, log_path = client_and_log
    _login(monkeypatch, active=False)
    assert client.post("/api/debug/client-log", json={"message": "x"}).status_code == 403
    assert not log_path.exists()


def test_valid_session_writes_normalized_log(client_and_log, monkeypatch):
    client, log_path = client_and_log
    _login(monkeypatch)
    result = client.post("/api/debug/client-log", json={"message": "legitimate"})
    assert result.status_code == 200 and result.json()["success"] is True
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["message"] == "legitimate"
    assert record["runId"] == "client"


@pytest.mark.parametrize(
    ("body", "expected_status"),
    [(b"{", 400), (b"[]", 422), (b'"message"', 422)],
)
def test_invalid_json_does_not_append(client_and_log, monkeypatch, body, expected_status):
    client, log_path = client_and_log
    _login(monkeypatch)
    result = client.post(
        "/api/debug/client-log",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert result.status_code == expected_status
    assert not log_path.exists()


def test_oversized_body_does_not_append(client_and_log, monkeypatch):
    client, log_path = client_and_log
    _login(monkeypatch)
    result = client.post(
        "/api/debug/client-log",
        json={"message": "x" * debug_route._MAX_CLIENT_LOG_BYTES},
    )
    assert result.status_code == 413
    assert not log_path.exists()


def test_unknown_length_stream_is_limited(client_and_log, monkeypatch):
    client, log_path = client_and_log
    _login(monkeypatch)

    def chunks():
        yield b'{"message":"'
        yield b"x" * debug_route._MAX_CLIENT_LOG_BYTES
        yield b'"}'

    result = client.post(
        "/api/debug/client-log",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert result.status_code == 413
    assert not log_path.exists()


@pytest.mark.parametrize("padding,expected", [(0, 200), (20_000, 413)])
def test_byte_limit_uses_original_json(client_and_log, monkeypatch, padding, expected):
    client, log_path = client_and_log
    _login(monkeypatch)
    body = b" " * padding + json.dumps({"message": "中" * 3000}, ensure_ascii=False).encode()
    result = client.post(
        "/api/debug/client-log", content=body, headers={"Content-Type": "application/json"}
    )
    assert result.status_code == expected
    assert log_path.exists() is (expected == 200)
