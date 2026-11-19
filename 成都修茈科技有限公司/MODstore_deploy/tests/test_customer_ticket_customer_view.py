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
INTERNAL_KEYS = {
    "actor_type",
    "repair_verified",
    "resolution",
    "employee_reports",
    "team",
}
INTERNAL_KEYS |= {"data_correction", "backup_tables", "request", "result", "error"}


def _keys(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    return {k for v in value for k in _keys(v)} if isinstance(value, list) else set()


def _seed(owner_id: int) -> tuple[int, int]:
    from modstore_server import models_cs as cs
    from modstore_server.models import get_session_factory

    resolution = {"repair_verified": True, "team": [{"role": "scout", "error": LEAK}]}
    resolution["data_correction"] = {"reason": "备份表 bak_t39_20261018_*"}
    report = {
        "progress": f"排查未完成：{LEAK}",
        "team_ok": False,
        "at": "2026-10-16T04:48:46",
    }
    evidence = {
        "resolution": resolution,
        "employee_reports": [report],
        "source_ref": "WO-1",
    }
    with get_session_factory()() as db:
        session = cs.CustomerServiceSession(user_id=owner_id)
        db.add(session)
        db.flush()
        ticket = cs.CustomerServiceTicket(
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
            cs.CustomerServiceAction(
                **{"ticket_id": ticket.id, "user_id": owner_id, "status": "failed"},
                action_type="employee.dispatch",
                result_json=json.dumps({"progress": LEAK}),
                error=LEAK,
                idempotency_key=uuid.uuid4().hex,
            )
        )
        detail = {"progress": LEAK, "backup_tables": ["bak_t39_20261018_ticket"]}
        db.add(
            cs.CustomerServiceAuditLog(
                **ids, actor_type="ai", event_type="x", detail_json=json.dumps(detail)
            )
        )
        payload = {
            "ticket": {"evidence": evidence},
            "employee_progress": {"progress": LEAK},
        }
        for role, content in (
            ("user", "还是看不到 1.0.0.6"),
            ("assistant", f"进展：{LEAK}"),
        ):
            db.add(
                cs.CustomerServiceMessage(
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
        assert "submitter_type" not in detail["ticket"]
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


def test_ticket_transcript_binds_owner_ticket_and_session_and_restores_raster_attachment(client):
    from modstore_server import customer_service_api
    from modstore_server import models_cs as cs
    from modstore_server.app import app
    from modstore_server.customer_ticket_reader import TicketReader
    from modstore_server.models import get_session_factory

    owner = _make_user("transcript_owner")
    admin = _make_user("transcript_admin", admin=True)
    other = _make_user("transcript_outsider")
    tid, sid = _seed(owner.id)
    _, other_sid = _seed(owner.id)
    png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mP8/x8AAwMCAO+jR1sAAAAASUVORK5CYII="
    )
    svg = "data:image/svg+xml;base64,PHN2Zy8+"
    with get_session_factory()() as db:
        sibling = cs.CustomerServiceTicket(
            user_id=owner.id, session_id=sid, ticket_no=f"SIBLING-{uuid.uuid4().hex}"
        )
        db.add(sibling)
        db.flush()
        for user_id, session_id, ticket_id, role, text, image in (
            (owner.id, sid, tid, "user", "原单截图", png),
            (owner.id, sid, tid, "user", "不安全的图片类型", svg),
            (owner.id, sid, tid, "user", "损坏的图片编码", "data:image/png;base64,%%"),
            (owner.id, sid, tid, "assistant", "助手不能提供用户截图", png),
            (owner.id, sid, None, "user", "建单前的会话信息", png),
            (owner.id, sid, sibling.id, "user", "同会话的其他工单", png),
            (other.id, sid, tid, "user", "不一致的消息用户", png),
            (owner.id, other_sid, tid, "user", "不一致的消息会话", png),
        ):
            db.add(
                cs.CustomerServiceMessage(
                    user_id=user_id,
                    session_id=session_id,
                    ticket_id=ticket_id,
                    role=role,
                    content=text,
                    payload_json=json.dumps({"image_data_url": image}),
                )
            )
        db.commit()
    base = "/api/customer-service"
    detail_route = f"{base}/tickets/{tid}"
    route = f"{detail_route}?include_transcript=true"
    generic = f"{base}/sessions/{sid}"

    def get_as(user, path):
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
        return client.get(path)

    def by_content(body):
        return {row["content"]: row["payload"] for row in body["messages"]}

    try:
        ordinary = get_as(owner, detail_route)
        assert ordinary.status_code == 200
        assert ordinary.json() == get_as(owner, f"{detail_route}?include_transcript=false").json()
        assert set(ordinary.json()) == {"ticket", "decisions", "actions", "audit_logs"}
        owner_reply = get_as(owner, route)
        assert owner_reply.status_code == 200, owner_reply.text
        body = owner_reply.json()
        assert body["ticket"]["id"] == tid and body["session_id"] == sid
        assert body["can_reply"] is True
        rows = by_content(body)
        assert rows["原单截图"]["image_data_url"] == png
        assert rows["建单前的会话信息"]["image_data_url"] == png
        for text in ("不安全的图片类型", "损坏的图片编码", "助手不能提供用户截图"):
            assert "image_data_url" not in rows[text]
        assert not {"同会话的其他工单", "不一致的消息用户", "不一致的消息会话"} & rows.keys()
        assert by_content(get_as(owner, generic).json())["原单截图"]["image_data_url"] == png

        admin_reply = get_as(admin, route)
        assert admin_reply.status_code == 200, admin_reply.text
        body = admin_reply.json()
        assert body["can_reply"] is False and body["ticket"]["id"] == tid
        assert by_content(body)["原单截图"]["image_data_url"] == png
        assert "建单前的会话信息" not in by_content(body)
        assert all(message["ticket_id"] == tid for message in body["messages"])
        assert get_as(admin, generic).status_code == 404
        assert get_as(other, route).status_code == 404
        reader = TicketReader("grant", "company-reader", "company", "instance", (owner.id,))
        assert get_as(reader, route).status_code == 403
        with get_session_factory()() as db:
            db.get(cs.CustomerServiceSession, sid).user_id = other.id
            db.commit()
        assert get_as(owner, route).status_code == 404
        assert get_as(admin, route).status_code == 404
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def _dispatch(detail):
    return {
        "action_type": "employee.dispatch",
        "created_at": detail["actions"][0]["created_at"],
    }
