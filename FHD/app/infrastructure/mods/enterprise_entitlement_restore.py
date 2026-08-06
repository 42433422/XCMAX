"""Restore enterprise MOD entitlements from a persisted server session."""

import logging

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def restore_entitlements_from_session_id(session_id: str | None) -> None:
    """Recover the entitlement cache required before a protected MOD route mounts."""
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        from app.enterprise.mod_entitlements import (
            _augment_entitled_for_username,
            _session_username_for_entitlements,
            get_cached_entitled_client_mod_ids,
            get_cached_market_identity,
            restore_entitlements_from_session_row,
            set_session_entitlements,
        )

        restore_entitlements_from_session_row(sid)
        username = _session_username_for_entitlements(sid)
        market_user_id, market_username = get_cached_market_identity()
        entitled_ids = _augment_entitled_for_username(
            username, get_cached_entitled_client_mod_ids() or set()
        )
        if entitled_ids:
            set_session_entitlements(
                market_user_id=market_user_id,
                market_username=username or market_username,
                entitled_client_mod_ids=entitled_ids,
            )
    except RECOVERABLE_ERRORS:
        logger.debug("restore entitlements from session failed", exc_info=True)
