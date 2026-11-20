"""Bind an original report to the single approved corporate download probe."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy.orm import Query, Session

from modstore_server.custom_delivery_incident_policy import is_delivery_managed
from modstore_server.customer_service_tools import json_loads
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)

_CASE = "corp_download_case"
_HOST = r"https://(?:www\.)?xiu-ci\.com"
_CONTROL = rf"`?(?:{_HOST})?/download`?"
_ORIGINAL = rf"`?(?:{_HOST})?/download/`?"
_TITLE = r"(?:XCAGI|XCMAX)\s*官网(?:的)?(?:产品)?下载(?:页|路径|链接)?"
_OPEN = r"(?:(?:直接)?(?:访问|打开)|地址改成)\s*"
_NOT_FOUND = r"(?:返回|显示|出现|报(?:错)?|[：:])\s*(?:HTTP\s*)?404"
_OBSERVED = re.compile(
    rf"(?:{_TITLE}\s*)?(?:(?:{_OPEN})?{_CONTROL}\s*返回\s*(?:HTTP\s*)?200[，,]\s*)?"
    rf"(?:{_OPEN})?{_ORIGINAL}\s*{_NOT_FOUND}(?:[，,]\s*请?提交工单)?"
)
_STEPS = re.compile(
    rf"复现[：:]\s*(?:在未登录浏览器)?依次(?:打开|访问)\s*{_CONTROL}\s*(?:和|与)\s*{_ORIGINAL}"
)
_COMPARISON = re.compile(
    rf"前者返回\s*(?:HTTP\s*)?200[，,]\s*显示\s*XCAGI\s*产品下载[，,]\s*后者\s*{_NOT_FOUND}"
)
_CONTEXT = re.compile(
    rf"(?:{_TITLE}\s*带末尾斜杠时\s*{_NOT_FOUND}|www\s*域名同样|实际故障可复现|请?提交工单|"
    r"预期[：:]\s*带末尾斜杠的(?:分享)?链接(?:也)?能进入同一下载页(?:[，,]\s*或跳转到正确地址)?)"
)
_CLAUSE_SEPARATOR = re.compile(r"[。！；;\n]+")
_OFFICIAL_SITE = re.compile(rf"{_TITLE}|{_HOST}/download(?:/|\b)")
_TEST_BATCH_LABEL = re.compile(r"\A【CX[0-9]{4}-[0-9]{4}-C｜闭环测试·真实缺陷】\s*")


def is_corp_download_report(report: str) -> bool:
    """Recognize only the explicitly supported report for this fixed probe."""
    report = _TEST_BATCH_LABEL.sub("", report, count=1)
    if not _OFFICIAL_SITE.search(report):
        return False
    observed = ordered_paths = False
    for clause in _CLAUSE_SEPARATOR.split(report):
        text = clause.strip().rstrip(".")
        if not text or _CONTEXT.fullmatch(text):
            continue
        if _STEPS.fullmatch(text):
            ordered_paths = True
        elif _OBSERVED.fullmatch(text) or (ordered_paths and _COMPARISON.fullmatch(text)):
            observed = True
        else:
            # Extra claims and unrecognized assertions need their own verification.
            return False
    return observed


def _ordinary_product_case(ticket: CustomerServiceTicket, evidence: dict[str, Any]) -> bool:
    resolution = evidence.get("resolution", {})
    review = evidence.get("intake_review")
    intent = str(ticket.intent or "")
    return (
        intent == "product_issue"
        and not ticket.closed_at
        and str(ticket.status or "") in {"open", "processing", "awaiting_customer"}
        and not is_delivery_managed(intent, evidence)
        and isinstance(resolution, dict)
        and resolution.get("route") in (None, "shared_core")
        and evidence.get("issue_domain") != "custom"
        and evidence.get("source") != "private_mod_rework"
        and not (evidence.get("target_mod_id") or resolution.get("target_mod_id"))
        and evidence.get("classification_status") != "pending_verification"
        and not any(
            evidence.get(key)
            for key in ("dispatch_revocation", "admin_disposition", "assistant_disposition")
        )
        and (
            "intake_review" not in evidence
            or (isinstance(review, dict) and review.get("disposition") == "actionable")
        )
    )


def _owner_messages(db: Session, ticket: CustomerServiceTicket) -> Query[CustomerServiceMessage]:
    return (
        db.query(CustomerServiceMessage)
        .join(
            CustomerServiceSession, CustomerServiceSession.id == CustomerServiceMessage.session_id
        )
        .filter(
            CustomerServiceMessage.session_id == ticket.session_id,
            CustomerServiceMessage.user_id == ticket.user_id,
            CustomerServiceMessage.role == "user",
            CustomerServiceSession.user_id == ticket.user_id,
        )
    )


def _original_case(
    db: Session, ticket: CustomerServiceTicket, evidence: dict[str, Any]
) -> dict[str, Any] | None:
    if not _ordinary_product_case(ticket, evidence):
        return None
    with db.no_autoflush:
        message = (
            _owner_messages(db, ticket)
            .filter(CustomerServiceMessage.ticket_id == ticket.id)
            .order_by(CustomerServiceMessage.id)
            .populate_existing()
            .first()
        )
    resolution = evidence.get("resolution", {})
    original = resolution.get("original_request", ticket.summary)
    if message is None or not isinstance(original, str):
        return None
    report = str(message.content or "")
    if report != original or not is_corp_download_report(report):
        return None
    return {
        "schema_version": 1,
        "source_message_id": int(message.id),
        "report_sha256": hashlib.sha256(report.encode()).hexdigest(),
        "original_path": "/download/",
    }


def register_corp_download_case(
    db: Session, ticket: CustomerServiceTicket, evidence: dict[str, Any]
) -> None:
    """Record the verified source in the trusted worker's existing transaction."""
    if _CASE not in evidence and (case := _original_case(db, ticket, evidence)):
        evidence[_CASE] = case


def read_corp_download_case(
    db: Session, ticket: CustomerServiceTicket, evidence: dict[str, Any]
) -> dict[str, Any] | None:
    """Read back the original owner, ticket and exact report binding."""
    prior = evidence.get(_CASE)
    if (
        not isinstance(prior, dict)
        or type(prior.get("source_message_id")) is not int
        or type(prior.get("schema_version")) is not int
    ):
        return None
    case = _original_case(db, ticket, evidence)
    return case if case == prior else None


def bind_submitted_corp_download_report(
    db: Session,
    ticket: CustomerServiceTicket,
    *,
    owner_id: int,
    submitted_text: str,
    reviewed_report: str | None,
) -> None:
    """Link the exact preceding report under the chat transaction's session lock."""
    if (
        submitted_text != "提交工单"
        or ticket.user_id != owner_id
        or ticket.status != "open"
        or ticket.assigned_admin_id is not None
        or not reviewed_report
        or ticket.summary != reviewed_report
    ):
        return
    evidence = json_loads(ticket.evidence_json, {})
    if (
        not isinstance(evidence, dict)
        or "intake_review" not in evidence
        or not _ordinary_product_case(ticket, evidence)
        or not is_corp_download_report(reviewed_report)
    ):
        return
    latest = _owner_messages(db, ticket).order_by(CustomerServiceMessage.id.desc()).limit(2).all()
    if len(latest) != 2:
        return
    submit, source = latest
    if (
        submit.ticket_id != ticket.id
        or submit.content != submitted_text
        or source.ticket_id is not None
        or source.content != reviewed_report
    ):
        return
    db.query(CustomerServiceMessage).filter_by(
        id=source.id,
        ticket_id=None,
        session_id=ticket.session_id,
        user_id=owner_id,
        role="user",
        content=reviewed_report,
    ).update({"ticket_id": ticket.id}, synchronize_session="fetch")
