"""官网匿名/未绑定联系表单 → CRM 线索漏斗（无 market_user_id 时用 landing_contact_id 建档）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_code(landing_contact_id: int) -> str:
    return f"XC-{int(landing_contact_id):06d}"


def sync_anonymous_landing_to_crm(submission: dict[str, Any]) -> dict[str, Any]:
    """未关联企业账户的落地页提交：按 landing_contact_id 写入 CRM 线索表。"""
    from app.services.user_cs_crm_store import _connect, _row_to_dict, ensure_crm_schema

    lid = int(submission.get("landing_contact_id") or 0)
    if lid <= 0:
        raise ValueError("landing_contact_id required")

    ensure_crm_schema()
    company = str(submission.get("company") or "").strip()
    contact_name = str(submission.get("name") or "").strip()
    title = company or contact_name or f"官网线索#{lid}"
    audit = _audit_code(lid)
    now = _now_iso()
    meta = {
        "source": str(submission.get("intake_source") or submission.get("source") or "landing"),
        "intake_submitted_at": submission.get("submitted_at") or now,
        "anonymous_lead": True,
    }
    # Negative market_user_id: one orphan lead per landing_contact_id under UNIQUE(market_user_id).
    synthetic_uid = -lid

    with _connect() as conn:
        by_landing = conn.execute(
            "SELECT id, market_user_id FROM cs_crm_opportunities WHERE landing_contact_id = ?",
            (lid,),
        ).fetchone()
        if by_landing:
            opp_id = int(by_landing["id"])
            conn.execute(
                """
                UPDATE cs_crm_opportunities SET
                  stage = COALESCE(NULLIF(stage, ''), 'intake_done'),
                  title = ?, company = ?, contact_name = ?,
                  contact_email = ?, contact_phone = ?, intake_message = ?,
                  audit_code = ?, meta_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title[:256],
                    company[:256],
                    contact_name[:128],
                    str(submission.get("email") or "")[:256],
                    str(submission.get("phone") or "")[:64],
                    str(submission.get("message") or "")[:8000],
                    audit,
                    json.dumps(meta, ensure_ascii=False),
                    now,
                    opp_id,
                ),
            )
        else:
            existing_uid = conn.execute(
                "SELECT id FROM cs_crm_opportunities WHERE market_user_id = ?",
                (synthetic_uid,),
            ).fetchone()
            if existing_uid:
                opp_id = int(existing_uid["id"])
                conn.execute(
                    """
                    UPDATE cs_crm_opportunities SET
                      landing_contact_id = ?, stage = 'intake_done',
                      title = ?, company = ?, contact_name = ?,
                      contact_email = ?, contact_phone = ?, intake_message = ?,
                      audit_code = ?, meta_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        lid,
                        title[:256],
                        company[:256],
                        contact_name[:128],
                        str(submission.get("email") or "")[:256],
                        str(submission.get("phone") or "")[:64],
                        str(submission.get("message") or "")[:8000],
                        audit,
                        json.dumps(meta, ensure_ascii=False),
                        now,
                        opp_id,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO cs_crm_opportunities (
                      market_user_id, landing_contact_id, erp_customer_id, stage,
                      title, company, contact_name, contact_email, contact_phone,
                      intake_message, audit_code, owner_username, meta_json,
                      created_at, updated_at
                    ) VALUES (?, ?, NULL, 'intake_done', ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                    """,
                    (
                        synthetic_uid,
                        lid,
                        title[:256],
                        company[:256],
                        contact_name[:128],
                        str(submission.get("email") or "")[:256],
                        str(submission.get("phone") or "")[:64],
                        str(submission.get("message") or "")[:8000],
                        audit,
                        json.dumps(meta, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                opp_id = int(cur.lastrowid)
        conn.commit()
        out = conn.execute("SELECT * FROM cs_crm_opportunities WHERE id = ?", (opp_id,)).fetchone()
    row = _row_to_dict(out) or {}
    row["crm_funnel_synced_at"] = now
    return row


def apply_landing_submission_to_funnel(
    submission: dict[str, Any],
    *,
    username: str = "",
    notify_wechat: bool = True,
) -> dict[str, Any]:
    """有 market_user_id 走 Pipeline+CRM；否则仅 CRM 线索。"""
    uid = int(submission.get("market_user_id") or 0)
    if uid > 0:
        from app.services.user_cs_demand_form import apply_landing_submission_to_pipeline

        doc = apply_landing_submission_to_pipeline(
            uid, submission, username=username, notify_wechat=notify_wechat
        )
        try:
            from app.services.operations_line_bridge import emit_operations_event

            emit_operations_event(
                "O1",
                "completed",
                {
                    "market_user_id": uid,
                    "landing_contact_id": submission.get("landing_contact_id"),
                    "stage": doc.get("stage"),
                },
            )
        except Exception:
            logger.debug("operations O1 event skipped", exc_info=True)
        return doc
    crm = sync_anonymous_landing_to_crm(submission)
    out = {
        "stage": "intake_done",
        "crm_opportunity_id": crm.get("id"),
        "landing_contact_id": submission.get("landing_contact_id"),
        "anonymous_lead": True,
    }
    try:
        from app.services.operations_line_bridge import emit_operations_event

        emit_operations_event(
            "O1",
            "completed",
            {
                "landing_contact_id": submission.get("landing_contact_id"),
                "anonymous_lead": True,
                "crm_opportunity_id": crm.get("id"),
            },
        )
    except Exception:
        logger.debug("operations O1 anonymous event skipped", exc_info=True)
    return out
