"""Tool action contract samples used by the orchestrator at runtime.

These are NOT test fixtures. They seed ToolActionSpecV2.contract_samples
(legacy field alias: test_fixtures) for tools that need explicit I/O examples.
"""

from __future__ import annotations

from typing import Any


def _sample(name: str, input: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "input": input, "output": output}


def _success(**fields: Any) -> dict[str, Any]:
    return {"success": True, **fields}


_SPECIAL_TOOL_CONTRACTS: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("sales", "create_order"): [
        _sample(
            "confirmed_named_order",
            {
                "customer_name": "测试客户",
                "items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}],
            },
            _success(data={"id": 1, "state": "confirmed", "total_amount": 100}),
        )
    ],
    ("sales", "quote"): [
        _sample(
            "named_quote",
            {
                "customer_name": "测试客户",
                "items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}],
            },
            _success(data={"id": 1, "total_amount": 100}),
        )
    ],
    ("business_db", "read"): [
        _sample(
            "read_products_by_keyword",
            {"entity": "products", "keyword": "5003"},
            _success(data=[{"model_number": "5003", "name": "sample product"}]),
        )
    ],
    ("business_db", "write"): [
        _sample(
            "create_customer",
            {
                "entity": "customers",
                "operation": "create",
                "payload": {"unit_name": "Acme Trading"},
            },
            _success(message="customer created", data={"id": "cust_1"}),
        )
    ],
    ("customers", "create"): [
        _sample(
            "create_customer_route",
            {
                "unit_name": "星光贸易",
                "contact_person": "张三",
                "contact_phone": "13900000000",
                "contact_address": "上海",
            },
            _success(data={"id": 7, "unit_name": "星光贸易", "contact_person": "张三"}),
        )
    ],
    ("customers", "update"): [
        _sample(
            "update_customer_route",
            {"id": 7, "unit_name": "星光贸易二部", "contact_person": "李四"},
            _success(data={"id": 7, "unit_name": "星光贸易二部", "contact_person": "李四"}),
        )
    ],
    ("customers", "delete"): [
        _sample("delete_customer_route", {"id": 7}, _success(message="已删除"))
    ],
    ("customers", "batch_delete"): [
        _sample(
            "batch_delete_customer_route",
            {"ids": [7, "bad", 8]},
            _success(message="已删除 2 条", deleted=2, skipped=["bad"]),
        )
    ],
    ("products", "create"): [
        _sample(
            "create_product",
            {"name_or_model": "5003", "unit_name": "星光贸易", "unit_price": 12.5},
            {
                "success": True,
                "created": True,
                "raw": _success(data={"id": 7, "model_number": "5003"}),
            },
        )
    ],
    ("products", "update"): [
        _sample(
            "update_product",
            {"id": 7, "name": "5003 v2"},
            _success(data={"id": 7, "name": "5003 v2"}),
        )
    ],
    ("products", "delete"): [
        _sample("delete_product", {"id": 7}, _success(message="产品删除成功"))
    ],
    ("products", "batch_create"): [
        _sample(
            "batch_create_products",
            {"products": [{"name": "5003", "unit_price": 12.5}]},
            _success(data={"success_count": 1, "failed_count": 0}),
        )
    ],
    ("products", "batch_delete"): [
        _sample(
            "batch_delete_products",
            {"ids": [7, 8]},
            _success(message="已删除 2 条", deleted=2, skipped=[]),
        )
    ],
    ("materials", "create"): [
        _sample(
            "create_material",
            {"name": "树脂", "material_code": "R-001", "min_quantity": 12},
            _success(message="创建成功", data={"id": 1, "name": "树脂"}),
        )
    ],
    ("materials", "update"): [
        _sample(
            "update_material",
            {"id": 1, "name": "树脂 v2"},
            _success(message="更新成功", data={"id": 1, "name": "树脂 v2"}),
        )
    ],
    ("materials", "delete"): [
        _sample(
            "delete_material",
            {"id": 1},
            _success(message="删除成功", data={"id": 1}),
        )
    ],
    ("materials", "batch_delete"): [
        _sample(
            "batch_delete_materials",
            {"ids": [1, 2]},
            _success(message="已删除 2 条记录", deleted_count=2),
        )
    ],
    ("inventory", "create_storage_location"): [
        _sample(
            "create_storage_location",
            {"warehouse_id": 1, "code": "A-01"},
            _success(id=11),
        )
    ],
    ("inventory", "update_storage_location"): [
        _sample(
            "update_storage_location",
            {"location_id": 11, "status": "full"},
            _success(data={"id": 11, "status": "full"}),
        )
    ],
    ("inventory", "create_warehouse"): [
        _sample(
            "create_warehouse",
            {"name": "主仓"},
            _success(data={"id": 1, "name": "主仓"}),
        )
    ],
    ("inventory", "update_warehouse"): [
        _sample(
            "update_warehouse",
            {"warehouse_id": 1, "name": "副仓"},
            _success(data={"id": 1, "name": "副仓"}),
        )
    ],
    ("inventory", "delete_warehouse"): [
        _sample("delete_warehouse", {"warehouse_id": 1}, _success(message="deleted"))
    ],
    ("inventory", "stock_in"): [
        _sample(
            "inventory_stock_in",
            {"product_id": 1, "warehouse_id": 2, "quantity": 3.0},
            _success(data={"transaction_type": "in"}),
        )
    ],
    ("inventory", "stock_out"): [
        _sample(
            "inventory_stock_out",
            {"product_id": 1, "warehouse_id": 2, "quantity": 1.0},
            _success(data={"transaction_type": "out"}),
        )
    ],
    ("inventory", "transfer"): [
        _sample(
            "inventory_transfer",
            {"product_id": 1, "from_warehouse_id": 1, "to_warehouse_id": 2, "quantity": 1.0},
            _success(data={"transaction_type": "transfer"}),
        )
    ],
    ("purchase", "create_supplier"): [
        _sample(
            "create_purchase_supplier",
            {"name": "星光供应商", "contact_person": "张三"},
            _success(message="创建成功", data={"id": 1, "name": "星光供应商"}),
        )
    ],
    ("purchase", "update_supplier"): [
        _sample(
            "update_purchase_supplier",
            {"supplier_id": 1, "status": "active"},
            _success(message="更新成功", data={"id": 1, "status": "active"}),
        )
    ],
    ("purchase", "delete_supplier"): [
        _sample("delete_purchase_supplier", {"supplier_id": 1}, _success(message="删除成功"))
    ],
    ("purchase", "create_order"): [
        _sample(
            "create_purchase_order",
            {"supplier_id": 1, "items": [{"product_id": 2, "quantity": 3}]},
            _success(message="创建成功", data={"id": 9, "status": "draft"}),
        )
    ],
    ("purchase", "update_order"): [
        _sample(
            "update_purchase_order",
            {"order_id": 9, "remark": "调整交期"},
            _success(message="更新成功", data={"id": 9, "remark": "调整交期"}),
        )
    ],
    ("purchase", "approve_order"): [
        _sample(
            "approve_purchase_order",
            {"order_id": 9, "approver": "manager"},
            _success(message="审批成功", data={"id": 9, "status": "approved"}),
        )
    ],
    ("purchase", "cancel_order"): [
        _sample(
            "cancel_purchase_order",
            {"order_id": 9},
            _success(message="取消成功", data={"id": 9, "status": "cancelled"}),
        )
    ],
    ("purchase", "create_inbound"): [
        _sample(
            "create_purchase_inbound",
            {"order_id": 9, "items": [{"product_id": 2, "quantity": 3}]},
            _success(message="入库成功", data={"id": 5, "order_id": 9}),
        )
    ],
    ("finance", "create_transaction"): [
        _sample(
            "create_finance_transaction",
            {"transaction_type": "expense", "amount": 128.5, "description": "运费"},
            _success(data={"id": 31, "transaction_type": "expense", "amount": 128.5}),
        )
    ],
    ("finance", "update_transaction"): [
        _sample(
            "update_finance_transaction",
            {"transaction_id": 31, "status": "paid"},
            _success(data={"id": 31, "status": "paid"}),
        )
    ],
    ("finance", "delete_transaction"): [
        _sample(
            "delete_finance_transaction",
            {"transaction_id": 31},
            _success(message="凭证已删除"),
        )
    ],
    ("employee", "list"): [
        _sample(
            "list_available_employees",
            {},
            _success(data=[{"employee_id": "quote-agent", "name": "报价员工"}]),
        )
    ],
    ("employee", "execute"): [
        _sample(
            "execute_quote_employee",
            {
                "employee_id": "quote-agent",
                "task": "Prepare a quote",
                "input": {"customer": "Acme Trading"},
            },
            _success(
                message="employee run accepted",
                employee_id="quote-agent",
                data={"status": "accepted"},
            ),
        )
    ],
    ("employee", "context"): [
        _sample(
            "read_quote_employee_context",
            {
                "employee_id": "quote-agent",
                "task": "Summarize the customer account context",
                "input": {},
            },
            _success(
                message="员工协作上下文已生成",
                employee_id="quote-agent",
                data={"result": {"summary": "当前客户账户上下文"}},
            ),
        )
    ],
    ("excel_import", "execute_import"): [
        _sample(
            "execute_pending_import",
            {"pending_import_id": "pending-import-1"},
            _success(
                message="import completed",
                imported_count=1,
                data={"pending_import_id": "pending-import-1"},
            ),
        )
    ],
    ("excel_import", "import_records"): [
        _sample(
            "import_structured_records",
            {
                "records": [{"unit_name": "Acme Trading", "model_number": "5003"}],
                "source": "agent_fixture",
            },
            _success(message="records imported", imported_count=1, data={"records": 1}),
        )
    ],
    ("unit_products_import", "execute_import"): [
        _sample(
            "import_unit_products_db",
            {
                "saved_name": "unit-products.db",
                "unit_name": "Acme Trading",
                "skip_duplicates": True,
            },
            _success(
                message="unit products imported",
                created_customers=1,
                created_products=2,
                data={"unit_name": "Acme Trading"},
            ),
        )
    ],
    ("template_extract", "extract"): [
        _sample(
            "extract_excel_template_structure",
            {"file_path": "/tmp/shipment-template.xlsx", "sheet_name": "出货"},
            _success(
                file_path="/tmp/shipment-template.xlsx",
                sheet_names=["出货"],
                fields=[{"label": "客户", "type": "dynamic"}],
                sample_rows=[{"客户": "ACME Trading"}],
                grid_preview={"rows": [["客户"], ["ACME Trading"]]},
                grid_style_cache={"cells": {}},
                sheets=[{"sheet_name": "出货"}],
                artifacts=[
                    {"artifact_type": "template_analysis", "name": "shipment-template.xlsx"}
                ],
            ),
        )
    ],
    ("business_event", "print_label"): [
        _sample(
            "submit_business_print_label_event",
            {
                "job_id": "print-job-1",
                "document_name": "发货标签.pdf",
                "printer_id": "default",
                "copies": 1,
            },
            _success(job_id="print-job-1", event="print.job.submitted"),
        )
    ],
    ("business_event", "inventory_update"): [
        _sample(
            "submit_business_inventory_update_event",
            {
                "product_id": "sku-1",
                "warehouse_id": "main",
                "delta": -2,
                "reason": "shipment",
                "new_quantity": 18,
            },
            _success(event="inventory.changed"),
        )
    ],
    ("shipment_records", "create"): [
        _sample(
            "create_shipment_record",
            {
                "unit_name": "星光贸易",
                "products": [
                    {
                        "name": "5003",
                        "quantity_tins": 2,
                        "tin_spec": 10,
                        "unit_price": 3.5,
                        "amount": 70,
                    }
                ],
                "contact_person": "张三",
                "contact_phone": "13900000000",
            },
            _success(message="出货记录已创建", data={"id": 7, "unit_name": "星光贸易"}),
        )
    ],
    ("shipment_records", "update"): [
        _sample(
            "update_shipment_record",
            {"id": 7, "unit_name": "星光贸易", "status": "printed"},
            _success(message="出货记录已更新", data={"id": 7, "status": "printed"}),
        )
    ],
    ("shipment_records", "delete"): [
        _sample(
            "delete_shipment_record",
            {"id": 7},
            _success(message="出货记录已删除", deleted_count=1),
        )
    ],
    ("shipment_orders", "generate"): [
        _sample(
            "generate_shipment_order",
            {
                "unit_name": "星光贸易",
                "products": [{"name": "5003", "qty": 2}],
                "date": "2026-06-19",
            },
            _success(
                file_path="/tmp/shipment.xlsx", doc_name="shipment.xlsx", record_id=7, order_id=7
            ),
        )
    ],
    ("shipment_orders", "generate_batch"): [
        _sample(
            "generate_shipment_order_batch",
            {"shipments": [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}]},
            _success(data={"processed": 1, "total": 1, "errors": []}),
        )
    ],
    ("shipment_orders", "print"): [
        _sample(
            "mark_shipment_order_printed",
            {"file_path": "/tmp/shipment.xlsx", "order_id": 7, "printer_name": "HP"},
            _success(
                message="已标记为已打印",
                file_path="/tmp/shipment.xlsx",
                updated=True,
                printed_at="2026-06-19T10:00:00",
            ),
        )
    ],
    ("shipment_orders", "clear_shipment"): [
        _sample(
            "clear_shipment_orders_for_unit",
            {"purchase_unit": "星光贸易"},
            _success(message="已清空星光贸易的发货记录", purchase_unit="星光贸易", cleared_count=3),
        )
    ],
    ("shipment_orders", "set_sequence"): [
        _sample(
            "set_shipment_order_sequence",
            {"sequence": 12},
            _success(message="序号已设置为 12", sequence=12),
        )
    ],
    ("shipment_orders", "reset_sequence"): [
        _sample(
            "reset_shipment_order_sequence",
            {},
            _success(message="序号已重置", sequence=1),
        )
    ],
    ("shipment_orders", "clear_all"): [
        _sample(
            "clear_all_shipment_orders",
            {},
            _success(message="已清空所有发货单", deleted_count=5),
        )
    ],
    ("shipment_orders", "delete"): [
        _sample(
            "delete_shipment_order",
            {"id": 7, "order_number": "7"},
            _success(message="订单 7 已删除", deleted_id=7),
        )
    ],
    ("print", "print_document"): [
        _sample(
            "print_document_route",
            {
                "file_path": "/tmp/document.pdf",
                "printer_name": "DocPrinter",
                "use_automation": False,
            },
            _success(
                message="文档已提交打印",
                file_path="/tmp/document.pdf",
                printer_name="DocPrinter",
                status="printed",
            ),
        )
    ],
    ("print", "print_label"): [
        _sample(
            "print_label_route",
            {"file_path": "/tmp/label.png", "printer_name": "LabelPrinter", "copies": 2},
            _success(
                message="标签已打印",
                file_path="/tmp/label.png",
                printer_name="LabelPrinter",
                copies=2,
                status="printed",
                require_confirm=False,
            ),
        )
    ],
    ("print", "test"): [
        _sample(
            "test_printer_route",
            {"printer_name": "DocPrinter"},
            _success(message="测试页已发送", printer_name="DocPrinter", status="printed"),
        )
    ],
    ("print", "save_printer_selection"): [
        _sample(
            "save_printer_selection_route",
            {"document_printer": "DocPrinter", "label_printer": "LabelPrinter"},
            _success(
                message="打印机选择已保存",
                document_printer="DocPrinter",
                label_printer="LabelPrinter",
                document=["DocPrinter"],
                label=["LabelPrinter"],
            ),
        )
    ],
    ("print", "workflow_label_dispatch"): [
        _sample(
            "workflow_label_dispatch_route",
            {"model_number": "M-1", "quantity": 2, "idempotency_key": "idem-1"},
            _success(
                message="标签已打印",
                model_number="M-1",
                product_name="M-1",
                quantity=2,
                status="printed",
            ),
        )
    ],
    ("business_event", "shipment_create"): [
        _sample(
            "submit_business_shipment_create_event",
            {
                "unit_name": "ACME Trading",
                "items": [{"sku": "sku-1", "qty": 2}],
                "contact_person": "Lee",
                "contact_phone": "13800000000",
            },
            _success(event="shipment.created", published=True),
        )
    ],
    ("system_maintenance", "set_default_printer"): [
        _sample(
            "set_default_printer",
            {"printer_name": "HP"},
            _success(message="默认打印机已更新", http_status_code=200),
        )
    ],
    ("system_maintenance", "enable_startup"): [
        _sample(
            "enable_startup",
            {},
            _success(message="已启用开机启动", http_status_code=200),
        )
    ],
    ("system_maintenance", "disable_startup"): [
        _sample(
            "disable_startup",
            {},
            _success(message="已关闭开机启动", http_status_code=200),
        )
    ],
    ("system_maintenance", "backup_database"): [
        _sample(
            "backup_database",
            {},
            _success(message="数据库备份完成", backup_file="backup.sql", http_status_code=200),
        )
    ],
    ("system_maintenance", "delete_database_backup"): [
        _sample(
            "delete_database_backup",
            {"backup_file": "backup.sql"},
            _success(message="备份已删除", backup_file="backup.sql", http_status_code=200),
        )
    ],
    ("system_maintenance", "restore_database"): [
        _sample(
            "restore_database",
            {"backup_file": "backup.sql"},
            _success(message="数据库恢复完成", backup_file="backup.sql", http_status_code=200),
        )
    ],
    ("system_maintenance", "clear_performance_cache"): [
        _sample(
            "clear_performance_cache",
            {"pattern": "test:*"},
            _success(message="已清除模式 'test:*' 的缓存 (5 个键)", http_status_code=200),
        )
    ],
    ("system_maintenance", "invalidate_performance_cache"): [
        _sample(
            "invalidate_performance_cache",
            {"keys": ["k1"]},
            _success(
                message="已删除 1 个缓存键",
                data={"deleted_count": 1, "requested_keys": 1},
                http_status_code=200,
            ),
        )
    ],
    ("system_maintenance", "reinitialize_performance"): [
        _sample(
            "reinitialize_performance",
            {},
            _success(
                message="性能优化系统已重新初始化", data={"status": "ok"}, http_status_code=200
            ),
        )
    ],
    ("excel_analyzer", "analyze"): [
        _sample(
            "analyze_excel_template_zones",
            {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            _success(
                file_path="/tmp/template.xlsx",
                file="template.xlsx",
                sheet="Sheet1",
                structure={"max_row": 8, "max_col": 4},
                zones=[{"name": "header", "type": "template"}],
                merged_cells=[],
                editable_ranges=[],
                cells={},
            ),
        )
    ],
    ("excel_toolkit", "view"): [
        _sample(
            "view_excel_content",
            {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1", "max_rows": 20},
            _success(
                file_path="/tmp/template.xlsx",
                file="template.xlsx",
                sheet="Sheet1",
                structure={"max_row": 2, "max_col": 2, "dimensions": "A1:B2"},
                content=[{"row": 1, "cells": [{"coordinate": "A1", "value": "客户"}]}],
                row_count=1,
            ),
        )
    ],
    ("excel_toolkit", "merged"): [
        _sample(
            "inspect_excel_merged_cells",
            {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            _success(
                file_path="/tmp/template.xlsx",
                file="template.xlsx",
                sheet="Sheet1",
                merged_cells=[],
                count=0,
            ),
        )
    ],
    ("excel_toolkit", "styles"): [
        _sample(
            "inspect_excel_cell_styles",
            {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1", "max_rows": 10},
            _success(
                file_path="/tmp/template.xlsx",
                file="template.xlsx",
                sheet="Sheet1",
                styles=[{"coordinate": "A1", "value": "客户"}],
            ),
        )
    ],
    ("excel_toolkit", "structure"): [
        _sample(
            "inspect_excel_structure",
            {"file_path": "/tmp/template.xlsx", "sheet_name": "Sheet1"},
            _success(
                file_path="/tmp/template.xlsx",
                file="template.xlsx",
                sheet_names=["Sheet1"],
                current_sheet="Sheet1",
                structure={"total_rows": 2, "total_columns": 2},
                columns=[{"index": 1, "letter": "A", "header": "客户"}],
            ),
        )
    ],
    ("label_template_generator", "execute"): [
        _sample(
            "generate_label_template_from_image",
            {
                "image_path": "/tmp/label.png",
                "class_name": "ProductLabelTemplate",
                "enable_ocr": True,
            },
            {
                "success": True,
                "image_path": "/tmp/label.png",
                "analysis": {"file": "label.png", "size": [800, 600]},
                "ocr_result": _success(fields=[{"label": "品名", "value": "清漆"}]),
                "code": "class ProductLabelTemplate:\\n    pass\\n",
            },
        )
    ],
    ("document_template", "create"): [
        _sample(
            "create_document_template",
            {
                "name": "发货模板",
                "template_type": "Excel",
                "fields": [{"label": "客户"}],
                "preview_data": {"sheet_name": "Sheet1"},
            },
            _success(
                message="模板创建成功",
                template={"id": "db:1", "db_id": 1, "name": "发货模板"},
                http_status_code=200,
            ),
        )
    ],
    ("document_template", "update"): [
        _sample(
            "update_document_template",
            {"id": "db:1", "name": "发货模板 v2", "fields": [{"label": "客户"}]},
            _success(
                message="模板更新成功",
                template={"id": "db:1", "db_id": 1, "name": "发货模板 v2"},
                http_status_code=200,
            ),
        )
    ],
    ("document_template", "delete"): [
        _sample(
            "delete_document_template",
            {"id": "db:1"},
            _success(
                message="模板删除成功", deleted={"id": "db:1", "db_id": 1}, http_status_code=200
            ),
        )
    ],
    ("generate_office_document", "execute"): [
        _sample(
            "generate_contract_docx",
            {"user_request": "Generate a contract", "output_format": "docx"},
            _success(
                message="document generated",
                file_name="contract.docx",
                download_url="/api/ai/kitten/document/pickup/token",
                pickup_token="token",
                artifacts=[
                    {
                        "artifact_type": "office_document",
                        "name": "contract.docx",
                        "source": "generate_office_document",
                    }
                ],
            ),
        )
    ],
    ("excel_vector_index", "execute"): [
        _sample(
            "build_excel_vector_index",
            {"file_path": "/tmp/products.xlsx", "index_name": "products"},
            _success(
                message="index built",
                index_id="excel-index-1",
                excel_vector_index_id="excel-index-1",
                excel_index_id="excel-index-1",
                chunk_count=3,
                row_count=10,
            ),
        )
    ],
    ("excel_vector_index", "query"): [
        _sample(
            "query_excel_vector_index",
            {"index_id": "excel-index-1", "query": "5003 清漆", "top_k": 3},
            _success(
                index_id="excel-index-1",
                query="5003 清漆",
                hits=[{"score": 0.92, "row": {"model_number": "5003", "product_name": "清漆"}}],
            ),
        )
    ],
    ("ocr", "recognize"): [
        _sample(
            "recognize_ocr_image",
            {"file_path": "/tmp/label.png"},
            _success(
                message="识别成功",
                text="购货单位：ACME Trading",
                file_path="/tmp/label.png",
                artifacts=[{"artifact_type": "ocr_text", "name": "ocr_result"}],
            ),
        )
    ],
    ("ocr", "request"): [
        _sample(
            "publish_business_ocr_request",
            {
                "request_id": "ocr-request-1",
                "image_url": "https://example.invalid/label.png",
                "ocr_type": "general",
                "user_id": "tenant-a",
            },
            _success(
                message="OCR 请求已发布",
                request_id="ocr-request-1",
                image_url="https://example.invalid/label.png",
                ocr_type="general",
                user_id="tenant-a",
                event="ocr.requested",
                published=True,
            ),
        )
    ],
    ("ocr", "extract"): [
        _sample(
            "extract_ocr_fields",
            {"text": "购货单位：ACME Trading\n联系人：Alice"},
            _success(
                message="提取成功",
                data={"purchase_unit": "ACME Trading", "contact_person": "Alice"},
            ),
        )
    ],
    ("ocr", "analyze"): [
        _sample(
            "analyze_ocr_text",
            {"text": "订单编号：SO-1\n购货单位：ACME Trading"},
            _success(message="分析成功", data={"text_type": "order", "confidence": 0.67}),
        )
    ],
    ("ocr", "recognize_and_extract"): [
        _sample(
            "recognize_and_extract_ocr_image",
            {"file_path": "/tmp/order.png"},
            _success(
                message="识别和提取成功",
                text="购货单位：ACME Trading",
                data={"purchase_unit": "ACME Trading"},
                analysis={"text_type": "customer", "confidence": 0.67},
                artifacts=[{"artifact_type": "ocr_text", "name": "ocr_result"}],
            ),
        )
    ],
    ("dataset_rag", "query"): [
        _sample(
            "query_dataset_rag_with_citations",
            {
                "dataset_id": "platform-docs",
                "query": "Which model should AI routes use?",
                "top_k": 2,
                "include_answer": True,
            },
            _success(
                dataset_id="platform-docs",
                query="Which model should AI routes use?",
                answer="AI routes should use XCauto [1].",
                chunks=[
                    {
                        "chunk_id": "chunk_1",
                        "text": "AI routes should use XCauto.",
                        "source": "policy.pdf",
                    }
                ],
                citations=[{"index": 1, "source": "policy.pdf", "chunk_index": 0}],
            ),
        )
    ],
    ("dataset_rag", "ingest_document"): [
        _sample(
            "ingest_dataset_document",
            {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "text": "AI routes should use XCauto.",
                "tenant_id": "tenant-a",
                "metadata": {"doc_type": "policy"},
            },
            _success(
                dataset_id="platform-docs",
                document={"document_id": "doc_1", "source": "policy.pdf"},
                chunk_count=1,
            ),
        )
    ],
    ("dataset_rag", "diff_versions"): [
        _sample(
            "diff_dataset_document_versions",
            {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "from_version": "v1",
                "to_version": "latest",
            },
            _success(
                dataset_id="platform-docs",
                source="policy.pdf",
                from_version=1,
                to_version=2,
                changed=True,
                added_lines=["Use AgentOrchestrator."],
                removed_lines=[],
                diff=["--- policy.pdf@v1", "+++ policy.pdf@v2"],
            ),
        )
    ],
    ("dataset_rag", "rollback_version"): [
        _sample(
            "rollback_dataset_document_version",
            {
                "dataset_id": "platform-docs",
                "source": "policy.pdf",
                "target_version": "v1",
                "metadata": {"reason": "bad update"},
            },
            _success(
                dataset_id="platform-docs",
                document={"document_id": "doc_rollback", "source": "policy.pdf"},
                chunk_count=1,
                rolled_back_from={"document_id": "doc_v1", "version": 1},
            ),
        )
    ],
    ("dataset_rag", "rebuild_index"): [
        _sample(
            "rebuild_dataset_index",
            {
                "dataset_id": "platform-docs",
                "tenant_id": "tenant-a",
                "background": True,
                "max_attempts": 1,
            },
            _success(
                dataset_id="platform-docs",
                job={"job_id": "rag_rebuild_1", "status": "queued"},
                background=True,
            ),
        )
    ],
    ("dataset_rag", "cancel_rebuild"): [
        _sample(
            "cancel_dataset_rebuild",
            {"dataset_id": "platform-docs", "job_id": "rag_rebuild_1"},
            _success(
                dataset_id="platform-docs",
                job_id="rag_rebuild_1",
                job={"job_id": "rag_rebuild_1", "status": "cancelled"},
            ),
        )
    ],
    ("dataset_rag", "delete_document"): [
        _sample(
            "delete_dataset_document",
            {"dataset_id": "platform-docs", "document_id": "doc_1"},
            _success(dataset_id="platform-docs", document_id="doc_1", deleted_chunks=1),
        )
    ],
    ("dataset_rag", "clear_dataset"): [
        _sample(
            "clear_dataset_documents",
            {"dataset_id": "persy-knowledge"},
            _success(dataset_id="persy-knowledge", deleted_documents=2, deleted_chunks=8),
        )
    ],
    ("memory_v2", "propose_candidate"): [
        _sample(
            "propose_memory_v2_candidate",
            {
                "user_id": "tenant-a",
                "memory_type": "preference",
                "key": "favorite_customer",
                "value": "ACME Trading",
                "source": "settings_ui",
                "confidence": 0.9,
            },
            _success(
                created=True,
                candidate={
                    "memory_id": "mem_1",
                    "memory_type": "preference",
                    "key": "favorite_customer",
                    "status": "pending",
                },
            ),
        )
    ],
    ("memory_v2", "confirm"): [
        _sample(
            "confirm_memory_v2_candidate",
            {"user_id": "tenant-a", "memory_id": "mem_1"},
            _success(
                memory={"memory_id": "mem_1", "status": "active", "eligible_for_planner": True}
            ),
        )
    ],
    ("memory_v2", "reject"): [
        _sample(
            "reject_memory_v2_candidate",
            {"user_id": "tenant-a", "memory_id": "mem_1", "reason": "not useful"},
            _success(memory={"memory_id": "mem_1", "status": "rejected"}),
        )
    ],
    ("memory_v2", "correct"): [
        _sample(
            "correct_memory_v2_record",
            {
                "user_id": "tenant-a",
                "memory_id": "mem_1",
                "key": "favorite_customer",
                "value": "ACME Trading Ltd.",
                "reason": "user corrected value",
            },
            _success(
                memory={
                    "memory_id": "mem_1",
                    "key": "favorite_customer",
                    "value": "ACME Trading Ltd.",
                }
            ),
        )
    ],
    ("memory_v2", "delete"): [
        _sample(
            "delete_memory_v2_record",
            {"user_id": "tenant-a", "memory_id": "mem_1", "reason": "user removed memory"},
            _success(memory={"memory_id": "mem_1", "status": "deleted"}),
        )
    ],
}
