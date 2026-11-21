"""客户身份的工单接口只出白名单字段，不出内部审计、派单原文和执行器报错；管理端照旧。"""

from __future__ import annotations

import base64
import json
import re
import uuid

import pytest

from tests.test_customer_service_api import _make_user

pytest.importorskip("fastapi")

LEAK = "Cursor Agent 失败: Command failed: /Users/a4243342/x; git clone https://github.com/o/r.git"
PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
    "EQVR42mP8/x8AAwMCAO+jR1sAAAAASUVORK5CYII="
)
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
    message_ids = {}
    svg = "data:image/svg+xml;base64,PHN2Zy8+"
    with get_session_factory()() as db:
        sibling = cs.CustomerServiceTicket(
            user_id=owner.id, session_id=sid, ticket_no=f"SIBLING-{uuid.uuid4().hex}"
        )
        db.add(sibling)
        db.flush()
        for user_id, session_id, ticket_id, role, text, image in (
            (owner.id, sid, tid, "user", "原单截图", PNG),
            (owner.id, sid, tid, "user", "不安全的图片类型", svg),
            (owner.id, sid, tid, "user", "损坏的图片编码", "data:image/png;base64,%%"),
            (owner.id, sid, tid, "assistant", "助手不能提供用户截图", PNG),
            (owner.id, sid, None, "user", "建单前的会话信息", PNG),
            (owner.id, sid, sibling.id, "user", "同会话的其他工单", PNG),
            (other.id, sid, tid, "user", "不一致的消息用户", PNG),
            (owner.id, other_sid, tid, "user", "不一致的消息会话", PNG),
        ):
            row = cs.CustomerServiceMessage(
                user_id=user_id,
                session_id=session_id,
                ticket_id=ticket_id,
                role=role,
                content=text,
                payload_json=json.dumps({"image_data_url": image}),
            )
            db.add(row)
            db.flush()
            message_ids[text] = row.id
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

    def image_path(text):
        return f"{detail_route}?transcript_image_message_id={message_ids[text]}"

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
        assert body["next_before_id"] is None
        rows = by_content(body)
        assert rows["原单截图"]["has_screenshot"] is True
        assert rows["建单前的会话信息"]["has_screenshot"] is True
        assert all("image_data_url" not in payload for payload in rows.values())
        for text in ("不安全的图片类型", "损坏的图片编码", "助手不能提供用户截图"):
            assert "has_screenshot" not in rows[text]
            assert get_as(owner, image_path(text)).status_code == 404
        assert not {"同会话的其他工单", "不一致的消息用户", "不一致的消息会话"} & rows.keys()
        assert by_content(get_as(owner, generic).json())["原单截图"]["image_data_url"] == PNG
        for text in ("同会话的其他工单", "不一致的消息用户", "不一致的消息会话"):
            assert get_as(owner, image_path(text)).status_code == 404
        original = get_as(owner, image_path("原单截图"))
        assert original.status_code == 200
        assert original.headers["content-type"] == "image/png"
        assert original.headers["x-content-type-options"] == "nosniff"
        assert original.headers["cache-control"] == "private, no-store"
        assert original.content == base64.b64decode(PNG.split(",", 1)[1])
        assert get_as(owner, image_path("建单前的会话信息")).content == original.content

        admin_reply = get_as(admin, route)
        assert admin_reply.status_code == 200, admin_reply.text
        body = admin_reply.json()
        assert body["can_reply"] is False and body["ticket"]["id"] == tid
        assert by_content(body)["原单截图"]["has_screenshot"] is True
        assert "建单前的会话信息" not in by_content(body)
        assert all(message["ticket_id"] == tid for message in body["messages"])
        assert get_as(admin, image_path("原单截图")).content == original.content
        assert get_as(admin, image_path("建单前的会话信息")).status_code == 404
        assert get_as(admin, generic).status_code == 404
        assert get_as(other, route).status_code == 404
        assert get_as(other, image_path("原单截图")).status_code == 404
        reader = TicketReader("grant", "company-reader", "company", "instance", (owner.id,))
        assert get_as(reader, route).status_code == 403
        assert get_as(reader, image_path("原单截图")).status_code == 403
        with get_session_factory()() as db:
            db.get(cs.CustomerServiceSession, sid).user_id = other.id
            db.commit()
        assert get_as(owner, route).status_code == 404
        assert get_as(admin, route).status_code == 404
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_ticket_transcript_pages_keep_original_text_and_attachment(client, monkeypatch):
    from modstore_server import customer_service_api, customer_service_transcript
    from modstore_server import models_cs as cs
    from modstore_server.app import app
    from modstore_server.models import get_session_factory

    owner = _make_user("paged_transcript_owner")
    tid, sid = _seed(owner.id)
    monkeypatch.setitem(
        app.dependency_overrides, customer_service_api._get_current_user, lambda: owner
    )
    monkeypatch.setattr(customer_service_transcript, "TRANSCRIPT_PAGE_SIZE", 3)
    monkeypatch.setattr(customer_service_transcript, "MAX_MESSAGE_METADATA_LENGTH", 1200)
    with get_session_factory()() as db:
        rows = [
            cs.CustomerServiceMessage(
                ticket_id=tid,
                session_id=sid,
                user_id=owner.id,
                role="user",
                content=f"跟进 {idx}",
                payload_json=json.dumps(
                    {"image_data_url": PNG, "context": {"notes": "资料" * 800}}, ensure_ascii=False
                ),
            )
            for idx in range(4)
        ]
        db.add_all(rows)
        db.commit()
        screenshot_id = rows[0].id

    route = f"/api/customer-service/tickets/{tid}"
    first = client.get(route, params={"include_transcript": True}).json()
    assert [m["content"] for m in first["messages"]] == ["跟进 1", "跟进 2", "跟进 3"]
    assert all(m["payload"] == {"has_screenshot": True} for m in first["messages"])
    assert first["next_before_id"] == first["messages"][0]["id"]
    older = client.get(
        route, params={"include_transcript": True, "transcript_before_id": first["next_before_id"]}
    ).json()
    assert [m["content"] for m in older["messages"]][::2] == ["还是看不到 1.0.0.6", "跟进 0"]
    assert older["messages"][-1]["id"] == screenshot_id and older["next_before_id"] is None
    attachment = client.get(route, params={"transcript_image_message_id": screenshot_id})
    assert attachment.content == base64.b64decode(PNG.split(",", 1)[1])


def test_chat_screenshot_quota_allows_original_text_follow_up(client, monkeypatch):
    from modstore_server import customer_service_api, customer_service_transcript
    from modstore_server.app import app

    owner = _make_user("screenshot_quota_owner")
    tid, sid = _seed(owner.id)
    monkeypatch.setitem(
        app.dependency_overrides, customer_service_api._get_current_user, lambda: owner
    )
    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    monkeypatch.setattr(customer_service_transcript, "MAX_TICKET_SCREENSHOT_STORAGE", len(PNG))
    body = {"session_id": sid, "context": {"ticket_id": tid}, "message": "原单补充截图"}
    route = "/api/customer-service/chat"
    accepted = client.post(route, json={**body, "image_data_url": PNG})
    assert accepted.status_code == 200, accepted.text
    assert "image_data_url" not in accepted.json()["session"]["context"]
    assert client.post(route, json={**body, "image_data_url": PNG}).status_code == 413
    assert client.post(route, json={**body, "message": "截图已补，现补充文字"}).status_code == 200
    messages = client.get(f"/api/customer-service/tickets/{tid}?include_transcript=true").json()[
        "messages"
    ]
    assert sum(m["payload"].get("has_screenshot") is True for m in messages) == 1
    assert [m["content"] for m in messages].count("原单补充截图") == 1
    assert "截图已补，现补充文字" in [m["content"] for m in messages]


def _dispatch(detail):
    return {
        "action_type": "employee.dispatch",
        "created_at": detail["actions"][0]["created_at"],
    }
