"""Preview-state construction for linked customer/product imports."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from app.application.etl.targets.base import json_safe
from app.application.etl.targets.customer_product_support import customer_values, owned_query
from app.application.etl.targets.helpers import model_values, optional_text
from app.application.etl.targets.products import ProductAdapter
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit


class CustomerProductPreviewMixin:
    """Build deterministic in-file and database match state for the aggregate."""

    _customer_fields: frozenset[str]
    _product_fields: frozenset[str]

    def _customer_data(self, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _product_data(self, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _customer_preview_state(
        self,
        db: Session,
        data: dict[str, Any],
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("customer_product_customer_by_name")
        if index is None:
            index = {
                str(item.unit_name): {
                    "id": item.id,
                    "before": customer_values(item),
                    "after": customer_values(item),
                    "is_new": False,
                }
                for item in owned_query(db, PurchaseUnit).all()
            }
            cache["customer_product_customer_by_name"] = index
        name = str(data.get("customer_name") or "").strip()
        state = index.get(name)
        if state is None:
            after = {
                "customer_name": name,
                "contact_person": optional_text(data.get("contact_person")),
                "contact_phone": optional_text(data.get("contact_phone")),
                "contact_address": optional_text(data.get("contact_address")),
            }
            state = {
                "id": None,
                "before": {},
                "after": after,
                "is_new": True,
                "input_values": {},
            }
            index[name] = state
        input_values = state.setdefault("input_values", {})
        conflicts: list[dict[str, Any]] = []
        for key, value in self._customer_data(data).items():
            if key == "customer_name":
                continue
            previous = input_values.get(key)
            if previous not in (None, "") and str(previous) != str(value):
                conflicts.append(
                    {
                        "code": "ETL_PARENT_FIELDS_CONFLICT",
                        "field": key,
                        "severity": "error",
                        "message": f"同一客户在文件中的{key}不一致，请先确认",
                    }
                )
            else:
                input_values[key] = value
        state["conflicts_in_row"] = conflicts
        if state["is_new"]:
            state["changed_in_row"] = False
            return cast("dict[str, Any]", state)
        updates = {
            key: data.get(key)
            for key in allowed_update_fields & self._customer_fields
            if data.get(key) not in (None, "") and data.get(key) != state["after"].get(key)
        }
        state["changed_in_row"] = bool(updates)
        if updates:
            state["after"] = {**state["after"], **updates}
        return cast("dict[str, Any]", state)

    def _product_preview_state(
        self,
        db: Session,
        data: dict[str, Any],
        allowed_update_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        product_data = self._product_data(data)
        cache = context.setdefault("_preview_cache", {})
        index = cache.get("customer_product_product_by_match_key")
        name_index = cache.get("customer_product_product_by_name_key")
        product_adapter = ProductAdapter()
        if index is None or name_index is None:
            index = {}
            name_index = {}
            for item in owned_query(db, Product).all():
                item_data = {
                    "unit": item.unit,
                    "model_number": item.model_number,
                    "name": item.name,
                }
                state = {
                    "id": item.id,
                    "before": model_values(item, ProductAdapter.fields),
                    "after": model_values(item, ProductAdapter.fields),
                    "is_new": False,
                }
                index[product_adapter._match_key(item_data)] = state
                name_index.setdefault(product_adapter._name_key(item_data), []).append(state)
            cache["customer_product_product_by_match_key"] = index
            cache["customer_product_product_by_name_key"] = name_index
        match_key = product_adapter._match_key(product_data)
        state = index.get(match_key)
        ambiguity = product_adapter.model_ambiguity_issue(
            product_data,
            list(name_index.get(product_adapter._name_key(product_data), [])),
            exact_match=bool(state),
        )
        if ambiguity:
            existing = state or {}
            return {
                "id": existing.get("id"),
                "before": existing.get("before", {}),
                "after": existing.get("after", json_safe(product_data)),
                "is_new": state is None,
                "model_ambiguity_issues": [ambiguity],
            }
        if state is None:
            state = {
                "id": None,
                "before": {},
                "after": json_safe(product_data),
                "is_new": True,
                "seen": True,
            }
            index[match_key] = state
            name_index.setdefault(product_adapter._name_key(product_data), []).append(state)
            return state
        if state.get("seen"):
            state["duplicate_in_source"] = True
            return cast("dict[str, Any]", state)
        state["seen"] = True
        updates = {
            key: product_data.get(key)
            for key in allowed_update_fields & self._product_fields
            if product_data.get(key) not in (None, "")
            and product_data.get(key) != state["after"].get(key)
        }
        state["changed_in_row"] = bool(updates)
        if updates:
            state["after"] = {**state["after"], **updates}
        return cast("dict[str, Any]", state)
