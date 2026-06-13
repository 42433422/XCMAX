"""SLO histogram metrics: login duration + chat stream first-byte."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.fastapi_app import create_fastapi_app


@pytest.fixture
def client(monkeypatch):
    from tests.fixtures.app_factory import get_test_fastapi_app, prime_test_env

    prime_test_env(sqlite_url="sqlite:///:memory:")
    monkeypatch.setattr("app.db.init_db.ensure_runtime_auth_bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.db.init_db.ensure_sqlite_per_mod_database_copies", lambda *a, **k: None
    )
    app = get_test_fastapi_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _metrics_text(client: TestClient) -> str:
    r = client.get("/metrics")
    assert r.status_code == 200
    return r.text


def test_auth_login_duration_histogram_after_invalid_login(client: TestClient):
    before = _metrics_text(client)
    client.post(
        "/api/auth/login",
        json={"username": "", "password": "", "account_kind": "personal"},
    )
    after = _metrics_text(client)
    assert "auth_login_duration_seconds" in after
    if "auth_login_duration_seconds" not in before:
        assert "auth_login_duration_seconds_count" in after


def test_chat_stream_first_byte_metric_on_stream(client: TestClient):
    async def _fake_stream(request, body, *, ai_tier: str):
        yield b'data: {"type":"token","text":"hi"}\n\n'

    # CI 默认跳过 legacy compat；chat/stream 在该 router 内，测试内按需挂载。
    from app.fastapi_routes.domains.conversation.compat_routes import router as chat_router

    client.app.include_router(chat_router, prefix="/api")

    # chat/stream 非 CSRF 豁免；先 GET 拿 token 再 POST。
    client.get("/api/health")
    csrf = client.cookies.get("csrf_token") or ""

    with patch(
        "app.fastapi_routes.domains.conversation.compat_routes.compat_chat_stream_async",
        new=_fake_stream,
    ):
        with patch(
            "app.fastapi_routes.domains.conversation.compat_routes.assert_p2_elevated_claim_or_raise",
            return_value=None,
        ):
            r = client.post(
                "/api/ai/chat/stream",
                json={"message": "probe"},
                headers={"X-CSRF-Token": csrf},
            )
    assert r.status_code == 200
    text = _metrics_text(client)
    assert "chat_stream_first_byte_seconds" in text
