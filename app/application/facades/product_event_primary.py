"""
Event-primary facade for product mutations (create/update/delete/batch).
Read paths delegate to core via __getattr__.
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.facades.event_primary_base import EventPrimaryDispatcher
from app.application.product_app_service import ProductApplicationService
from app.contexts.flags import is_event_primary_enabled

logger = logging.getLogger(__name__)


class ProductApplicationServiceEventPrimary:
    def __init__(self, core: ProductApplicationService) -> None:
        self._core = core
        self._dispatcher = EventPrimaryDispatcher()

    def __getattr__(self, name: str):
        return getattr(self._core, name)

    def create_product(self, data: dict[str, Any]) -> dict[str, Any]:
        if not is_event_primary_enabled("product"):
            return self._core.create_product(data)
        payload = dict(data)
        payload.setdefault("product_name", data.get("name") or data.get("product_name"))
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("product.created", payload),
            lambda: self._core.create_product(data),
            log_label="product.create",
        )

    def update_product(self, product_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if not is_event_primary_enabled("product"):
            return self._core.update_product(product_id, data)
        payload = {"product_id": product_id, **dict(data)}
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command("product.updated", payload),
            lambda: self._core.update_product(product_id, data),
            log_label="product.update",
        )

    def delete_product(self, product_id: int) -> dict[str, Any]:
        if not is_event_primary_enabled("product"):
            return self._core.delete_product(product_id)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "product.deleted", {"product_id": product_id}
            ),
            lambda: self._core.delete_product(product_id),
            log_label="product.delete",
        )

    def batch_add_products(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        if not is_event_primary_enabled("product"):
            return self._core.batch_add_products(products)
        return self._dispatcher.run_command_with_fallback(
            self._dispatcher.dispatch_command(
                "product.imported",
                {"products": products, "count": len(products)},
            ),
            lambda: self._core.batch_add_products(products),
            log_label="product.batch_add",
        )
