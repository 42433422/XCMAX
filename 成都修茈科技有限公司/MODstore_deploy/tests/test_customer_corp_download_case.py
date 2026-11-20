"""The corporate download probe may only use an original report of this ticket."""

import hashlib
import json
from uuid import uuid4

import pytest

from modstore_server.customer_corp_download_case import (
    bind_submitted_corp_download_report,
    read_corp_download_case,
    register_corp_download_case,
)
from modstore_server.models import User, get_session_factory
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)
from modstore_server.services import llm
from tests.test_customer_ticket_intake_review import _authenticated_ticket_user

REPORT = (
    "XCAGI 官网下载路径带末尾斜杠时返回 404。"
    "复现：在未登录浏览器依次打开 https://xiu-ci.com/download 和 https://xiu-ci.com/download/。"
    "前者返回 200，显示 XCAGI 产品下载，后者返回 404；www 域名同样。"
    "预期：带末尾斜杠的分享链接也能进入同一下载页，或跳转到正确地址。实际故障可复现。"
)
SHORT_REPORT = "XCAGI 官网产品下载页 /download 返回 200，地址改成 /download/ 返回 404。"
LABELED_REPORT = "【CX1120-0329-C｜闭环测试·真实缺陷】" + REPORT


def _user(db):
    user = User(username=f"corp-case-{uuid4().hex}", password_hash="fixture", is_admin=False)
    db.add(user)
    db.flush()
    return user


def _ticket(db, report=REPORT):
    owner = _user(db)
    session = CustomerServiceSession(user_id=owner.id)
    db.add(session)
    db.flush()
    ticket = CustomerServiceTicket(
        ticket_no=f"CS{uuid4().hex}",
        session_id=session.id,
        user_id=owner.id,
        intent="product_issue",
        status="open",
        summary=report,
        evidence_json=json.dumps({"intake_review": {"disposition": "actionable"}}),
    )
    db.add(ticket)
    db.flush()
    return ticket


def _message(db, ticket, content, *, bound=True, owner_id=None):
    message = CustomerServiceMessage(
        ticket_id=ticket.id if bound else None,
        session_id=ticket.session_id,
        user_id=ticket.user_id if owner_id is None else owner_id,
        role="user",
        content=content,
    )
    db.add(message)
    db.flush()
    return message


@pytest.mark.parametrize("report", [REPORT, SHORT_REPORT, LABELED_REPORT])
def test_registered_site_case_uses_digest_of_exact_bound_owner_message(client, report):
    with get_session_factory()() as db:
        ticket = _ticket(db, report)
        original = _message(db, ticket, report)
        evidence = {"resolution": {"route": "shared_core", "original_request": report}}
        register_corp_download_case(db, ticket, evidence)
        case = {
            "schema_version": 1,
            "source_message_id": original.id,
            "report_sha256": hashlib.sha256(report.encode()).hexdigest(),
            "original_path": "/download/",
        }
        assert evidence["corp_download_case"] == case
        assert read_corp_download_case(db, ticket, evidence) == case
        assert "corp_download_case" not in ticket.evidence_json

        other_ticket = _ticket(db, report)
        _message(db, other_ticket, report)
        assert read_corp_download_case(db, other_ticket, evidence) is None
        original.content = report + " 后续说明"
        db.flush()
        assert read_corp_download_case(db, ticket, evidence) is None


@pytest.mark.parametrize(
    "report",
    [
        "我问过薄荷浇水。实际故障是 XCAGI 官网下载 /download/ 返回 404。",
        SHORT_REPORT + "账户充值未入账，也请退款。",
        SHORT_REPORT + "本描述为虚构演练，未实际发生。",
        "【演练，未实际发生】" + REPORT,
        "【CX1120-0329-C｜闭环测试·虚构演练】" + REPORT,
        "XCAGI 官网下载页 /download/ 没有返回 404。",
        "XCAGI 官网下载页 /download/ 返回 200。",
        "XCAGI 官网下载页 /download 返回 404。",
        "访问 https://example.invalid/download/ 返回 404。",
        "访问 https://xiu-ci.com/download/?from=external 返回 404。",
        "访问 https://xiu-ci.com/market/download/ 返回 404。",
        "XCAGI 官网下载页 /download/ 返回 404，另一个页面也报错。",
        REPORT.replace(
            "/download 和 https://xiu-ci.com/download/", "/download/ 和 https://xiu-ci.com/download"
        ),
    ],
)
def test_other_negative_mixed_or_ambiguous_cases_do_not_register(client, report):
    with get_session_factory()() as db:
        ticket = _ticket(db, report)
        _message(db, ticket, report)
        evidence = {}
        register_corp_download_case(db, ticket, evidence)
        assert evidence == {}


@pytest.mark.parametrize("scope", ["unbound", "other_owner", "custom", "revoked", "negative"])
def test_original_scope_and_case_ownership_are_required(client, scope):
    with get_session_factory()() as db:
        ticket = _ticket(db)
        _message(
            db,
            ticket,
            REPORT,
            bound=scope != "unbound",
            owner_id=_user(db).id if scope == "other_owner" else None,
        )
        evidence = {
            "custom": {"resolution": {"route": "private_mod"}},
            "revoked": {"dispatch_revocation": {"at": "recorded"}},
            "negative": {"intake_review": {"disposition": "invalid"}},
        }.get(scope, {})
        register_corp_download_case(db, ticket, evidence)
        assert "corp_download_case" not in evidence


@pytest.mark.parametrize(
    "scenario", ["exact", "wrong_report", "supplement", "other_owner", "bound"]
)
def test_submit_binds_only_the_immediately_previous_exact_owner_report(client, scenario):
    with get_session_factory()() as db:
        ticket = _ticket(db)
        original = _message(
            db,
            ticket,
            SHORT_REPORT if scenario == "wrong_report" else REPORT,
            bound=scenario == "bound",
            owner_id=_user(db).id if scenario == "other_owner" else None,
        )
        if scenario == "supplement":
            _message(db, ticket, "这是另一个问题。", bound=False)
        submit = _message(db, ticket, "提交工单")
        bind_submitted_corp_download_report(
            db,
            ticket,
            owner_id=ticket.user_id,
            submitted_text="提交工单",
            reviewed_report=REPORT,
        )
        db.refresh(original)
        assert original.ticket_id == (ticket.id if scenario in {"exact", "bound"} else None)
        assert submit.ticket_id == ticket.id
        evidence = {}
        register_corp_download_case(db, ticket, evidence)
        assert ("corp_download_case" in evidence) == (scenario in {"exact", "bound"})


def test_live_chat_transaction_links_the_message_before_issuing_intake(client, monkeypatch):
    from modstore_server import customer_service_api

    owner = _authenticated_ticket_user(monkeypatch)
    scheduled = []

    async def classify(_provider, _model, messages, **_opts):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "disposition": "actionable",
                    "intent": "product_issue",
                    "reason": "说明了官网原路由实际返回的错误",
                    "evidence_excerpt": "XCAGI 官网下载路径带末尾斜杠时返回 404。",
                }
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", classify)
    monkeypatch.setattr(
        customer_service_api, "_schedule_customer_ticket_incident", scheduled.append
    )
    endpoint = "/api/customer-service/chat"
    entered = client.post(endpoint, json={"message": LABELED_REPORT}).json()
    assert entered["ticket"] is None
    session_id = entered["session"]["id"]
    submitted = client.post(endpoint, json={"message": "提交工单", "session_id": session_id})
    assert submitted.status_code == 200, submitted.text
    ticket_id = submitted.json()["ticket"]["id"]
    assert scheduled == [{"ticket_id": ticket_id}]
    with get_session_factory()() as db:
        message = (
            db.query(CustomerServiceMessage)
            .filter_by(user_id=owner.id, session_id=session_id, role="user", content=LABELED_REPORT)
            .one()
        )
        assert message.ticket_id == ticket_id
        ticket = db.get(CustomerServiceTicket, ticket_id)
        evidence = json.loads(ticket.evidence_json)
        register_corp_download_case(db, ticket, evidence)
        assert evidence["corp_download_case"]["source_message_id"] == message.id
