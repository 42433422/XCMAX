"""需求表单提交后的 CRM/ERP 归档。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.utils.operational_errors import OPERATIONAL_ERRORS


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def finalize_intake_submission(
    market_user_id: int,
    doc: dict[str, Any],
    *,
    username: str = "",
    notify_wechat: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.services.user_cs_crm_store import sync_crm_from_pipeline_doc
    from app.services.user_cs_pipeline import save_pipeline

    doc = dict(doc)
    uid = int(market_user_id)
    intake = doc.get("intake_form") if isinstance(doc.get("intake_form"), dict) else {}
    company = str(intake.get("company") or doc.get("erp_customer_name") or "").strip()
    if company and not doc.get("erp_customer_name"):
        doc["erp_customer_name"] = company
    if company and not doc.get("erp_customer_id"):
        doc["erp_customer_id"] = uid
    if not doc.get("crm_opportunity_id"):
        doc["crm_opportunity_id"] = uid
    doc = sync_crm_from_pipeline_doc(doc)
    doc["crm_funnel_synced_at"] = _now_iso()
    doc = save_pipeline(doc)

    meta: dict[str, Any] = {
        "erp_linked": bool(doc.get("erp_customer_id") or doc.get("erp_customer_name")),
        "erp_customer_id": doc.get("erp_customer_id"),
        "erp_customer_name": doc.get("erp_customer_name"),
        "crm_funnel_synced_at": doc.get("crm_funnel_synced_at"),
        "crm_opportunity_id": doc.get("crm_opportunity_id"),
        "wechat_notice": {"sent": False},
    }
    if notify_wechat:
        try:
            from app.services.user_cs_intake_notice import maybe_send_intake_form_notice

            contact = str(intake.get("name") or company or username or "")
            out = maybe_send_intake_form_notice(
                uid, username=username, contact_name=contact, brief="", force=False
            )
            meta["wechat_notice"] = {"sent": bool(out.get("sent")), **out}
            if out.get("sent"):
                doc["intake_done_notice_sent"] = True
                doc = save_pipeline(doc)
        except OPERATIONAL_ERRORS:
            pass
    return doc, meta
