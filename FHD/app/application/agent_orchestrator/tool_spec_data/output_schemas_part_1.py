from __future__ import annotations

from typing import Any

SPECIAL_OUTPUT_SCHEMAS_PART_1: dict[tuple[str, str], dict[str, Any]] = {
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
}
