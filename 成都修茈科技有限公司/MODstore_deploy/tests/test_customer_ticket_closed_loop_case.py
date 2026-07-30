"""案例验收：官网浅色模式 CS 工单黄金路径闭环。

路径：
  /chat product_issue → enrich publish → intake routing_plan →
  incident_bus 派发 proposed_owner → apply_customer_ticket_incident_progress
"""

from __future__ import annotations

import importlib.util
import types
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EMPLOYEE_ROOT = REPO_ROOT / "FHD" / "mods" / "_employees"


def _make_user(username: str, *, admin: bool = False):
    from modstore_server.models import User, get_session_factory

    username = f"{username}_{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
            is_admin=admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(
            id=user.id, username=user.username, email=user.email, is_admin=user.is_admin
        )


def _load_intake():
    path = EMPLOYEE_ROOT / "intake-dispatcher" / "backend" / "employees" / "intake_dispatcher.py"
    spec = importlib.util.spec_from_file_location("case_intake_dispatcher", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def case_ticket_payload():
    return {
        "subject_id": "CS20260724153100001",
        "ticket_id": 24072401,
        "ticket_no": "CS20260724153100001",
        "title": "官网浅色模式文字看不见",
        "intent": "product_issue",
        "issue_domain": "website",
        "status": "processing",
        "summary": "官网首页浅色模式下正文对比度过低，无法阅读",
        "user_id": 42,
        "session_id": 1001,
        "scope": "website",
        "source": "customer_ticket",
        "raw": {
            "title": "官网浅色模式文字看不见",
            "body": "官网首页浅色模式下正文对比度过低，无法阅读",
            "issue_domain": "website",
            "ticket_no": "CS20260724153100001",
        },
    }


def test_case_a_publish_enrich_then_intake_plan_then_routing_dispatch(
    monkeypatch, case_ticket_payload
):
    from modstore_server import customer_service_api
    from modstore_server.duty_workforce_contracts import (
        enrich_customer_ticket_publish_payload,
    )
    from modstore_server.incident_bus import (
        _dispatch_intake_routing_plan,
        _extract_routing_plan,
    )

    # 1) publish 边界 enrich
    enriched = enrich_customer_ticket_publish_payload(dict(case_ticket_payload))
    assert enriched["requests"][0]["id"].startswith("CS")
    assert enriched["ticket"]["knowledge_sources"]
    assert "对比度" in enriched["requests"][0]["text"]

    published: list[dict] = []

    def _capture_publish(event_type, payload, source="unit", fingerprint=None):
        published.append({"event_type": event_type, "payload": dict(payload), "source": source})
        return True

    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        _capture_publish,
    )
    customer_service_api._publish_customer_ticket_incident(dict(case_ticket_payload))
    assert published and published[0]["event_type"] == "ops.intake.customer_ticket"
    assert published[0]["payload"].get("requests")
    assert published[0]["payload"].get("ticket", {}).get("knowledge_sources")

    # 2) intake live 规划 + side_effects
    intake = _load_intake()
    plan_out = intake.run(
        {
            **published[0]["payload"],
            "event_type": "ops.intake.customer_ticket",
        },
        {},
    )
    assert plan_out["ok"] is True
    assert plan_out["read_only"] is False
    assert plan_out["side_effects"]
    assert plan_out["routing_plan"][0]["proposed_owner"] == "user-customer-service-officer"

    # 3) incident_bus 消费 routing_plan → 真派发 proposed_owner
    executed: list[str] = []

    def _fake_execute(employee_id, brief, input_data=None, user_id=0, **kwargs):
        executed.append(str(employee_id))
        return {
            "employee_id": employee_id,
            "handler_failed": False,
            "result": {"ok": True},
        }

    monkeypatch.setattr(
        "modstore_server.incident_bus.execute_employee_task",
        _fake_execute,
    )
    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.duty_event_execution_input",
        lambda eid, **kw: {
            "event_type": "ops.intake.customer_ticket",
            "requests": enriched["requests"],
            "ticket": enriched.get("ticket"),
        },
    )

    exec_result = {
        "result": {
            "outputs": [
                {
                    "handler": "direct_python",
                    "ok": True,
                    "output": plan_out,
                }
            ]
        }
    }
    assert _extract_routing_plan(exec_result)
    extra = _dispatch_intake_routing_plan(
        exec_result,
        incident_payload=enriched,
        event_type="ops.intake.customer_ticket",
        source="customer-service-api",
        admin_id=1,
        catalog_ids={"user-customer-service-officer", "intake-dispatcher"},
        skip_ids={"intake-dispatcher"},
        brief="[ops.intake.customer_ticket] 官网浅色模式文字看不见",
    )
    assert extra >= 1
    assert "user-customer-service-officer" in executed


def test_case_a_progress_writeback_lifecycle(client, monkeypatch, case_ticket_payload):
    """工单创建后，incident team 结果回写 lifecycle >= 3。"""
    from modstore_server import customer_service_api
    from modstore_server.app import app
    from modstore_server.customer_service_orchestrator import (
        apply_customer_ticket_incident_progress,
        ticket_lifecycle_stage,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import CustomerServiceTicket

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    monkeypatch.setattr(
        customer_service_api,
        "_schedule_customer_ticket_incident",
        lambda payload: None,
    )
    user = _make_user("cs_case_loop")
    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r1 = client.post(
            "/api/customer-service/chat",
            json={"message": case_ticket_payload["summary"], "context": {}},
        )
        assert r1.status_code == 200, r1.text
        sid = r1.json()["session"]["id"]
        r2 = client.post(
            "/api/customer-service/chat",
            json={
                "message": "提交工单",
                "session_id": sid,
                "context": {"reason": case_ticket_payload["summary"]},
            },
        )
        assert r2.status_code == 200, r2.text
        ticket = r2.json().get("ticket") or {}
        ticket_id = int(ticket["id"])
        assert str(ticket.get("ticket_no") or "").startswith("CS")
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)

    sf = get_session_factory()
    with sf() as db:
        out = apply_customer_ticket_incident_progress(
            db,
            ticket_id=ticket_id,
            event_id=20260724,
            team_ok=True,
            team_rows=[
                {
                    "role": "scout",
                    "employee_id": "change-request-auditor",
                    "ok": True,
                    "status": "success",
                },
                {
                    "role": "fix",
                    "employee_id": "vibe-coding-maintainer",
                    "ok": True,
                    "status": "success",
                },
                {
                    "role": "verify",
                    "employee_id": "test-qa-runner",
                    "ok": True,
                    "status": "success",
                },
            ],
            summary_hint=case_ticket_payload["summary"],
        )
        db.commit()
        assert out.get("ok") is True
        assert int(out.get("lifecycle_stage") or 0) >= 3
        row = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.id == ticket_id).first()
        assert row is not None
        assert ticket_lifecycle_stage(row.status, row.decision_status) >= 3
