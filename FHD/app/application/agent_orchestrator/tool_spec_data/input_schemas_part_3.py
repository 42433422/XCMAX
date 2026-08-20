from __future__ import annotations

from typing import Any

_BUSINESS_ENTITIES = ["customers", "products", "materials", "shipment_records"]

SPECIAL_INPUT_SCHEMAS_PART_3: dict[tuple[str, str], dict[str, Any]] = {
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
