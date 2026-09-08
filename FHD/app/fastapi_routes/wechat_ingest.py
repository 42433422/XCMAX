"""微信聊天记录摄取回流路由（本机 → 服务器 → 本机，AI 第一载体基建）。

认证与 ops_autonomy 同源：AUTONOMY_WEBHOOK_TOKEN / MODSTORE_OPS_INGEST_TOKEN
或管理端 admin session 旁路；CSRF 豁免见 app/middleware/csrf.py。
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.application.wechat_ingest_service import (
    build_contact_context,
    ingest_wechat_payload,
    link_wechat_contact,
    list_wechat_contacts,
)
from app.utils.operational_errors import BOUNDARY_ERRORS

router = APIRouter(prefix="/api/ops/wechat", tags=["ops-wechat"])


def _expected_token() -> str:
    return (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()


def _auth(
    authorization: str | None,
    x_wechat_token: str | None,
    request: Request | None = None,
) -> None:
    # admin session 旁路：管理端浏览器访问时放行
    if request is not None:
        try:
            from app.enterprise.mod_entitlements import is_admin_account_session

            if is_admin_account_session():
                return
        except BOUNDARY_ERRORS:  # 旁路探测失败回落 webhook token（认证旁路边界）
            pass
    expected = _expected_token()
    supplied = str(x_wechat_token or "").strip()
    bearer = str(authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        supplied = bearer[7:].strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid wechat sync token")


@router.post("/ingest")
async def wechat_ingest(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_wechat_token: str | None = Header(default=None, alias="X-Wechat-Token"),
) -> dict[str, Any]:
    """本机批量上行：联系人 + 消息（幂等），响应内含各联系人上下文（回流第二载体）。"""
    _auth(authorization, x_wechat_token)
    return ingest_wechat_payload(payload)


@router.get("/context")
async def wechat_context(
    contact_key: str,
    limit: int = 30,
    tenant_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_wechat_token: str | None = Header(default=None, alias="X-Wechat-Token"),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """查询单个联系人的客户情报（身份绑定 + 档案 + 最近消息）。"""
    _auth(authorization, x_wechat_token, request)
    return build_contact_context(contact_key, tenant_id=tenant_id, limit=limit)


@router.get("/contacts")
async def wechat_contacts(
    tenant_id: int | None = None,
    limit: int = 200,
    authorization: str | None = Header(default=None),
    x_wechat_token: str | None = Header(default=None, alias="X-Wechat-Token"),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """联系人映射列表（管理端用）。"""
    _auth(authorization, x_wechat_token, request)
    return list_wechat_contacts(tenant_id=tenant_id, limit=limit)


@router.post("/contacts/{contact_key}/link")
async def wechat_contact_link(
    contact_key: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_wechat_token: str | None = Header(default=None, alias="X-Wechat-Token"),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """管理端人工绑定联系人 → 客户。"""
    _auth(authorization, x_wechat_token, request)
    raw = payload.get("customer_id")
    if raw is None:
        raise HTTPException(status_code=400, detail="customer_id required") from None
    try:
        customer_id = int(str(raw))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="customer_id must be int") from None
    return link_wechat_contact(contact_key, customer_id)
