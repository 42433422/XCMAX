"""获客表单到内部客服 pipeline 的闭环回归测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.user_cs_landing_crm import apply_landing_submission_to_funnel
from app.services.user_cs_pipeline import load_pipeline, save_pipeline

FHD_ROOT = Path(__file__).resolve().parents[2]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_landing_submission_preserves_intake_fields_and_finalizes(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    doc = apply_landing_submission_to_funnel(
        {
            "market_user_id": 9101,
            "landing_contact_id": 7788,
            "audit_code": "XC-007788",
            "name": "张三",
            "email": "lead@example.com",
            "phone": "13800000000",
            "company": "成都路演客户有限公司",
            "message": "想演示获客工单闭环",
            "desktop_os": "mac",
            "need_mobile": True,
            "submitted_at": "2026-07-27T12:00:00+00:00",
            "intake_source": "offline_event",
            "campaign": "brand_acquisition_2026",
            "medium": "qr",
            "content": "event_offline",
            "privacy_agreed": True,
            "privacy_version": "2026-06-20",
            "privacy_url": "/privacy.html",
            "privacy_agreed_at": "2026-07-27T12:00:00+00:00",
        },
        notify_wechat=False,
    )

    saved = load_pipeline(9101)
    assert doc["stage"] == "intake_done"
    assert saved["stage"] == "intake_done"
    assert saved["intake_form"]["company"] == "成都路演客户有限公司"
    assert saved["intake_form"]["campaign"] == "brand_acquisition_2026"
    assert saved["intake_form"]["medium"] == "qr"
    assert saved["intake_form"]["content"] == "event_offline"
    assert saved["intake_form"]["privacy_agreed"] is True
    assert saved["intake_form"]["privacy_version"] == "2026-06-20"
    assert saved["intake_form"]["privacy_url"] == "/privacy.html"
    assert saved["intake_form"]["privacy_agreed_at"] == "2026-07-27T12:00:00+00:00"
    assert saved["intake_form"]["audit_code"] == "XC-007788"
    assert saved["intake_submitted_at"] == "2026-07-27T12:00:00+00:00"
    assert saved["landing_contact_id"] == 7788
    assert saved["crm_opportunity_id"] == 9101
    assert saved["crm_funnel_synced_at"]


def test_user_customer_service_employee_supports_acquisition_actions():
    module = _load_module(
        FHD_ROOT
        / "mods"
        / "_employees"
        / "user-customer-service-officer"
        / "backend"
        / "employees"
        / "user_customer_service_officer.py",
        "user_customer_service_officer_test",
    )

    status = module.run({"action": "status"}, {})
    assert status["ok"] is True
    assert status["status"] == "ready"

    demand = module.run(
        {
            "action": "demand_intake",
            "brief": "客户想把 Excel、微信跟进和结果回执串起来。",
            "client_name": "王总",
            "form_url": "https://xiu-ci.com/contact.html?market_user_id=9102",
            "channel": "wechat",
        },
        {},
    )
    assert demand["ok"] is True
    assert demand["items"][0]["form_url"].endswith("market_user_id=9102")
    assert "未发送客户消息" in demand["summary"]

    ticket = module.run(
        {
            "ticket": {
                "id": "T-1",
                "issue": "客户询问安装包",
                "knowledge_sources": ["release-note"],
                "severity": "normal",
            }
        },
        {},
    )
    assert ticket["ok"] is True
    assert ticket["status"] == "approved"


def _bridge_client(module_name: str):
    module = _load_module(
        FHD_ROOT / "mods" / "xcagi-customer-service-bridge" / "backend" / "blueprints.py",
        module_name,
    )
    app = FastAPI()
    module.register_fastapi_routes(app, "xcagi-customer-service-bridge")
    return module, TestClient(app)


def test_demand_intake_failure_does_not_mark_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    uid = 9201
    doc = load_pipeline(uid)
    doc["stage"] = "intake_done"
    save_pipeline(doc)
    module, client = _bridge_client("user_cs_bridge_failure_test")

    async def fake_employee(_: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "data": {"ok": False, "error": "missing_ticket"}}

    monkeypatch.setattr(module, "_run_user_cs_employee", fake_employee)
    res = client.post(
        "/api/mod/xcagi-customer-service-bridge/user-cs/demand-intake",
        json={
            "brief": "路演获客测试",
            "client_name": "测试客户",
            "form_url": "https://xiu-ci.com",
            "market_user_id": uid,
        },
    )

    body = res.json()
    saved = load_pipeline(uid)
    assert body["success"] is False
    assert body["data"]["ok"] is False
    assert saved["intake_sent"] is False
    assert saved["stage"] == "intake_done"


def test_demand_intake_success_marks_sent_without_stage_regression(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    uid = 9202
    doc = load_pipeline(uid)
    doc["stage"] = "intake_done"
    save_pipeline(doc)
    module, client = _bridge_client("user_cs_bridge_success_test")

    async def fake_employee(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "data": {
                "ok": True,
                "items": [
                    {
                        "message_text": f"请填写 {payload['form_url']}",
                        "form_url": payload["form_url"],
                    }
                ],
            },
        }

    monkeypatch.setattr(module, "_run_user_cs_employee", fake_employee)
    res = client.post(
        "/api/mod/xcagi-customer-service-bridge/user-cs/demand-intake",
        json={
            "brief": "路演获客测试",
            "client_name": "测试客户",
            "form_url": "https://xiu-ci.com",
            "market_user_id": uid,
        },
    )

    body = res.json()
    saved = load_pipeline(uid)
    assert body["success"] is True
    assert body["data"]["form_url"].startswith("https://xiu-ci.com/contact.html?")
    assert "market_user_id=9202" in body["data"]["form_url"]
    assert saved["intake_sent"] is True
    assert saved["stage"] == "intake_done"
