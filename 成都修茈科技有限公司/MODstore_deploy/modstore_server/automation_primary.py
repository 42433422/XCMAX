"""日更自动化主跑机归属：Mac 主跑 digest/编排，服务器跟 git + 对外 API。"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def automation_primary_target() -> str:
    return (os.environ.get("MODSTORE_AUTOMATION_PRIMARY") or "").strip().lower()


def automation_local_role() -> str:
    return (os.environ.get("MODSTORE_AUTOMATION_ROLE") or "").strip().lower()


def is_daily_automation_delegated() -> bool:
    """本机是否应跳过 08:00 摘要 / 08:15–08:25 编排（委托给 MODSTORE_AUTOMATION_PRIMARY）。"""
    target = automation_primary_target()
    if not target or target in ("self", "local", "here", "this"):
        return False
    role = automation_local_role()
    if not role:
        return False
    return role != target


def skip_daily_automation_result(*, job: str) -> Optional[Dict[str, Any]]:
    """若应委托给主跑机，返回 skipped dict；否则 None。"""
    if not is_daily_automation_delegated():
        return None
    payload = {
        "ok": True,
        "skipped": True,
        "reason": "delegated_to_automation_primary",
        "job": job,
        "primary": automation_primary_target(),
        "role": automation_local_role(),
    }
    logger.info(
        "daily automation %s skipped — primary=%s role=%s",
        job,
        payload["primary"],
        payload["role"],
    )
    return payload
