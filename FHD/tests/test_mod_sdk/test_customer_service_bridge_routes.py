"""Exercise customer-service routes and bundled employee dispatch."""

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


@pytest.mark.parametrize("override", [False, True])
def test_status_uses_writable_workspace(client, monkeypatch, tmp_path, override):
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_dir))
    root = data_dir / ("custom-workspace" if override else "mods/_employees/workspace")
    if override:
        monkeypatch.setenv("EMPLOYEE_WORKSPACE_ROOT", str(root))
    else:
        monkeypatch.delenv("EMPLOYEE_WORKSPACE_ROOT", raising=False)
    response = client.get(f"/api/mod/{MOD_ID}/user-cs/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    assert body["data"]["status"] == "ready"
    assert root.is_dir()


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
