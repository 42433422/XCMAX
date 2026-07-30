"""Build a safe, user-facing explanation of an AgentRun tool step.

The execution result remains the source of truth for the tool.  This module only
projects a small allow-listed summary for the smart-chat orchestration view:
which database was read or changed, which business records moved, which AI
employee was called, and what a print step depended on.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any


_ENTITY_META: dict[str, tuple[str, str, str]] = {
    "customers": ("products.db", "客户/产品主库", "customers / purchase_units"),
    "products": ("products.db", "客户/产品主库", "products"),
    "materials": ("products.db", "业务主库", "materials"),
    "shipment_records": ("products.db", "业务主库", "shipment_records"),
    "inventory": ("products.db", "业务主库", "inventory_ledger / inventory_transactions"),
    "purchase": ("products.db", "业务主库", "suppliers / purchase_orders / purchase_inbounds"),
    "finance": ("products.db", "业务主库", "financial_transactions"),
}

_ENTITY_ALIASES = {
    "customer": "customers",
    "customers": "customers",
    "客户": "customers",
    "product": "products",
    "products": "products",
    "产品": "products",
    "material": "materials",
    "materials": "materials",
    "物料": "materials",
    "shipment": "shipment_records",
    "shipment_records": "shipment_records",
    "发货": "shipment_records",
}


def _text(value: Any, *, limit: int = 160) -> str:
    result = str(value or "").strip()
    return result[:limit] + ("..." if len(result) > limit else "")


def _count(value: Any, fallback: int = 0) -> int:
    """Coerce tool output counts without allowing malformed output to break a run."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _entity(value: Any) -> str:
    raw = _text(value, limit=80).lower()
    return _ENTITY_ALIASES.get(raw, raw)


def _storage_context(runtime_context: dict[str, Any]) -> tuple[str, str]:
    explicit_mode = _text(
        runtime_context.get("storage_mode") or runtime_context.get("database_mode"),
        limit=40,
    )
    database_url = _text(
        runtime_context.get("database_url") or os.environ.get("DATABASE_URL"),
        limit=500,
    )
    if database_url.startswith("sqlite"):
        filename = database_url.rsplit("/", 1)[-1] or "products.db"
        return explicit_mode or "local_sqlite", PurePosixPath(filename).name
    if database_url.startswith(("postgres", "postgresql")):
        return explicit_mode or "remote_postgresql", "PostgreSQL（密码已隐藏）"
    return explicit_mode or "local_sqlite", _text(
        runtime_context.get("database_name") or "products.db",
        limit=80,
    )


def _database(
    entity: str,
    runtime_context: dict[str, Any],
    *,
    role: str,
    tables: str | None = None,
) -> dict[str, Any]:
    default_id, default_name, default_tables = _ENTITY_META.get(
        entity,
        ("products.db", "业务主库", "业务表"),
    )
    storage_mode, runtime_db_name = _storage_context(runtime_context)
    database_id = _text(runtime_context.get("database_id") or default_id, limit=100)
    database_name = _text(runtime_context.get("database_label") or default_name, limit=100)
    active_mod = _text(runtime_context.get("active_mod_id"), limit=80)
    return {
        "database_id": database_id,
        "database_name": database_name,
        "runtime_database": runtime_db_name,
        "storage_mode": storage_mode,
        "role": role,
        "tables": _text(tables or default_tables, limit=180),
        **({"active_mod_id": active_mod} if active_mod else {}),
    }


def _payload(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("payload")
    return dict(raw) if isinstance(raw, dict) else dict(params)


def _product_items(params: dict[str, Any], output: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for value in (params.get("products"), output.get("products"), output.get("data")):
        if isinstance(value, list):
            candidates.extend(value)
    if not candidates:
        candidates = [_payload(params)]
    items: list[dict[str, Any]] = []
    for raw in candidates[:12]:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {}
        for key in ("id", "name", "product_name", "model_number", "product_code", "unit", "qty", "quantity", "unit_price", "price"):
            value = raw.get(key)
            if value not in (None, ""):
                item[key] = value
        if item:
            items.append(item)
    return items


def _product_change(
    action: str,
    params: dict[str, Any],
    output: dict[str, Any],
    database: dict[str, Any],
) -> dict[str, Any] | None:
    operation = str(action or "").strip().lower()
    aliases = {
        "batch_create": "create",
        "batch_delete": "delete",
        "write": str(params.get("operation") or params.get("op") or "create").strip().lower(),
    }
    operation = aliases.get(operation, operation)
    if operation not in {"create", "update", "delete", "upsert"}:
        return None
    items = _product_items(params, output)
    change_type = {
        "create": "added",
        "update": "updated",
        "delete": "deleted",
        "upsert": "upserted",
    }[operation]
    for item in items:
        item["change_type"] = change_type
    counts = {
        "created": _count(output.get("created_products") or output.get("created"), len(items) if operation in {"create", "upsert"} else 0),
        "updated": _count(output.get("updated_products") or output.get("updated"), len(items) if operation == "update" else 0),
        "deleted": _count(output.get("deleted_products") or output.get("deleted"), len(items) if operation == "delete" else 0),
    }
    labels = {"create": "新增产品", "update": "修改产品", "delete": "删除产品", "upsert": "新增/更新产品"}
    return {
        **database,
        "entity": "products",
        "operation": operation,
        "label": labels[operation],
        "counts": counts,
        "items": items,
        "field_changes": _field_changes(output),
    }


def _field_changes(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep explicit before/after diffs when a connector provides them."""
    before = output.get("before") or output.get("before_data") or output.get("previous")
    after = output.get("after") or output.get("after_data") or output.get("data")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    fields: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        old_value = before.get(key)
        new_value = after.get(key)
        if old_value == new_value or key in {"updated_at", "created_at"}:
            continue
        fields.append({
            "field": _text(key, limit=80),
            "before": _text(old_value, limit=120),
            "after": _text(new_value, limit=120),
        })
    return fields[:20]


def build_orchestration_evidence(
    tool_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    runtime_context: dict[str, Any] | None = None,
    *,
    status: str = "running",
) -> dict[str, Any]:
    """Return an allow-listed orchestration projection for one tool call."""

    params = dict(params or {})
    output = dict(output or {})
    runtime_context = dict(runtime_context or {})
    tool = _text(tool_id, limit=80)
    operation = _text(action, limit=80)
    entity = _entity(params.get("entity") or params.get("table") or tool)
    databases: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    employees: list[dict[str, Any]] = []
    print_info: dict[str, Any] | None = None

    is_employee = tool == "employee" or tool.endswith("employee")
    is_print = tool in {"print", "business_event"} or tool == "shipment_orders" and operation == "print"
    is_read = operation in {"read", "query", "list", "exists"}
    is_write = operation in {
        "write", "create", "update", "delete", "batch_create", "batch_delete", "upsert",
        "stock_in", "stock_out", "transfer", "approve_order", "create_inbound",
    }

    if is_employee:
        employee_id = _text(
            params.get("employee_id") or params.get("pack_id") or params.get("tool_name") or tool,
            limit=100,
        )
        employees.append({
            "employee_id": employee_id,
            "employee_name": _text(params.get("employee_name") or employee_id, limit=120),
            "task": _text(params.get("task") or params.get("user_request") or runtime_context.get("message"), limit=180),
            "status": status,
        })

    if tool == "business_db":
        if entity in _ENTITY_META:
            databases.append(_database(entity, runtime_context, role="write" if is_write else "read"))
            if is_write and entity == "products":
                change = _product_change(str(params.get("operation") or "create"), params, output, databases[0])
                if change:
                    changes.append(change)
    elif tool in _ENTITY_META:
        db_role = "read" if is_read else "write" if is_write else "observe"
        databases.append(_database(tool, runtime_context, role=db_role))
        if tool == "products" and is_write:
            change = _product_change(operation, params, output, databases[0])
            if change:
                changes.append(change)

    if is_print:
        # Label printing resolves the product first; shipment printing may carry
        # its reads in preceding nodes, so this is intentionally additive.
        if operation == "workflow_label_dispatch" or tool == "shipment_orders":
            databases.append(_database("products", runtime_context, role="read", tables="products"))
        raw_path = _text(params.get("file_path"), limit=240)
        print_info = {
            "kind": "label" if "label" in operation else "document",
            "printer_name": _text(params.get("printer_name") or output.get("printer_name"), limit=120),
            "copies": _count(params.get("copies") or params.get("quantity"), 1),
            "template": _text(params.get("template") or params.get("template_id"), limit=120),
            "file_name": PurePosixPath(raw_path).name if raw_path else "",
            "job_id": _text(output.get("job_id") or output.get("print_job_id"), limit=120),
        }

    if not databases and is_read:
        databases.append(_database(entity, runtime_context, role="read"))

    kind = "employee" if is_employee else "print" if is_print else "database_write" if changes or is_write else "database_read" if databases else "tool"
    labels = {
        "employee": "调用 AI 员工",
        "print": "打印/打单",
        "database_write": "写入数据库",
        "database_read": "读取数据库",
        "tool": "执行工具",
    }
    evidence = {
        "schema_version": "orchestration_evidence_v1",
        "kind": kind,
        "label": labels[kind],
        "status": status,
        "tool_id": tool,
        "action": operation,
        "databases": databases,
        "changes": changes,
        "employees": employees,
    }
    if print_info is not None:
        evidence["print"] = print_info
    if is_read:
        evidence["query"] = _text(
            params.get("keyword") or params.get("query") or params.get("model_number") or runtime_context.get("message"),
            limit=180,
        )
        rows = output.get("data")
        if isinstance(rows, list):
            evidence["result_count"] = len(rows)
    return evidence
