"""Resolve recent shipment products for a customer unit."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _normalize_unit_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
    return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)


def resolve_products_for_unit(unit_name: str, *, limit: int = 1) -> list[dict[str, Any]]:
    """Use a customer's latest shipment when a print request omits products."""
    name = str(unit_name or "").strip()
    if not name:
        return []
    try:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
        getter = getattr(svc, "get_latest_products_for_unit", None)
        if callable(getter):
            rows = getter(name, limit=limit)
            if isinstance(rows, list) and rows:
                return list(rows)
        unit_token = _normalize_unit_token(name)
        for order in svc.get_orders(20) or []:
            if not isinstance(order, dict):
                continue
            customer = str(
                order.get("customer_name")
                or order.get("unit_name")
                or order.get("purchase_unit")
                or ""
            ).strip()
            cust_token = _normalize_unit_token(customer)
            if customer and (
                customer == name
                or name in customer
                or customer in name
                or (unit_token and cust_token and unit_token in cust_token)
            ):
                items = order.get("products") or order.get("items") or []
                if isinstance(items, list) and items:
                    return list(items)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("resolve_products_for_unit failed: %s", exc, exc_info=True)
    return []
