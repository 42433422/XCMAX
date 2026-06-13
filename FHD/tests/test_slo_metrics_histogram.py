"""SLO histogram metrics: login duration + chat stream first-byte."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.fastapi_app import create_fastapi_app


@pytest.fixture
def client():
    app = create_fastapi_app()
    with TestClient(app) as c:
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
            )
    assert r.status_code == 200
    text = _metrics_text(client)
    assert "chat_stream_first_byte_seconds" in text
