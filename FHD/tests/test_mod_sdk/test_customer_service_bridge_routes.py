"""客户服务桥路由回归：微信域退役后不再引用已删除的服务。

``/user-cs/analyze``、``/user-cs/delivery/check-payment``、``/user-cs/wechat/send``
曾调用 39db69615（wechat 域退役）已删除的 ``app.services.wechat_*``；请求时会
``ModuleNotFoundError`` 返回 500（Windows 真机取证里 ch-wechat-* 因此落 BLOCKED）。
本用例挂载真实 Mod 蓝图、用宿主假实现驱动，锁住这些路由可跑通。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

FHD = Path(__file__).resolve().parents[2]
MOD_ID = "xcagi-customer-service-bridge"
MOD_BLUEPRINTS = FHD / "mods" / MOD_ID / "backend" / "blueprints.py"


@pytest.fixture
def client(monkeypatch):
    import app.mod_sdk.host_services as host

    spec = importlib.util.spec_from_file_location("fixture_cs_backend", MOD_BLUEPRINTS)
    assert spec and spec.loader
    backend = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = backend
    spec.loader.exec_module(backend)

    app = FastAPI()
    backend.register_fastapi_routes(app, MOD_ID)

    monkeypatch.setattr(host, "PIPELINE_STAGES", ("idle", "connected", "intake"))
    monkeypatch.setattr(
        host,
        "analyze_customer_pipeline",
        lambda uid, **kwargs: {"market_user_id": uid, "stage": "idle"},
    )
    monkeypatch.setattr(
        host,
        "load_pipeline",
        lambda uid, **kwargs: {"market_user_id": uid, "stage": "idle"},
    )
    monkeypatch.setattr(host, "save_pipeline", lambda doc, **kwargs: doc)
    monkeypatch.setattr(
        host, "ensure_delivery_on_doc", lambda doc, **kwargs: dict(doc, delivery={})
    )
    monkeypatch.setattr(
        host,
        "try_confirm_payment_and_invoice",
        lambda uid, doc, **kwargs: {"payment": None, "invoice": None},
    )

    class _Automation:
        @staticmethod
        def send_wechat_message(contact: str, text: str) -> dict:
            return {"success": True, "message_sent": True, "contact": contact, "text": text}

    monkeypatch.setattr(host, "get_desktop_automation_service", _Automation)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_analyze_route_runs_without_retired_wechat_services(client):
    response = client.post(
        f"/api/mod/{MOD_ID}/user-cs/analyze",
        json={"market_user_id": 7, "username": "u", "has_binding": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["pipeline"]["stage"] == "idle"
    assert body["data"]["message_count"] == 0


def test_check_payment_route_runs_without_retired_wechat_services(client):
    response = client.post(
        f"/api/mod/{MOD_ID}/user-cs/delivery/check-payment",
        json={"market_user_id": 7, "username": "u"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["pipeline"]["market_user_id"] == 7


def test_wechat_send_route_reports_not_sent_without_desktop_automation(client):
    response = client.post(
        f"/api/mod/{MOD_ID}/user-cs/wechat/send",
        json={"market_user_id": 7, "contact_name": "某客户群", "message": "hello"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"]["message_sent"] is True
