"""客户身份的工单接口只出白名单字段，不出内部审计、派单原文和执行器报错；管理端照旧。"""

from __future__ import annotations

import json
import re
import uuid

import pytest

from tests.test_customer_service_api import _make_user

pytest.importorskip("fastapi")

LEAK = "Cursor Agent 失败: Command failed: /Users/a4243342/x; git clone https://github.com/o/r.git"
LEAK_RE = re.compile(r"/Users/|git clone|Cursor Agent|github\.com|bak_t39|Traceback")
INTERNAL_KEYS = {"actor_type", "repair_verified", "resolution", "employee_reports", "team"}
INTERNAL_KEYS |= {"data_correction", "backup_tables", "request", "result", "error"}


def _keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    return {k for v in value for k in _keys(v)} if isinstance(value, list) else set()


def _seed(owner_id: int) -> tuple[int, int]:
    from modstore_server.models import get_session_factory
    from modstore_server.models_cs import (
        CustomerServiceAction as Action,
        CustomerServiceAuditLog as Audit,
        CustomerServiceMessage as Message,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    resolution = {"repair_verified": True, "team": [{"role": "scout", "error": LEAK}]}
    resolution["data_correction"] = {"reason": "备份表 bak_t39_20261018_*"}
    report = {"progress": f"排查未完成：{LEAK}", "team_ok": False, "at": "2026-10-16T04:48:46"}
    evidence = {"resolution": resolution, "employee_reports": [report], "source_ref": "WO-1"}
    with get_session_factory()() as db:
        session = CustomerServiceSession(user_id=owner_id)
        db.add(session)
        db.flush()
        ticket = CustomerServiceTicket(
            user_id=owner_id,
            session_id=session.id,
            ticket_no=f"LEAK-{uuid.uuid4().hex}",
            intent="product_issue",
            status="processing",
            summary="官网更新日志看不到新版本",
            evidence_json=json.dumps(evidence, ensure_ascii=False),
        )
        db.add(ticket)
        db.flush()
        ids = {"ticket_id": ticket.id, "session_id": session.id}
        db.add(
            Action(
                **{"ticket_id": ticket.id, "user_id": owner_id, "status": "failed"},
                action_type="employee.dispatch",
                result_json=json.dumps({"progress": LEAK}),
                error=LEAK,
                idempotency_key=uuid.uuid4().hex,
            )
        )
        detail = {"progress": LEAK, "backup_tables": ["bak_t39_20261018_ticket"]}
        db.add(Audit(**ids, actor_type="ai", event_type="x", detail_json=json.dumps(detail)))
        payload = {"ticket": {"evidence": evidence}, "employee_progress": {"progress": LEAK}}
        for role, content in (("user", "还是看不到 1.0.0.6"), ("assistant", f"进展：{LEAK}")):
            db.add(
                Message(
                    **ids,
                    user_id=owner_id,
                    role=role,
                    content=content,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            )
        db.commit()
        return ticket.id, session.id


def test_customer_views_hide_internal_fields_admin_keeps_everything(client):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    owner, admin = _make_user("leak_owner"), _make_user("leak_admin", admin=True)
    tid, sid = _seed(owner.id)
    base = "/api/customer-service"
    try:
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: owner
        bodies = [
            client.get(f"{base}/{path}").json()
            for path in (
                f"tickets/{tid}",
                "tickets",
                f"sessions/{sid}",
                "issues/mine",
                f"actions?ticket_id={tid}",
            )
        ]
        for body in bodies:
            text = json.dumps(body, ensure_ascii=False)
            assert not LEAK_RE.search(text), text
            assert not _keys(body) & INTERNAL_KEYS, _keys(body) & INTERNAL_KEYS
        detail, _, session, mine, _ = bodies
        assert detail["audit_logs"] == [] and detail["ticket"]["evidence"] == {"source_ref": "WO-1"}
        assert detail["actions"] == [{"id": detail["actions"][0]["id"], **_dispatch(detail)}]
        assert detail["ticket"]["progress"][0]["text"].startswith("处理过程中遇到内部问题")
        assert session["messages"][0]["content"] == "还是看不到 1.0.0.6"
        assert mine["items"][0]["latest_result"]["progress"]

        app.dependency_overrides[customer_service_api._get_current_user] = lambda: admin
        full = client.get(f"{base}/tickets/{tid}").json()
        assert full["audit_logs"][0]["actor_type"] == "ai"
        assert full["actions"][0]["error"] == LEAK and full["actions"][0]["status"] == "failed"
        assert full["ticket"]["evidence"]["resolution"]["repair_verified"] is True
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def _dispatch(detail):
    return {"action_type": "employee.dispatch", "created_at": detail["actions"][0]["created_at"]}
