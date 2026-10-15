"""Owner work-order review endpoints mounted under the autonomy router."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def _owner_meta(request: Request) -> dict[str, Any] | None:
    from app.application.session_account_meta import load_session_account_meta
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) if sid else None
    owner_id = str(os.environ.get("FHD_BOSS_USER_ID") or "").strip()
    if not owner_id.isdigit() or str((meta or {}).get("local_user_id") or "") != owner_id:
        return None
    return meta if meta and meta.get("impersonating_market_user_id") is None else None


@router.get("/work-orders")
async def owner_work_orders(request: Request, limit: int = 200) -> Any:
    from app.application.work_order_review_service import list_owner_work_orders
    from app.fastapi_routes.xcmax_admin_auth import require_market_admin_session

    denied = require_market_admin_session(request)
    if denied is not None:
        return denied
    items = list_owner_work_orders(limit, is_owner=_owner_meta(request) is not None)
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/work-orders/{wo_id}/owner-decision")
async def owner_work_order_decision(wo_id: str, request: Request) -> Any:
    from app.application.work_order_review_service import decide_owner_work_order
    from app.fastapi_routes.xcmax_admin_auth import (
        admin_approver_from_session,
        require_market_admin_session,
    )

    denied = require_market_admin_session(request)
    if denied is not None:
        return denied
    meta = _owner_meta(request)
    if meta is None:
        raise HTTPException(status_code=403, detail="仅 Owner 本人可执行工单决策")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    decision = str(body.get("decision") or "").strip().lower()
    if decision not in {"approved", "rejected", "held"}:
        raise HTTPException(status_code=400, detail="decision 必须为 approved、rejected 或 held")
    actor = admin_approver_from_session(request)
    result = decide_owner_work_order(
        wo_id,
        decision,
        local_user_id=meta["local_user_id"],
        actor=actor,
        note=str(body.get("note") or ""),
    )
    if result.get("reason") == "unknown_work_order":
        raise HTTPException(status_code=404, detail="工单不存在")
    if result.get("reason") == "gates_incomplete":
        raise HTTPException(
            status_code=409, detail="工单必须先通过 RED、GREEN 和 Owner Instance 验证"
        )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail="Owner 决策未写入共享工单")
    return {"ok": True, "wo_id": wo_id, "decision": decision, "actor": actor, "receipt": result}
