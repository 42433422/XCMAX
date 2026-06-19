from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

from app.utils.operational_errors import RECOVERABLE_ERRORS

RiskLevel = Literal["low", "medium", "high"]

_DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["success"],
    "properties": {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {},
    },
}

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

_SPECIAL_OUTPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("business_db", "read"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "array"},
            "error": {"type": "string"},
        },
    },
    ("business_db", "write"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("customers", "create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "created": {"type": "boolean"},
            "data": {"type": "object"},
            "raw": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("customers", "update"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("customers", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("customers", "batch_delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted": {"type": "integer"},
            "deleted_count": {"type": "integer"},
            "skipped": {"type": "array"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("products", "create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "created": {"type": "boolean"},
            "raw": {"type": "object"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("products", "update"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("products", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("products", "batch_create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("products", "batch_delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted": {"type": "integer"},
            "deleted_count": {"type": "integer"},
            "skipped": {"type": "array"},
            "data": {"type": "object"},
            "status_code": {"type": "integer"},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("materials", "create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "created": {"type": "boolean"},
            "error": {"type": "string"},
        },
    },
    ("materials", "update"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("materials", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "deleted_count": {"type": "integer"},
            "error": {"type": "string"},
        },
    },
    ("materials", "batch_delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "warning": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "create_storage_location"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "id": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "update_storage_location"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "create_warehouse"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "id": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "update_warehouse"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "delete_warehouse"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "stock_in"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "stock_out"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("inventory", "transfer"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "create_supplier"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "update_supplier"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "delete_supplier"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "create_order"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "update_order"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "approve_order"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "cancel_order"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("purchase", "create_inbound"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("finance", "create_transaction"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("finance", "update_transaction"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("finance", "delete_transaction"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("employee", "list"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "array"},
        },
    },
    ("employee", "execute"): {
        "type": "object",
        "required": ["success", "message", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "employee_id": {"type": "string"},
        },
    },
    ("excel_import", "execute_import"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "imported_count": {"type": "integer"},
            "data": {"type": "object"},
        },
    },
    ("excel_import", "import_records"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "imported_count": {"type": "integer"},
            "data": {"type": "object"},
        },
    },
    ("unit_products_import", "execute_import"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "created_customers": {"type": "integer"},
            "created_products": {"type": "integer"},
            "data": {"type": "object"},
        },
    },
    ("generate_office_document", "execute"): {
        "type": "object",
        "required": ["success", "file_name", "download_url", "artifacts"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_name": {"type": "string"},
            "download_url": {"type": "string"},
            "pickup_token": {"type": "string"},
            "artifacts": {"type": "array"},
        },
    },
    ("excel_vector_index", "execute"): {
        "type": "object",
        "required": ["success", "index_id"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "index_id": {"type": "string"},
            "excel_vector_index_id": {"type": "string"},
            "excel_index_id": {"type": "string"},
            "chunk_count": {"type": "integer"},
            "row_count": {"type": "integer"},
            "error": {"type": "string"},
        },
    },
    ("excel_vector_index", "query"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "index_id": {"type": "string"},
            "query": {"type": "string"},
            "hits": {"type": "array"},
            "error": {"type": "string"},
        },
    },
    ("ocr", "recognize"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "text": {"type": "string"},
            "file_path": {"type": "string"},
            "confidence": {"type": "number"},
            "artifacts": {"type": "array"},
            "error_code": {"type": "string"},
        },
    },
    ("ocr", "request"): {
        "type": "object",
        "required": ["success", "request_id", "event", "published"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "request_id": {"type": "string"},
            "image_url": {"type": "string"},
            "ocr_type": {"type": "string"},
            "user_id": {"type": "string"},
            "event": {"type": "string"},
            "published": {"type": "boolean"},
            "error_code": {"type": "string"},
        },
    },
    ("ocr", "extract"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error_code": {"type": "string"},
        },
    },
    ("ocr", "analyze"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error_code": {"type": "string"},
        },
    },
    ("ocr", "recognize_and_extract"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "text": {"type": "string"},
            "data": {"type": "object"},
            "analysis": {"type": "object"},
            "artifacts": {"type": "array"},
            "error_code": {"type": "string"},
        },
    },
    ("shipment_records", "create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "record_id": {"type": "integer"},
            "order_id": {"type": "integer"},
            "error": {"type": "string"},
        },
    },
    ("shipment_records", "update"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_records", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "generate"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "doc_name": {"type": "string"},
            "record_id": {"type": "integer"},
            "order_id": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "generate_batch"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "print"): {
        "type": "object",
        "required": ["success", "file_path", "updated"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "updated": {"type": "boolean"},
            "printed_at": {"type": "string"},
            "warning": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "clear_shipment"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "purchase_unit": {"type": "string"},
            "cleared_count": {"type": "integer"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "set_sequence"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "sequence": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "reset_sequence"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "sequence": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "clear_all"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "cleared_count": {"type": "integer"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("shipment_orders", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted_id": {"type": "integer"},
            "deleted_count": {"type": "integer"},
            "data": {"type": "object"},
            "error": {"type": "string"},
        },
    },
    ("print", "print_document"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "printer": {},
            "printer_name": {"type": "string"},
            "status": {"type": "string"},
            "job_id": {"type": "string"},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("print", "print_label"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "printer": {},
            "printer_name": {"type": "string"},
            "copies": {"type": "integer"},
            "status": {"type": "string"},
            "require_confirm": {"type": "boolean"},
            "job_id": {"type": "string"},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("print", "test"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "printer_name": {"type": "string"},
            "status": {"type": "string"},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("print", "save_printer_selection"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "selection": {"type": "object"},
            "document_printer": {"type": "string"},
            "label_printer": {"type": "string"},
            "document": {},
            "label": {},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("print", "workflow_label_dispatch"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "model_number": {"type": "string"},
            "product_name": {"type": "string"},
            "quantity": {"type": "integer"},
            "file_path": {"type": "string"},
            "status": {"type": "string"},
            "job_id": {"type": "string"},
            "error_code": {"type": "string"},
            "error": {"type": "string"},
        },
    },
    ("business_event", "print_label"): {
        "type": "object",
        "required": ["success", "job_id", "event"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "job_id": {"type": "string"},
            "event": {"type": "string"},
        },
    },
    ("business_event", "inventory_update"): {
        "type": "object",
        "required": ["success", "event"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "event": {"type": "string"},
        },
    },
    ("business_event", "shipment_create"): {
        "type": "object",
        "required": ["success", "event", "published"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "event": {"type": "string"},
            "published": {"type": "boolean"},
        },
    },
    ("system_maintenance", "set_default_printer"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "enable_startup"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "disable_startup"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "backup_database"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "backup_file": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "delete_database_backup"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "backup_file": {"type": "string"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "restore_database"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "backup_file": {"type": "string"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "clear_performance_cache"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "invalidate_performance_cache"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("system_maintenance", "reinitialize_performance"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("excel_analysis", "read"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "data": {"type": "object"},
        },
    },
    ("excel_analysis", "query"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "answer": {"type": "string"},
            "data": {"type": "object"},
        },
    },
    ("excel_analyzer", "analyze"): {
        "type": "object",
        "required": ["success", "file_path"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "file": {"type": "string"},
            "sheet": {"type": "string"},
            "structure": {"type": "object"},
            "zones": {"type": "array"},
            "merged_cells": {"type": "array"},
            "editable_ranges": {"type": "array"},
            "cells": {"type": "object"},
            "output_file": {"type": "string"},
        },
    },
    ("excel_toolkit", "view"): {
        "type": "object",
        "required": ["success", "file_path"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "file": {"type": "string"},
            "sheet": {"type": "string"},
            "structure": {"type": "object"},
            "content": {"type": "array"},
            "row_count": {"type": "integer"},
        },
    },
    ("excel_toolkit", "merged"): {
        "type": "object",
        "required": ["success", "file_path"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "file": {"type": "string"},
            "sheet": {"type": "string"},
            "merged_cells": {"type": "array"},
            "count": {"type": "integer"},
        },
    },
    ("excel_toolkit", "styles"): {
        "type": "object",
        "required": ["success", "file_path"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "file": {"type": "string"},
            "sheet": {"type": "string"},
            "styles": {"type": "array"},
        },
    },
    ("excel_toolkit", "structure"): {
        "type": "object",
        "required": ["success", "file_path"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "file": {"type": "string"},
            "sheet_names": {"type": "array"},
            "current_sheet": {"type": "string"},
            "structure": {"type": "object"},
            "columns": {"type": "array"},
        },
    },
    ("label_template_generator", "execute"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "image_path": {"type": "string"},
            "analysis": {"type": "object"},
            "ocr_result": {"type": "object"},
            "code": {"type": "string"},
            "output_file": {"type": "string"},
            "output_error": {"type": "string"},
        },
    },
    ("document_template", "create"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "template": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("document_template", "update"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "template": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("document_template", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "deleted": {"type": "object"},
            "http_status_code": {"type": "integer"},
        },
    },
    ("template_extract", "extract"): {
        "type": "object",
        "required": ["success", "file_path", "fields", "sample_rows"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "file_path": {"type": "string"},
            "sheet_names": {"type": "array"},
            "fields": {"type": "array"},
            "sample_rows": {"type": "array"},
            "grid_preview": {"type": "object"},
            "grid_style_cache": {"type": "object"},
            "sheets": {"type": "array"},
            "artifacts": {"type": "array"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "query"): {
        "type": "object",
        "required": ["success", "dataset_id", "query", "chunks", "citations", "answer"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "query": {"type": "string"},
            "answer": {"type": "string"},
            "chunks": {"type": "array"},
            "citations": {"type": "array"},
            "tenant_id": {"type": "string"},
            "version": {"type": "string"},
            "vector_backend_used": {"type": "boolean"},
            "index": {"type": "object"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "ingest_document"): {
        "type": "object",
        "required": ["success", "dataset_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "document": {"type": "object"},
            "chunk_count": {"type": "integer"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "diff_versions"): {
        "type": "object",
        "required": ["success", "dataset_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "source": {"type": "string"},
            "tenant_id": {"type": "string"},
            "from_document": {"type": "object"},
            "to_document": {"type": "object"},
            "from_version": {},
            "to_version": {},
            "changed": {"type": "boolean"},
            "added_lines": {"type": "array"},
            "removed_lines": {"type": "array"},
            "diff": {"type": "array"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "rollback_version"): {
        "type": "object",
        "required": ["success", "dataset_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "document": {"type": "object"},
            "chunk_count": {"type": "integer"},
            "rolled_back_from": {"type": "object"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "rebuild_index"): {
        "type": "object",
        "required": ["success", "dataset_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "job": {"type": "object"},
            "background": {"type": "boolean"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "cancel_rebuild"): {
        "type": "object",
        "required": ["success", "dataset_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "job_id": {"type": "string"},
            "job": {"type": "object"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("dataset_rag", "delete_document"): {
        "type": "object",
        "required": ["success", "dataset_id", "document_id"],
        "properties": {
            "success": {"type": "boolean"},
            "dataset_id": {"type": "string"},
            "document_id": {"type": "string"},
            "deleted_chunks": {"type": "integer"},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    },
    ("memory_v2", "propose_candidate"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "created": {"type": "boolean"},
            "candidate": {"type": "object"},
            "message": {"type": "string"},
        },
    },
    ("memory_v2", "confirm"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "memory": {"type": "object"},
            "message": {"type": "string"},
        },
    },
    ("memory_v2", "reject"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "memory": {"type": "object"},
            "message": {"type": "string"},
        },
    },
    ("memory_v2", "correct"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "memory": {"type": "object"},
            "message": {"type": "string"},
        },
    },
    ("memory_v2", "delete"): {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "memory": {"type": "object"},
            "message": {"type": "string"},
        },
    },
}

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

_SPECIAL_TEST_FIXTURES: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("business_db", "read"): [
        {
            "name": "read_products_by_keyword",
            "input": {"entity": "products", "keyword": "5003"},
            "output": {
                "success": True,
                "data": [{"model_number": "5003", "name": "sample product"}],
            },
        }
    ],
    ("business_db", "write"): [
        {
            "name": "create_customer",
            "input": {
                "entity": "customers",
                "operation": "create",
                "payload": {"unit_name": "Acme Trading"},
            },
            "output": {
                "success": True,
                "message": "customer created",
                "data": {"id": "cust_1"},
            },
        }
    ],
    ("customers", "create"): [
        {
            "name": "create_customer_route",
            "input": {
                "unit_name": "星光贸易",
                "contact_person": "张三",
                "contact_phone": "13900000000",
                "contact_address": "上海",
            },
            "output": {
                "success": True,
                "data": {
                    "id": 7,
                    "unit_name": "星光贸易",
                    "contact_person": "张三",
                },
            },
        }
    ],
    ("customers", "update"): [
        {
            "name": "update_customer_route",
            "input": {
                "id": 7,
                "unit_name": "星光贸易二部",
                "contact_person": "李四",
            },
            "output": {
                "success": True,
                "data": {
                    "id": 7,
                    "unit_name": "星光贸易二部",
                    "contact_person": "李四",
                },
            },
        }
    ],
    ("customers", "delete"): [
        {
            "name": "delete_customer_route",
            "input": {"id": 7},
            "output": {"success": True, "message": "已删除"},
        }
    ],
    ("customers", "batch_delete"): [
        {
            "name": "batch_delete_customer_route",
            "input": {"ids": [7, "bad", 8]},
            "output": {
                "success": True,
                "message": "已删除 2 条",
                "deleted": 2,
                "skipped": ["bad"],
            },
        }
    ],
    ("products", "create"): [
        {
            "name": "create_product",
            "input": {"name_or_model": "5003", "unit_name": "星光贸易", "unit_price": 12.5},
            "output": {
                "success": True,
                "created": True,
                "raw": {"success": True, "data": {"id": 7, "model_number": "5003"}},
            },
        }
    ],
    ("products", "update"): [
        {
            "name": "update_product",
            "input": {"id": 7, "name": "5003 v2"},
            "output": {
                "success": True,
                "data": {"id": 7, "name": "5003 v2"},
            },
        }
    ],
    ("products", "delete"): [
        {
            "name": "delete_product",
            "input": {"id": 7},
            "output": {"success": True, "message": "产品删除成功"},
        }
    ],
    ("products", "batch_create"): [
        {
            "name": "batch_create_products",
            "input": {"products": [{"name": "5003", "unit_price": 12.5}]},
            "output": {
                "success": True,
                "data": {"success_count": 1, "failed_count": 0},
            },
        }
    ],
    ("products", "batch_delete"): [
        {
            "name": "batch_delete_products",
            "input": {"ids": [7, 8]},
            "output": {
                "success": True,
                "message": "已删除 2 条",
                "deleted": 2,
                "skipped": [],
            },
        }
    ],
    ("materials", "create"): [
        {
            "name": "create_material",
            "input": {"name": "树脂", "material_code": "R-001", "min_quantity": 12},
            "output": {
                "success": True,
                "message": "创建成功",
                "data": {"id": 1, "name": "树脂"},
            },
        }
    ],
    ("materials", "update"): [
        {
            "name": "update_material",
            "input": {"id": 1, "name": "树脂 v2"},
            "output": {
                "success": True,
                "message": "更新成功",
                "data": {"id": 1, "name": "树脂 v2"},
            },
        }
    ],
    ("materials", "delete"): [
        {
            "name": "delete_material",
            "input": {"id": 1},
            "output": {
                "success": True,
                "message": "删除成功",
                "data": {"id": 1},
            },
        }
    ],
    ("materials", "batch_delete"): [
        {
            "name": "batch_delete_materials",
            "input": {"ids": [1, 2]},
            "output": {
                "success": True,
                "message": "已删除 2 条记录",
                "deleted_count": 2,
            },
        }
    ],
    ("inventory", "create_storage_location"): [
        {
            "name": "create_storage_location",
            "input": {"warehouse_id": 1, "code": "A-01"},
            "output": {"success": True, "id": 11},
        }
    ],
    ("inventory", "update_storage_location"): [
        {
            "name": "update_storage_location",
            "input": {"location_id": 11, "status": "full"},
            "output": {"success": True, "data": {"id": 11, "status": "full"}},
        }
    ],
    ("inventory", "create_warehouse"): [
        {
            "name": "create_warehouse",
            "input": {"name": "主仓"},
            "output": {"success": True, "data": {"id": 1, "name": "主仓"}},
        }
    ],
    ("inventory", "update_warehouse"): [
        {
            "name": "update_warehouse",
            "input": {"warehouse_id": 1, "name": "副仓"},
            "output": {"success": True, "data": {"id": 1, "name": "副仓"}},
        }
    ],
    ("inventory", "delete_warehouse"): [
        {
            "name": "delete_warehouse",
            "input": {"warehouse_id": 1},
            "output": {"success": True, "message": "deleted"},
        }
    ],
    ("inventory", "stock_in"): [
        {
            "name": "inventory_stock_in",
            "input": {"product_id": 1, "warehouse_id": 2, "quantity": 3.0},
            "output": {"success": True, "data": {"transaction_type": "in"}},
        }
    ],
    ("inventory", "stock_out"): [
        {
            "name": "inventory_stock_out",
            "input": {"product_id": 1, "warehouse_id": 2, "quantity": 1.0},
            "output": {"success": True, "data": {"transaction_type": "out"}},
        }
    ],
    ("inventory", "transfer"): [
        {
            "name": "inventory_transfer",
            "input": {
                "product_id": 1,
                "from_warehouse_id": 1,
                "to_warehouse_id": 2,
                "quantity": 1.0,
            },
            "output": {"success": True, "data": {"transaction_type": "transfer"}},
        }
    ],
    ("purchase", "create_supplier"): [
        {
            "name": "create_purchase_supplier",
            "input": {"name": "星光供应商", "contact_person": "张三"},
            "output": {
                "success": True,
                "message": "创建成功",
                "data": {"id": 1, "name": "星光供应商"},
            },
        }
    ],
    ("purchase", "update_supplier"): [
        {
            "name": "update_purchase_supplier",
            "input": {"supplier_id": 1, "status": "active"},
            "output": {
                "success": True,
                "message": "更新成功",
                "data": {"id": 1, "status": "active"},
            },
        }
    ],
    ("purchase", "delete_supplier"): [
        {
            "name": "delete_purchase_supplier",
            "input": {"supplier_id": 1},
            "output": {"success": True, "message": "删除成功"},
        }
    ],
    ("purchase", "create_order"): [
        {
            "name": "create_purchase_order",
            "input": {"supplier_id": 1, "items": [{"product_id": 2, "quantity": 3}]},
            "output": {
                "success": True,
                "message": "创建成功",
                "data": {"id": 9, "status": "draft"},
            },
        }
    ],
    ("purchase", "update_order"): [
        {
            "name": "update_purchase_order",
            "input": {"order_id": 9, "remark": "调整交期"},
            "output": {
                "success": True,
                "message": "更新成功",
                "data": {"id": 9, "remark": "调整交期"},
            },
        }
    ],
    ("purchase", "approve_order"): [
        {
            "name": "approve_purchase_order",
            "input": {"order_id": 9, "approver": "manager"},
            "output": {
                "success": True,
                "message": "审批成功",
                "data": {"id": 9, "status": "approved"},
            },
        }
    ],
    ("purchase", "cancel_order"): [
        {
            "name": "cancel_purchase_order",
            "input": {"order_id": 9},
            "output": {
                "success": True,
                "message": "取消成功",
                "data": {"id": 9, "status": "cancelled"},
            },
        }
    ],
    ("purchase", "create_inbound"): [
        {
            "name": "create_purchase_inbound",
            "input": {"order_id": 9, "items": [{"product_id": 2, "quantity": 3}]},
            "output": {
                "success": True,
                "message": "入库成功",
                "data": {"id": 5, "order_id": 9},
            },
        }
    ],
    ("finance", "create_transaction"): [
        {
            "name": "create_finance_transaction",
            "input": {
                "transaction_type": "expense",
                "amount": 128.5,
                "description": "运费",
            },
            "output": {
                "success": True,
                "data": {"id": 31, "transaction_type": "expense", "amount": 128.5},
            },
        }
    ],
    ("finance", "update_transaction"): [
        {
            "name": "update_finance_transaction",
            "input": {"transaction_id": 31, "status": "paid"},
            "output": {
                "success": True,
                "data": {"id": 31, "status": "paid"},
            },
        }
    ],
    ("finance", "delete_transaction"): [
        {
            "name": "delete_finance_transaction",
            "input": {"transaction_id": 31},
            "output": {"success": True, "message": "凭证已删除"},
        }
    ],
    ("employee", "list"): [
        {
            "name": "list_available_employees",
            "input": {},
            "output": {
                "success": True,
                "data": [{"employee_id": "quote-agent", "name": "报价员工"}],
            },
        }
    ],
    ("employee", "execute"): [
        {
            "name": "execute_quote_employee",
            "input": {
                "employee_id": "quote-agent",
                "task": "Prepare a quote",
                "input": {"customer": "Acme Trading"},
            },
            "output": {
                "success": True,
                "message": "employee run accepted",
                "employee_id": "quote-agent",
                "data": {"status": "accepted"},
            },
        }
    ],
    ("excel_import", "execute_import"): [
        {
            "name": "execute_pending_import",
            "input": {"pending_import_id": "pending-import-1"},
            "output": {
                "success": True,
                "message": "import completed",
                "imported_count": 1,
                "data": {"pending_import_id": "pending-import-1"},
            },
        }
    ],
    ("excel_import", "import_records"): [
        {
            "name": "import_structured_records",
            "input": {
                "records": [{"unit_name": "Acme Trading", "model_number": "5003"}],
                "source": "agent_fixture",
            },
            "output": {
                "success": True,
                "message": "records imported",
                "imported_count": 1,
                "data": {"records": 1},
            },
        }
    ],
    ("unit_products_import", "execute_import"): [
        {
            "name": "import_unit_products_db",
            "input": {
                "saved_name": "unit-products.db",
                "unit_name": "Acme Trading",
                "skip_duplicates": True,
            },
            "output": {
                "success": True,
                "message": "unit products imported",
                "created_customers": 1,
                "created_products": 2,
                "data": {"unit_name": "Acme Trading"},
            },
        }
    ],
    ("template_extract", "extract"): [
        {
            "name": "extract_excel_template_structure",
            "input": {"file_path": "/tmp/shipment-template.xlsx", "sheet_name": "出货"},
            "output": {
                "success": True,
                "file_path": "/tmp/shipment-template.xlsx",
                "sheet_names": ["出货"],
                "fields": [{"label": "客户", "type": "dynamic"}],
                "sample_rows": [{"客户": "ACME Trading"}],
                "grid_preview": {"rows": [["客户"], ["ACME Trading"]]},
                "grid_style_cache": {"cells": {}},
                "sheets": [{"sheet_name": "出货"}],
                "artifacts": [
                    {"artifact_type": "template_analysis", "name": "shipment-template.xlsx"}
                ],
            },
        }
    ],
    ("business_event", "print_label"): [
        {
            "name": "submit_business_print_label_event",
            "input": {
                "job_id": "print-job-1",
                "document_name": "发货标签.pdf",
                "printer_id": "default",
                "copies": 1,
            },
            "output": {
                "success": True,
                "job_id": "print-job-1",
                "event": "print.job.submitted",
            },
        }
    ],
    ("business_event", "inventory_update"): [
        {
            "name": "submit_business_inventory_update_event",
            "input": {
                "product_id": "sku-1",
                "warehouse_id": "main",
                "delta": -2,
                "reason": "shipment",
                "new_quantity": 18,
            },
            "output": {
                "success": True,
                "event": "inventory.changed",
            },
        }
    ],
    ("shipment_records", "create"): [
        {
            "name": "create_shipment_record",
            "input": {
                "unit_name": "星光贸易",
                "products": [{"name": "5003", "qty": 2}],
                "contact_person": "张三",
                "contact_phone": "13900000000",
            },
            "output": {
                "success": True,
                "message": "出货记录已创建",
                "data": {"id": 7, "unit_name": "星光贸易"},
            },
        }
    ],
    ("shipment_records", "update"): [
        {
            "name": "update_shipment_record",
            "input": {
                "id": 7,
                "unit_name": "星光贸易",
                "status": "printed",
            },
            "output": {
                "success": True,
                "message": "出货记录已更新",
                "data": {"id": 7, "status": "printed"},
            },
        }
    ],
    ("shipment_records", "delete"): [
        {
            "name": "delete_shipment_record",
            "input": {"id": 7},
            "output": {"success": True, "message": "出货记录已删除", "deleted_count": 1},
        }
    ],
    ("shipment_orders", "generate"): [
        {
            "name": "generate_shipment_order",
            "input": {
                "unit_name": "星光贸易",
                "products": [{"name": "5003", "qty": 2}],
                "date": "2026-06-19",
            },
            "output": {
                "success": True,
                "file_path": "/tmp/shipment.xlsx",
                "doc_name": "shipment.xlsx",
                "record_id": 7,
                "order_id": 7,
            },
        }
    ],
    ("shipment_orders", "generate_batch"): [
        {
            "name": "generate_shipment_order_batch",
            "input": {
                "shipments": [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}]
            },
            "output": {
                "success": True,
                "data": {"processed": 1, "total": 1, "errors": []},
            },
        }
    ],
    ("shipment_orders", "print"): [
        {
            "name": "mark_shipment_order_printed",
            "input": {
                "file_path": "/tmp/shipment.xlsx",
                "order_id": 7,
                "printer_name": "HP",
            },
            "output": {
                "success": True,
                "message": "已标记为已打印",
                "file_path": "/tmp/shipment.xlsx",
                "updated": True,
                "printed_at": "2026-06-19T10:00:00",
            },
        }
    ],
    ("shipment_orders", "clear_shipment"): [
        {
            "name": "clear_shipment_orders_for_unit",
            "input": {"purchase_unit": "星光贸易"},
            "output": {
                "success": True,
                "message": "已清空星光贸易的发货记录",
                "purchase_unit": "星光贸易",
                "cleared_count": 3,
            },
        }
    ],
    ("shipment_orders", "set_sequence"): [
        {
            "name": "set_shipment_order_sequence",
            "input": {"sequence": 12},
            "output": {
                "success": True,
                "message": "序号已设置为 12",
                "sequence": 12,
            },
        }
    ],
    ("shipment_orders", "reset_sequence"): [
        {
            "name": "reset_shipment_order_sequence",
            "input": {},
            "output": {
                "success": True,
                "message": "序号已重置",
                "sequence": 1,
            },
        }
    ],
    ("shipment_orders", "clear_all"): [
        {
            "name": "clear_all_shipment_orders",
            "input": {},
            "output": {
                "success": True,
                "message": "已清空所有发货单",
                "deleted_count": 5,
            },
        }
    ],
    ("shipment_orders", "delete"): [
        {
            "name": "delete_shipment_order",
            "input": {"id": 7, "order_number": "7"},
            "output": {
                "success": True,
                "message": "订单 7 已删除",
                "deleted_id": 7,
            },
        }
    ],
    ("print", "print_document"): [
        {
            "name": "print_document_route",
            "input": {
                "file_path": "/tmp/document.pdf",
                "printer_name": "DocPrinter",
                "use_automation": False,
            },
            "output": {
                "success": True,
                "message": "文档已提交打印",
                "file_path": "/tmp/document.pdf",
                "printer_name": "DocPrinter",
                "status": "printed",
            },
        }
    ],
    ("print", "print_label"): [
        {
            "name": "print_label_route",
            "input": {
                "file_path": "/tmp/label.png",
                "printer_name": "LabelPrinter",
                "copies": 2,
            },
            "output": {
                "success": True,
                "message": "标签已打印",
                "file_path": "/tmp/label.png",
                "printer_name": "LabelPrinter",
                "copies": 2,
                "status": "printed",
                "require_confirm": False,
            },
        }
    ],
    ("print", "test"): [
        {
            "name": "test_printer_route",
            "input": {"printer_name": "DocPrinter"},
            "output": {
                "success": True,
                "message": "测试页已发送",
                "printer_name": "DocPrinter",
                "status": "printed",
            },
        }
    ],
    ("print", "save_printer_selection"): [
        {
            "name": "save_printer_selection_route",
            "input": {"document_printer": "DocPrinter", "label_printer": "LabelPrinter"},
            "output": {
                "success": True,
                "message": "打印机选择已保存",
                "document_printer": "DocPrinter",
                "label_printer": "LabelPrinter",
                "document": ["DocPrinter"],
                "label": ["LabelPrinter"],
            },
        }
    ],
    ("print", "workflow_label_dispatch"): [
        {
            "name": "workflow_label_dispatch_route",
            "input": {"model_number": "M-1", "quantity": 2, "idempotency_key": "idem-1"},
            "output": {
                "success": True,
                "message": "标签已打印",
                "model_number": "M-1",
                "product_name": "M-1",
                "quantity": 2,
                "status": "printed",
            },
        }
    ],
    ("business_event", "shipment_create"): [
        {
            "name": "submit_business_shipment_create_event",
            "input": {
                "unit_name": "ACME Trading",
                "items": [{"sku": "sku-1", "qty": 2}],
                "contact_person": "Lee",
                "contact_phone": "13800000000",
            },
            "output": {
                "success": True,
                "event": "shipment.created",
                "published": True,
            },
        }
    ],
    ("system_maintenance", "set_default_printer"): [
        {
            "name": "set_default_printer",
            "input": {"printer_name": "HP"},
            "output": {"success": True, "message": "默认打印机已更新", "http_status_code": 200},
        }
    ],
    ("system_maintenance", "enable_startup"): [
        {
            "name": "enable_startup",
            "input": {},
            "output": {"success": True, "message": "已启用开机启动", "http_status_code": 200},
        }
    ],
    ("system_maintenance", "disable_startup"): [
        {
            "name": "disable_startup",
            "input": {},
            "output": {"success": True, "message": "已关闭开机启动", "http_status_code": 200},
        }
    ],
    ("system_maintenance", "backup_database"): [
        {
            "name": "backup_database",
            "input": {},
            "output": {
                "success": True,
                "message": "数据库备份完成",
                "backup_file": "backup.sql",
                "http_status_code": 200,
            },
        }
    ],
    ("system_maintenance", "delete_database_backup"): [
        {
            "name": "delete_database_backup",
            "input": {"backup_file": "backup.sql"},
            "output": {
                "success": True,
                "message": "备份已删除",
                "backup_file": "backup.sql",
                "http_status_code": 200,
            },
        }
    ],
    ("system_maintenance", "restore_database"): [
        {
            "name": "restore_database",
            "input": {"backup_file": "backup.sql"},
            "output": {
                "success": True,
                "message": "数据库恢复完成",
                "backup_file": "backup.sql",
                "http_status_code": 200,
            },
        }
    ],
    ("system_maintenance", "clear_performance_cache"): [
        {
            "name": "clear_performance_cache",
            "input": {"pattern": "test:*"},
            "output": {
                "success": True,
                "message": "已清除模式 'test:*' 的缓存 (5 个键)",
                "http_status_code": 200,
            },
        }
    ],
    ("system_maintenance", "invalidate_performance_cache"): [
        {
            "name": "invalidate_performance_cache",
            "input": {"keys": ["k1"]},
            "output": {
                "success": True,
                "message": "已删除 1 个缓存键",
                "data": {"deleted_count": 1, "requested_keys": 1},
                "http_status_code": 200,
            },
        }
    ],
    ("system_maintenance", "reinitialize_performance"): [
        {
            "name": "reinitialize_performance",
            "input": {},
            "output": {
                "success": True,
                "message": "性能优化系统已重新初始化",
                "data": {"status": "ok"},
                "http_status_code": 200,
            },
        }
    ],
    ("excel_analyzer", "analyze"): [
        {
            "name": "analyze_excel_template_zones",
            "input": {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            "output": {
                "success": True,
                "file_path": "/tmp/template.xlsx",
                "file": "template.xlsx",
                "sheet": "Sheet1",
                "structure": {"max_row": 8, "max_col": 4},
                "zones": [{"name": "header", "type": "template"}],
                "merged_cells": [],
                "editable_ranges": [],
                "cells": {},
            },
        }
    ],
    ("excel_toolkit", "view"): [
        {
            "name": "view_excel_content",
            "input": {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1", "max_rows": 20},
            "output": {
                "success": True,
                "file_path": "/tmp/template.xlsx",
                "file": "template.xlsx",
                "sheet": "Sheet1",
                "structure": {"max_row": 2, "max_col": 2, "dimensions": "A1:B2"},
                "content": [{"row": 1, "cells": [{"coordinate": "A1", "value": "客户"}]}],
                "row_count": 1,
            },
        }
    ],
    ("excel_toolkit", "merged"): [
        {
            "name": "inspect_excel_merged_cells",
            "input": {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            "output": {
                "success": True,
                "file_path": "/tmp/template.xlsx",
                "file": "template.xlsx",
                "sheet": "Sheet1",
                "merged_cells": [],
                "count": 0,
            },
        }
    ],
    ("excel_toolkit", "styles"): [
        {
            "name": "inspect_excel_cell_styles",
            "input": {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1", "max_rows": 10},
            "output": {
                "success": True,
                "file_path": "/tmp/template.xlsx",
                "file": "template.xlsx",
                "sheet": "Sheet1",
                "styles": [{"coordinate": "A1", "value": "客户"}],
            },
        }
    ],
    ("excel_toolkit", "structure"): [
        {
            "name": "inspect_excel_structure",
            "input": {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            "output": {
                "success": True,
                "file_path": "/tmp/template.xlsx",
                "file": "template.xlsx",
                "sheet_names": ["Sheet1"],
                "current_sheet": "Sheet1",
                "structure": {"total_rows": 2, "total_columns": 2},
                "columns": [{"index": 1, "letter": "A", "header": "客户"}],
            },
        }
    ],
    ("label_template_generator", "execute"): [
        {
            "name": "generate_label_template_from_image",
            "input": {
                "image_path": "/tmp/label.png",
                "class_name": "ProductLabelTemplate",
                "enable_ocr": True,
            },
            "output": {
                "success": True,
                "image_path": "/tmp/label.png",
                "analysis": {"file": "label.png", "size": [800, 600]},
                "ocr_result": {"success": True, "fields": [{"label": "品名", "value": "清漆"}]},
                "code": "class ProductLabelTemplate:\\n    pass\\n",
            },
        }
    ],
    ("document_template", "create"): [
        {
            "name": "create_document_template",
            "input": {
                "name": "发货模板",
                "template_type": "Excel",
                "fields": [{"label": "客户"}],
                "preview_data": {"sheet_name": "Sheet1"},
            },
            "output": {
                "success": True,
                "message": "模板创建成功",
                "template": {"id": "db:1", "db_id": 1, "name": "发货模板"},
                "http_status_code": 200,
            },
        }
    ],
    ("document_template", "update"): [
        {
            "name": "update_document_template",
            "input": {
                "id": "db:1",
                "name": "发货模板 v2",
                "fields": [{"label": "客户"}],
            },
            "output": {
                "success": True,
                "message": "模板更新成功",
                "template": {"id": "db:1", "db_id": 1, "name": "发货模板 v2"},
                "http_status_code": 200,
            },
        }
    ],
    ("document_template", "delete"): [
        {
            "name": "delete_document_template",
            "input": {
                "id": "db:1",
            },
            "output": {
                "success": True,
                "message": "模板删除成功",
                "deleted": {"id": "db:1", "db_id": 1},
                "http_status_code": 200,
            },
        }
    ],
    ("generate_office_document", "execute"): [
        {
            "name": "generate_contract_docx",
            "input": {"user_request": "Generate a contract", "output_format": "docx"},
            "output": {
                "success": True,
                "message": "document generated",
                "file_name": "contract.docx",
                "download_url": "/api/ai/kitten/document/pickup/token",
                "pickup_token": "token",
                "artifacts": [
                    {
                        "artifact_type": "office_document",
                        "name": "contract.docx",
                        "source": "generate_office_document",
                    }
                ],
            },
        }
    ],
    ("excel_vector_index", "execute"): [
        {
            "name": "build_excel_vector_index",
            "input": {
                "file_path": "/tmp/products.xlsx",
                "index_name": "products",
            },
            "output": {
                "success": True,
                "message": "index built",
                "index_id": "excel-index-1",
                "excel_vector_index_id": "excel-index-1",
                "excel_index_id": "excel-index-1",
                "chunk_count": 3,
                "row_count": 10,
            },
        }
    ],
    ("excel_vector_index", "query"): [
        {
            "name": "query_excel_vector_index",
            "input": {
                "index_id": "excel-index-1",
                "query": "5003 清漆",
                "top_k": 3,
            },
            "output": {
                "success": True,
                "index_id": "excel-index-1",
                "query": "5003 清漆",
                "hits": [
                    {
                        "score": 0.92,
                        "row": {"model_number": "5003", "product_name": "清漆"},
                    }
                ],
            },
        }
    ],
    ("ocr", "recognize"): [
        {
            "name": "recognize_ocr_image",
            "input": {"file_path": "/tmp/label.png"},
            "output": {
                "success": True,
                "message": "识别成功",
                "text": "购货单位：ACME Trading",
                "file_path": "/tmp/label.png",
                "artifacts": [{"artifact_type": "ocr_text", "name": "ocr_result"}],
            },
        }
    ],
    ("ocr", "request"): [
        {
            "name": "publish_business_ocr_request",
            "input": {
                "request_id": "ocr-request-1",
                "image_url": "https://example.invalid/label.png",
                "ocr_type": "general",
                "user_id": "tenant-a",
            },
            "output": {
                "success": True,
                "message": "OCR 请求已发布",
                "request_id": "ocr-request-1",
                "image_url": "https://example.invalid/label.png",
                "ocr_type": "general",
                "user_id": "tenant-a",
                "event": "ocr.requested",
                "published": True,
            },
        }
    ],
    ("ocr", "extract"): [
        {
            "name": "extract_ocr_fields",
            "input": {"text": "购货单位：ACME Trading\n联系人：Alice"},
            "output": {
                "success": True,
                "message": "提取成功",
                "data": {"purchase_unit": "ACME Trading", "contact_person": "Alice"},
            },
        }
    ],
    ("ocr", "analyze"): [
        {
            "name": "analyze_ocr_text",
            "input": {"text": "订单编号：SO-1\n购货单位：ACME Trading"},
            "output": {
                "success": True,
                "message": "分析成功",
                "data": {"text_type": "order", "confidence": 0.67},
            },
        }
    ],
    ("ocr", "recognize_and_extract"): [
        {
            "name": "recognize_and_extract_ocr_image",
            "input": {"file_path": "/tmp/order.png"},
            "output": {
                "success": True,
                "message": "识别和提取成功",
                "text": "购货单位：ACME Trading",
                "data": {"purchase_unit": "ACME Trading"},
                "analysis": {"text_type": "customer", "confidence": 0.67},
                "artifacts": [{"artifact_type": "ocr_text", "name": "ocr_result"}],
            },
        }
    ],
    ("dataset_rag", "query"): [
        {
            "name": "query_dataset_rag_with_citations",
            "input": {
                "dataset_id": "platform-docs",
                "query": "Which model should AI routes use?",
                "top_k": 2,
                "include_answer": True,
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "query": "Which model should AI routes use?",
                "answer": "AI routes should use XCauto [1].",
                "chunks": [
                    {
                        "chunk_id": "chunk_1",
                        "text": "AI routes should use XCauto.",
                        "source": "policy.pdf",
                    }
                ],
                "citations": [
                    {
                        "index": 1,
                        "source": "policy.pdf",
                        "chunk_index": 0,
                    }
                ],
            },
        }
    ],
    ("dataset_rag", "ingest_document"): [
        {
            "name": "ingest_dataset_document",
            "input": {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "text": "AI routes should use XCauto.",
                "tenant_id": "tenant-a",
                "metadata": {"doc_type": "policy"},
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "document": {"document_id": "doc_1", "source": "policy.pdf"},
                "chunk_count": 1,
            },
        }
    ],
    ("dataset_rag", "diff_versions"): [
        {
            "name": "diff_dataset_document_versions",
            "input": {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "from_version": "v1",
                "to_version": "latest",
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "from_version": 1,
                "to_version": 2,
                "changed": True,
                "added_lines": ["Use AgentOrchestrator."],
                "removed_lines": [],
                "diff": ["--- policy.pdf@v1", "+++ policy.pdf@v2"],
            },
        }
    ],
    ("dataset_rag", "rollback_version"): [
        {
            "name": "rollback_dataset_document_version",
            "input": {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "target_version": "v1",
                "metadata": {"reason": "bad update"},
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "document": {"document_id": "doc_rollback", "source": "policy.pdf"},
                "chunk_count": 1,
                "rolled_back_from": {"document_id": "doc_v1", "version": 1},
            },
        }
    ],
    ("dataset_rag", "rebuild_index"): [
        {
            "name": "rebuild_dataset_index",
            "input": {
                "dataset_id": "platform-docs",
                "tenant_id": "tenant-a",
                "background": True,
                "max_attempts": 1,
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "job": {"job_id": "rag_rebuild_1", "status": "queued"},
                "background": True,
            },
        }
    ],
    ("dataset_rag", "cancel_rebuild"): [
        {
            "name": "cancel_dataset_rebuild",
            "input": {
                "dataset_id": "platform-docs",
                "job_id": "rag_rebuild_1",
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "job_id": "rag_rebuild_1",
                "job": {"job_id": "rag_rebuild_1", "status": "cancelled"},
            },
        }
    ],
    ("dataset_rag", "delete_document"): [
        {
            "name": "delete_dataset_document",
            "input": {
                "dataset_id": "platform-docs",
                "document_id": "doc_1",
            },
            "output": {
                "success": True,
                "dataset_id": "platform-docs",
                "document_id": "doc_1",
                "deleted_chunks": 1,
            },
        }
    ],
    ("memory_v2", "propose_candidate"): [
        {
            "name": "propose_memory_v2_candidate",
            "input": {
                "user_id": "tenant-a",
                "memory_type": "preference",
                "key": "favorite_customer",
                "value": "ACME Trading",
                "source": "settings_ui",
                "confidence": 0.9,
            },
            "output": {
                "success": True,
                "created": True,
                "candidate": {
                    "memory_id": "mem_1",
                    "memory_type": "preference",
                    "key": "favorite_customer",
                    "status": "pending",
                },
            },
        }
    ],
    ("memory_v2", "confirm"): [
        {
            "name": "confirm_memory_v2_candidate",
            "input": {
                "user_id": "tenant-a",
                "memory_id": "mem_1",
            },
            "output": {
                "success": True,
                "memory": {
                    "memory_id": "mem_1",
                    "status": "active",
                    "eligible_for_planner": True,
                },
            },
        }
    ],
    ("memory_v2", "reject"): [
        {
            "name": "reject_memory_v2_candidate",
            "input": {
                "user_id": "tenant-a",
                "memory_id": "mem_1",
                "reason": "not useful",
            },
            "output": {
                "success": True,
                "memory": {
                    "memory_id": "mem_1",
                    "status": "rejected",
                },
            },
        }
    ],
    ("memory_v2", "correct"): [
        {
            "name": "correct_memory_v2_record",
            "input": {
                "user_id": "tenant-a",
                "memory_id": "mem_1",
                "key": "favorite_customer",
                "value": "ACME Trading Ltd.",
                "reason": "user corrected value",
            },
            "output": {
                "success": True,
                "memory": {
                    "memory_id": "mem_1",
                    "key": "favorite_customer",
                    "value": "ACME Trading Ltd.",
                },
            },
        }
    ],
    ("memory_v2", "delete"): [
        {
            "name": "delete_memory_v2_record",
            "input": {
                "user_id": "tenant-a",
                "memory_id": "mem_1",
                "reason": "user removed memory",
            },
            "output": {
                "success": True,
                "memory": {
                    "memory_id": "mem_1",
                    "status": "deleted",
                },
            },
        }
    ],
}


@dataclass(frozen=True)
class ToolActionSpecV2:
    tool_id: str
    action: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_OUTPUT_SCHEMA))
    risk: RiskLevel = "medium"
    permission: str = ""
    cost_units: int = 0
    timeout_seconds: int = 60
    retry: dict[str, Any] = field(default_factory=lambda: {"max_attempts": 0})
    idempotent: bool = False
    required_params: list[str] = field(default_factory=list)
    availability: str = "shared"
    test_fixtures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "action": self.action,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk": self.risk,
            "permission": self.permission,
            "cost_units": self.cost_units,
            "timeout_seconds": self.timeout_seconds,
            "retry": self.retry,
            "idempotent": self.idempotent,
            "required_params": self.required_params,
            "availability": self.availability,
            "test_fixtures": self.test_fixtures,
        }


@dataclass(frozen=True)
class ToolValidationResult:
    ok: bool
    tool_id: str
    action: str
    spec: ToolActionSpecV2 | None = None
    error_code: str = ""
    message: str = ""


def _normalize_tool_action(action: str, params: dict[str, Any] | None = None) -> str:
    from app.services.tools_execution.registry import _normalize_action

    return _normalize_action(action, params)


def _risk_value(value: Any) -> RiskLevel:
    text = str(value or "medium").strip().lower()
    if text in {"low", "medium", "high"}:
        return text  # type: ignore[return-value]
    return "medium"


def _schema_from_required(required_params: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required_params),
        "properties": {key: {} for key in required_params},
    }


def _sample_value_for_property(key: str, prop: dict[str, Any]) -> Any:
    enum_values = prop.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    expected_type = str(prop.get("type") or "").strip()
    if key == "success":
        return True
    if key in {"ids", "records", "artifacts", "data"} and expected_type == "array":
        return [{"sample": True}]
    if key == "payload":
        return {"sample": True}
    if key in {"created_customers", "created_products", "imported_count"}:
        return 1
    if key == "download_url":
        return "/api/sample/download"
    if key == "file_name":
        return "sample.docx"
    if expected_type == "object":
        return {"sample": True}
    if expected_type == "array":
        return [{"sample": True}]
    if expected_type == "integer":
        return 1
    if expected_type == "number":
        return 1.0
    if expected_type == "boolean":
        return True
    return f"sample_{key}"


def _sample_payload_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    payload: dict[str, Any] = {}
    for key, prop in properties.items():
        payload[str(key)] = _sample_value_for_property(
            str(key), prop if isinstance(prop, dict) else {}
        )
    for key in required:
        normalized_key = str(key)
        if normalized_key not in payload:
            payload[normalized_key] = f"sample_{normalized_key}"
    return payload


def _default_fixture(
    tool_id: str,
    action: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "name": f"{tool_id}.{action}.contract",
            "input": _sample_payload_from_schema(input_schema),
            "output": _sample_payload_from_schema(output_schema),
        }
    ]


def _special_permission(tool_id: str, action: str) -> str:
    if tool_id == "aiopen":
        return f"aiopen.{action}"
    if tool_id == "business_db":
        return f"business_db.{action}"
    if tool_id == "employee":
        return f"employee.{action}"
    if tool_id == "dataset_rag":
        if action in {"query", "diff_versions"}:
            return "dataset.read"
        return "dataset.write"
    if tool_id == "memory_v2":
        return "memory_v2.write"
    return f"tool.{tool_id}.{action}"


def _cost_units(tool_id: str, action: str, risk: RiskLevel) -> int:
    if tool_id == "aiopen" and action == "chat":
        return 2
    if tool_id == "employee" and action == "execute":
        return 5
    if tool_id == "business_db" and action == "write":
        return 2
    if risk == "low":
        return 1
    return 2


def _aiopen_tool_risk(action: str) -> tuple[RiskLevel, bool]:
    if action in {"api_catalog", "ui_sessions", "ui_snapshot"}:
        return "low", True
    if action in {"api_call", "chat", "ui_navigate", "ui_click", "ui_type", "ui_scroll"}:
        return "medium", False
    return "medium", False


def _add_aiopen_tool_specs(specs: dict[tuple[str, str], ToolActionSpecV2]) -> None:
    try:
        from app.application.aiopen.service import TOOL_DEFINITIONS
    except RECOVERABLE_ERRORS:
        return

    output_schema = {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "code": {"type": "string"},
            "data": {},
            "routes": {"type": "array"},
            "sessions": {"type": "array"},
            "status_code": {"type": "integer"},
        },
    }
    for tool in TOOL_DEFINITIONS:
        if not isinstance(tool, dict):
            continue
        action = _normalize_tool_action(str(tool.get("name") or ""))
        if not action:
            continue
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        required = (
            input_schema.get("required") if isinstance(input_schema.get("required"), list) else []
        )
        required_params = [str(item) for item in required]
        risk, idempotent = _aiopen_tool_risk(action)
        fixture = _default_fixture("aiopen", action, input_schema, output_schema)
        if action == "api_catalog":
            fixture = [
                {
                    "name": "list_aiopen_catalog",
                    "input": {},
                    "output": {
                        "success": True,
                        "routes": [{"path": "/api/ai/chat", "enabled": True}],
                    },
                }
            ]
        elif action == "chat":
            fixture = [
                {
                    "name": "invoke_aiopen_chat",
                    "input": {"message": "你好"},
                    "output": {"success": True, "data": {"reply": "你好"}},
                }
            ]
        specs[("aiopen", action)] = ToolActionSpecV2(
            tool_id="aiopen",
            action=action,
            description=str(tool.get("description") or f"AIOPEN {action}"),
            input_schema=deepcopy(input_schema),
            output_schema=deepcopy(output_schema),
            risk=risk,
            permission=_special_permission("aiopen", action),
            cost_units=_cost_units("aiopen", action, risk),
            timeout_seconds=30,
            retry={"max_attempts": 0},
            idempotent=idempotent,
            required_params=required_params,
            availability="aiopen",
            test_fixtures=deepcopy(fixture),
        )


def build_tool_specs_v2() -> dict[tuple[str, str], ToolActionSpecV2]:
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    specs: dict[tuple[str, str], ToolActionSpecV2] = {}
    for tool_id, tool_meta in registry.items():
        actions = tool_meta.get("actions") if isinstance(tool_meta, dict) else None
        if not isinstance(actions, dict):
            continue
        tool_description = str(tool_meta.get("description") or "")
        for action, action_meta in actions.items():
            if not isinstance(action_meta, dict):
                continue
            normalized_action = _normalize_tool_action(str(action or "view"))
            required = action_meta.get("required_params")
            required_params = [str(x) for x in required] if isinstance(required, list) else []
            risk = _risk_value(action_meta.get("risk"))
            input_schema = _SPECIAL_INPUT_SCHEMAS.get(
                (str(tool_id), normalized_action),
                _schema_from_required(required_params),
            )
            output_schema = _SPECIAL_OUTPUT_SCHEMAS.get(
                (str(tool_id), normalized_action),
                _DEFAULT_OUTPUT_SCHEMA,
            )
            test_fixtures = _SPECIAL_TEST_FIXTURES.get(
                (str(tool_id), normalized_action),
                _default_fixture(str(tool_id), normalized_action, input_schema, output_schema),
            )
            spec = ToolActionSpecV2(
                tool_id=str(tool_id),
                action=normalized_action,
                description=tool_description,
                input_schema=deepcopy(input_schema),
                output_schema=deepcopy(output_schema),
                risk=risk,
                permission=_special_permission(str(tool_id), normalized_action),
                cost_units=_cost_units(str(tool_id), normalized_action, risk),
                timeout_seconds=int(action_meta.get("timeout_seconds") or 60),
                retry=dict(action_meta.get("retry") or {"max_attempts": 0}),
                idempotent=bool(action_meta.get("idempotent", False)),
                required_params=required_params,
                availability=str(
                    action_meta.get("availability") or tool_meta.get("availability") or "shared"
                ),
                test_fixtures=deepcopy(test_fixtures),
            )
            specs[(spec.tool_id, spec.action)] = spec
    _add_aiopen_tool_specs(specs)
    return specs


def get_tool_action_spec(tool_id: str, action: str) -> ToolActionSpecV2 | None:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"))
    return build_tool_specs_v2().get((normalized_tool_id, normalized_action))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema_payload(
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    subject: str,
) -> tuple[bool, str]:
    expected_root_type = str(schema.get("type") or "object").strip()
    if expected_root_type == "object" and not isinstance(payload, dict):
        return False, f"{subject} 必须是 object"
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if subject == "工具输出" and payload.get("success") is False:
        required = [key for key in required if str(key) == "success"]
    for key in required:
        if _is_empty(payload.get(str(key))):
            return False, f"{subject} 缺少字段：{key}"

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for key, prop in properties.items():
        if key not in payload or _is_empty(payload.get(key)):
            continue
        if not isinstance(prop, dict):
            continue
        expected_type = str(prop.get("type") or "").strip()
        if expected_type and not _type_matches(payload.get(key), expected_type):
            return False, f"{subject} 字段 {key} 类型错误，应为 {expected_type}"
        enum_values = prop.get("enum")
        if isinstance(enum_values, list) and enum_values and payload.get(key) not in enum_values:
            return False, f"{subject} 字段 {key} 不在允许范围内"
    return True, ""


def _validate_input_schema(spec: ToolActionSpecV2, params: dict[str, Any]) -> tuple[bool, str]:
    return _validate_schema_payload(spec.input_schema or {}, params, subject="参数")


def validate_tool_result(
    tool_id: str,
    action: str,
    result: dict[str, Any] | None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"))
    spec = get_tool_action_spec(normalized_tool_id, normalized_action)
    if spec is None:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            error_code="unknown_tool_action",
            message=f"未注册的工具动作: {normalized_tool_id}.{normalized_action}",
        )

    payload = dict(result or {})
    ok, message = _validate_schema_payload(spec.output_schema or {}, payload, subject="工具输出")
    if not ok:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="output_schema_validation_failed",
            message=message,
        )
    return ToolValidationResult(
        ok=True,
        tool_id=normalized_tool_id,
        action=normalized_action,
        spec=spec,
    )


def validate_tool_spec_fixtures() -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for (tool_id, action), spec in build_tool_specs_v2().items():
        key = f"{tool_id}.{action}"
        if not spec.test_fixtures:
            errors.setdefault(key, []).append("missing test_fixtures")
            continue
        for index, fixture in enumerate(spec.test_fixtures):
            name = str(fixture.get("name") or f"fixture_{index}")
            input_payload = fixture.get("input")
            if not isinstance(input_payload, dict):
                errors.setdefault(key, []).append(f"{name}: input must be object")
                continue
            input_result = validate_tool_call(tool_id, action, input_payload)
            if not input_result.ok:
                errors.setdefault(key, []).append(
                    f"{name}: input {input_result.error_code}: {input_result.message}"
                )
            output_payload = fixture.get("output")
            if not isinstance(output_payload, dict):
                errors.setdefault(key, []).append(f"{name}: output must be object")
                continue
            output_result = validate_tool_result(tool_id, action, output_payload)
            if not output_result.ok:
                errors.setdefault(key, []).append(
                    f"{name}: output {output_result.error_code}: {output_result.message}"
                )
    return errors


def validate_tool_call(
    tool_id: str,
    action: str,
    params: dict[str, Any] | None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"), dict(params or {}))
    spec = get_tool_action_spec(normalized_tool_id, normalized_action)
    if spec is None:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            error_code="unknown_tool_action",
            message=f"未注册的工具动作: {normalized_tool_id}.{normalized_action}",
        )

    payload = dict(params or {})
    if spec.tool_id == "business_db" and any(k in payload for k in ("sql", "raw_sql", "query_sql")):
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="unsafe_raw_sql",
            message="business_db 不接受任意 SQL，请使用 entity/operation/payload。",
        )

    ok, message = _validate_input_schema(spec, payload)
    if not ok:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="schema_validation_failed",
            message=message,
        )
    return ToolValidationResult(
        ok=True,
        tool_id=normalized_tool_id,
        action=normalized_action,
        spec=spec,
    )
