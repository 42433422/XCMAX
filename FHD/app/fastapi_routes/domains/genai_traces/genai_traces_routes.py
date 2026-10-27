"""GenAI (LLM) 调用链路只读查询 API（管理员专用）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.infrastructure.auth.dependencies import get_logged_in_user

router = APIRouter(prefix="/api/admin/genai", tags=["admin-genai"])


def _require_admin_user(user=Depends(get_logged_in_user)):
    role = str(getattr(user, "role", "") or "").lower()
    if role not in {"admin", "superadmin"}:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail={"message": {"code": "FORBIDDEN", "message": "需要管理员权限"}},
        )
    return user


@router.get("/traces")
def list_genai_traces(
    request: Request,
    trace_id: str | None = Query(None),
    model: str | None = Query(None),
    status: str | None = Query(None),
    since: float | None = Query(None),
    until: float | None = Query(None),
    has_guardrail_block: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _admin=Depends(_require_admin_user),
):
    """按条件查询本地 JSONL 存储的 GenAI span（按 start_time 倒序）。"""
    from app.infrastructure.llm.trace_store import get_trace_store

    items = get_trace_store().query(
        trace_id=trace_id,
        model=model,
        status=status,
        since=since,
        until=until,
        has_guardrail_block=has_guardrail_block,
        limit=limit,
    )
    return JSONResponse({"success": True, "data": {"items": items, "total": len(items)}})
