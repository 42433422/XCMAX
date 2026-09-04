"""Lifecycle boundary for the authenticated paid-asset desktop worker."""

from __future__ import annotations

import logging

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def start_paid_asset_installs() -> None:
    """Start the worker when this process is an eligible installed desktop."""
    try:
        from app.desktop_runtime.asset_install_scheduler import start_asset_install_scheduler

        start_asset_install_scheduler()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("paid asset install scheduler skipped: %s", exc)


async def stop_paid_asset_installs() -> None:
    """Stop and await the worker without breaking the remaining shutdown path."""
    try:
        from app.desktop_runtime.asset_install_scheduler import stop_asset_install_scheduler

        await stop_asset_install_scheduler()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("paid asset install scheduler shutdown skipped: %s", exc)
