"""private_mod_delivery entity applier (split from xcmax_sync_service)."""

from __future__ import annotations

import logging
from typing import Any

from app.services.xcmax_sync_service import register_entity_applier
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


@register_entity_applier("private_mod_delivery")
def _apply_private_mod_delivery(item: dict[str, Any]) -> None:
    """客户私有 Mod 交付快照：同步到管理端可查询的账号状态文件。"""
    payload = item.get("payload") or {}
    if not isinstance(payload, dict):
        return
    entity_id = str(payload.get("market_user_id") or item.get("entity_id") or "").strip()
    if not entity_id:
        return
    try:
        from app.application.private_mod.delivery import account_scope, apply_account_state

        apply_account_state(
            account_scope(int(entity_id), str(payload.get("username") or "")),
            payload,
        )
    except OPERATIONAL_ERRORS as exc:
        logger.warning("apply_private_mod_delivery failed user=%s: %s", entity_id, exc)
