"""Small, independently-owned scheduler registrations.

Keeping optional integrations here prevents the central scheduler bootstrap
from growing whenever an owned component needs a periodic job.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def register_extensions(
    scheduler: Any,
    *,
    track_job: Callable[[str, Callable[[], Any]], Any],
) -> None:
    from importlib import import_module

    for module, register in (
        ("capability_proposal_relay", "register_capability_proposal_relay_job"),
        ("cs_webhook_outbox", "register_retry_job"),
        ("incident_team_completion", "register_completion_job"),
    ):
        try:
            getattr(import_module(f"modstore_server.{module}"), register)(
                scheduler, track_job=track_job
            )
        except RECOVERABLE_ERRORS:
            logger.exception("register %s failed", module)
