"""FHD 元信息接口（令牌状态等）。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/fhd", tags=["fhd"])


@router.get("/db-tokens/status")
def db_tokens_status() -> dict:
    try:
        from app.request_active_mod_ctx import get_request_active_mod_id

        active_mod_id = str(get_request_active_mod_id() or "").strip()
    except Exception:
        active_mod_id = ""
    from app.infrastructure.auth.db_token import (
        configured_db_read_token,
        configured_db_write_token,
    )

    read_t = str(configured_db_read_token(active_mod_id) or "").strip()
    write_t = str(configured_db_write_token(active_mod_id) or "").strip()
    return {
        "read_token_configured": bool(read_t),
        "write_token_configured": bool(write_t),
        "active_mod_id": active_mod_id,
    }
