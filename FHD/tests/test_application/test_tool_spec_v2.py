from __future__ import annotations

from unittest.mock import patch

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import (
    build_tool_specs_v2,
    get_tool_action_spec,
    validate_tool_call,
    validate_tool_result,
    validate_tool_spec_fixtures,
)


def test_build_tool_specs_v2_exposes_business_db_and_employee_contracts() -> None:
    specs = build_tool_specs_v2()

    read_spec = specs[("business_db", "read")]
    assert read_spec.risk == "low"
    assert read_spec.idempotent is True
    assert read_spec.required_params == ["entity"]
    assert read_spec.input_schema["required"] == ["entity"]
    assert read_spec.permission == "business_db.read"

    write_spec = specs[("business_db", "write")]
    assert write_spec.risk == "medium"
    assert write_spec.idempotent is False
    assert write_spec.input_schema["properties"]["payload"]["type"] == "object"

    employee_spec = specs[("employee", "execute")]
    assert employee_spec.risk == "medium"
    assert employee_spec.permission == "employee.execute"
    assert "task" in employee_spec.required_params
    assert employee_spec.output_schema["required"] == ["success", "message", "data"]
    assert employee_spec.test_fixtures[0]["input"]["task"] == "Prepare a quote"

    customer_update_spec = specs[("customers", "update")]
    assert customer_update_spec.risk == "medium"
    assert customer_update_spec.required_params == ["id"]
    assert customer_update_spec.input_schema["required"] == ["id"]
    assert customer_update_spec.test_fixtures[0]["input"]["id"] == 7

    customer_delete_spec = specs[("customers", "delete")]
    assert customer_delete_spec.risk == "high"
    assert customer_delete_spec.permission == "tool.customers.delete"

    customer_batch_spec = specs[("customers", "batch_delete")]
    assert customer_batch_spec.risk == "high"
    assert customer_batch_spec.input_schema["required"] == ["ids"]
    assert customer_batch_spec.test_fixtures[0]["output"]["deleted"] == 2

    product_update_spec = specs[("products", "update")]
    assert product_update_spec.risk == "medium"
    assert product_update_spec.required_params == ["id"]
    assert product_update_spec.input_schema["required"] == ["id"]
    assert product_update_spec.test_fixtures[0]["input"]["id"] == 7

    product_delete_spec = specs[("products", "delete")]
    assert product_delete_spec.risk == "high"
    assert product_delete_spec.permission == "tool.products.delete"

    product_batch_spec = specs[("products", "batch_create")]
    assert product_batch_spec.risk == "high"
    assert product_batch_spec.input_schema["required"] == ["products"]
    assert product_batch_spec.test_fixtures[0]["output"]["data"]["success_count"] == 1

    print_event_spec = specs[("business_event", "print_label")]
    assert print_event_spec.risk == "high"
    assert print_event_spec.idempotent is False
    assert print_event_spec.required_params == ["document_name"]
    assert print_event_spec.output_schema["required"] == ["success", "job_id", "event"]

    inventory_event_spec = specs[("business_event", "inventory_update")]
    assert inventory_event_spec.risk == "high"
    assert inventory_event_spec.input_schema["required"] == ["product_id"]
    assert inventory_event_spec.test_fixtures[0]["output"]["event"] == "inventory.changed"

    stock_in_spec = specs[("inventory", "stock_in")]
    assert stock_in_spec.risk == "high"
    assert stock_in_spec.input_schema["required"] == ["product_id", "warehouse_id", "quantity"]
    assert stock_in_spec.test_fixtures[0]["output"]["data"]["transaction_type"] == "in"

    warehouse_delete_spec = specs[("inventory", "delete_warehouse")]
    assert warehouse_delete_spec.risk == "high"
    assert warehouse_delete_spec.permission == "tool.inventory.delete_warehouse"

    purchase_approve_spec = specs[("purchase", "approve_order")]
    assert purchase_approve_spec.risk == "high"
    assert purchase_approve_spec.required_params == ["order_id"]
    assert purchase_approve_spec.permission == "tool.purchase.approve_order"
    assert purchase_approve_spec.test_fixtures[0]["input"]["approver"] == "manager"

    purchase_inbound_spec = specs[("purchase", "create_inbound")]
    assert purchase_inbound_spec.risk == "high"
    assert purchase_inbound_spec.input_schema["properties"]["items"]["type"] == "array"
    assert purchase_inbound_spec.test_fixtures[0]["output"]["data"]["order_id"] == 9

    finance_create_spec = specs[("finance", "create_transaction")]
    assert finance_create_spec.risk == "high"
    assert finance_create_spec.required_params == ["transaction_type", "amount"]
    assert finance_create_spec.input_schema["required"] == ["transaction_type", "amount"]
    assert finance_create_spec.test_fixtures[0]["input"]["transaction_type"] == "expense"

    finance_delete_spec = specs[("finance", "delete_transaction")]
    assert finance_delete_spec.risk == "high"
    assert finance_delete_spec.permission == "tool.finance.delete_transaction"
    assert finance_delete_spec.test_fixtures[0]["input"]["transaction_id"] == 31

    shipment_create_spec = specs[("shipment_records", "create")]
    assert shipment_create_spec.risk == "high"
    assert shipment_create_spec.required_params == ["unit_name"]
    assert shipment_create_spec.input_schema["required"] == ["unit_name"]
    assert shipment_create_spec.test_fixtures[0]["output"]["data"]["id"] == 7

    shipment_update_spec = specs[("shipment_records", "update")]
    assert shipment_update_spec.risk == "medium"
    assert shipment_update_spec.permission == "tool.shipment_records.update"

    shipment_delete_spec = specs[("shipment_records", "delete")]
    assert shipment_delete_spec.risk == "high"
    assert shipment_delete_spec.test_fixtures[0]["output"]["deleted_count"] == 1

    shipment_order_generate_spec = specs[("shipment_orders", "generate")]
    assert shipment_order_generate_spec.risk == "high"
    assert shipment_order_generate_spec.required_params == ["unit_name", "products"]
    assert shipment_order_generate_spec.input_schema["required"] == ["unit_name", "products"]
    assert shipment_order_generate_spec.test_fixtures[0]["output"]["record_id"] == 7

    shipment_order_batch_spec = specs[("shipment_orders", "generate_batch")]
    assert shipment_order_batch_spec.risk == "high"
    assert shipment_order_batch_spec.input_schema["required"] == ["shipments"]
    assert shipment_order_batch_spec.output_schema["required"] == ["success", "data"]

    shipment_order_print_spec = specs[("shipment_orders", "print")]
    assert shipment_order_print_spec.risk == "high"
    assert shipment_order_print_spec.permission == "tool.shipment_orders.print"
    assert shipment_order_print_spec.output_schema["required"] == [
        "success",
        "file_path",
        "updated",
    ]

    shipment_order_clear_spec = specs[("shipment_orders", "clear_shipment")]
    assert shipment_order_clear_spec.risk == "high"
    assert shipment_order_clear_spec.required_params == ["purchase_unit"]
    assert shipment_order_clear_spec.input_schema["required"] == ["purchase_unit"]
    assert shipment_order_clear_spec.test_fixtures[0]["output"]["cleared_count"] == 3

    shipment_order_set_sequence_spec = specs[("shipment_orders", "set_sequence")]
    assert shipment_order_set_sequence_spec.risk == "high"
    assert shipment_order_set_sequence_spec.required_params == ["sequence"]
    assert shipment_order_set_sequence_spec.test_fixtures[0]["input"]["sequence"] == 12

    shipment_order_reset_sequence_spec = specs[("shipment_orders", "reset_sequence")]
    assert shipment_order_reset_sequence_spec.risk == "high"
    assert shipment_order_reset_sequence_spec.required_params == []
    assert shipment_order_reset_sequence_spec.test_fixtures[0]["output"]["sequence"] == 1

    shipment_order_clear_all_spec = specs[("shipment_orders", "clear_all")]
    assert shipment_order_clear_all_spec.risk == "high"
    assert shipment_order_clear_all_spec.permission == "tool.shipment_orders.clear_all"
    assert shipment_order_clear_all_spec.test_fixtures[0]["output"]["deleted_count"] == 5

    shipment_order_delete_spec = specs[("shipment_orders", "delete")]
    assert shipment_order_delete_spec.risk == "high"
    assert shipment_order_delete_spec.input_schema["required"] == ["id"]
    assert shipment_order_delete_spec.test_fixtures[0]["output"]["deleted_id"] == 7

    products_batch_delete_spec = specs[("products", "batch_delete")]
    assert products_batch_delete_spec.risk == "high"
    assert products_batch_delete_spec.required_params == ["ids"]
    assert products_batch_delete_spec.input_schema["required"] == ["ids"]
    assert products_batch_delete_spec.test_fixtures[0]["output"]["deleted"] == 2

    print_document_spec = specs[("print", "print_document")]
    assert print_document_spec.risk == "high"
    assert print_document_spec.required_params == ["file_path"]
    assert print_document_spec.permission == "tool.print.print_document"
    assert print_document_spec.test_fixtures[0]["input"]["printer_name"] == "DocPrinter"

    print_label_spec = specs[("print", "print_label")]
    assert print_label_spec.risk == "high"
    assert print_label_spec.input_schema["required"] == ["file_path"]
    assert print_label_spec.test_fixtures[0]["output"]["require_confirm"] is False

    print_test_spec = specs[("print", "test")]
    assert print_test_spec.risk == "medium"
    assert print_test_spec.required_params == ["printer_name"]
    assert print_test_spec.test_fixtures[0]["output"]["printer_name"] == "DocPrinter"

    print_selection_spec = specs[("print", "save_printer_selection")]
    assert print_selection_spec.risk == "medium"
    assert print_selection_spec.permission == "tool.print.save_printer_selection"
    assert print_selection_spec.test_fixtures[0]["output"]["document_printer"] == "DocPrinter"

    print_workflow_spec = specs[("print", "workflow_label_dispatch")]
    assert print_workflow_spec.risk == "high"
    assert print_workflow_spec.required_params == ["model_number"]
    assert print_workflow_spec.input_schema["required"] == ["model_number"]
    assert print_workflow_spec.test_fixtures[0]["input"]["quantity"] == 2

    shipment_event_spec = specs[("business_event", "shipment_create")]
    assert shipment_event_spec.risk == "high"
    assert shipment_event_spec.output_schema["required"] == ["success", "event", "published"]
    assert shipment_event_spec.test_fixtures[0]["output"]["published"] is True

    printer_spec = specs[("system_maintenance", "set_default_printer")]
    assert printer_spec.risk == "medium"
    assert printer_spec.idempotent is False
    assert printer_spec.required_params == ["printer_name"]
    assert printer_spec.input_schema["required"] == ["printer_name"]

    restore_spec = specs[("system_maintenance", "restore_database")]
    assert restore_spec.risk == "high"
    assert restore_spec.required_params == ["backup_file"]
    assert restore_spec.timeout_seconds == 120
    assert restore_spec.test_fixtures[0]["input"]["backup_file"] == "backup.sql"

    invalidate_spec = specs[("system_maintenance", "invalidate_performance_cache")]
    assert invalidate_spec.risk == "medium"
    assert invalidate_spec.input_schema["properties"]["keys"]["type"] == "array"
    assert invalidate_spec.test_fixtures[0]["output"]["data"]["deleted_count"] == 1


def test_build_tool_specs_v2_exposes_import_contracts_as_write_risk() -> None:
    specs = build_tool_specs_v2()

    excel_import_spec = specs[("excel_import", "import_records")]
    assert excel_import_spec.risk == "medium"
    assert excel_import_spec.idempotent is False
    assert excel_import_spec.input_schema["properties"]["records"]["type"] == "array"
    assert excel_import_spec.output_schema["properties"]["imported_count"]["type"] == "integer"

    unit_products_spec = specs[("unit_products_import", "execute_import")]
    assert unit_products_spec.risk == "medium"
    assert unit_products_spec.idempotent is False
    assert unit_products_spec.input_schema["required"] == ["saved_name", "unit_name"]
    assert unit_products_spec.test_fixtures[0]["output"]["created_products"] == 2


def test_build_tool_specs_v2_exposes_dataset_rag_query_contract() -> None:
    specs = build_tool_specs_v2()

    rag_spec = specs[("dataset_rag", "query")]
    assert rag_spec.risk == "low"
    assert rag_spec.idempotent is True
    assert rag_spec.required_params == ["dataset_id", "query"]
    assert rag_spec.permission == "dataset.read"
    assert rag_spec.input_schema["required"] == ["dataset_id", "query"]
    assert rag_spec.output_schema["required"] == [
        "success",
        "dataset_id",
        "query",
        "chunks",
        "citations",
        "answer",
    ]
    assert rag_spec.test_fixtures[0]["input"]["include_answer"] is True


def test_build_tool_specs_v2_exposes_document_generation_contract() -> None:
    specs = build_tool_specs_v2()

    document_spec = specs[("generate_office_document", "execute")]
    assert document_spec.risk == "medium"
    assert document_spec.idempotent is False
    assert document_spec.timeout_seconds == 120
    assert document_spec.input_schema["properties"]["output_format"]["enum"] == ["docx", "xlsx"]
    assert document_spec.output_schema["required"] == [
        "success",
        "file_name",
        "download_url",
        "artifacts",
    ]
    assert document_spec.test_fixtures[0]["output"]["download_url"].startswith(
        "/api/ai/kitten/document/pickup/"
    )


def test_build_tool_specs_v2_exposes_excel_vector_contract() -> None:
    specs = build_tool_specs_v2()

    template_spec = specs[("template_extract", "extract")]
    assert template_spec.risk == "low"
    assert template_spec.idempotent is True
    assert template_spec.required_params == ["file_path"]
    assert template_spec.input_schema["required"] == ["file_path"]
    assert template_spec.output_schema["required"] == [
        "success",
        "file_path",
        "fields",
        "sample_rows",
    ]
    assert (
        template_spec.test_fixtures[0]["output"]["artifacts"][0]["artifact_type"]
        == "template_analysis"
    )

    analyzer_spec = specs[("excel_analyzer", "analyze")]
    assert analyzer_spec.risk == "low"
    assert analyzer_spec.idempotent is True
    assert analyzer_spec.required_params == ["file_path"]
    assert analyzer_spec.input_schema["required"] == ["file_path"]
    assert analyzer_spec.output_schema["required"] == ["success", "file_path"]
    assert analyzer_spec.test_fixtures[0]["output"]["zones"][0]["name"] == "header"

    toolkit_spec = specs[("excel_toolkit", "view")]
    assert toolkit_spec.risk == "low"
    assert toolkit_spec.idempotent is True
    assert toolkit_spec.required_params == ["file_path"]
    assert toolkit_spec.input_schema["properties"]["max_rows"]["type"] == "integer"
    assert toolkit_spec.output_schema["required"] == ["success", "file_path"]
    assert toolkit_spec.test_fixtures[0]["output"]["row_count"] == 1

    label_spec = specs[("label_template_generator", "execute")]
    assert label_spec.risk == "low"
    assert label_spec.idempotent is True
    assert label_spec.required_params == ["image_path"]
    assert label_spec.timeout_seconds == 120
    assert label_spec.input_schema["required"] == ["image_path"]
    assert label_spec.output_schema["properties"]["code"]["type"] == "string"
    assert label_spec.test_fixtures[0]["output"]["code"].startswith("class ProductLabelTemplate")

    template_create_spec = specs[("document_template", "create")]
    assert template_create_spec.risk == "medium"
    assert template_create_spec.idempotent is False
    assert template_create_spec.cost_units == 2
    assert template_create_spec.input_schema["properties"]["preview_data"]["type"] == "object"
    assert template_create_spec.output_schema["properties"]["template"]["type"] == "object"
    assert template_create_spec.test_fixtures[0]["output"]["template"]["id"] == "db:1"

    template_update_spec = specs[("document_template", "update")]
    assert template_update_spec.risk == "medium"
    assert template_update_spec.idempotent is False
    assert template_update_spec.required_params == ["id"]
    assert template_update_spec.input_schema["required"] == ["id"]
    assert template_update_spec.test_fixtures[0]["output"]["template"]["name"] == "发货模板 v2"

    template_delete_spec = specs[("document_template", "delete")]
    assert template_delete_spec.risk == "high"
    assert template_delete_spec.idempotent is False
    assert template_delete_spec.required_params == ["id"]
    assert template_delete_spec.input_schema["required"] == ["id"]
    assert template_delete_spec.output_schema["properties"]["deleted"]["type"] == "object"
    assert template_delete_spec.test_fixtures[0]["output"]["deleted"]["id"] == "db:1"

    index_spec = specs[("excel_vector_index", "execute")]
    assert index_spec.risk == "low"
    assert index_spec.idempotent is True
    assert index_spec.required_params == ["file_path"]
    assert index_spec.permission == "tool.excel_vector_index.execute"
    assert index_spec.input_schema["required"] == ["file_path"]
    assert index_spec.output_schema["required"] == ["success", "index_id"]
    assert index_spec.test_fixtures[0]["output"]["excel_vector_index_id"] == "excel-index-1"

    query_spec = specs[("excel_vector_index", "query")]
    assert query_spec.risk == "low"
    assert query_spec.idempotent is True
    assert query_spec.required_params == ["index_id", "query"]
    assert query_spec.input_schema["properties"]["top_k"]["type"] == "integer"
    assert query_spec.output_schema["required"] == ["success"]
    assert query_spec.test_fixtures[0]["output"]["hits"][0]["row"]["model_number"] == "5003"


def test_build_tool_specs_v2_exposes_ocr_contract() -> None:
    specs = build_tool_specs_v2()

    recognize_spec = specs[("ocr", "recognize")]
    assert recognize_spec.risk == "low"
    assert recognize_spec.idempotent is True
    assert recognize_spec.required_params == ["file_path"]
    assert recognize_spec.input_schema["required"] == ["file_path"]
    assert recognize_spec.output_schema["properties"]["artifacts"]["type"] == "array"
    assert recognize_spec.test_fixtures[0]["output"]["artifacts"][0]["artifact_type"] == "ocr_text"

    request_spec = specs[("ocr", "request")]
    assert request_spec.risk == "low"
    assert request_spec.idempotent is True
    assert request_spec.required_params == ["request_id", "image_url"]
    assert request_spec.input_schema["required"] == ["request_id", "image_url"]
    assert request_spec.output_schema["required"] == ["success", "request_id", "event", "published"]
    assert request_spec.test_fixtures[0]["output"]["event"] == "ocr.requested"

    analyze_spec = specs[("ocr", "analyze")]
    assert analyze_spec.risk == "low"
    assert analyze_spec.required_params == ["text"]
    assert analyze_spec.output_schema["properties"]["data"]["type"] == "object"

    combined_spec = specs[("ocr", "recognize_and_extract")]
    assert combined_spec.required_params == ["file_path"]
    assert combined_spec.output_schema["properties"]["analysis"]["type"] == "object"


def test_build_tool_specs_v2_exposes_aiopen_mcp_contracts() -> None:
    specs = build_tool_specs_v2()

    catalog_spec = specs[("aiopen", "api_catalog")]
    assert catalog_spec.risk == "low"
    assert catalog_spec.idempotent is True
    assert catalog_spec.permission == "aiopen.api_catalog"
    assert catalog_spec.input_schema["additionalProperties"] is False
    assert catalog_spec.test_fixtures[0]["output"]["routes"][0]["path"] == "/api/ai/chat"

    chat_spec = specs[("aiopen", "chat")]
    assert chat_spec.risk == "medium"
    assert chat_spec.idempotent is False
    assert chat_spec.required_params == ["message"]

    valid_ui_type = validate_tool_call(
        "aiopen",
        "ui_type",
        {"selector": "#message", "text": "hello"},
    )
    assert valid_ui_type.ok is True

    invalid_ui_type = validate_tool_call("aiopen", "ui_type", {"selector": "#message"})
    assert invalid_ui_type.ok is False
    assert invalid_ui_type.error_code == "schema_validation_failed"
    assert "text" in invalid_ui_type.message


def test_build_tool_specs_v2_provides_fixture_for_every_registry_action() -> None:
    specs = build_tool_specs_v2()

    assert specs
    assert all(spec.test_fixtures for spec in specs.values())
    assert specs[("customers", "query")].test_fixtures[0]["input"] == {}


def test_validate_tool_call_rejects_missing_params_and_raw_sql() -> None:
    missing = validate_tool_call("business_db", "read", {})
    assert missing.ok is False
    assert missing.error_code == "schema_validation_failed"
    assert "entity" in missing.message

    raw_sql = validate_tool_call("business_db", "read", {"entity": "products", "sql": "select 1"})
    assert raw_sql.ok is False
    assert raw_sql.error_code == "unsafe_raw_sql"

    valid = validate_tool_call("business_db", "read", {"entity": "products", "keyword": "5003"})
    assert valid.ok is True
    assert valid.spec is not None


def test_validate_tool_call_checks_schema_types() -> None:
    invalid = validate_tool_call(
        "business_db",
        "write",
        {"entity": "customers", "operation": "create", "payload": "not dict"},
    )

    assert invalid.ok is False
    assert invalid.error_code == "schema_validation_failed"
    assert "payload" in invalid.message


def test_validate_tool_call_rejects_invalid_document_format() -> None:
    invalid = validate_tool_call(
        "generate_office_document",
        "execute",
        {"user_request": "生成合同", "output_format": "pdf"},
    )

    assert invalid.ok is False
    assert invalid.error_code == "schema_validation_failed"
    assert "output_format" in invalid.message


def test_validate_tool_result_checks_output_schema() -> None:
    valid = validate_tool_result(
        "generate_office_document",
        "execute",
        {
            "success": True,
            "file_name": "contract.docx",
            "download_url": "/api/ai/kitten/document/pickup/token",
            "artifacts": [{"artifact_type": "office_document"}],
        },
    )
    assert valid.ok is True

    invalid = validate_tool_result(
        "generate_office_document",
        "execute",
        {"success": True, "file_name": "contract.docx"},
    )
    assert invalid.ok is False
    assert invalid.error_code == "output_schema_validation_failed"
    assert "download_url" in invalid.message


def test_validate_tool_result_allows_structured_failure_without_success_payload_fields() -> None:
    failed = validate_tool_result(
        "business_db",
        "read",
        {"success": False, "message": "temporary database error"},
    )

    assert failed.ok is True


def test_validate_tool_spec_fixtures_pass_for_all_registry_actions() -> None:
    assert validate_tool_spec_fixtures() == {}


def test_get_tool_action_spec_normalizes_action_alias() -> None:
    spec = get_tool_action_spec("employee", "run")
    assert spec is not None
    assert spec.action == "execute"


def test_agent_tool_executor_validates_before_registered_dispatch() -> None:
    step = AgentStep(
        node_id="n1",
        tool_id="business_db",
        action="read",
        params={},
        risk="low",
        idempotent=True,
    )

    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as execute:
        result = AgentToolExecutor().execute(step, runtime_context={"run_id": "run_1"})

    assert result["success"] is False
    assert result["error_code"] == "schema_validation_failed"
    execute.assert_not_called()


def test_agent_tool_executor_enforces_registered_output_schema() -> None:
    step = AgentStep(
        node_id="n1",
        tool_id="generate_office_document",
        action="execute",
        params={"user_request": "Generate a contract", "output_format": "docx"},
        risk="medium",
        idempotent=False,
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "file_name": "contract.docx"},
    ) as execute:
        result = AgentToolExecutor().execute(step, runtime_context={"run_id": "run_1"})

    assert result["success"] is False
    assert result["error_code"] == "output_schema_validation_failed"
    assert result["tool_id"] == "generate_office_document"
    assert result["action"] == "execute"
    assert "download_url" in result["message"]
    assert result["output_keys"] == ["file_name", "success"]
    execute.assert_called_once()


def test_agent_tool_executor_rejects_non_object_tool_result() -> None:
    step = AgentStep(
        node_id="n1",
        tool_id="business_db",
        action="read",
        params={"entity": "products"},
        risk="low",
        idempotent=True,
    )

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value="not-json-object",
    ):
        result = AgentToolExecutor().execute(step, runtime_context={"run_id": "run_1"})

    assert result["success"] is False
    assert result["error_code"] == "tool_result_not_object"
    assert result["tool_id"] == "business_db"
    assert result["action"] == "read"
