"""官网落地页提交 → pipeline / CRM 漏斗。"""

from __future__ import annotations

from typing import Any


def apply_landing_submission_to_funnel(
    payload: dict[str, Any],
    *,
    notify_wechat: bool = False,
) -> dict[str, Any]:
    from app.services.user_cs_demand_form import apply_landing_submission_to_pipeline
    from app.services.user_cs_intake_finalize import finalize_intake_submission

    uid = int(payload.get("market_user_id") or 0)
    if uid <= 0:
        return {
            "anonymous_lead": True,
            "crm_opportunity_id": None,
            "landing_contact_id": payload.get("landing_contact_id"),
        }
    doc = apply_landing_submission_to_pipeline(payload)
    if doc.get("intake_submitted_at") and not doc.get("crm_funnel_synced_at"):
        doc, _ = finalize_intake_submission(uid, doc, notify_wechat=notify_wechat)
    return doc
