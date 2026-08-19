from __future__ import annotations

from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

SPECIAL_INPUT_SCHEMAS_PART_2: dict[tuple[str, str], dict[str, Any]] = {
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
    ("document_template", "ingest"): {
        "type": "object",
        "required": [],
        "properties": {
            "file_path": {"type": "string"},
            "original_file_path": {"type": "string"},
            "filename": {"type": "string"},
            "template_name": {"type": "string"},
            "name": {"type": "string"},
            "template_scope": {"type": "string"},
            "business_scope": {"type": "string"},
            "source": {"type": "string"},
        },
    },
    ("document_template", "upload"): {
        "type": "object",
        "required": [],
        "properties": {
            "file_path": {"type": "string"},
            "original_file_path": {"type": "string"},
            "filename": {"type": "string"},
            "template_name": {"type": "string"},
            "name": {"type": "string"},
            "template_scope": {"type": "string"},
            "business_scope": {"type": "string"},
            "source": {"type": "string"},
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
}
