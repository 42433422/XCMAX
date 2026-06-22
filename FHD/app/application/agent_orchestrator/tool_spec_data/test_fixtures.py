from __future__ import annotations

from typing import Any

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
