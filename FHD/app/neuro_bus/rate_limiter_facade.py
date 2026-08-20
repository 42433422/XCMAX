"""Public NeuroBus facade behavior for the dynamic rate limiter."""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Protocol, cast

from app.neuro_bus.events.base import NeuroEvent

logger = logging.getLogger(__name__)


class _LimiterFactory(Protocol):
    def __call__(self, *, default_config: Any) -> Any: ...


class NeuroRateLimiterMixin:
    """Facade methods shared by the concrete limiter declared in the public module."""

    DOMAIN_LIMITS: ClassVar[dict[str, Any]]
    DYNAMIC_LIMITER_CLASS: ClassVar[_LimiterFactory]

    def __init__(self) -> None:
        self._limiter = self.DYNAMIC_LIMITER_CLASS(default_config=self.DOMAIN_LIMITS["default"])
        for domain, config in self.DOMAIN_LIMITS.items():
            if domain != "default":
                self._limiter.set_domain_limit(domain, config)

    def check_rate(self, event: NeuroEvent) -> bool:
        """Return whether an event passes rate limiting."""
        return cast("bool", self._limiter.allow(event))

    def try_check_rate(self, event: NeuroEvent) -> tuple[bool, float]:
        """Return the decision and non-blocking wait duration."""
        return cast("tuple[bool, float]", self._limiter.try_allow(event))

    def set_domain_limit(self, domain: str, config: Any) -> None:
        self._limiter.set_domain_limit(domain, config)
        logger.info("NeuroRateLimiter domain [%s] config updated", domain)

    def set_event_limit(self, event_type: str, config: Any) -> None:
        self._limiter.set_event_limit(event_type, config)
        logger.info("NeuroRateLimiter event [%s] config updated", event_type)

    def change_default_limit(self, new_rps: float) -> None:
        self._limiter.change_limit_for_period(new_rps)

    def change_default_burst(self, new_burst: int) -> None:
        self._limiter.change_burst_size(new_burst)

    def drain_domain(self, domain: str) -> None:
        self._limiter.drain_domain(domain)

    def drain_event(self, event_type: str) -> None:
        self._limiter.drain_event(event_type)

    def get_stats(self) -> dict:
        return cast("dict[Any, Any]", self._limiter.get_stats())

    def get_all_metrics(self) -> dict:
        base = self._limiter.get_stats()
        return {
            "allowed": base["allowed"],
            "rejected": base["rejected"],
            "available_tokens": base["available_tokens"],
            "wait_time_avg": base["wait_time_avg"],
            "config_snapshot": base["config_snapshot"],
            "global": base,
            "domains": base["domain_stats"],
            "event_types": base["event_stats"],
        }
