"""需求已提交（intake_done）阶段：CRM 漏斗落库、ERP 客户关联、群通知。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _pipeline():
    from app.services import user_cs_pipeline as mod

    return mod


def _normalize_company_key(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().casefold())


def _company_match_score(query: str, candidate: str) -> int:
    q = _normalize_company_key(query)
    c = _normalize_company_key(candidate)
    if not q or not c:
        return -1
    if q == c:
        return 100
    if c.startswith(q) or q.startswith(c):
        return 85
    if q in c or c in q:
        return 70
    return -1


def _row_display_name(row: dict[str, Any]) -> str:
    return str(row.get("customer_name") or row.get("name") or row.get("unit_name") or "").strip()


def _row_phone(row: dict[str, Any]) -> str:
    return str(row.get("contact_phone") or row.get("phone") or "").strip()


def resolve_erp_customer_for_intake(
    *,
    company: str = "",
    phone: str = "",
    name: str = "",
) -> dict[str, Any] | None:
    """按公司名/联系人匹配 ERP 客户主数据（/api/customers/list 同源）。"""
    query = (company or name or "").strip()
    if not query:
        return None

    rows: list[dict[str, Any]] = []
    try:
        from app.bootstrap import get_customer_app_service

        out = get_customer_app_service().get_all(keyword=query, page=1, per_page=80)
        if out.get("success"):
            rows = [r for r in (out.get("data") or []) if isinstance(r, dict)]
    except Exception:
        logger.debug("resolve_erp via customer service skipped", exc_info=True)

    if not rows:
        try:
            from app.fastapi_routes.domains.db.queries import _load_customers_rows

            all_rows = _load_customers_rows()
            qk = query.casefold()
            rows = [
                r
                for r in all_rows
                if isinstance(r, dict)
                and (
                    qk in _row_display_name(r).casefold()
                    or qk in _row_phone(r)
                    or (phone and phone in _row_phone(r))
                )
            ][:80]
        except Exception:
            logger.debug("resolve_erp via _load_customers_rows skipped", exc_info=True)
            return None

    phone_q = re.sub(r"\D", "", phone or "")
    best: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        cn = _row_display_name(row)
        score = _company_match_score(query, cn)
        if phone_q and phone_q in re.sub(r"\D", "", _row_phone(row)):
            score = max(score, 90)
        if score > best_score:
            best_score = score
            best = row
    if not best or best_score < 60:
        return None
    cid = best.get("id") or best.get("customer_id")
    return {
        "erp_customer_id": int(cid) if cid is not None else None,
        "erp_customer_name": _row_display_name(best),
        "erp_match_score": best_score,
        "erp_match_source": "customers_list",
        "erp_contact_phone": _row_phone(best),
    }


def bootstrap_pipeline_lead(
    market_user_id: int,
    *,
    username: str = "",
    max_steps: int = 4,
) -> dict[str, Any]:
    """确保有群绑定的客户从 idle 起至少进入 connected / intake（不越过 intake_done）。"""
    pipe = _pipeline()
    uid = int(market_user_id)
    doc = pipe.load_pipeline(uid, username=username)
    for _ in range(max_steps):
        stage = str(doc.get("stage") or "idle")
        if stage in (
            "intake_done",
            "quoted",
            "negotiating",
            "contract_pending",
            "signed",
            "delivering",
            "delivered",
        ):
            break
        doc, advanced = pipe.auto_advance_pipeline_if_ready(uid, username=username)
        if not advanced:
            break
    return doc


def build_intake_done_notice_message(
    *,
    client_name: str = "",
    audit_code: str = "",
    company: str = "",
    erp_linked: bool = False,
    erp_customer_name: str = "",
) -> str:
    who = (client_name or "您好").strip()
    if who and not who.endswith("好") and who != "您好":
        greeting = f"{who}，您好"
    else:
        greeting = who if who else "您好"

    lines = [
        f"{greeting}！",
        "",
        "我们已收到您提交的需求表单，信息已进入 CRM 跟进流程，专属顾问会据此整理方案。",
    ]
    if audit_code:
        lines.append(f"需求单号：{audit_code}")
    if company:
        lines.append(f"单位/公司：{company}")
    if erp_linked and erp_customer_name:
        lines.append(f"已关联 ERP 客户档案：{erp_customer_name}")
    elif company:
        lines.append("（系统正在为您匹配 ERP 客户主数据，匹配结果将同步至内部商机看板。）")
    lines.extend(
        [
            "",
            "下一步我们将在本群与您核对需求范围与交付边界，确认后提供正式报价。",
            "如有补充说明，请直接在本群留言。",
            "",
            "感谢配合！",
        ]
    )
    return "\n".join(lines)


def _format_audit_code(landing_contact_id: int | None) -> str:
    if not landing_contact_id:
        return ""
    return f"XC-{int(landing_contact_id):06d}"


def _primary_contact_name(market_user_id: int) -> Optional[str]:
    from app.services.wechat_group_customer_bridge import get_bindings_for_user

    bindings = get_bindings_for_user(int(market_user_id))
    if not bindings:
        return None
    first = bindings[0]
    return str(first.get("contact_name") or first.get("remark") or "").strip() or None


def maybe_send_intake_done_notice(
    market_user_id: int,
    *,
    username: str = "",
    contact_name: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """需求已提交后向绑定微信群发送确认（默认仅一次）。"""
    from app.desktop_automation.service import get_desktop_automation_service

    pipe = _pipeline()
    uid = int(market_user_id)
    doc = pipe.load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")
    if pipe._stage_rank(stage) < pipe._stage_rank("intake_done") and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "before_intake_done",
            "stage": stage,
        }
    if doc.get("intake_done_notice_sent") and not force:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "already_sent",
            "sent_at": doc.get("intake_done_notice_sent_at"),
        }

    contact = (contact_name or _primary_contact_name(uid) or "").strip()
    if not contact:
        return {
            "attempted": False,
            "sent": False,
            "skipped": True,
            "reason": "no_binding_contact",
        }

    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(form.get("company") or "")
    audit_code = _format_audit_code(doc.get("landing_contact_id"))
    display = (username or doc.get("username") or str(form.get("name") or "")).strip()
    text = build_intake_done_notice_message(
        client_name=display,
        audit_code=audit_code,
        company=company,
        erp_linked=bool(doc.get("erp_customer_id")),
        erp_customer_name=str(doc.get("erp_customer_name") or ""),
    )

    try:
        svc = get_desktop_automation_service()
        send_result = svc.send_wechat_message(contact, text)
    except Exception as exc:
        logger.exception("intake_done notice send failed uid=%s", uid)
        return {
            "attempted": True,
            "sent": False,
            "skipped": False,
            "reason": "send_error",
            "error": str(exc)[:500],
            "contact_name": contact,
            "message": text,
        }

    ok = bool(send_result.get("success")) and bool(
        send_result.get("message_sent", send_result.get("success"))
    )
    if ok:
        now = datetime.now(timezone.utc).isoformat()
        doc["intake_done_notice_sent"] = True
        doc["intake_done_notice_sent_at"] = now
        doc["intake_done_notice_message"] = text
        timeline = list(doc.get("timeline") or [])
        timeline.append({"stage": "intake_done", "at": now, "source": "intake_done_notice"})
        doc["timeline"] = timeline[-30:]
        pipe.save_pipeline(doc)

    return {
        "attempted": True,
        "sent": ok,
        "skipped": False,
        "reason": "ok" if ok else "send_failed",
        "contact_name": contact,
        "message": text,
        "send_result": send_result,
        "error": ""
        if ok
        else str(send_result.get("error") or send_result.get("message") or "send failed"),
    }


def finalize_intake_submission(
    market_user_id: int,
    doc: dict[str, Any],
    *,
    username: str = "",
    notify_wechat: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    intake_done 阶段收尾：漏斗 bootstrap、ERP 关联、报价草稿占位、可选群通知。
    返回 (pipeline_doc, meta)。
    """
    uid = int(market_user_id)
    meta: dict[str, Any] = {
        "erp_linked": False,
        "erp_customer_id": None,
        "wechat_notice": None,
        "bootstrap_applied": False,
    }

    doc = bootstrap_pipeline_lead(uid, username=username)
    meta["bootstrap_applied"] = True
    meta["stage_after_bootstrap"] = str(doc.get("stage") or "idle")

    form = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(form.get("company") or "")
    phone = str(form.get("phone") or "")
    name = str(form.get("name") or "")

    if not doc.get("erp_customer_id"):
        match = resolve_erp_customer_for_intake(company=company, phone=phone, name=name)
        if match:
            doc["erp_customer_id"] = match.get("erp_customer_id")
            doc["erp_customer_name"] = match.get("erp_customer_name")
            doc["erp_match_score"] = match.get("erp_match_score")
            doc["erp_match_source"] = match.get("erp_match_source")
            doc["erp_linked_at"] = datetime.now(timezone.utc).isoformat()
            meta["erp_linked"] = True
            meta["erp_customer_id"] = doc.get("erp_customer_id")
            meta["erp_customer_name"] = doc.get("erp_customer_name")
    else:
        meta["erp_linked"] = True
        meta["erp_customer_id"] = doc.get("erp_customer_id")
        meta["erp_customer_name"] = doc.get("erp_customer_name")

    now = datetime.now(timezone.utc).isoformat()
    doc["quote_draft"] = {
        "status": "pending_review",
        "created_at": now,
        "erp_customer_id": doc.get("erp_customer_id"),
        "company": company,
        "landing_contact_id": doc.get("landing_contact_id"),
        "note": "auto_from_intake_done",
    }
    doc["crm_funnel_synced_at"] = now
    pipe = _pipeline()
    doc = pipe.save_pipeline(doc)

    stage = str(doc.get("stage") or "idle")

    if pipe._stage_rank(stage) < pipe._stage_rank("intake_done") and doc.get("intake_submitted_at"):
        try:
            doc = pipe.set_pipeline_stage(
                uid,
                "intake_done",
                username=username,
                source="intake_finalize",
                note="crm_funnel_sync",
            )
        except ValueError:
            pass

    if notify_wechat:
        notice = maybe_send_intake_done_notice(uid, username=username, force=False)
        meta["wechat_notice"] = notice
        if notice.get("sent"):
            doc = pipe.load_pipeline(uid, username=username)

    meta["crm_opportunity_id"] = doc.get("crm_opportunity_id")
    meta["crm_quote_id"] = doc.get("crm_quote_id")

    try:
        from app.services.user_cs_demand_form import notify_market_landing_crm_link

        notify_market_landing_crm_link(
            doc.get("landing_contact_id"),
            doc.get("crm_opportunity_id"),
            market_user_id=uid,
        )
    except Exception:
        logger.debug("market landing crm link skipped", exc_info=True)

    return doc, meta
