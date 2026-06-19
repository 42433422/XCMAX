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
    return {
        "customers": {
            "description": "购买单位管理",
            "availability": "shared",
            "actions": {
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "ensure_exists": {
                    "risk": "medium",
                    "idempotent": True,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
                "update": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "batch_delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["ids"],
                    "availability": "shared",
                },
            },
        },
        "products": {
            "description": "产品管理",
            "availability": "shared",
            "actions": {
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "exists": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["name_or_model", "unit_name"],
                    "availability": "shared",
                },
                "update": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "batch_create": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["products"],
                    "availability": "shared",
                },
                "batch_delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["ids"],
                    "availability": "shared",
                },
            },
        },
        "materials": {
            "description": "原材料仓库与列表管理",
            "availability": "shared",
            "actions": {
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["name"],
                    "availability": "shared",
                },
                "update": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "batch_delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "export": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "shipment_records": {
            "description": "出货记录管理",
            "availability": "shared",
            "actions": {
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "create": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
                "update": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "export": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "inventory": {
            "description": "库存仓库、库位、入库、出库与调拨管理",
            "availability": "shared",
            "actions": {
                "create_storage_location": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "update_storage_location": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["location_id"],
                    "availability": "shared",
                },
                "create_warehouse": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "update_warehouse": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["warehouse_id"],
                    "availability": "shared",
                },
                "delete_warehouse": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["warehouse_id"],
                    "availability": "shared",
                },
                "stock_in": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["product_id", "warehouse_id", "quantity"],
                    "availability": "shared",
                },
                "stock_out": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["product_id", "warehouse_id", "quantity"],
                    "availability": "shared",
                },
                "transfer": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [
                        "product_id",
                        "from_warehouse_id",
                        "to_warehouse_id",
                        "quantity",
                    ],
                    "availability": "shared",
                },
            },
        },
        "purchase": {
            "description": "采购供应商、采购订单与采购入库管理",
            "availability": "shared",
            "actions": {
                "create_supplier": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "update_supplier": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["supplier_id"],
                    "availability": "shared",
                },
                "delete_supplier": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["supplier_id"],
                    "availability": "shared",
                },
                "create_order": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "update_order": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["order_id"],
                    "availability": "shared",
                },
                "approve_order": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["order_id"],
                    "availability": "shared",
                },
                "cancel_order": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["order_id"],
                    "availability": "shared",
                },
                "create_inbound": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "finance": {
            "description": "财务凭证交易管理",
            "availability": "shared",
            "actions": {
                "create_transaction": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["transaction_type", "amount"],
                    "availability": "shared",
                },
                "update_transaction": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["transaction_id"],
                    "availability": "shared",
                },
                "delete_transaction": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["transaction_id"],
                    "availability": "shared",
                },
            },
        },
        "generate_office_document": {
            "description": "生成可下载的 Office 文档",
            "availability": "shared",
            "actions": {
                "execute": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
            },
        },
        "excel_vector_index": {
            "description": "Excel 向量索引与语义查询",
            "availability": "shared",
            "actions": {
                "execute": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["index_id", "query"],
                    "availability": "shared",
                },
            },
        },
        "ocr": {
            "description": "OCR 图片文字识别、结构化提取与文本分析",
            "availability": "shared",
            "actions": {
                "recognize": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
                "request": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["request_id", "image_url"],
                    "availability": "shared",
                },
                "extract": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["text"],
                    "availability": "shared",
                },
                "analyze": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["text"],
                    "availability": "shared",
                },
                "recognize_and_extract": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
            },
        },
        "shipment_orders": {
            "description": "发货单生成、打印和订单副作用管理",
            "availability": "shared",
            "actions": {
                "generate": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["unit_name", "products"],
                    "availability": "shared",
                },
                "generate_batch": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["shipments"],
                    "availability": "shared",
                },
                "print": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "clear_shipment": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["purchase_unit"],
                    "availability": "shared",
                },
                "set_sequence": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["sequence"],
                    "availability": "shared",
                },
                "reset_sequence": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "clear_all": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
            },
        },
        "business_event": {
            "description": "业务 API 事件发布桥接",
            "availability": "shared",
            "actions": {
                "print_label": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["document_name"],
                    "availability": "shared",
                },
                "inventory_update": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["product_id"],
                    "availability": "shared",
                },
                "shipment_create": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["unit_name"],
                    "availability": "shared",
                },
            },
        },
        "system_maintenance": {
            "description": "系统维护、数据库备份恢复与性能维护操作",
            "availability": "shared",
            "actions": {
                "set_default_printer": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["printer_name"],
                    "availability": "shared",
                },
                "enable_startup": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "disable_startup": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "backup_database": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
                "delete_database_backup": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["backup_file"],
                    "availability": "shared",
                },
                "restore_database": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["backup_file"],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
                "clear_performance_cache": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "invalidate_performance_cache": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["keys"],
                    "availability": "shared",
                },
                "reinitialize_performance": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
            },
        },
        "template_extract": {
            "description": "Excel 模板结构提取与网格预览",
            "availability": "shared",
            "actions": {
                "extract": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "excel_analyzer": {
            "description": "Excel 模板结构分析技能",
            "availability": "shared",
            "actions": {
                "analyze": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
            },
        },
        "excel_toolkit": {
            "description": "Excel 文件查看与结构检查技能",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "merged": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "styles": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "structure": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
            },
        },
        "label_template_generator": {
            "description": "从标签图片生成可复用标签模板代码",
            "availability": "shared",
            "actions": {
                "execute": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["image_path"],
                    "availability": "shared",
                    "timeout_seconds": 120,
                },
            },
        },
        "document_template": {
            "description": "文档/Excel 模板库创建、更新与删除",
            "availability": "shared",
            "actions": {
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "update": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["id"],
                    "availability": "shared",
                },
            },
        },
        "business_docking": {
            "description": "业务对接与模板网格提取",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "extract": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "preview": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
            },
        },
        "template_preview": {
            "description": "模板预览与管理",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "create": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "wechat": {
            "description": "微信联系人与消息缓存管理",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "refresh_contact_cache": {
                    "risk": "medium",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "refresh_messages_cache": {
                    "risk": "medium",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "print": {
            "description": "标签与文档打印",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "print_label": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "print_document": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "test": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["printer_name"],
                    "availability": "shared",
                },
                "save_printer_selection": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "workflow_label_dispatch": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["model_number"],
                    "availability": "shared",
                },
            },
        },
        "printer_list": {
            "description": "打印机列表与默认打印机设置",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "set_default": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["printer_name"],
                    "availability": "shared",
                },
            },
        },
        "settings": {
            "description": "系统设置与运行环境配置",
            "availability": "shared",
            "actions": {
                "view": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "get_system_info": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "get_startup_config": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "enable_startup": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
                "disable_startup": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": [],
                    "availability": "shared",
                },
            },
        },
        "employee": {
            "description": (
                "调用本机已安装的 AI 员工 employee_pack。先用 list 查看员工包；"
                "已知 employee_id 时用 execute 真正运行员工，返回员工运行时结果。"
            ),
            "availability": "shared",
            "actions": {
                "list": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "shared",
                },
                "execute": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["task"],
                    "availability": "shared",
                },
            },
        },
        "business_db": {
            "description": (
                "受控业务数据库读写工具。只允许通过业务服务访问 customers、products、"
                "materials、shipment_records，不接受任意 SQL。read 用于查询，write 用于"
                "create/update/delete 等受控写入。"
            ),
            "availability": "shared",
            "actions": {
                "read": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["entity"],
                    "availability": "shared",
                },
                "write": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["entity", "operation", "payload"],
                    "availability": "shared",
                },
            },
        },
        "dataset_rag": {
            "description": "Dataset/RAG 文档库工具。用于文档入库、检索问答、版本治理、索引重建和文档删除。",
            "availability": "shared",
            "actions": {
                "ingest_document": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["dataset_id"],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["dataset_id", "query"],
                    "availability": "shared",
                },
                "diff_versions": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["dataset_id", "source", "from_version"],
                    "availability": "shared",
                },
                "rollback_version": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["dataset_id", "source", "target_version"],
                    "availability": "shared",
                },
                "rebuild_index": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["dataset_id"],
                    "availability": "shared",
                },
                "cancel_rebuild": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["dataset_id", "job_id"],
                    "availability": "shared",
                },
                "delete_document": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["dataset_id", "document_id"],
                    "availability": "shared",
                },
            },
        },
        "memory_v2": {
            "description": "Memory v2 记忆生命周期工具。用于创建候选、确认、拒绝、修正和删除可治理记忆。",
            "availability": "shared",
            "actions": {
                "propose_candidate": {
                    "risk": "medium",
                    "idempotent": True,
                    "required_params": ["user_id", "memory_type", "key", "value"],
                    "availability": "shared",
                },
                "confirm": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["user_id", "memory_id"],
                    "availability": "shared",
                },
                "reject": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["user_id", "memory_id"],
                    "availability": "shared",
                },
                "correct": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["user_id", "memory_id"],
                    "availability": "shared",
                },
                "delete": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": ["user_id", "memory_id"],
                    "availability": "shared",
                },
            },
        },
        "normal_slot_dispatch": {
            "description": "普通版槽位：产品查询浮窗、发货单编号预览（与 /api/ai/unified_chat 同源）",
            "availability": "normal_only",
            "actions": {
                "product_query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "normal_only",
                },
                "shipment_preview": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": [],
                    "availability": "normal_only",
                },
            },
        },
        "excel_analysis": {
            "description": "Excel文件智能分析：读取内容、分析结构、统计汇总、自然语言查询",
            "availability": "shared",
            "actions": {
                "read": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "structure": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
                "query": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path", "question"],
                    "availability": "shared",
                },
                "statistics": {
                    "risk": "low",
                    "idempotent": True,
                    "required_params": ["file_path"],
                    "availability": "shared",
                },
            },
        },
        "excel_import": {
            "description": "Excel 解析记录入库工具。只接受结构化 records 或待确认 pending_import_id，不接受任意 SQL。",
            "availability": "shared",
            "actions": {
                "execute_import": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["pending_import_id"],
                    "availability": "shared",
                },
                "import_records": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["records"],
                    "availability": "shared",
                },
            },
        },
        "unit_products_import": {
            "description": "从已分析的 unit_products .db 文件导入客户和产品。写入业务数据库前必须经过 AgentRun 确认。",
            "availability": "shared",
            "actions": {
                "execute_import": {
                    "risk": "medium",
                    "idempotent": False,
                    "required_params": ["saved_name", "unit_name"],
                    "availability": "shared",
                },
            },
        },
    }
