from __future__ import annotations

from typing import Any

from .report_input_schemas import REPORT_INPUT_SCHEMAS


def _object_schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "required": required, "properties": properties}


_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

_SHIPMENT_PRODUCTS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["unit_price"],
        "allOf": [
            {"anyOf": [{"required": ["product_name"]}, {"required": ["name"]}]},
            {
                "anyOf": [
                    {"required": ["quantity_kg"]},
                    {
                        "required": ["quantity", "unit"],
                        "properties": {
                            "unit": {"pattern": "^(?:[kK][gG]|公斤|千克)$", "type": "string"}
                        },
                    },
                    {
                        "required": ["quantity", "quantity_unit"],
                        "properties": {
                            "quantity_unit": {
                                "pattern": "^(?:[kK][gG]|公斤|千克)$",
                                "type": "string",
                            }
                        },
                    },
                    {
                        "allOf": [
                            {
                                "anyOf": [
                                    {"required": ["quantity_tins"]},
                                    {"required": ["quantity", "unit"]},
                                    {"required": ["quantity", "quantity_unit"]},
                                ]
                            },
                            {
                                "anyOf": [
                                    {"required": ["tin_spec"]},
                                    {"required": ["spec_per_tin"]},
                                    {"required": ["spec"]},
                                    {"required": ["weight_per_unit"]},
                                ]
                            },
                        ]
                    },
                ]
            },
        ],
    },
}

_PRODUCTS_DELETE_INPUT = _object_schema(["id"], {"id": {"type": "integer"}})

_PRINT_TEST_INPUT = _object_schema(["printer_name"], {"printer_name": {"type": "string"}})

_SYSTEM_MAINTENANCE_DELETE_DATABASE_BACKUP_INPUT = _object_schema(
    ["backup_file"], {"backup_file": {"type": "string"}}
)

_EXCEL_TOOLKIT_VIEW_INPUT = _object_schema(
    ["file_path"],
    {
        "file_path": {"type": "string"},
        "sheet_name": {"type": "string"},
        "max_rows": {"type": "integer"},
    },
)

_EXCEL_TOOLKIT_MERGED_INPUT = _object_schema(
    ["file_path"], {"file_path": {"type": "string"}, "sheet_name": {"type": "string"}}
)

_DOCUMENT_TEMPLATE_INGEST_INPUT = _object_schema(
    [],
    {
        "file_path": {"type": "string"},
        "original_file_path": {"type": "string"},
        "filename": {"type": "string"},
        "template_name": {"type": "string"},
        "name": {"type": "string"},
        "template_scope": {"type": "string"},
        "business_scope": {"type": "string"},
        "source": {"type": "string"},
    },
)

_SALES_QUOTE_INPUT = {
    "type": "object",
    "required": ["items"],
    "anyOf": [{"required": ["customer_id"]}, {"required": ["customer_name"]}],
    "properties": {
        "customer_id": {"type": "integer", "title": "客户编号"},
        "customer_name": {"type": "string", "title": "客户名称"},
        "items": {
            "type": "array",
            "title": "报价明细",
            "items": _object_schema(
                ["quantity", "unit_price"],
                {
                    "product_id": {"type": "integer"},
                    "model_number": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                },
            ),
        },
    },
}

_MEMORY_V2_REJECT_INPUT = _object_schema(
    ["user_id", "memory_id"],
    {
        "user_id": {"type": "string"},
        "memory_id": {"type": "string"},
        "reason": {"type": "string"},
    },
)

_OCR_RECOGNIZE_INPUT = _object_schema(["file_path"], {"file_path": {"type": "string"}})

_OCR_EXTRACT_INPUT = _object_schema(["text"], {"text": {"type": "string"}})


_SPECIAL_INPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    **REPORT_INPUT_SCHEMAS,
    ("business_db", "read"): _object_schema(
        ["entity"],
        {
            "entity": {
                "type": "string",
                "enum": ["customers", "products", "materials", "shipment_records"],
            },
            "id": {"type": "integer", "minimum": 1},
            "keyword": {"type": "string"},
            "query": {"type": "string"},
        },
    ),
    ("business_db", "write"): _object_schema(
        ["entity", "operation", "payload"],
        {
            "entity": {
                "type": "string",
                "enum": ["customers", "products", "materials", "shipment_records"],
            },
            "operation": {
                "type": "string",
                "enum": ["create", "ensure_exists", "upsert", "update", "delete", "batch_delete"],
            },
            "payload": {"type": "object"},
        },
    ),
    ("customers", "create"): _object_schema(
        ["unit_name"],
        {
            "unit_name": {"type": "string"},
            "customer_name": {"type": "string"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "contact_address": {"type": "string"},
            "address": {"type": "string"},
        },
    ),
    ("customers", "update"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "customer_id": {"type": "integer"},
            "unit_name": {"type": "string"},
            "customer_name": {"type": "string"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "contact_address": {"type": "string"},
            "address": {"type": "string"},
            "expected_version": {"type": "integer"},
        },
    ),
    ("customers", "delete"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "customer_id": {"type": "integer"},
            "force": {
                "type": "boolean",
                "description": "级联删除关联产品和发货记录，须有效登录及跨域编辑权限；不是仅忽略关联检查",
            },
        },
    ),
    ("customers", "batch_delete"): _object_schema(
        ["ids"],
        {
            "ids": {"type": "array"},
            "customer_ids": {"type": "array"},
            "force": {
                "type": "boolean",
                "description": "级联删除关联产品和发货记录，须有效登录及跨域编辑权限；不是仅忽略关联检查",
            },
        },
    ),
    ("customers", "clear"): _object_schema([], {}),
    ("products", "create"): _object_schema(
        ["name_or_model"],
        {
            "name_or_model": {"type": "string"},
            "unit_name": {"type": "string"},
            "product_name": {"type": "string"},
            "name": {"type": "string"},
            "model_number": {"type": "string"},
            "product_code": {"type": "string"},
            "specification": {"type": "string"},
            "unit_price": {"type": "number"},
            "price": {"type": "number"},
            "unit": {"type": "string"},
        },
    ),
    ("products", "update"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "product_name": {"type": "string"},
            "name": {"type": "string"},
            "model_number": {"type": "string"},
            "product_code": {"type": "string"},
            "specification": {"type": "string"},
            "unit_price": {"type": "number"},
            "price": {"type": "number"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
        },
    ),
    ("products", "delete"): _PRODUCTS_DELETE_INPUT,
    ("products", "batch_create"): _object_schema(["products"], {"products": {"type": "array"}}),
    ("products", "batch_delete"): _object_schema(
        ["ids"], {"ids": {"type": "array"}, "product_ids": {"type": "array"}}
    ),
    ("products", "clear"): _object_schema([], {}),
    ("materials", "create"): _object_schema(
        ["name"],
        {
            "name": {"type": "string"},
            "material_name": {"type": "string"},
            "material_code": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
            "min_stock": {"type": "number"},
            "min_quantity": {"type": "number"},
        },
    ),
    ("materials", "update"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
            "min_stock": {"type": "number"},
        },
    ),
    ("materials", "delete"): _PRODUCTS_DELETE_INPUT,
    ("materials", "batch_delete"): _object_schema(
        [], {"ids": {"type": "array"}, "material_ids": {"type": "array"}}
    ),
    ("materials", "clear"): _object_schema([], {}),
    ("inventory", "create_storage_location"): _object_schema(
        [],
        {
            "warehouse_id": {},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("inventory", "update_storage_location"): _object_schema(
        ["location_id"],
        {
            "location_id": {"type": "integer"},
            "warehouse_id": {},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("inventory", "create_warehouse"): _object_schema(
        [],
        {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("inventory", "update_warehouse"): _object_schema(
        ["warehouse_id"],
        {
            "warehouse_id": {"type": "integer"},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("inventory", "delete_warehouse"): _object_schema(
        ["warehouse_id"], {"warehouse_id": {"type": "integer"}}
    ),
    ("inventory", "stock_in"): {
        "type": "object",
        "required": ["quantity"],
        "allOf": [
            {"anyOf": [{"required": ["product_id"]}, {"required": ["model_number"]}]},
            {"anyOf": [{"required": ["warehouse_id"]}, {"required": ["warehouse_name"]}]},
        ],
        "properties": {
            "model_number": {"type": "string", "title": "产品型号"},
            "warehouse_name": {"type": "string", "title": "入库仓库名称"},
            "product_id": {},
            "warehouse_id": {},
            "quantity": {"type": "number"},
            "batch_no": {"type": "string"},
            "location_id": {},
            "unit_price": {"type": "number"},
            "reference_type": {"type": "string"},
            "reference_id": {},
            "operator": {"type": "string"},
            "remark": {"type": "string"},
        },
    },
    ("inventory", "stock_out"): _object_schema(
        ["product_id", "warehouse_id", "quantity"],
        {
            "product_id": {},
            "warehouse_id": {},
            "quantity": {"type": "number"},
            "batch_no": {"type": "string"},
            "location_id": {},
            "unit_price": {"type": "number"},
            "reference_type": {"type": "string"},
            "reference_id": {},
            "operator": {"type": "string"},
            "remark": {"type": "string"},
        },
    ),
    ("inventory", "transfer"): _object_schema(
        ["product_id", "from_warehouse_id", "to_warehouse_id", "quantity"],
        {
            "product_id": {},
            "from_warehouse_id": {},
            "to_warehouse_id": {},
            "quantity": {"type": "number"},
            "batch_no": {"type": "string"},
            "from_location_id": {},
            "to_location_id": {},
            "operator": {"type": "string"},
            "remark": {"type": "string"},
        },
    ),
    ("purchase", "create_supplier"): _object_schema(
        [],
        {
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "address": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("purchase", "update_supplier"): _object_schema(
        ["supplier_id"],
        {
            "supplier_id": {"type": "integer"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "address": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("purchase", "delete_supplier"): _object_schema(
        ["supplier_id"], {"supplier_id": {"type": "integer"}}
    ),
    ("purchase", "create_order"): _object_schema(
        [],
        {
            "supplier_id": {},
            "items": {"type": "array"},
            "order_date": {"type": "string"},
            "expected_date": {"type": "string"},
            "remark": {"type": "string"},
        },
    ),
    ("purchase", "update_order"): _object_schema(
        ["order_id"],
        {
            "order_id": {"type": "integer"},
            "supplier_id": {},
            "items": {"type": "array"},
            "status": {"type": "string"},
            "remark": {"type": "string"},
        },
    ),
    ("purchase", "approve_order"): _object_schema(
        ["order_id"], {"order_id": {"type": "integer"}, "approver": {"type": "string"}}
    ),
    ("purchase", "cancel_order"): _object_schema(["order_id"], {"order_id": {"type": "integer"}}),
    ("purchase", "create_inbound"): _object_schema(
        [],
        {
            "supplier_id": {},
            "order_id": {},
            "items": {"type": "array"},
            "inbound_date": {"type": "string"},
            "operator": {"type": "string"},
            "remark": {"type": "string"},
        },
    ),
    ("finance", "create_transaction"): _object_schema(
        ["transaction_type", "amount"],
        {
            "transaction_type": {
                "type": "string",
                "enum": [
                    "revenue",
                    "expense",
                    "receivable",
                    "payable",
                    "receipt",
                    "payment",
                    "adjustment",
                ],
            },
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "description": {"type": "string"},
            "reference_type": {"type": "string"},
            "reference_id": {"type": "string"},
            "transaction_date": {"type": "string"},
            "due_date": {"type": "string"},
            "status": {"type": "string"},
            "counterparty_name": {"type": "string"},
            "counterparty_id": {},
            "created_by": {"type": "string"},
        },
    ),
    ("finance", "update_transaction"): _object_schema(
        ["transaction_id"],
        {
            "transaction_id": {"type": "integer"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "description": {"type": "string"},
            "reference_type": {"type": "string"},
            "reference_id": {"type": "string"},
            "transaction_date": {"type": "string"},
            "due_date": {"type": "string"},
            "status": {"type": "string"},
            "counterparty_name": {"type": "string"},
            "counterparty_id": {},
        },
    ),
    ("finance", "delete_transaction"): _object_schema(
        ["transaction_id"], {"transaction_id": {"type": "integer"}}
    ),
    ("employee", "execute"): _object_schema(
        ["task"],
        {
            "employee_id": {"type": "string"},
            "pack_id": {"type": "string"},
            "task": {"type": "string"},
            "input": {
                "type": "object",
                "properties": {
                    "user_request": {"type": "string"},
                    "table_json": {
                        "type": "object",
                        "properties": {
                            "columns": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "object"}},
                        },
                    },
                },
            },
        },
    ),
    ("employee", "context"): _object_schema(
        ["task"],
        {
            "employee_id": {"type": "string"},
            "pack_id": {"type": "string"},
            "task": {"type": "string"},
            "input": {"type": "object"},
        },
    ),
    ("business_event", "print_label"): _object_schema(
        ["document_name"],
        {
            "job_id": {"type": "string"},
            "document_name": {"type": "string"},
            "printer_id": {"type": "string"},
            "copies": {"type": "integer"},
        },
    ),
    ("business_event", "inventory_update"): _object_schema(
        ["product_id"],
        {
            "product_id": {"type": "string"},
            "warehouse_id": {"type": "string"},
            "delta": {"type": "integer"},
            "reason": {"type": "string"},
            "new_quantity": {"type": "integer"},
        },
    ),
    ("business_event", "shipment_create"): _object_schema(
        ["unit_name"],
        {
            "unit_name": {"type": "string"},
            "items": {"type": "array"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
        },
    ),
    ("shipment_records", "create"): {
        "type": "object",
        "allOf": [
            {"anyOf": [{"required": ["unit_name"]}, {"required": ["purchase_unit"]}]},
            {"anyOf": [{"required": ["products"]}, {"required": ["items"]}]},
        ],
        "properties": {
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["unit_price"],
                    "allOf": [
                        {"anyOf": [{"required": ["product_name"]}, {"required": ["name"]}]},
                        {
                            "anyOf": [
                                {"required": ["quantity_kg"]},
                                {
                                    "required": ["quantity", "unit"],
                                    "properties": {
                                        "unit": {
                                            "pattern": "^(?:[kK][gG]|公斤|千克)$",
                                            "type": "string",
                                        }
                                    },
                                },
                                {
                                    "required": ["quantity", "quantity_unit"],
                                    "properties": {
                                        "quantity_unit": {
                                            "pattern": "^(?:[kK][gG]|公斤|千克)$",
                                            "type": "string",
                                        }
                                    },
                                },
                                {
                                    "allOf": [
                                        {
                                            "anyOf": [
                                                {"required": ["quantity_tins"]},
                                                {"required": ["quantity", "unit"]},
                                                {"required": ["quantity", "quantity_unit"]},
                                            ]
                                        },
                                        {
                                            "anyOf": [
                                                {"required": ["tin_spec"]},
                                                {"required": ["spec_per_tin"]},
                                                {"required": ["spec"]},
                                                {"required": ["weight_per_unit"]},
                                            ]
                                        },
                                    ]
                                },
                            ]
                        },
                    ],
                },
            },
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["unit_price"],
                    "allOf": [
                        {"anyOf": [{"required": ["product_name"]}, {"required": ["name"]}]},
                        {
                            "anyOf": [
                                {"required": ["quantity_kg"]},
                                {
                                    "required": ["quantity", "unit"],
                                    "properties": {
                                        "unit": {
                                            "pattern": "^(?:[kK][gG]|公斤|千克)$",
                                            "type": "string",
                                        }
                                    },
                                },
                                {
                                    "required": ["quantity", "quantity_unit"],
                                    "properties": {
                                        "quantity_unit": {
                                            "pattern": "^(?:[kK][gG]|公斤|千克)$",
                                            "type": "string",
                                        }
                                    },
                                },
                                {
                                    "allOf": [
                                        {
                                            "anyOf": [
                                                {"required": ["quantity_tins"]},
                                                {"required": ["quantity", "unit"]},
                                                {"required": ["quantity", "quantity_unit"]},
                                            ]
                                        },
                                        {
                                            "anyOf": [
                                                {"required": ["tin_spec"]},
                                                {"required": ["spec_per_tin"]},
                                                {"required": ["spec"]},
                                                {"required": ["weight_per_unit"]},
                                            ]
                                        },
                                    ]
                                },
                            ]
                        },
                    ],
                },
            },
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
        },
    },
    ("shipment_records", "update"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {"type": "array"},
            "items": {"type": "array"},
            "date": {"type": "string"},
            "status": {"type": "string"},
        },
    ),
    ("shipment_records", "delete"): _PRODUCTS_DELETE_INPUT,
    ("shipment_records", "clear"): _object_schema([], {}),
    ("shipment_orders", "generate"): _object_schema(
        ["unit_name", "products"],
        {
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {"type": "array"},
            "items": {"type": "array"},
            "date": {"type": "string"},
        },
    ),
    ("shipment_orders", "generate_batch"): _object_schema(
        ["shipments"], {"shipments": {"type": "array"}}
    ),
    ("shipment_orders", "print"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "order_id": {},
            "printer_name": {"type": "string"},
        },
    ),
    ("shipment_orders", "clear_shipment"): _object_schema(
        ["purchase_unit"], {"purchase_unit": {"type": "string"}, "unit_name": {"type": "string"}}
    ),
    ("shipment_orders", "set_sequence"): _object_schema(
        ["sequence"], {"sequence": {"type": "integer"}}
    ),
    ("shipment_orders", "reset_sequence"): {"type": "object", "properties": {}},
    ("shipment_orders", "clear_all"): {"type": "object", "properties": {}},
    ("shipment_orders", "delete"): _object_schema(
        ["id"],
        {
            "id": {"type": "integer"},
            "shipment_id": {"type": "integer"},
            "order_id": {"type": "integer"},
            "order_number": {"type": "string"},
        },
    ),
    ("print", "print_document"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "printer_name": {"type": "string"},
            "use_automation": {"type": "boolean"},
        },
    ),
    ("print", "print_label"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "printer_name": {"type": "string"},
            "copies": {"type": "integer"},
        },
    ),
    ("print", "test"): _PRINT_TEST_INPUT,
    ("print", "save_printer_selection"): {
        "type": "object",
        "properties": {"document_printer": {"type": "string"}, "label_printer": {"type": "string"}},
    },
    ("print", "workflow_label_dispatch"): _object_schema(
        ["model_number"],
        {
            "model_number": {"type": "string"},
            "quantity": {"type": "integer"},
            "idempotency_key": {"type": "string"},
        },
    ),
    ("system_maintenance", "set_default_printer"): _PRINT_TEST_INPUT,
    ("system_maintenance", "enable_startup"): _object_schema([], {}),
    ("system_maintenance", "disable_startup"): _object_schema([], {}),
    ("system_maintenance", "backup_database"): _object_schema([], {}),
    (
        "system_maintenance",
        "delete_database_backup",
    ): _SYSTEM_MAINTENANCE_DELETE_DATABASE_BACKUP_INPUT,
    ("system_maintenance", "restore_database"): _SYSTEM_MAINTENANCE_DELETE_DATABASE_BACKUP_INPUT,
    ("system_maintenance", "clear_performance_cache"): _object_schema(
        [], {"pattern": {"type": "string"}}
    ),
    ("system_maintenance", "invalidate_performance_cache"): _object_schema(
        ["keys"], {"keys": {"type": "array", "minItems": 1}}
    ),
    ("system_maintenance", "reinitialize_performance"): _object_schema([], {}),
    ("excel_analysis", "export"): _object_schema(
        ["file_path", "rows"],
        {
            "file_path": {"type": "string"},
            "rows": {"type": "array", "minItems": 1},
        },
    ),
    ("excel_analysis", "read"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "header_row": {"type": "integer"},
            "offset": {"type": "integer"},
            "max_rows": {"type": "integer"},
        },
    ),
    ("excel_analysis", "query"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "question": {"type": "string"},
            "natural_language": {"type": "string"},
            "sheet_name": {"type": "string"},
            "offset": {"type": "integer"},
            "max_rows": {"type": "integer"},
        },
    ),
    ("import_excel_to_database", "import"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "import_type": {"type": "string", "enum": ["products", "customers", "orders"]},
            "sheet_name": {"type": "string"},
            "header_row": {"type": "integer"},
            "last_data_row_1based": {"type": "integer"},
            "unit_name": {"type": "string"},
            "price_column": {"type": "string"},
            "confirm": {"type": "boolean"},
        },
    ),
    ("elt_import", "preview"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "valid_rows_only": {"type": "boolean"},
        },
    ),
    ("elt_import", "execute"): _object_schema(
        ["run_id"],
        {
            "run_id": {"type": "string"},
            "valid_rows_only": {"type": "boolean"},
        },
    ),
    ("excel_import", "execute_import"): _object_schema(
        ["pending_import_id"], {"pending_import_id": {"type": "string"}}
    ),
    ("excel_import", "import_records"): _object_schema(
        ["records"], {"records": {"type": "array"}, "source": {"type": "string"}}
    ),
    ("excel_analyzer", "analyze"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "output_json": {"type": "string"},
        },
    ),
    ("excel_toolkit", "view"): _EXCEL_TOOLKIT_VIEW_INPUT,
    ("excel_toolkit", "merged"): _EXCEL_TOOLKIT_MERGED_INPUT,
    ("excel_toolkit", "styles"): _EXCEL_TOOLKIT_VIEW_INPUT,
    ("excel_toolkit", "structure"): _EXCEL_TOOLKIT_MERGED_INPUT,
    ("label_template_generator", "execute"): _object_schema(
        ["image_path"],
        {
            "image_path": {"type": "string"},
            "class_name": {"type": "string"},
            "output_file": {"type": "string"},
            "enable_ocr": {"type": "boolean"},
            "verbose": {"type": "boolean"},
        },
    ),
    ("document_template", "create"): _object_schema(
        [],
        {
            "name": {"type": "string"},
            "template_name": {"type": "string"},
            "template_type": {"type": "string"},
            "business_scope": {"type": "string"},
            "category": {"type": "string"},
            "source": {"type": "string"},
            "file_path": {"type": "string"},
            "original_file_path": {"type": "string"},
            "fields": {"type": "array"},
            "preview_data": {"type": "object"},
        },
    ),
    ("document_template", "update"): _object_schema(
        ["id"],
        {
            "id": {},
            "name": {"type": "string"},
            "template_name": {"type": "string"},
            "template_type": {"type": "string"},
            "business_scope": {"type": "string"},
            "category": {"type": "string"},
            "source": {"type": "string"},
            "file_path": {"type": "string"},
            "original_file_path": {"type": "string"},
            "fields": {"type": "array"},
            "preview_data": {"type": "object"},
            "enforce_scope_match": {"type": "boolean"},
            "replace_mode": {"type": "boolean"},
        },
    ),
    ("document_template", "delete"): _object_schema(["id"], {"id": {}}),
    ("document_template", "clear"): _object_schema([], {}),
    ("document_template", "ingest"): _DOCUMENT_TEMPLATE_INGEST_INPUT,
    ("document_template", "upload"): _DOCUMENT_TEMPLATE_INGEST_INPUT,
    ("dataset_rag", "query"): _object_schema(
        ["dataset_id", "query"],
        {
            "dataset_id": {"type": "string"},
            "query": {"type": "string"},
            "tenant_id": {"type": "string"},
            "top_k": {"type": "integer"},
            "version": {"type": "string"},
            "metadata_filter": {"type": "object"},
            "rerank": {"type": "boolean"},
            "include_answer": {"type": "boolean"},
        },
    ),
    ("dataset_rag", "ingest_document"): _object_schema(
        ["dataset_id"],
        {
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "text": {"type": "string"},
            "file_path": {"type": "string"},
            "document_id": {"type": "string"},
            "tenant_id": {"type": "string"},
            "version": {"type": "string"},
            "version_label": {"type": "string"},
            "chunk_strategy": {"type": "string", "enum": ["semantic", "fixed"]},
            "chunk_size": {"type": "integer"},
            "chunk_overlap": {"type": "integer"},
            "metadata": {"type": "object"},
            "access_context": {"type": "object"},
        },
    ),
    ("dataset_rag", "diff_versions"): _object_schema(
        ["dataset_id", "source", "from_version"],
        {
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "tenant_id": {"type": "string"},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "access_context": {"type": "object"},
        },
    ),
    ("dataset_rag", "rollback_version"): _object_schema(
        ["dataset_id", "source", "target_version"],
        {
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "tenant_id": {"type": "string"},
            "target_version": {"type": "string"},
            "metadata": {"type": "object"},
            "access_context": {"type": "object"},
        },
    ),
    ("dataset_rag", "rebuild_index"): _object_schema(
        ["dataset_id"],
        {
            "dataset_id": {"type": "string"},
            "tenant_id": {"type": "string"},
            "metadata_filter": {"type": "object"},
            "background": {"type": "boolean"},
            "max_attempts": {"type": "integer"},
            "access_context": {"type": "object"},
        },
    ),
    ("dataset_rag", "cancel_rebuild"): _object_schema(
        ["dataset_id", "job_id"],
        {
            "dataset_id": {"type": "string"},
            "job_id": {"type": "string"},
            "access_context": {"type": "object"},
        },
    ),
    ("sales", "quote"): _SALES_QUOTE_INPUT,
    ("dataset_rag", "delete_document"): _object_schema(
        ["dataset_id", "document_id"],
        {
            "dataset_id": {"type": "string"},
            "document_id": {"type": "string"},
            "access_context": {"type": "object"},
        },
    ),
    ("dataset_rag", "clear_dataset"): _object_schema(
        ["dataset_id"],
        {
            "dataset_id": {"type": "string"},
            "tenant_id": {"type": "string"},
            "access_context": {"type": "object"},
        },
    ),
    ("memory_v2", "propose_candidate"): _object_schema(
        ["user_id", "memory_type", "key", "value"],
        {
            "user_id": {"type": "string"},
            "memory_type": {"type": "string", "enum": ["preference", "entity", "episodic"]},
            "type": {"type": "string"},
            "key": {"type": "string"},
            "value": {},
            "source": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "array"},
        },
    ),
    ("memory_v2", "confirm"): _object_schema(
        ["user_id", "memory_id"],
        {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "correction": {"type": "object"},
        },
    ),
    ("memory_v2", "reject"): _MEMORY_V2_REJECT_INPUT,
    ("memory_v2", "correct"): _object_schema(
        ["user_id", "memory_id"],
        {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "key": {"type": "string"},
            "value": {},
            "reason": {"type": "string"},
        },
    ),
    ("memory_v2", "delete"): _MEMORY_V2_REJECT_INPUT,
    ("template_extract", "extract"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "template_name": {"type": "string"},
            "template_scope": {"type": "string"},
        },
    ),
    ("unit_products_import", "execute_import"): _object_schema(
        ["saved_name", "unit_name"],
        {
            "saved_name": {"type": "string"},
            "unit_name": {"type": "string"},
            "create_purchase_unit": {"type": "boolean"},
            "skip_duplicates": {"type": "boolean"},
        },
    ),
    ("excel_vector_index", "execute"): _object_schema(
        ["file_path"],
        {
            "file_path": {"type": "string"},
            "index_name": {"type": "string"},
            "index_id": {"type": "string"},
        },
    ),
    ("excel_vector_index", "query"): _object_schema(
        ["index_id", "query"],
        {
            "index_id": {"type": "string"},
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
    ),
    ("ocr", "recognize"): _OCR_RECOGNIZE_INPUT,
    ("ocr", "request"): _object_schema(
        ["request_id", "image_url"],
        {
            "request_id": {"type": "string"},
            "image_url": {"type": "string"},
            "ocr_type": {"type": "string"},
            "user_id": {"type": "string"},
        },
    ),
    ("ocr", "extract"): _OCR_EXTRACT_INPUT,
    ("ocr", "analyze"): _OCR_EXTRACT_INPUT,
    ("ocr", "recognize_and_extract"): _OCR_RECOGNIZE_INPUT,
    ("generate_office_document", "execute"): _object_schema(
        [],
        {
            "user_request": {"type": "string"},
            "prompt": {"type": "string"},
            "request": {"type": "string"},
            "output_format": {"type": "string", "enum": ["docx", "xlsx"]},
            "template_id": {"type": "string"},
            "template_name": {"type": "string"},
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object"}},
            "field_mapping": {"type": "object"},
            "output_name": {"type": "string"},
        },
    ),
    ("sales", "create_order"): _SALES_QUOTE_INPUT,
}
