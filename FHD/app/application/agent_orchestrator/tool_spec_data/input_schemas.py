from __future__ import annotations

from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

_SPECIAL_INPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("business_db", "read"): {
        "type": "object",
        "required": ["entity"],
        "properties": {
            "entity": {"type": "string", "enum": _BUSINESS_ENTITIES},
            "keyword": {"type": "string"},
            "query": {"type": "string"},
        },
    },
    ("business_db", "write"): {
        "type": "object",
        "required": ["entity", "operation", "payload"],
        "properties": {
            "entity": {"type": "string", "enum": _BUSINESS_ENTITIES},
            "operation": {
                "type": "string",
                "enum": ["create", "ensure_exists", "upsert", "update", "delete", "batch_delete"],
            },
            "payload": {"type": "object"},
        },
    },
    ("customers", "create"): {
        "type": "object",
        "required": ["unit_name"],
        "properties": {
            "unit_name": {"type": "string"},
            "customer_name": {"type": "string"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "contact_address": {"type": "string"},
            "address": {"type": "string"},
        },
    },
    ("customers", "update"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "customer_id": {"type": "integer"},
            "unit_name": {"type": "string"},
            "customer_name": {"type": "string"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "contact_address": {"type": "string"},
            "address": {"type": "string"},
        },
    },
    ("customers", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "customer_id": {"type": "integer"},
            "force": {"type": "boolean"},
        },
    },
    ("customers", "batch_delete"): {
        "type": "object",
        "required": ["ids"],
        "properties": {
            "ids": {"type": "array"},
            "customer_ids": {"type": "array"},
            "force": {"type": "boolean"},
        },
    },
    ("products", "create"): {
        "type": "object",
        "required": ["name_or_model", "unit_name"],
        "properties": {
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
    },
    ("products", "update"): {
        "type": "object",
        "required": ["id"],
        "properties": {
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
    },
    ("products", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
        },
    },
    ("products", "batch_create"): {
        "type": "object",
        "required": ["products"],
        "properties": {
            "products": {"type": "array"},
        },
    },
    ("products", "batch_delete"): {
        "type": "object",
        "required": ["ids"],
        "properties": {
            "ids": {"type": "array"},
            "product_ids": {"type": "array"},
        },
    },
    ("materials", "create"): {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "material_name": {"type": "string"},
            "material_code": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
            "min_stock": {"type": "number"},
            "min_quantity": {"type": "number"},
        },
    },
    ("materials", "update"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "quantity": {"type": "number"},
            "min_stock": {"type": "number"},
        },
    },
    ("materials", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
        },
    },
    ("materials", "batch_delete"): {
        "type": "object",
        "required": [],
        "properties": {
            "ids": {"type": "array"},
            "material_ids": {"type": "array"},
        },
    },
    ("inventory", "create_storage_location"): {
        "type": "object",
        "required": [],
        "properties": {
            "warehouse_id": {},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("inventory", "update_storage_location"): {
        "type": "object",
        "required": ["location_id"],
        "properties": {
            "location_id": {"type": "integer"},
            "warehouse_id": {},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("inventory", "create_warehouse"): {
        "type": "object",
        "required": [],
        "properties": {
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("inventory", "update_warehouse"): {
        "type": "object",
        "required": ["warehouse_id"],
        "properties": {
            "warehouse_id": {"type": "integer"},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("inventory", "delete_warehouse"): {
        "type": "object",
        "required": ["warehouse_id"],
        "properties": {
            "warehouse_id": {"type": "integer"},
        },
    },
    ("inventory", "stock_in"): {
        "type": "object",
        "required": ["product_id", "warehouse_id", "quantity"],
        "properties": {
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
    ("inventory", "stock_out"): {
        "type": "object",
        "required": ["product_id", "warehouse_id", "quantity"],
        "properties": {
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
    ("inventory", "transfer"): {
        "type": "object",
        "required": ["product_id", "from_warehouse_id", "to_warehouse_id", "quantity"],
        "properties": {
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
    },
    ("purchase", "create_supplier"): {
        "type": "object",
        "required": [],
        "properties": {
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "address": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("purchase", "update_supplier"): {
        "type": "object",
        "required": ["supplier_id"],
        "properties": {
            "supplier_id": {"type": "integer"},
            "name": {"type": "string"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
            "address": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("purchase", "delete_supplier"): {
        "type": "object",
        "required": ["supplier_id"],
        "properties": {
            "supplier_id": {"type": "integer"},
        },
    },
    ("purchase", "create_order"): {
        "type": "object",
        "required": [],
        "properties": {
            "supplier_id": {},
            "items": {"type": "array"},
            "order_date": {"type": "string"},
            "expected_date": {"type": "string"},
            "remark": {"type": "string"},
        },
    },
    ("purchase", "update_order"): {
        "type": "object",
        "required": ["order_id"],
        "properties": {
            "order_id": {"type": "integer"},
            "supplier_id": {},
            "items": {"type": "array"},
            "status": {"type": "string"},
            "remark": {"type": "string"},
        },
    },
    ("purchase", "approve_order"): {
        "type": "object",
        "required": ["order_id"],
        "properties": {
            "order_id": {"type": "integer"},
            "approver": {"type": "string"},
        },
    },
    ("purchase", "cancel_order"): {
        "type": "object",
        "required": ["order_id"],
        "properties": {
            "order_id": {"type": "integer"},
        },
    },
    ("purchase", "create_inbound"): {
        "type": "object",
        "required": [],
        "properties": {
            "supplier_id": {},
            "order_id": {},
            "items": {"type": "array"},
            "inbound_date": {"type": "string"},
            "operator": {"type": "string"},
            "remark": {"type": "string"},
        },
    },
    ("finance", "create_transaction"): {
        "type": "object",
        "required": ["transaction_type", "amount"],
        "properties": {
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
    },
    ("finance", "update_transaction"): {
        "type": "object",
        "required": ["transaction_id"],
        "properties": {
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
    },
    ("finance", "delete_transaction"): {
        "type": "object",
        "required": ["transaction_id"],
        "properties": {
            "transaction_id": {"type": "integer"},
        },
    },
    ("employee", "execute"): {
        "type": "object",
        "required": ["task"],
        "properties": {
            "employee_id": {"type": "string"},
            "pack_id": {"type": "string"},
            "task": {"type": "string"},
            "input": {"type": "object"},
        },
    },
    ("business_event", "print_label"): {
        "type": "object",
        "required": ["document_name"],
        "properties": {
            "job_id": {"type": "string"},
            "document_name": {"type": "string"},
            "printer_id": {"type": "string"},
            "copies": {"type": "integer"},
        },
    },
    ("business_event", "inventory_update"): {
        "type": "object",
        "required": ["product_id"],
        "properties": {
            "product_id": {"type": "string"},
            "warehouse_id": {"type": "string"},
            "delta": {"type": "integer"},
            "reason": {"type": "string"},
            "new_quantity": {"type": "integer"},
        },
    },
    ("business_event", "shipment_create"): {
        "type": "object",
        "required": ["unit_name"],
        "properties": {
            "unit_name": {"type": "string"},
            "items": {"type": "array"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
        },
    },
    ("shipment_records", "create"): {
        "type": "object",
        "required": ["unit_name"],
        "properties": {
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {"type": "array"},
            "items": {"type": "array"},
            "contact_person": {"type": "string"},
            "contact_phone": {"type": "string"},
        },
    },
    ("shipment_records", "update"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {"type": "array"},
            "items": {"type": "array"},
            "date": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    ("shipment_records", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
        },
    },
    ("shipment_orders", "generate"): {
        "type": "object",
        "required": ["unit_name", "products"],
        "properties": {
            "unit_name": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "products": {"type": "array"},
            "items": {"type": "array"},
            "date": {"type": "string"},
        },
    },
    ("shipment_orders", "generate_batch"): {
        "type": "object",
        "required": ["shipments"],
        "properties": {
            "shipments": {"type": "array"},
        },
    },
    ("shipment_orders", "print"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "order_id": {},
            "printer_name": {"type": "string"},
        },
    },
    ("shipment_orders", "clear_shipment"): {
        "type": "object",
        "required": ["purchase_unit"],
        "properties": {
            "purchase_unit": {"type": "string"},
            "unit_name": {"type": "string"},
        },
    },
    ("shipment_orders", "set_sequence"): {
        "type": "object",
        "required": ["sequence"],
        "properties": {
            "sequence": {"type": "integer"},
        },
    },
    ("shipment_orders", "reset_sequence"): {
        "type": "object",
        "properties": {},
    },
    ("shipment_orders", "clear_all"): {
        "type": "object",
        "properties": {},
    },
    ("shipment_orders", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "shipment_id": {"type": "integer"},
            "order_id": {"type": "integer"},
            "order_number": {"type": "string"},
        },
    },
    ("print", "print_document"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "printer_name": {"type": "string"},
            "use_automation": {"type": "boolean"},
        },
    },
    ("print", "print_label"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "printer_name": {"type": "string"},
            "copies": {"type": "integer"},
        },
    },
    ("print", "test"): {
        "type": "object",
        "required": ["printer_name"],
        "properties": {
            "printer_name": {"type": "string"},
        },
    },
    ("print", "save_printer_selection"): {
        "type": "object",
        "properties": {
            "document_printer": {"type": "string"},
            "label_printer": {"type": "string"},
        },
    },
    ("print", "workflow_label_dispatch"): {
        "type": "object",
        "required": ["model_number"],
        "properties": {
            "model_number": {"type": "string"},
            "quantity": {"type": "integer"},
            "idempotency_key": {"type": "string"},
        },
    },
    ("system_maintenance", "set_default_printer"): {
        "type": "object",
        "required": ["printer_name"],
        "properties": {
            "printer_name": {"type": "string"},
        },
    },
    ("system_maintenance", "enable_startup"): {
        "type": "object",
        "required": [],
        "properties": {},
    },
    ("system_maintenance", "disable_startup"): {
        "type": "object",
        "required": [],
        "properties": {},
    },
    ("system_maintenance", "backup_database"): {
        "type": "object",
        "required": [],
        "properties": {},
    },
    ("system_maintenance", "delete_database_backup"): {
        "type": "object",
        "required": ["backup_file"],
        "properties": {
            "backup_file": {"type": "string"},
        },
    },
    ("system_maintenance", "restore_database"): {
        "type": "object",
        "required": ["backup_file"],
        "properties": {
            "backup_file": {"type": "string"},
        },
    },
    ("system_maintenance", "clear_performance_cache"): {
        "type": "object",
        "required": [],
        "properties": {
            "pattern": {"type": "string"},
        },
    },
    ("system_maintenance", "invalidate_performance_cache"): {
        "type": "object",
        "required": ["keys"],
        "properties": {
            "keys": {"type": "array"},
        },
    },
    ("system_maintenance", "reinitialize_performance"): {
        "type": "object",
        "required": [],
        "properties": {},
    },
    ("excel_analysis", "read"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "header_row": {"type": "integer"},
        },
    },
    ("excel_analysis", "query"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "question": {"type": "string"},
            "natural_language": {"type": "string"},
            "sheet_name": {"type": "string"},
        },
    },
    ("excel_import", "execute_import"): {
        "type": "object",
        "required": ["pending_import_id"],
        "properties": {
            "pending_import_id": {"type": "string"},
        },
    },
    ("excel_import", "import_records"): {
        "type": "object",
        "required": ["records"],
        "properties": {
            "records": {"type": "array"},
            "source": {"type": "string"},
        },
    },
    ("excel_import", "import_roster_file"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "source": {"type": "string"},
        },
    },
    ("excel_analyzer", "analyze"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "output_json": {"type": "string"},
        },
    },
    ("excel_toolkit", "view"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "max_rows": {"type": "integer"},
        },
    },
    ("excel_toolkit", "merged"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
        },
    },
    ("excel_toolkit", "styles"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "max_rows": {"type": "integer"},
        },
    },
    ("excel_toolkit", "structure"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
        },
    },
    ("label_template_generator", "execute"): {
        "type": "object",
        "required": ["image_path"],
        "properties": {
            "image_path": {"type": "string"},
            "class_name": {"type": "string"},
            "output_file": {"type": "string"},
            "enable_ocr": {"type": "boolean"},
            "verbose": {"type": "boolean"},
        },
    },
    ("document_template", "create"): {
        "type": "object",
        "required": [],
        "properties": {
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
    },
    ("document_template", "update"): {
        "type": "object",
        "required": ["id"],
        "properties": {
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
    },
    ("document_template", "delete"): {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {},
        },
    },
    ("dataset_rag", "query"): {
        "type": "object",
        "required": ["dataset_id", "query"],
        "properties": {
            "dataset_id": {"type": "string"},
            "query": {"type": "string"},
            "tenant_id": {"type": "string"},
            "top_k": {"type": "integer"},
            "version": {"type": "string"},
            "metadata_filter": {"type": "object"},
            "rerank": {"type": "boolean"},
            "include_answer": {"type": "boolean"},
        },
    },
    ("dataset_rag", "ingest_document"): {
        "type": "object",
        "required": ["dataset_id"],
        "properties": {
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
    },
    ("dataset_rag", "diff_versions"): {
        "type": "object",
        "required": ["dataset_id", "source", "from_version"],
        "properties": {
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "tenant_id": {"type": "string"},
            "from_version": {"type": "string"},
            "to_version": {"type": "string"},
            "access_context": {"type": "object"},
        },
    },
    ("dataset_rag", "rollback_version"): {
        "type": "object",
        "required": ["dataset_id", "source", "target_version"],
        "properties": {
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "tenant_id": {"type": "string"},
            "target_version": {"type": "string"},
            "metadata": {"type": "object"},
            "access_context": {"type": "object"},
        },
    },
    ("dataset_rag", "rebuild_index"): {
        "type": "object",
        "required": ["dataset_id"],
        "properties": {
            "dataset_id": {"type": "string"},
            "tenant_id": {"type": "string"},
            "metadata_filter": {"type": "object"},
            "background": {"type": "boolean"},
            "max_attempts": {"type": "integer"},
            "access_context": {"type": "object"},
        },
    },
    ("dataset_rag", "cancel_rebuild"): {
        "type": "object",
        "required": ["dataset_id", "job_id"],
        "properties": {
            "dataset_id": {"type": "string"},
            "job_id": {"type": "string"},
            "access_context": {"type": "object"},
        },
    },
    ("dataset_rag", "delete_document"): {
        "type": "object",
        "required": ["dataset_id", "document_id"],
        "properties": {
            "dataset_id": {"type": "string"},
            "document_id": {"type": "string"},
            "access_context": {"type": "object"},
        },
    },
    ("memory_v2", "propose_candidate"): {
        "type": "object",
        "required": ["user_id", "memory_type", "key", "value"],
        "properties": {
            "user_id": {"type": "string"},
            "memory_type": {"type": "string", "enum": ["preference", "entity", "episodic"]},
            "type": {"type": "string"},
            "key": {"type": "string"},
            "value": {},
            "source": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "array"},
        },
    },
    ("memory_v2", "confirm"): {
        "type": "object",
        "required": ["user_id", "memory_id"],
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "correction": {"type": "object"},
        },
    },
    ("memory_v2", "reject"): {
        "type": "object",
        "required": ["user_id", "memory_id"],
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
    ("memory_v2", "correct"): {
        "type": "object",
        "required": ["user_id", "memory_id"],
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "key": {"type": "string"},
            "value": {},
            "reason": {"type": "string"},
        },
    },
    ("memory_v2", "delete"): {
        "type": "object",
        "required": ["user_id", "memory_id"],
        "properties": {
            "user_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
    ("template_extract", "extract"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "sheet_name": {"type": "string"},
            "template_name": {"type": "string"},
            "template_scope": {"type": "string"},
        },
    },
    ("unit_products_import", "execute_import"): {
        "type": "object",
        "required": ["saved_name", "unit_name"],
        "properties": {
            "saved_name": {"type": "string"},
            "unit_name": {"type": "string"},
            "create_purchase_unit": {"type": "boolean"},
            "skip_duplicates": {"type": "boolean"},
        },
    },
    ("excel_vector_index", "execute"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
            "index_name": {"type": "string"},
            "index_id": {"type": "string"},
        },
    },
    ("excel_vector_index", "query"): {
        "type": "object",
        "required": ["index_id", "query"],
        "properties": {
            "index_id": {"type": "string"},
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
    },
    ("ocr", "recognize"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
        },
    },
    ("ocr", "request"): {
        "type": "object",
        "required": ["request_id", "image_url"],
        "properties": {
            "request_id": {"type": "string"},
            "image_url": {"type": "string"},
            "ocr_type": {"type": "string"},
            "user_id": {"type": "string"},
        },
    },
    ("ocr", "extract"): {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
        },
    },
    ("ocr", "analyze"): {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
        },
    },
    ("ocr", "recognize_and_extract"): {
        "type": "object",
        "required": ["file_path"],
        "properties": {
            "file_path": {"type": "string"},
        },
    },
    ("generate_office_document", "execute"): {
        "type": "object",
        "required": [],
        "properties": {
            "user_request": {"type": "string"},
            "prompt": {"type": "string"},
            "request": {"type": "string"},
            "output_format": {"type": "string", "enum": ["docx", "xlsx"]},
        },
    },
}
