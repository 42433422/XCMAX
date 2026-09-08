"""Execute event handlers with retry, identity propagation and failure accounting."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.neuro_bus.bus_primitives import HandlerSubscription
from app.neuro_bus.delivery_metrics import record_delivery_metric
from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.neuro_bus.bus import NeuroBus

logger = logging.getLogger(__name__)


async def call_handler(bus: NeuroBus, subscription: HandlerSubscription, event: NeuroEvent) -> bool:
    """调用处理器；返回是否成功（无异常）。"""
    if bus._rel_circuit is not None and not bus._rel_circuit.can_execute():
        logger.warning("NeuroBus circuit open; skipping handler for %s", event.event_type)
        return False

    async def _invoke() -> None:
        if subscription.is_async:
            await subscription.handler(event)
        else:
            from contextvars import copy_context

            await asyncio.get_running_loop().run_in_executor(
                bus._executor, copy_context().run, subscription.handler, event
            )

    retry_count = 0
    try:
        if bus._rel_retry_handler is not None:
            domain = event.metadata.domain or "default"
            retry_handler = bus._rel_retry_handler.get_handler(domain)
            try:
                await retry_handler.execute(
                    _invoke,
                    operation_name=getattr(subscription.handler, "__name__", "handler"),
                )
            except RECOVERABLE_ERRORS:
                retry_count = retry_handler._config.max_retries  # noqa: SLF001
                raise
        else:
            await _invoke()
        subscription.record_call(success=True)
        if bus._rel_circuit is not None:
            bus._rel_circuit.record_success()

    except RECOVERABLE_ERRORS as e:
        logger.exception("Handler error for event %s: %s", event, e)
        subscription.record_call(success=False)
        bus._error_count += 1
        if bus._rel_circuit is not None:
            bus._rel_circuit.record_failure()
        if bus._dlq_integration is not None:
            try:
                bus._dlq_integration.handle_failure(
                    event,
                    e,
                    retry_count=retry_count,
                    handler_name=getattr(subscription.handler, "__name__", None),
                )
                record_delivery_metric(bus._enable_metrics, "dead_lettered")
            except RECOVERABLE_ERRORS as dlq_exc:
                logger.exception("NeuroBus DLQ enqueue failed: %s", dlq_exc)
                record_delivery_metric(bus._enable_metrics, "lost")
        return False
    return True

