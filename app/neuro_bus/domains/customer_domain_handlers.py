"""
Customer 领域事件处理器 — HTTP event-primary 命令落库与 CommandGateway 回填。
"""

from __future__ import annotations

import logging
from typing import Any

from app.bootstrap import get_customer_application_service_core
from app.neuro_bus.command_gateway import try_complete_command_reply
from app.neuro_bus.events.base import NeuroEvent

logger = logging.getLogger(__name__)


class CustomerDomainHandlers:
    async def handle_registered(self, event: NeuroEvent) -> dict[str, Any]:
        core = get_customer_application_service_core()
        p = event.payload
        data = {
            "customer_name": p.get("customer_name") or p.get("unit_name"),
            "contact_person": p.get("contact_person", ""),
            "contact_phone": p.get("contact_phone") or p.get("phone", ""),
            "contact_address": p.get("contact_address") or p.get("address", ""),
        }
        try:
            result = core.create(data)
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[CustomerDomain] 注册失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_updated(self, event: NeuroEvent) -> dict[str, Any]:
        core = get_customer_application_service_core()
        try:
            cid = int(event.payload.get("customer_id"))
            updates = event.payload.get("updates") or {}
            result = core.update(cid, updates)
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[CustomerDomain] 更新失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_deactivated(self, event: NeuroEvent) -> dict[str, Any]:
        core = get_customer_application_service_core()
        try:
            cid = int(event.payload.get("customer_id"))
            force = bool(event.payload.get("force"))
            result = core.delete(cid, force=force)
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[CustomerDomain] 停用失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_batch_deactivated(self, event: NeuroEvent) -> dict[str, Any]:
        core = get_customer_application_service_core()
        try:
            ids = [int(x) for x in (event.payload.get("customer_ids") or [])]
            force = bool(event.payload.get("force"))
            result = core.batch_delete(ids, force=force)
            try_complete_command_reply(event, result)
            return result
        except Exception as e:
            logger.exception("[CustomerDomain] 批量停用失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise


_handlers: CustomerDomainHandlers | None = None


def get_customer_domain_handlers() -> CustomerDomainHandlers:
    global _handlers
    if _handlers is None:
        _handlers = CustomerDomainHandlers()
    return _handlers


def register_customer_domain_handlers(bus) -> None:
    h = get_customer_domain_handlers()
    bus.subscribe("customer.registered", h.handle_registered)
    bus.subscribe("customer.updated", h.handle_updated)
    bus.subscribe("customer.deactivated", h.handle_deactivated)
    bus.subscribe("customer.batch_deactivated", h.handle_batch_deactivated)
    logger.info("[CustomerDomain] 所有事件处理器已注册")
