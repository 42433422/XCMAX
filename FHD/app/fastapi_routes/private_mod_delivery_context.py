"""生产员工私有交付路由共享的账号、目录与同步上下文。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import HTTPException, Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


async def _private_mod_context(request: Request) -> dict[str, Any]:
    """读取**当前登录账号**可见的客户私有 Mod。

    规则（customer_delivery SSOT）：
    - 只暴露 ``legacy_mod_id``，不含 ``industry_mod_id``
    - 必须以当前会话 ``entitled_mod_ids`` 为准，禁止把交付清单里其它客户的定制包一并列出
    - 无会话 / 无权益 → 空列表（生产员工交付线不是全局客户目录）
    - 定制线通道身份取 sessions.market_user_id，写入 scope=market:{id}，与管理端对齐
    """
    from app.enterprise.mod_entitlements import (
        enterprise_mod_filter_active,
        sync_entitlements_from_request,
    )
    from app.enterprise.private_delivery_binding import load_session_private_delivery_binding
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.mod_sdk.customer_delivery import (
        delivery_for_account_custom_mod,
        list_account_custom_mod_ids,
        list_industry_mod_ids_from_delivery,
    )

    account_custom = list_account_custom_mod_ids()
    industry_packs = list_industry_mod_ids_from_delivery()
    sid = session_id_from_request(request) or ""

    binding: dict[str, Any] = {
        "mod_ids": set(),
        "market_user_id": None,
        "username": "",
        "company_brand": "",
    }
    if sid:
        # 企业 SKU：尽量向市场刷新；平台壳 generic 也按 sessions 行隔离。
        if enterprise_mod_filter_active():
            await sync_entitlements_from_request(request)
        binding = load_session_private_delivery_binding(sid)

    entitled = {
        mid
        for mid in (binding.get("mod_ids") or set())
        if str(mid).strip() in account_custom and str(mid).strip() not in industry_packs
    }
    # 共享运行模块的定制身份还必须属于当前账号，不能仅凭同名运行包推断。
    username = str(binding.get("username") or "").strip().casefold()
    entitled = {
        mid
        for mid in entitled
        if not (row := delivery_for_account_custom_mod(mid))
        or row.get("delivery_mode") != "integrated_feature"
        or str(row.get("customer_account") or "").strip().casefold() == username
    }
    return {
        "mod_ids": entitled,
        "market_user_id": binding.get("market_user_id"),
        "username": str(binding.get("username") or binding.get("company_brand") or "").strip(),
    }


def _enterprise_delivery_scope(context: dict[str, Any], mod_ids: set[str] | None = None) -> str:
    """企业端定制线写/读 scope：必须 market:{uid}，禁止静默落入 local:*。"""
    from app.application.private_mod_delivery_app import (
        account_scope,
        merge_orphan_local_delivery_into_market,
    )

    try:
        uid = int(context.get("market_user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise HTTPException(
            status_code=401,
            detail="企业端定制线缺少市场账号身份（sessions.market_user_id），请重新登录企业账号",
        )
    scope = account_scope(uid, _safe_text(context.get("username")))
    merge_orphan_local_delivery_into_market(scope, mod_ids or context.get("mod_ids") or set())
    return scope


def _schedule_delivery_outbox_push() -> None:
    """企业端 best-effort 后台推送同步 outbox（失败只记日志，不阻塞交付主流程）。"""

    def _push() -> None:
        try:
            from app.application.xcmax_sync_app import push_outbox

            result = push_outbox(
                remote_host=os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147"),
                remote_port=int(os.environ.get("XCMAX_REMOTE_PORT", "9999")),
            )
            logger.info("private Mod delivery outbox push: %s", result)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("private Mod delivery outbox push failed: %s", exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _push()
        return
    loop.run_in_executor(None, _push)


async def _private_delivery_market_token(request: Request) -> str:
    from app.fastapi_routes.market_account import resolve_valid_market_access_token
    from app.infrastructure.auth.dependencies import session_id_from_request

    sid = session_id_from_request(request)
    return await resolve_valid_market_access_token(sid) if sid else ""


def _private_mod_local_rows(mod_ids: set[str]) -> dict[str, dict[str, Any]]:
    from app.infrastructure.mods.mod_manager import get_mod_manager

    rows: dict[str, dict[str, Any]] = {}
    for row in get_mod_manager().list_all_mods():
        mid = str(row.get("id") or "").strip()
        if mid in mod_ids:
            rows[mid] = row
    return rows


def _private_mod_items(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in row.get("menu") or []:
        if not isinstance(item, dict):
            continue
        label = _safe_text(item.get("label") or item.get("name") or item.get("id"))
        if label and label not in seen:
            seen.add(label)
            modules.append({"id": _safe_text(item.get("id") or label), "label": label})
    for item in row.get("menu_overrides") or []:
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        label = _safe_text(item.get("label") or item.get("key"))
        if label and label not in seen:
            seen.add(label)
            modules.append({"id": _safe_text(item.get("key") or label), "label": label})
    employees = [
        {
            "id": _safe_text(item.get("id")),
            "label": _safe_text(item.get("label") or item.get("id")),
            "summary": _safe_text(item.get("panel_summary") or item.get("summary")),
        }
        for item in (row.get("workflow_employees") or [])
        if isinstance(item, dict) and _safe_text(item.get("id") or item.get("label"))
    ]
    return modules, employees


def _private_mod_declared_nodes(
    mod_id: str,
    row: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """优先 customer_delivery SSOT 双轨节点，空则回退 manifest menu / workflow_employees。"""
    from app.mod_sdk.customer_delivery import track_nodes_for_custom_mod

    declared = track_nodes_for_custom_mod(mod_id)
    modules = list(declared.get("modules") or [])
    employees = list(declared.get("employees") or [])
    if not modules and not employees:
        fallback_modules, fallback_employees = _private_mod_items(row)
        modules = fallback_modules
        employees = fallback_employees
    return {"modules": modules, "employees": employees}


__all__ = [
    "_enterprise_delivery_scope",
    "_private_delivery_market_token",
    "_private_mod_context",
    "_private_mod_declared_nodes",
    "_private_mod_items",
    "_private_mod_local_rows",
    "_safe_text",
    "_schedule_delivery_outbox_push",
]
