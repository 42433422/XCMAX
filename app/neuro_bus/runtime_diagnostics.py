"""NeuroBus subscription diagnostics at startup."""

from __future__ import annotations

import logging
from typing import Any

from app.neuro_bus.bus import NeuroBus

logger = logging.getLogger(__name__)


def log_subscription_snapshot(bus: NeuroBus) -> dict[str, Any]:
    summary = bus.summarize_subscriptions()
    flat = summary.get("flat_event_handlers") or {}
    logger.info(
        "NeuroBus subscription snapshot: %d flat event types, %d domain keys, global=%s",
        len(flat),
        len(summary.get("domain_handlers") or {}),
        summary.get("global_handlers"),
    )
    if flat:
        sample = dict(list(flat.items())[:40])
        logger.debug("NeuroBus flat handler counts (sample): %s", sample)
    return summary
