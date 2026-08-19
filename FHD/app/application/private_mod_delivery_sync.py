"""XCmax inbox 对客户私有交付快照的应用器。"""

from __future__ import annotations

import logging
from typing import Any

from app.application.private_mod_delivery_app import account_scope, apply_account_state
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def apply_private_mod_delivery(item: dict[str, Any]) -> None:
    payload = item.get("payload") or {}
    if not isinstance(payload, dict):
        return
    entity_id = str(payload.get("market_user_id") or item.get("entity_id") or "").strip()
    if not entity_id:
        return
    try:
        apply_account_state(
            account_scope(int(entity_id), str(payload.get("username") or "")),
            payload,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("apply_private_mod_delivery failed user=%s: %s", entity_id, exc)


__all__ = ["apply_private_mod_delivery"]
