"""客户交付行业组合包的桌面升级自愈。"""

from __future__ import annotations

import logging
from typing import Any

from app.mod_sdk.customer_delivery import industry_id_for_account
from app.mod_sdk.industry_seed import (
    industry_seed_mod_ids_for,
    install_industry_seed_with_fallback,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


async def ensure_delivery_industry_bundle_for_account(account_username: str) -> dict[str, Any]:
    """为已登录客户账号补齐交付 SSOT 指定的行业组合包与运行时路由。

    桌面端升级会恢复既有会话，不会重新经过产品引导页。仅覆盖行业画像会造成
    “显示新行业、仍缺业务模块”的半迁移状态，因此在账号态拉取 Mod 列表前调用
    本函数，幂等地安装行业壳和 capability_mod_ids，并挂载各自 HTTP 路由。
    """
    username = str(account_username or "").strip()
    if not username:
        return {
            "success": True,
            "status": "skipped",
            "account_username": "",
            "industry_id": "",
            "installed_mod_ids": [],
            "route_ready_mod_ids": [],
        }

    industry_id = industry_id_for_account(username)
    if not industry_id:
        return {
            "success": True,
            "status": "not_customer_delivery_account",
            "account_username": username,
            "industry_id": "",
            "installed_mod_ids": [],
            "route_ready_mod_ids": [],
        }

    result = await install_industry_seed_with_fallback(industry_id)
    if not result.get("success"):
        return {
            **result,
            "account_username": username,
            "industry_id": industry_id,
            "route_ready_mod_ids": [],
        }

    bundle_ids = industry_seed_mod_ids_for(industry_id)
    route_ready: list[str] = []
    try:
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready, get_mod_manager

        # 刷新磁盘扫描，保证同一个 /api/mods/ 请求能看到刚复制的组合包。
        get_mod_manager().scan_mods(use_cache=False)
        for mod_id in bundle_ids:
            if ensure_mod_api_ready(mod_id):
                route_ready.append(mod_id)
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "delivery industry bundle route mount failed account=%s industry=%s: %s",
            username,
            industry_id,
            exc,
        )

    return {
        **result,
        "account_username": username,
        "industry_id": industry_id,
        "installed_mod_ids": bundle_ids,
        "route_ready_mod_ids": route_ready,
        "runtime_ready": set(route_ready) == set(bundle_ids),
    }


__all__ = ["ensure_delivery_industry_bundle_for_account"]
