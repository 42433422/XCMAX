from __future__ import annotations

from typing import Any

_DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["success"],
    "properties": {
        "success": {"type": "boolean"},
        "message": {"type": "string"},
        "data": {},
    },
}


def _result(*, required=("success",), **properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required),
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            **properties,
        },
    }


_SPECIAL_OUTPUT_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("sales", "query"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "order_no": {"type": "string"},
                        "customer_name": {"type": "string"},
                        "created_at": {"type": "string"},
                        "state": {"type": "string"},
                        "total_amount": {"type": "number"},
                    },
                },
                "description": "销售订单明细数组；完整数组引用 node.data，不存在 data.orders",
            },
            "total": {"type": "integer"},
            "summary": {
                "type": "object",
                "properties": {"count": {"type": "integer"}, "amount": {"type": "number"}},
            },
        },
    },
    ("business_db", "read"): _result(
        required=["success", "data"], data={"type": "array"}, error={"type": "string"}
    ),
    ("business_db", "write"): _result(data={"type": "object"}, error={"type": "string"}),
    ("customers", "create"): _result(
        created={"type": "boolean"},
        data={"type": "object"},
        raw={"type": "object"},
        error={"type": "string"},
    ),
    ("customers", "update"): _result(data={"type": "object"}, error={"type": "string"}),
    ("customers", "delete"): _result(
        deleted_count={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("customers", "batch_delete"): _result(
        deleted={"type": "integer"},
        deleted_count={"type": "integer"},
        skipped={"type": "array"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("products", "create"): _result(
        created={"type": "boolean"},
        raw={"type": "object"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("products", "update"): _result(data={"type": "object"}, error={"type": "string"}),
    ("products", "delete"): _result(data={"type": "object"}, error={"type": "string"}),
    ("products", "batch_create"): _result(data={"type": "object"}, error={"type": "string"}),
    ("products", "batch_delete"): _result(
        deleted={"type": "integer"},
        deleted_count={"type": "integer"},
        skipped={"type": "array"},
        data={"type": "object"},
        status_code={"type": "integer"},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("materials", "create"): _result(
        data={"type": "object"}, created={"type": "boolean"}, error={"type": "string"}
    ),
    ("materials", "update"): _result(data={"type": "object"}, error={"type": "string"}),
    ("materials", "delete"): _result(
        data={"type": "object"}, deleted_count={"type": "integer"}, error={"type": "string"}
    ),
    ("materials", "batch_delete"): _result(
        deleted_count={"type": "integer"},
        data={"type": "object"},
        warning={"type": "string"},
        error={"type": "string"},
    ),
    ("inventory", "create_storage_location"): _result(
        id={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("inventory", "update_storage_location"): _result(
        data={"type": "object"}, error={"type": "string"}
    ),
    ("inventory", "create_warehouse"): _result(
        id={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("inventory", "update_warehouse"): _result(data={"type": "object"}, error={"type": "string"}),
    ("inventory", "delete_warehouse"): _result(data={"type": "object"}, error={"type": "string"}),
    ("inventory", "stock_in"): _result(data={"type": "object"}, error={"type": "string"}),
    ("inventory", "stock_out"): _result(data={"type": "object"}, error={"type": "string"}),
    ("inventory", "transfer"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "create_supplier"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "update_supplier"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "delete_supplier"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "create_order"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "update_order"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "approve_order"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "cancel_order"): _result(data={"type": "object"}, error={"type": "string"}),
    ("purchase", "create_inbound"): _result(data={"type": "object"}, error={"type": "string"}),
    ("finance", "create_transaction"): _result(data={"type": "object"}, error={"type": "string"}),
    ("finance", "update_transaction"): _result(data={"type": "object"}, error={"type": "string"}),
    ("finance", "delete_transaction"): _result(data={"type": "object"}, error={"type": "string"}),
    ("employee", "list"): _result(required=["success", "data"], data={"type": "array"}),
    ("employee", "execute"): _result(
        required=["success", "message", "data"],
        data={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "员工实际生成且经工作区校验的唯一输出文件路径；无文件或多文件时不提供",
                }
            },
        },
        employee_id={"type": "string"},
    ),
    ("employee", "context"): _result(
        required=["success", "message", "data"],
        data={"type": "object"},
        employee_id={"type": "string"},
    ),
    ("excel_import", "execute_import"): _result(
        imported_count={"type": "integer"}, data={"type": "object"}
    ),
    ("excel_import", "import_records"): _result(
        imported_count={"type": "integer"}, data={"type": "object"}
    ),
    ("unit_products_import", "execute_import"): _result(
        created_customers={"type": "integer"},
        created_products={"type": "integer"},
        data={"type": "object"},
    ),
    ("generate_office_document", "execute"): _result(
        required=["success", "file_name", "download_url", "artifacts"],
        file_name={"type": "string"},
        download_url={"type": "string"},
        pickup_token={"type": "string"},
        artifacts={"type": "array"},
    ),
    ("excel_vector_index", "execute"): _result(
        required=["success", "index_id"],
        index_id={"type": "string"},
        excel_vector_index_id={"type": "string"},
        excel_index_id={"type": "string"},
        chunk_count={"type": "integer"},
        row_count={"type": "integer"},
        error={"type": "string"},
    ),
    ("excel_vector_index", "query"): _result(
        index_id={"type": "string"},
        query={"type": "string"},
        hits={"type": "array"},
        error={"type": "string"},
    ),
    ("ocr", "recognize"): _result(
        text={"type": "string"},
        file_path={"type": "string"},
        confidence={"type": "number"},
        artifacts={"type": "array"},
        error_code={"type": "string"},
    ),
    ("ocr", "request"): _result(
        required=["success", "request_id", "event", "published"],
        request_id={"type": "string"},
        image_url={"type": "string"},
        ocr_type={"type": "string"},
        user_id={"type": "string"},
        event={"type": "string"},
        published={"type": "boolean"},
        error_code={"type": "string"},
    ),
    ("ocr", "extract"): _result(data={"type": "object"}, error_code={"type": "string"}),
    ("ocr", "analyze"): _result(data={"type": "object"}, error_code={"type": "string"}),
    ("ocr", "recognize_and_extract"): _result(
        text={"type": "string"},
        data={"type": "object"},
        analysis={"type": "object"},
        artifacts={"type": "array"},
        error_code={"type": "string"},
    ),
    ("shipment_records", "create"): _result(
        data={"type": "object"},
        record_id={"type": "integer"},
        order_id={"type": "integer"},
        error={"type": "string"},
    ),
    ("shipment_records", "update"): _result(data={"type": "object"}, error={"type": "string"}),
    ("shipment_records", "delete"): _result(
        deleted_count={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("shipment_orders", "generate"): _result(
        file_path={"type": "string"},
        doc_name={"type": "string"},
        record_id={"type": "integer"},
        order_id={"type": "integer"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("shipment_orders", "generate_batch"): _result(
        required=["success", "data"], data={"type": "object"}, error={"type": "string"}
    ),
    ("shipment_orders", "print"): _result(
        required=["success", "file_path", "updated"],
        file_path={"type": "string"},
        updated={"type": "boolean"},
        printed_at={"type": "string"},
        warning={"type": "string"},
        error={"type": "string"},
    ),
    ("shipment_orders", "clear_shipment"): _result(
        purchase_unit={"type": "string"},
        cleared_count={"type": "integer"},
        deleted_count={"type": "integer"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("shipment_orders", "set_sequence"): _result(
        sequence={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("shipment_orders", "reset_sequence"): _result(
        sequence={"type": "integer"}, data={"type": "object"}, error={"type": "string"}
    ),
    ("shipment_orders", "clear_all"): _result(
        cleared_count={"type": "integer"},
        deleted_count={"type": "integer"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("shipment_orders", "delete"): _result(
        deleted_id={"type": "integer"},
        deleted_count={"type": "integer"},
        data={"type": "object"},
        error={"type": "string"},
    ),
    ("print", "print_document"): _result(
        file_path={"type": "string"},
        printer={},
        printer_name={"type": "string"},
        status={"type": "string"},
        job_id={"type": "string"},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("print", "print_label"): _result(
        file_path={"type": "string"},
        printer={},
        printer_name={"type": "string"},
        copies={"type": "integer"},
        status={"type": "string"},
        require_confirm={"type": "boolean"},
        job_id={"type": "string"},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("print", "test"): _result(
        printer_name={"type": "string"},
        status={"type": "string"},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("print", "save_printer_selection"): _result(
        selection={"type": "object"},
        document_printer={"type": "string"},
        label_printer={"type": "string"},
        document={},
        label={},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("print", "workflow_label_dispatch"): _result(
        model_number={"type": "string"},
        product_name={"type": "string"},
        quantity={"type": "integer"},
        file_path={"type": "string"},
        status={"type": "string"},
        job_id={"type": "string"},
        error_code={"type": "string"},
        error={"type": "string"},
    ),
    ("business_event", "print_label"): _result(
        required=["success", "job_id", "event"], job_id={"type": "string"}, event={"type": "string"}
    ),
    ("business_event", "inventory_update"): _result(
        required=["success", "event"], event={"type": "string"}
    ),
    ("business_event", "shipment_create"): _result(
        required=["success", "event", "published"],
        event={"type": "string"},
        published={"type": "boolean"},
    ),
    ("system_maintenance", "set_default_printer"): _result(
        data={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "enable_startup"): _result(
        data={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "disable_startup"): _result(
        data={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "backup_database"): _result(
        backup_file={"type": "string"},
        data={"type": "object"},
        http_status_code={"type": "integer"},
    ),
    ("system_maintenance", "delete_database_backup"): _result(
        backup_file={"type": "string"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "restore_database"): _result(
        backup_file={"type": "string"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "clear_performance_cache"): _result(
        http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "invalidate_performance_cache"): _result(
        data={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("system_maintenance", "reinitialize_performance"): _result(
        data={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("excel_analysis", "read"): _result(required=["success", "data"], data={"type": "object"}),
    ("excel_analysis", "query"): {
        "type": "object",
        "required": ["success", "data"],
        "properties": {
            "success": {"type": "boolean"},
            "answer": {"type": "string"},
            "data": {"type": "object"},
        },
    },
    ("excel_analyzer", "analyze"): _result(
        required=["success", "file_path"],
        file_path={"type": "string"},
        file={"type": "string"},
        sheet={"type": "string"},
        structure={"type": "object"},
        zones={"type": "array"},
        merged_cells={"type": "array"},
        editable_ranges={"type": "array"},
        cells={"type": "object"},
        output_file={"type": "string"},
    ),
    ("excel_toolkit", "view"): _result(
        required=["success", "file_path"],
        file_path={"type": "string"},
        file={"type": "string"},
        sheet={"type": "string"},
        structure={"type": "object"},
        content={"type": "array"},
        row_count={"type": "integer"},
    ),
    ("excel_toolkit", "merged"): _result(
        required=["success", "file_path"],
        file_path={"type": "string"},
        file={"type": "string"},
        sheet={"type": "string"},
        merged_cells={"type": "array"},
        count={"type": "integer"},
    ),
    ("excel_toolkit", "styles"): _result(
        required=["success", "file_path"],
        file_path={"type": "string"},
        file={"type": "string"},
        sheet={"type": "string"},
        styles={"type": "array"},
    ),
    ("excel_toolkit", "structure"): _result(
        required=["success", "file_path"],
        file_path={"type": "string"},
        file={"type": "string"},
        sheet_names={"type": "array"},
        current_sheet={"type": "string"},
        structure={"type": "object"},
        columns={"type": "array"},
    ),
    ("label_template_generator", "execute"): _result(
        image_path={"type": "string"},
        analysis={"type": "object"},
        ocr_result={"type": "object"},
        code={"type": "string"},
        output_file={"type": "string"},
        output_error={"type": "string"},
    ),
    ("document_template", "create"): _result(
        template={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("document_template", "update"): _result(
        template={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("document_template", "delete"): _result(
        deleted={"type": "object"}, http_status_code={"type": "integer"}
    ),
    ("document_template", "ingest"): _result(
        ingested={"type": "boolean"},
        template={"type": "object"},
        analyzed={"type": "object"},
        http_status_code={"type": "integer"},
    ),
    ("document_template", "upload"): _result(
        ingested={"type": "boolean"},
        template={"type": "object"},
        analyzed={"type": "object"},
        http_status_code={"type": "integer"},
    ),
    ("template_extract", "extract"): _result(
        required=["success", "file_path", "fields", "sample_rows"],
        file_path={"type": "string"},
        sheet_names={"type": "array"},
        fields={"type": "array"},
        sample_rows={"type": "array"},
        grid_preview={"type": "object"},
        grid_style_cache={"type": "object"},
        sheets={"type": "array"},
        artifacts={"type": "array"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "query"): _result(
        required=["success", "dataset_id", "query", "chunks", "citations", "answer"],
        dataset_id={"type": "string"},
        query={"type": "string"},
        answer={"type": "string"},
        chunks={"type": "array"},
        citations={"type": "array"},
        tenant_id={"type": "string"},
        version={"type": "string"},
        vector_backend_used={"type": "boolean"},
        index={"type": "object"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "ingest_document"): _result(
        required=["success", "dataset_id"],
        dataset_id={"type": "string"},
        document={"type": "object"},
        chunk_count={"type": "integer"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "diff_versions"): _result(
        required=["success", "dataset_id"],
        dataset_id={"type": "string"},
        source={"type": "string"},
        tenant_id={"type": "string"},
        from_document={"type": "object"},
        to_document={"type": "object"},
        from_version={},
        to_version={},
        changed={"type": "boolean"},
        added_lines={"type": "array"},
        removed_lines={"type": "array"},
        diff={"type": "array"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "rollback_version"): _result(
        required=["success", "dataset_id"],
        dataset_id={"type": "string"},
        document={"type": "object"},
        chunk_count={"type": "integer"},
        rolled_back_from={"type": "object"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "rebuild_index"): _result(
        required=["success", "dataset_id"],
        dataset_id={"type": "string"},
        job={"type": "object"},
        background={"type": "boolean"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "cancel_rebuild"): _result(
        required=["success", "dataset_id"],
        dataset_id={"type": "string"},
        job_id={"type": "string"},
        job={"type": "object"},
        error_code={"type": "string"},
    ),
    ("dataset_rag", "delete_document"): _result(
        required=["success", "dataset_id", "document_id"],
        dataset_id={"type": "string"},
        document_id={"type": "string"},
        deleted_chunks={"type": "integer"},
        error_code={"type": "string"},
    ),
    ("memory_v2", "propose_candidate"): _result(
        created={"type": "boolean"}, candidate={"type": "object"}
    ),
    ("memory_v2", "confirm"): _result(memory={"type": "object"}),
    ("memory_v2", "reject"): _result(memory={"type": "object"}),
    ("memory_v2", "correct"): _result(memory={"type": "object"}),
    ("memory_v2", "delete"): _result(memory={"type": "object"}),
}
