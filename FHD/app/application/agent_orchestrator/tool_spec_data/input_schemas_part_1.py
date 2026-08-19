from __future__ import annotations

from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

SPECIAL_INPUT_SCHEMAS_PART_1: dict[tuple[str, str], dict[str, Any]] = {
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
}
