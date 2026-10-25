"""Tenant-safe customer create/ensure/upsert helpers for the business DB tool."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class CustomerMutationService(Protocol):
    def create(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update(self, customer_id: int, data: dict[str, Any]) -> dict[str, Any]: ...

    def match_purchase_unit(self, input_name: str) -> Any | None: ...


TargetResolver = Callable[[str, dict[str, Any]], tuple[list[dict[str, Any]], str]]


def _customer_name(params: dict[str, Any]) -> str:
    return str(
        params.get("unit_name") or params.get("customer_name") or params.get("name") or ""
    ).strip()


def _customer_data(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "customer_name": _customer_name(params),
        "contact_person": params.get("contact_person", ""),
        "contact_phone": params.get("contact_phone", ""),
        "contact_address": params.get("contact_address", params.get("address", "")),
    }


def _customer_selector(params: dict[str, Any]) -> dict[str, Any]:
    for key in ("id", "customer_id"):
        if params.get(key) not in (None, ""):
            return {key: params[key]}
    for key in ("customer_name", "unit_name", "name"):
        if params.get(key) not in (None, ""):
            return {key: params[key]}
    return {}


def _create_customer(params: dict[str, Any], svc: CustomerMutationService) -> dict[str, Any]:
    data = _customer_data(params)
    if not data["customer_name"]:
        return {"success": False, "message": "缺少 unit_name"}
    result = svc.create(data)
    if result.get("success"):
        return {"success": True, "created": True, "data": result.get("data", {})}
    return {"success": False, "message": result.get("message") or "创建失败"}


def _ensure_customer(params: dict[str, Any], svc: CustomerMutationService) -> dict[str, Any]:
    unit_name = _customer_name(params)
    if not unit_name:
        return {"success": False, "message": "缺少 unit_name"}
    matched = svc.match_purchase_unit(unit_name)
    if matched:
        return {"success": True, "exists": True, "unit_name": matched.unit_name}
    result = svc.create({"customer_name": unit_name})
    if result.get("success"):
        return {"success": True, "exists": False, "created": True, "unit_name": unit_name}
    message = str(result.get("message") or "")
    if "已存在" in message:
        return {"success": True, "exists": True, "unit_name": unit_name}
    return {"success": False, "message": message or "创建单位失败"}


def _upsert_customer(
    params: dict[str, Any],
    svc: CustomerMutationService,
    resolve_targets: TargetResolver,
) -> dict[str, Any]:
    candidates, selector_field = resolve_targets("customers", _customer_selector(params))
    if not selector_field:
        return {
            "success": False,
            "reason": "missing_target",
            "message": "customers.upsert 必须提供当前租户内的客户名称或 ID。",
            "candidates": [],
        }
    if len(candidates) > 1:
        return {
            "success": False,
            "reason": "ambiguous_target",
            "message": "精确条件匹配到多条客户记录，请选择唯一 ID。",
            "candidates": candidates,
        }
    if not candidates:
        if any(params.get(key) not in (None, "") for key in ("id", "customer_id")):
            return {
                "success": False,
                "reason": "target_not_found",
                "message": "当前租户内未找到指定客户 ID，未执行写入。",
                "candidates": [],
            }
        return _create_customer(params, svc)

    data = {
        key: value
        for key, value in _customer_data(params).items()
        if key == "customer_name" or value not in (None, "")
    }
    result = svc.update(int(candidates[0]["id"]), data)
    if result.get("success"):
        return {"success": True, "data": result.get("data", {})}
    return {"success": False, "message": result.get("message") or "更新失败"}


def execute_customer_create_like(
    action: str,
    params: dict[str, Any],
    *,
    svc: CustomerMutationService,
    resolve_targets: TargetResolver,
) -> dict[str, Any]:
    if action == "create":
        return _create_customer(params, svc)
    if action == "ensure_exists":
        return _ensure_customer(params, svc)
    return _upsert_customer(params, svc, resolve_targets)
