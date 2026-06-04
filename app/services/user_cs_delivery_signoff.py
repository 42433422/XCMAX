"""客户交付签收：持久化 + 触发已交付/对账/开票。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _backend_module():
    from app.infrastructure.cs.delivery_signoff_sot import is_postgres_signoff_sot

    if is_postgres_signoff_sot():
        from app.infrastructure.cs import delivery_signoff_pg as mod

        return mod
    from app.infrastructure.cs import delivery_signoff_sqlite as mod

    return mod


def ensure_signoff_schema() -> None:
    _backend_module().ensure_schema()


def signoff_backend_info() -> dict[str, Any]:
    from app.infrastructure.cs.delivery_signoff_sot import (
        is_postgres_signoff_sot,
        signoff_storage_hint,
    )

    mod = _backend_module()
    count = 0
    try:
        count = int(mod.count_rows())
    except Exception:
        logger.debug("signoff count failed", exc_info=True)
    return {
        "backend": "postgres" if is_postgres_signoff_sot() else "sqlite",
        "storage": signoff_storage_hint(),
        "row_count": count,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_signoff_request(
    market_user_id: int,
    *,
    username: str = "",
    signed_by: str = "",
    notes: str = "",
) -> dict[str, Any]:
    from app.services.user_cs_crm_store import ensure_crm_schema, get_opportunity_by_market_user
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    ensure_crm_schema()
    ensure_signoff_schema()
    uid = int(market_user_id)
    doc = load_pipeline(uid, username=username)
    opp = get_opportunity_by_market_user(uid)
    if not opp:
        raise ValueError("请先同步 CRM 商机")
    opp_id = int(opp["id"])
    now = _now_iso()
    mod = _backend_module()
    from app.infrastructure.cs.delivery_signoff_sot import is_postgres_signoff_sot

    if is_postgres_signoff_sot():
        from datetime import datetime as dt

        created = dt.fromisoformat(now.replace("Z", "+00:00")).replace(tzinfo=None)
        sid = mod.insert_pending(
            opportunity_id=opp_id,
            market_user_id=uid,
            signed_by=signed_by,
            notes=notes,
            created_at=created,
        )
    else:
        sid = mod.insert_pending(
            opportunity_id=opp_id,
            market_user_id=uid,
            signed_by=signed_by,
            notes=notes,
            created_at=now,
        )
    doc["delivery_signoff"] = {"id": sid, "status": "pending", "created_at": now}
    doc = save_pipeline(doc)
    return {"signoff_id": sid, "pipeline": doc}


def confirm_signoff(
    signoff_id: int,
    *,
    market_user_id: int,
    username: str = "",
    attachment_url: str = "",
) -> dict[str, Any]:
    from app.services.operations_line_bridge import emit_operations_event
    from app.services.user_cs_pipeline import set_pipeline_stage

    ensure_signoff_schema()
    uid = int(market_user_id)
    now = _now_iso()
    mod = _backend_module()
    from app.infrastructure.cs.delivery_signoff_sot import is_postgres_signoff_sot

    if is_postgres_signoff_sot():
        from datetime import datetime as dt

        signed = dt.fromisoformat(now.replace("Z", "+00:00")).replace(tzinfo=None)
        ok = mod.confirm_row(
            signoff_id=int(signoff_id),
            market_user_id=uid,
            attachment_url=attachment_url,
            signed_at=signed,
        )
    else:
        ok = mod.confirm_row(
            signoff_id=int(signoff_id),
            market_user_id=uid,
            attachment_url=attachment_url,
            signed_at=now,
        )
    if not ok:
        raise ValueError("签收记录不存在或无权确认")
    doc = set_pipeline_stage(
        uid, "delivered", username=username, source="signoff", note="customer_accepted"
    )
    doc["delivery_signoff"] = {"id": signoff_id, "status": "signed", "signed_at": now}
    try:
        from app.services.user_cs_software_delivery import notify_software_delivery

        sw = notify_software_delivery(uid, username=username)
        if sw.get("ok"):
            doc = sw.get("pipeline") or doc
        elif sw.get("error"):
            doc = dict(doc)
            doc["software_delivery_last_error"] = str(sw.get("error") or "")[:300]
            from app.services.user_cs_pipeline import save_pipeline

            doc = save_pipeline(doc)
    except Exception:
        logger.debug("auto software delivery on signoff skipped", exc_info=True)
    emit_operations_event("O8", "completed", {"market_user_id": uid, "signoff_id": signoff_id})
    try:
        emit_operations_event("O10", "reconciliation_preview", {"market_user_id": uid})
    except Exception:
        logger.debug("reconciliation preview skipped", exc_info=True)
    return {"pipeline": doc, "signoff_id": signoff_id}


def list_signoffs_for_market_user(market_user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    ensure_signoff_schema()
    mod = _backend_module()
    if hasattr(mod, "list_for_market_user"):
        return mod.list_for_market_user(int(market_user_id), limit=limit)
    return []
