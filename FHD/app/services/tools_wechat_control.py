"""Account-scoped WeChat reads and receipt-backed collector refreshes."""

from __future__ import annotations

import time
import uuid

from app.application.agent_orchestrator.execution_identity import current_execution_actor
from app.application.wechat_ingest_service import build_contact_context, list_wechat_contacts
from app.application.wechat_refresh_service import ACTIONS, get_refresh, request_refresh
from app.infrastructure.tenant_scope import current_tenant_id


def execute_wechat_control(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    actor = current_execution_actor()
    tenant = current_tenant_id()
    if not actor or tenant is None or tenant <= 0:
        return {
            "success": False,
            "error_code": "identity_required",
            "message": "缺少已验证的账号或租户",
        }
    # Model parameters and raw _runtime_context never grant tenant/account access.
    for key, expected in (("tenant_id", str(tenant)), ("user_id", actor), ("actor_id", actor)):
        if key in params and str(params[key]) != expected:
            return {
                "success": False,
                "error_code": "scope_mismatch",
                "message": "不能访问其他账号或租户",
            }
    if action in {"view", "list", "query"}:
        request_id = str(params.get("request_id") or "")
        if request_id:
            status = get_refresh(tenant, actor, request_id)
            if status is None:
                return {"success": False, "error_code": "not_found", "message": "刷新请求不存在"}
            return {"success": True, "data": status, "message": "已查询刷新状态"}
        try:
            limit = max(1, min(int(params.get("limit", 100)), 500))
        except (ValueError, TypeError):
            return {"success": False, "error_code": "invalid_limit", "message": "limit 必须是整数"}
        contact_key = str(params.get("contact_key") or "").strip()
        if contact_key:
            return build_contact_context(contact_key, tenant_id=tenant, limit=limit)
        return list_wechat_contacts(tenant_id=tenant, limit=limit)
    if action not in ACTIONS:
        return {"success": False, "error_code": "unsupported_action", "message": "未知微信动作"}
    key = str(
        params.get("request_key") or runtime_context.get("idempotency_key") or uuid.uuid4().hex
    )
    try:
        result = request_refresh(tenant, actor, action, key)
    except ValueError as exc:
        return {"success": False, "error_code": "refresh_conflict", "message": str(exc)}
    deadline = time.monotonic() + 10
    while result["state"] in {"pending", "running"} and time.monotonic() < deadline:
        time.sleep(0.2)
        result = get_refresh(tenant, actor, result["request_id"]) or result
    if result["completed"]:
        return {
            "success": True,
            "data": result,
            "message": "采集端已完成配置范围内的刷新并返回结果",
        }
    return {
        "success": False,
        "error_code": "wechat_refresh_" + result["state"],
        "message": "刷新尚未完成；请通过 request_id 查询采集端回执",
        "data": result,
        "request_key": key,
    }
