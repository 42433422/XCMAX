# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_employee(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    if action in ("list", "query"):
        status = build_employee_tools_status()
        return {
            "success": True,
            "message": f"已发现 {status.get('registered_tool_count', 0)} 个可调用员工",
            "data": status,
        }
    if action != "execute":
        return {"success": False, "message": f"未注册的 employee 动作: {action}"}
    employee_id = str(
        params.get("employee_id")
        or params.get("pack_id")
        or params.get("tool_name")
        or params.get("id")
        or ""
    ).strip()
    status = build_employee_tools_status()
    installed = status.get("employee_pack_tools") or []
    if not employee_id and user_message:
        for item in installed:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("pack_id") or item.get("tool_name") or "").strip()
            if candidate and candidate in user_message:
                employee_id = candidate
                break
    if not employee_id:
        return {
            "success": False,
            "message": "缺少 employee_id，请先用 employee.list 查看可用员工，或明确指定员工包 ID。",
            "data": {
                "available_employee_ids": [
                    str(x.get("pack_id") or "")
                    for x in installed
                    if isinstance(x, dict) and x.get("pack_id")
                ][:80]
            },
        }
    task = str(
        params.get("task")
        or params.get("user_request")
        or params.get("message")
        or user_message
        or ""
    ).strip()
    if not task:
        return {"success": False, "message": "缺少 task：请说明要让员工执行什么任务。"}
    input_data = params.get("input") if isinstance(params.get("input"), dict) else {}
    payload = dict(input_data or {})
    for key, value in params.items():
        if key in {"employee_id", "pack_id", "tool_name", "id", "task", "user_request", "input"}:
            continue
        payload.setdefault(key, value)
    payload.setdefault("source", "workflow_tool.employee")
    payload.setdefault("user_message", user_message)
    workspace_root = (
        str(params.get("workspace_root") or runtime_context.get("workspace_root") or "").strip()
        or None
    )
    raw_user_id = params.get("user_id") or runtime_context.get("user_id") or 0
    try:
        numeric_user_id = int(raw_user_id)
    except (TypeError, ValueError):
        numeric_user_id = 0
    from app.application.employee_runtime.executor import execute_employee_task_local

    result = execute_employee_task_local(
        employee_id,
        task,
        payload,
        user_id=numeric_user_id,
        workspace_root=workspace_root,
        session_id=str(runtime_context.get("session_id") or params.get("session_id") or "") or None,
    )
    ok = bool(result.get("success")) and (not bool(result.get("blocked_by_risk_gate")))
    return {
        "success": ok,
        "message": "员工执行完成" if ok else str(result.get("error") or "员工执行失败"),
        "employee_id": employee_id,
        "data": result,
    }


def _normalize_business_db_entity(raw: _facade().Any, user_message: str = "") -> str:
    text = str(raw or "").strip()
    if text:
        lowered = text.lower()
        if lowered in _facade()._BUSINESS_DB_ENTITY_ALIASES:
            return _facade()._BUSINESS_DB_ENTITY_ALIASES[lowered]
        if text in _facade()._BUSINESS_DB_ENTITY_ALIASES:
            return _facade()._BUSINESS_DB_ENTITY_ALIASES[text]
    msg = str(user_message or "")
    for token, entity in _facade()._BUSINESS_DB_ENTITY_ALIASES.items():
        if token and token in msg:
            return entity
    return ""


def get_recent_business_db_target(user_id: object) -> dict[str, _facade().Any] | None:
    target = _facade()._RECENT_BUSINESS_DB_TARGETS.get(str(user_id or "").strip())
    return dict(target) if target is not None else None


def _business_db_payload_contains_key(value: _facade().Any, forbidden: set[str]) -> bool:
    """Reject forbidden controls even when a model nests them in changes/fields/selector."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).strip().lower() in forbidden:
                return True
            if _business_db_payload_contains_key(nested, forbidden):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_business_db_payload_contains_key(item, forbidden) for item in value)
    return False


def _result_record_id(value: _facade().Any) -> int | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id") or value.get("product_id") or value.get("record_id")
    if raw_id not in (None, ""):
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    for key in ("data", "raw", "shipment", "result"):
        nested_id = _result_record_id(value.get(key))
        if nested_id:
            return nested_id
    return None


def _business_db_selector(payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    nested = payload.get("selector")
    selector = dict(nested) if isinstance(nested, dict) else {}
    for key in (
        "id",
        "customer_id",
        "record_id",
        "order_number",
        "customer_name",
        "unit_name",
        "name",
        "product_name",
        "name_or_model",
        "model_number",
        "material_name",
        "material_code",
    ):
        if key not in selector and payload.get(key) not in (None, ""):
            selector[key] = payload.get(key)
    return selector


def _business_db_target_candidates(
    entity: str, selector: dict[str, _facade().Any]
) -> tuple[list[dict[str, _facade().Any]], str]:
    """Resolve an exact target inside the active tenant scope.

    All involved models inherit TenantScopedMixin, and apply_tenant_filter is repeated here as
    defense in depth.  No fuzzy write target is ever accepted.
    """
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import apply_tenant_filter

    raw_id = (
        selector.get("id")
        or selector.get("customer_id")
        or selector.get("record_id")
        or selector.get("order_number")
    )
    numeric_id = 0
    if raw_id not in (None, ""):
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError):
            return ([], "id")
        if numeric_id <= 0:
            return ([], "id")
    with get_db() as db:
        if entity == "customers":
            from app.db.models.purchase_unit import PurchaseUnit

            query = apply_tenant_filter(db.query(PurchaseUnit), PurchaseUnit)
            selector_field = "id"
            if numeric_id:
                query = query.filter(PurchaseUnit.id == numeric_id)
            else:
                value = str(
                    selector.get("customer_name")
                    or selector.get("unit_name")
                    or selector.get("name")
                    or ""
                ).strip()
                if not value:
                    return ([], "")
                selector_field = next(
                    (
                        key
                        for key in ("customer_name", "unit_name", "name")
                        if selector.get(key) not in (None, "")
                    ),
                    "customer_name",
                )
                query = query.filter(PurchaseUnit.unit_name == value)
            rows = query.order_by(PurchaseUnit.id.asc()).limit(21).all()
            return (
                [
                    {"id": row.id, "customer_name": row.unit_name, "name": row.unit_name}
                    for row in rows
                ],
                selector_field,
            )
        if entity == "products":
            from app.db.models.product import Product

            query = apply_tenant_filter(db.query(Product), Product)
            selector_field = "id"
            if numeric_id:
                query = query.filter(Product.id == numeric_id)
            else:
                model_number = str(selector.get("model_number") or "").strip().upper()
                name = str(
                    selector.get("product_name")
                    or selector.get("name")
                    or selector.get("name_or_model")
                    or ""
                ).strip()
                if model_number:
                    selector_field = "model_number"
                    query = query.filter(Product.model_number == model_number)
                elif name:
                    selector_field = next(
                        (
                            key
                            for key in ("product_name", "name", "name_or_model")
                            if selector.get(key) not in (None, "")
                        ),
                        "name",
                    )
                    query = query.filter(Product.name == name)
                else:
                    return ([], "")
            rows = query.order_by(Product.id.asc()).limit(21).all()
            return (
                [
                    {
                        "id": row.id,
                        "name": row.name,
                        "product_name": row.name,
                        "model_number": row.model_number or "",
                    }
                    for row in rows
                ],
                selector_field,
            )
        if entity == "materials":
            from app.db.models.material import Material

            query = apply_tenant_filter(db.query(Material), Material)
            selector_field = "id"
            if numeric_id:
                query = query.filter(Material.id == numeric_id)
            else:
                code = str(selector.get("material_code") or "").strip()
                name = str(selector.get("material_name") or selector.get("name") or "").strip()
                if code:
                    selector_field = "material_code"
                    query = query.filter(Material.material_code == code)
                elif name:
                    selector_field = "material_name" if selector.get("material_name") else "name"
                    query = query.filter(Material.name == name)
                else:
                    return ([], "")
            rows = query.order_by(Material.id.asc()).limit(21).all()
            return (
                [
                    {
                        "id": row.id,
                        "name": row.name,
                        "material_name": row.name,
                        "material_code": row.material_code,
                    }
                    for row in rows
                ],
                selector_field,
            )
        if entity == "shipment_records":
            from app.db.models.shipment import ShipmentRecord

            if not numeric_id:
                return ([], "")
            rows = (
                apply_tenant_filter(db.query(ShipmentRecord), ShipmentRecord)
                .filter(ShipmentRecord.id == numeric_id)
                .order_by(ShipmentRecord.id.asc())
                .limit(2)
                .all()
            )
            return (
                [
                    {
                        "id": row.id,
                        "name": f"{row.purchase_unit} / {row.product_name}",
                        "purchase_unit": row.purchase_unit,
                        "product_name": row.product_name,
                    }
                    for row in rows
                ],
                "id",
            )
    return ([], "")
