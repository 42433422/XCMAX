"""Track entitled MODs that are absent from the local runtime installation."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MISSING_LOCAL: set[str] = set()


def mark_mod_missing_locally(mod_id: str) -> None:
    """Record one durable runtime issue without repeating it on every poll."""
    if mod_id in _MISSING_LOCAL:
        return
    _MISSING_LOCAL.add(mod_id)
    from app.runtime_integrity import record_runtime_issue

    record_runtime_issue(
        f"industry_mod:{mod_id}",
        f"Industry MOD is entitled but not installed locally: {mod_id}",
        ttl_seconds=24 * 60 * 60,
    )
    logger.warning("entitled MOD is not installed locally: %s", mod_id)


def clear_mod_missing_locally(mod_id: str) -> None:
    _MISSING_LOCAL.discard(mod_id)
    from app.runtime_integrity import clear_runtime_issue

    clear_runtime_issue(f"industry_mod:{mod_id}")
