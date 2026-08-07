from __future__ import annotations

CANONICAL_ACTIONS = {
    "view",
    "list",
    "query",
    "create",
    "update",
    "delete",
    "batch_delete",
    "import",
    "export",
    "analyze",
    "extract",
    "preview",
    "execute",
    "read",
    "write",
}

ACTION_ALIASES = {
    "查找": "query",
    "查询": "query",
    "搜索": "query",
    "search": "query",
    "find": "query",
    "add": "create",
    "新增": "create",
    "添加": "create",
    "create": "create",
    "modify": "update",
    "edit": "update",
    "更新": "update",
    "删除": "delete",
    "remove": "delete",
    "del": "delete",
    "删除批量": "batch_delete",
    "batch-delete": "batch_delete",
    "batch_delete": "batch_delete",
    "导入": "import",
    "导出": "export",
    "分析": "analyze",
    "提取": "extract",
    "执行": "execute",
    "exec": "execute",
    "run": "execute",
    "读取": "read",
    "读": "read",
    "read": "read",
    "写入": "write",
    "写": "write",
    "write": "write",
}

REQUIRED_PARAMS_BY_TOOL_ACTION = {
    ("products", "create"): ["name_or_model", "unit_name"],
    ("customers", "create"): ["unit_name"],
    ("customers", "update"): ["id"],
    ("customers", "delete"): ["id"],
    ("customers", "batch_delete"): ["ids"],
    ("products", "update"): ["id"],
    ("products", "delete"): ["id"],
    ("products", "batch_create"): ["products"],
    ("products", "batch_delete"): ["ids"],
    ("materials", "create"): ["name"],
    ("materials", "update"): ["id"],
    ("materials", "delete"): ["id"],
    ("materials", "batch_delete"): [],
    ("inventory", "update_storage_location"): ["location_id"],
    ("inventory", "delete_warehouse"): ["warehouse_id"],
    ("inventory", "update_warehouse"): ["warehouse_id"],
    ("inventory", "stock_in"): ["product_id", "warehouse_id", "quantity"],
    ("inventory", "stock_out"): ["product_id", "warehouse_id", "quantity"],
    ("inventory", "transfer"): ["product_id", "from_warehouse_id", "to_warehouse_id", "quantity"],
    ("purchase", "update_supplier"): ["supplier_id"],
    ("purchase", "delete_supplier"): ["supplier_id"],
    ("purchase", "update_order"): ["order_id"],
    ("purchase", "approve_order"): ["order_id"],
    ("purchase", "cancel_order"): ["order_id"],
    ("finance", "create_transaction"): ["transaction_type", "amount"],
    ("finance", "update_transaction"): ["transaction_id"],
    ("finance", "delete_transaction"): ["transaction_id"],
    ("finance", "journal_entry_create"): ["lines"],
    ("finance", "journal_entry_reverse"): ["entry_id"],
    ("finance", "aging_report"): ["account_type", "days"],
    ("finance", "chart_seed"): [],
    ("inventory", "inventory_count"): ["product_id", "warehouse_id", "actual_quantity"],
    ("inventory", "query_transactions"): [],
    ("customers", "add_address"): ["customer_id", "address_type", "address"],
    ("customers", "set_credit_limit"): ["customer_id", "credit_limit"],
    ("customers", "get_addresses"): [],
    ("mrp", "create_bom"): ["product_id", "lines"],
    ("mrp", "query_boms"): [],
    ("mrp", "get_bom"): ["bom_id"],
    ("mrp", "create_order"): ["bom_id", "quantity"],
    ("mrp", "confirm_order"): ["order_id"],
    ("mrp", "consume"): ["order_id", "warehouse_id"],
    ("mrp", "finish"): ["order_id", "warehouse_id"],
    ("mrp", "query_orders"): [],
    ("sales", "quote"): ["customer_id", "items"],
    ("sales", "confirm"): ["order_id"],
    ("sales", "deliver"): ["order_id"],
    ("sales", "invoice"): ["order_id"],
    ("sales", "payment"): ["order_id", "amount"],
    ("sales", "cancel"): ["order_id"],
    ("shipment_records", "update"): ["id"],
    ("shipment_records", "delete"): ["id"],
    ("shipment_orders", "generate"): ["unit_name", "products"],
    ("shipment_orders", "generate_batch"): ["shipments"],
    ("shipment_orders", "print"): ["file_path"],
    ("shipment_orders", "clear_shipment"): ["purchase_unit"],
    ("shipment_orders", "set_sequence"): ["sequence"],
    ("shipment_orders", "reset_sequence"): [],
    ("shipment_orders", "clear_all"): [],
    ("shipment_orders", "delete"): ["id"],
    ("template_extract", "extract"): ["file_path"],
    ("print", "print_label"): ["file_path"],
    ("print", "print_document"): ["file_path"],
    ("print", "test"): ["printer_name"],
    ("print", "save_printer_selection"): [],
    ("print", "workflow_label_dispatch"): ["model_number"],
    ("printer_list", "set_default"): ["printer_name"],
    ("wechat", "refresh_contact_cache"): [],
    ("wechat", "refresh_messages_cache"): [],
    ("employee", "execute"): ["task"],
    ("business_db", "read"): ["entity"],
    ("business_db", "write"): ["entity", "operation", "payload"],
    ("dataset_rag", "query"): ["dataset_id", "query"],
    ("ocr", "recognize"): ["file_path"],
    ("ocr", "request"): ["request_id", "image_url"],
    ("ocr", "extract"): ["text"],
    ("ocr", "analyze"): ["text"],
    ("ocr", "recognize_and_extract"): ["file_path"],
    ("business_event", "print_label"): ["document_name"],
    ("business_event", "inventory_update"): ["product_id"],
    ("business_event", "shipment_create"): ["unit_name"],
    ("system_maintenance", "set_default_printer"): ["printer_name"],
    ("system_maintenance", "enable_startup"): [],
    ("system_maintenance", "disable_startup"): [],
    ("system_maintenance", "backup_database"): [],
    ("system_maintenance", "delete_database_backup"): ["backup_file"],
    ("system_maintenance", "restore_database"): ["backup_file"],
    ("system_maintenance", "clear_performance_cache"): [],
    ("system_maintenance", "invalidate_performance_cache"): ["keys"],
    ("system_maintenance", "reinitialize_performance"): [],
    ("excel_vector_index", "execute"): ["file_path"],
    ("excel_vector_index", "query"): ["index_id", "query"],
    ("excel_analyzer", "analyze"): ["file_path"],
    ("excel_toolkit", "view"): ["file_path"],
    ("excel_toolkit", "merged"): ["file_path"],
    ("excel_toolkit", "styles"): ["file_path"],
    ("excel_toolkit", "structure"): ["file_path"],
    ("label_template_generator", "execute"): ["image_path"],
    ("document_template", "create"): [],
    ("document_template", "update"): ["id"],
    ("document_template", "delete"): ["id"],
    ("document_template", "ingest"): [],
    ("document_template", "upload"): [],
    ("excel_import", "execute_import"): ["pending_import_id"],
    ("excel_import", "import_records"): ["records"],
    ("unit_products_import", "execute_import"): ["saved_name", "unit_name"],
    ("generate_office_document", "execute"): [],
    ("shipment_records", "create"): ["unit_name"],
}


def _normalize_action(action: str, params: dict | None = None) -> str:
    raw = str(action or "").strip()
    if not raw:
        return "view"
    lowered = raw.lower()
    normalized = ACTION_ALIASES.get(raw) or ACTION_ALIASES.get(lowered) or lowered
    if normalized in CANONICAL_ACTIONS:
        return normalized
    if params and str(params.get("action") or "").strip():
        nested = str(params.get("action")).strip()
        nested_lower = nested.lower()
        mapped = ACTION_ALIASES.get(nested) or ACTION_ALIASES.get(nested_lower) or nested_lower
        if mapped in CANONICAL_ACTIONS:
            return mapped
    return normalized


def _validate_required_params(tool_id: str, action: str, params: dict | None) -> tuple[bool, str]:
    required = REQUIRED_PARAMS_BY_TOOL_ACTION.get(
        (str(tool_id or "").strip(), str(action or "").strip()), []
    )
    if not required:
        return True, ""
    payload = dict(params or {})
    missing = []
    for key in required:
        value = payload.get(key)
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
            continue
        if isinstance(value, list) and len(value) == 0:
            missing.append(key)
            continue
    if missing:
        return False, f"缺少参数：{', '.join(missing)}"
    return True, ""


def get_workflow_tool_registry() -> dict:
    """Return workflow tool registry loaded from config/risk_actions.registry.json."""
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    return get_workflow_tools_from_registry()
