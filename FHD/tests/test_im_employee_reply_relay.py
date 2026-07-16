"""老板 IM 回复 → MODstore 员工闭环回流：共享 relay 客户端 + 桌面/Web 路由接线。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.im.employee_reply_relay import relay_boss_reply_to_employee


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "{}"):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """替身 httpx.Client：记录 post 调用。"""

    calls: list[dict[str, Any]] = []
    next_status: int = 200

    def __init__(self, *args: Any, **kwargs: Any):
        self._init_kwargs = kwargs

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        _FakeClient.calls.append({"url": url, "init": self._init_kwargs, **kwargs})
        return _FakeResponse(status_code=_FakeClient.next_status)


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeClient.calls = []
    _FakeClient.next_status = 200
    yield


def test_relay_posts_answer_to_modstore(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "relay-test-key")
    monkeypatch.setenv("XCAGI_MODSTORE_INTERNAL_URL", "http://127.0.0.1:8765")
    with patch("httpx.Client", _FakeClient):
        ok = relay_boss_reply_to_employee(5, "excel-checker", "按方案 B 来")
    assert ok is True
    assert len(_FakeClient.calls) == 1
    call = _FakeClient.calls[0]
    assert call["url"] == "http://127.0.0.1:8765/api/admin/employee-autonomy/internal/answer-latest"
    assert call["headers"]["X-Internal-Api-Key"] == "relay-test-key"
    assert call["json"] == {"user_id": 5, "employee_id": "excel-checker", "answer": "按方案 B 来"}
    # 内部端点必须绕过本地代理（trust_env=False），否则 dev 机代理会 502
    assert call["init"].get("trust_env") is False


def test_relay_skipped_without_key_or_args(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_CS_INTAKE_LINK_SECRET", raising=False)
    with patch("httpx.Client", _FakeClient):
        assert relay_boss_reply_to_employee(5, "excel-checker", "hi") is False
        monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "k")
        assert relay_boss_reply_to_employee(0, "excel-checker", "hi") is False
        assert relay_boss_reply_to_employee(5, "", "hi") is False
        assert relay_boss_reply_to_employee(5, "excel-checker", "  ") is False
    assert not _FakeClient.calls


def test_relay_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "relay-test-key")
    _FakeClient.next_status = 503
    with patch("httpx.Client", _FakeClient):
        assert relay_boss_reply_to_employee(5, "excel-checker", "hi") is False


# ---------------------------------------------------------------------------
# 桌面/Web 路由接线：/api/im/conversations/{id}/messages 对员工对端触发回流
# ---------------------------------------------------------------------------


@pytest.fixture
def im_client():
    from app.fastapi_routes import im_routes
    from app.infrastructure.auth.dependencies import CurrentUser, get_current_user

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(1)

    mock_db = MagicMock()
    mock_svc = MagicMock()
    mock_svc.send_message.return_value = {
        "message": {"id": 2, "body": "sent"},
        "member_user_ids": [1, 2],
        "updated_at_ms": 123,
    }

    with (
        patch.object(im_routes, "_ensure_schema"),
        patch.object(im_routes, "HostSessionLocal", return_value=mock_db),
        patch.object(im_routes, "ImApplicationService", return_value=mock_svc),
        patch.object(im_routes.im_ws_hub, "send_to_user", new_callable=AsyncMock),
        patch.object(im_routes, "_notify_offline_im_members", new_callable=AsyncMock),
    ):
        yield TestClient(app), mock_svc


def test_desktop_send_to_employee_triggers_relay(im_client):
    client, mock_svc = im_client
    mock_svc.employee_id_for_conversation.return_value = "excel-checker"
    with patch("app.infrastructure.im.employee_reply_relay.relay_boss_reply_to_employee") as relay:
        resp = client.post("/api/im/conversations/10/messages", json={"body": "盘点一下库存"})
    assert resp.status_code == 200 and resp.json()["success"] is True
    relay.assert_called_once_with(1, "excel-checker", "盘点一下库存")


def test_desktop_send_to_human_peer_skips_relay(im_client):
    client, mock_svc = im_client
    mock_svc.employee_id_for_conversation.return_value = None
    with patch("app.infrastructure.im.employee_reply_relay.relay_boss_reply_to_employee") as relay:
        resp = client.post("/api/im/conversations/10/messages", json={"body": "中午吃什么"})
    assert resp.status_code == 200
    relay.assert_not_called()
