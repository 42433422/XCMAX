"""Small, independently-owned scheduler registrations.

Keeping optional integrations here prevents the central scheduler bootstrap
from growing whenever an owned component needs a periodic job.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def register_extensions(
    scheduler: Any,
    *,
    track_job: Callable[[str, Callable[[], Any]], Any],
) -> None:
    try:
        from modstore_server.capability_proposal_relay import (
            register_capability_proposal_relay_job,
        )

        register_capability_proposal_relay_job(scheduler, track_job=track_job)
    except Exception:
        logger.exception("register capability proposal relay failed")
    try:
        from modstore_server.cs_webhook_outbox import register_retry_job

        register_retry_job(scheduler, track_job=track_job)
    except Exception:
        logger.exception("register cs webhook outbox retry failed")
