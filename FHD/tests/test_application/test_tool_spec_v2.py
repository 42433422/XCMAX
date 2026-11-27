from __future__ import annotations

from time import perf_counter
from unittest.mock import patch

import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import (
    _string_constraint_error,
    build_tool_specs_v2,
    get_tool_action_spec,
    validate_tool_call,
    validate_tool_result,
    validate_tool_spec_fixtures,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("customer", [{"customer_id": 1}, {"customer_name": "客户甲"}])
def test_quote_contract_accepts_name_or_id_and_rejects_missing_price(customer):
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    params = {**customer, "items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
    assert validate_tool_call("sales", "quote", params).ok
    assert resolve_registered_capability_call(
        {"tool_id": "sales", "action": "quote", "params": params}
    )["success"]
    del params["items"][0]["unit_price"]
    assert not validate_tool_call("sales", "quote", params).ok
    assert not resolve_registered_capability_call(
        {"tool_id": "sales", "action": "quote", "params": params}
    )["success"]


def test_quote_requires_customer_even_when_details_are_complete():
    params = {"items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
    assert not validate_tool_call("sales", "quote", params).ok


@pytest.mark.parametrize("action,key", [("preview", "file_paths"), ("execute", "run_ids")])
def test_etl_batch_arrays_reject_overflow_without_silently_dropping_work(action, key):
    from copy import deepcopy

    params = {key: [f"f{i}.xlsx" for i in range(60)]}
    if action == "execute":
        params["preview_revisions"] = dict.fromkeys(params[key], "a" * 64)
    original = deepcopy(params)
    for options in ({}, {"allow_references_from": set()}):
        validation = validate_tool_call("elt_import", action, params, **options)
        assert not validation.ok and validation.error_code == "schema_validation_failed"
        assert "数量超限" in validation.message
        assert params == original


@pytest.mark.parametrize(
    "params, accepted",
    [
        ({"model_number": "A100", "warehouse_name": "主仓库", "quantity": 50}, True),
        ({"product_id": 1, "warehouse_id": 2, "quantity": 50}, True),
        ({"model_number": "A100", "quantity": 50}, False),
        ({"model_number": "A100", "warehouse_name": "主仓库", "quantity": -50}, False),
    ],
)
def test_stock_in_contract_requires_destination_and_valid_quantity(params, accepted):
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    assert validate_tool_call("inventory", "stock_in", params).ok is accepted
    assert (
        resolve_registered_capability_call(
            {"tool_id": "inventory", "action": "stock_in", "params": params}
        )["success"]
        is accepted
    )


@pytest.mark.parametrize(
    "action, read_only, permission",
    [
        ("query", True, "dataset.read"),
        ("ingest_document", False, "dataset.write"),
        ("clear_dataset", False, "dataset.write"),
        ("delete_document", False, "dataset.write"),
        ("rollback_version", False, "dataset.write"),
        ("update_document_acl", False, "dataset.write"),
        ("rebuild_index", False, "dataset.write"),
    ],
)
def test_dataset_query_read_only_contract_comes_from_authoritative_registry(
    action, read_only, permission
):
    from app.services.tools_execution.registry import get_workflow_tool_registry

    metadata = get_workflow_tool_registry()["dataset_rag"]["actions"][action]
    spec = get_tool_action_spec("dataset_rag", action)
    assert spec is not None
    assert (metadata.get("read_only") is True) is read_only
    assert spec.read_only is read_only
    assert spec.permission == permission
    assert spec.risk == metadata["risk"]
    assert spec.idempotent is metadata["idempotent"]


def test_build_tool_specs_v2_exposes_business_db_and_employee_contracts() -> None:
    specs = build_tool_specs_v2()

    def contract(tool, action, risk):
        spec = specs[(tool, action)]
        assert spec.risk == risk, (tool, action)
        return spec

    # Only actions whose implementation cannot publish or persist output may
    # use the explicit read-only result contract. Analyzer accepts output_json;
    # OCR request publishes an event, so neither inherits its read siblings.
    for tool, actions in {
        "materials": ("list", "query"),
        "template_extract": ("extract", "view"),
        "excel_toolkit": ("view", "merged", "styles", "structure"),
        "ocr": ("recognize", "extract", "analyze", "recognize_and_extract"),
    }.items():
        assert all(specs[(tool, action)].read_only for action in actions)
    for tool, action in (
        ("ocr", "request"),
        ("excel_analyzer", "analyze"),
        ("materials", "create"),
        ("document_template", "create"),
        ("generate_office_document", "execute"),
    ):
        assert specs[(tool, action)].read_only is False

    read_spec = contract("business_db", "read", "low")
    assert read_spec.read_only is True
    assert read_spec.idempotent is True
    assert read_spec.required_params == ["entity"]
    assert read_spec.input_schema["required"] == ["entity"]
    assert read_spec.permission == "business_db.read"

    write_spec = contract("business_db", "write", "medium")
    assert write_spec.read_only is False
    assert write_spec.idempotent is False
    assert write_spec.input_schema["properties"]["payload"]["type"] == "object"

    employee_spec = contract("employee", "execute", "medium")
    assert employee_spec.permission == "employee.execute"
    assert "task" in employee_spec.required_params
    assert employee_spec.output_schema["required"] == ["success", "message", "data"]
    assert employee_spec.test_fixtures[0]["input"]["task"] == "Prepare a quote"

    customer_update_spec = contract("customers", "update", "medium")
    assert customer_update_spec.required_params == ["id"]
    assert customer_update_spec.input_schema["required"] == ["id"]
    assert customer_update_spec.test_fixtures[0]["input"]["id"] == 7

    customer_delete_spec = contract("customers", "delete", "high")
    assert customer_delete_spec.permission == "customer.edit"

    customer_batch_spec = contract("customers", "batch_delete", "high")
    assert customer_batch_spec.input_schema["required"] == ["ids"]
    assert customer_batch_spec.test_fixtures[0]["output"]["deleted"] == 2

    product_update_spec = contract("products", "update", "medium")
    assert product_update_spec.required_params == ["id"]
    assert product_update_spec.input_schema["required"] == ["id"]
    assert product_update_spec.test_fixtures[0]["input"]["id"] == 7

    product_delete_spec = contract("products", "delete", "high")
    assert product_delete_spec.permission == "product.edit"

    product_batch_spec = contract("products", "batch_create", "high")
    assert product_batch_spec.input_schema["required"] == ["products"]
    assert product_batch_spec.test_fixtures[0]["output"]["data"]["success_count"] == 1

    print_event_spec = contract("business_event", "print_label", "high")
    assert print_event_spec.idempotent is False
    assert print_event_spec.required_params == ["document_name"]
    assert print_event_spec.output_schema["required"] == ["success", "job_id", "event"]

    inventory_event_spec = contract("business_event", "inventory_update", "high")
    assert inventory_event_spec.input_schema["required"] == ["product_id"]
    assert inventory_event_spec.test_fixtures[0]["output"]["event"] == "inventory.changed"

    stock_in_spec = contract("inventory", "stock_in", "high")
    assert stock_in_spec.input_schema["required"] == ["quantity"]
    assert stock_in_spec.test_fixtures[0]["output"]["data"]["transaction_type"] == "in"

    warehouse_delete_spec = contract("inventory", "delete_warehouse", "high")
    assert warehouse_delete_spec.permission == "tool.inventory.delete_warehouse"

    purchase_approve_spec = contract("purchase", "approve_order", "high")
    assert purchase_approve_spec.required_params == ["order_id"]
    assert purchase_approve_spec.permission == "tool.purchase.approve_order"
    assert purchase_approve_spec.test_fixtures[0]["input"]["approver"] == "manager"

    purchase_inbound_spec = contract("purchase", "create_inbound", "high")
    assert purchase_inbound_spec.input_schema["properties"]["items"]["type"] == "array"
    assert purchase_inbound_spec.test_fixtures[0]["output"]["data"]["order_id"] == 9

    finance_create_spec = contract("finance", "create_transaction", "high")
    assert finance_create_spec.required_params == ["transaction_type", "amount"]
    assert finance_create_spec.input_schema["required"] == ["transaction_type", "amount"]
    assert finance_create_spec.test_fixtures[0]["input"]["transaction_type"] == "expense"

    finance_delete_spec = contract("finance", "delete_transaction", "high")
    assert finance_delete_spec.permission == "tool.finance.delete_transaction"
    assert finance_delete_spec.test_fixtures[0]["input"]["transaction_id"] == 31

    assert specs[("shipment_orders", "generate")].permission == "shipment.create"
    shipment_create_spec = contract("shipment_records", "create", "high")
    assert shipment_create_spec.required_params == ["unit_name"]
    assert len(shipment_create_spec.input_schema["allOf"]) == 2
    assert shipment_create_spec.test_fixtures[0]["output"]["data"]["id"] == 7

    shipment_update_spec = contract("shipment_records", "update", "medium")
    assert shipment_update_spec.permission == "shipment.edit"
    assert shipment_update_spec.receipt_permission == "tool.shipment_records.update"

    shipment_delete_spec = contract("shipment_records", "delete", "high")
    assert shipment_delete_spec.test_fixtures[0]["output"]["deleted_count"] == 1

    shipment_order_generate_spec = contract("shipment_orders", "generate", "high")
    assert shipment_order_generate_spec.permission == "shipment.create"
    assert shipment_order_generate_spec.required_params == ["unit_name", "products"]
    assert shipment_order_generate_spec.input_schema["required"] == ["unit_name", "products"]
    assert shipment_order_generate_spec.test_fixtures[0]["output"]["record_id"] == 7

    shipment_order_batch_spec = contract("shipment_orders", "generate_batch", "high")
    assert shipment_order_batch_spec.input_schema["required"] == ["shipments"]
    assert shipment_order_batch_spec.output_schema["required"] == ["success", "data"]

    shipment_order_print_spec = contract("shipment_orders", "print", "high")
    assert shipment_order_print_spec.permission == "shipment.edit"
    assert shipment_order_print_spec.receipt_permission == "tool.shipment_orders.print"
    assert shipment_order_print_spec.output_schema["required"] == [
        "success",
        "file_path",
        "updated",
    ]

    shipment_order_clear_spec = contract("shipment_orders", "clear_shipment", "high")
    assert shipment_order_clear_spec.required_params == ["purchase_unit"]
    assert shipment_order_clear_spec.input_schema["required"] == ["purchase_unit"]
    assert shipment_order_clear_spec.test_fixtures[0]["output"]["cleared_count"] == 3

    shipment_order_set_sequence_spec = contract("shipment_orders", "set_sequence", "high")
    assert shipment_order_set_sequence_spec.required_params == ["sequence"]
    assert shipment_order_set_sequence_spec.test_fixtures[0]["input"]["sequence"] == 12

    shipment_order_reset_sequence_spec = contract("shipment_orders", "reset_sequence", "high")
    assert shipment_order_reset_sequence_spec.required_params == []
    assert shipment_order_reset_sequence_spec.test_fixtures[0]["output"]["sequence"] == 1

    shipment_order_clear_all_spec = contract("shipment_orders", "clear_all", "high")
    assert shipment_order_clear_all_spec.permission == "shipment.edit"
    assert shipment_order_clear_all_spec.receipt_permission == "tool.shipment_orders.clear_all"
    assert shipment_order_clear_all_spec.test_fixtures[0]["output"]["deleted_count"] == 5

    shipment_order_delete_spec = contract("shipment_orders", "delete", "high")
    assert shipment_order_delete_spec.input_schema["required"] == ["id"]
    assert shipment_order_delete_spec.test_fixtures[0]["output"]["deleted_id"] == 7

    products_batch_delete_spec = contract("products", "batch_delete", "high")
    assert products_batch_delete_spec.required_params == ["ids"]
    assert products_batch_delete_spec.input_schema["required"] == ["ids"]
    assert products_batch_delete_spec.test_fixtures[0]["output"]["deleted"] == 2

    print_document_spec = contract("print", "print_document", "high")
    assert print_document_spec.required_params == ["file_path"]
    assert print_document_spec.permission == "print.label"
    assert print_document_spec.test_fixtures[0]["input"]["printer_name"] == "DocPrinter"

    print_label_spec = contract("print", "print_label", "high")
    assert print_label_spec.input_schema["required"] == ["file_path"]
    assert print_label_spec.test_fixtures[0]["output"]["require_confirm"] is False

    print_test_spec = contract("print", "test", "medium")
    assert print_test_spec.required_params == ["printer_name"]
    assert print_test_spec.test_fixtures[0]["output"]["printer_name"] == "DocPrinter"

    print_selection_spec = contract("print", "save_printer_selection", "medium")
    assert print_selection_spec.permission == "print.label"
    assert print_selection_spec.test_fixtures[0]["output"]["document_printer"] == "DocPrinter"

    print_workflow_spec = contract("print", "workflow_label_dispatch", "high")
    assert print_workflow_spec.required_params == ["model_number"]
    assert print_workflow_spec.input_schema["required"] == ["model_number"]
    assert print_workflow_spec.test_fixtures[0]["input"]["quantity"] == 2

    shipment_event_spec = contract("business_event", "shipment_create", "high")
    assert shipment_event_spec.output_schema["required"] == ["success", "event", "published"]
    assert shipment_event_spec.test_fixtures[0]["output"]["published"] is True

    printer_spec = contract("system_maintenance", "set_default_printer", "medium")
    assert printer_spec.idempotent is False
    assert printer_spec.required_params == ["printer_name"]
    assert printer_spec.input_schema["required"] == ["printer_name"]

    restore_spec = contract("system_maintenance", "restore_database", "high")
    assert restore_spec.required_params == ["backup_file"]
    assert restore_spec.timeout_seconds == 120
    assert restore_spec.test_fixtures[0]["input"]["backup_file"] == "backup.sql"

    invalidate_spec = contract("system_maintenance", "invalidate_performance_cache", "medium")
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
    assert document_spec.permission == "tool.generate_office_document.execute"
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
    assert index_spec.risk == "medium"
    assert index_spec.idempotent is True
    assert index_spec.read_only is False
    assert index_spec.policy["requires_write_approval"] is True
    assert index_spec.policy["data_scope"] == "legacy_global"
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
    assert chat_spec.required_params == ["message", "request_id"]

    click = specs[("aiopen", "ui_click")]
    assert click.risk == "high" and click.idempotent is False and click.read_only is False
    snapshot = specs[("aiopen", "ui_snapshot")]
    assert snapshot.risk == "low" and snapshot.idempotent is True and snapshot.read_only is True

    valid_ui_type = validate_tool_call(
        "aiopen",
        "ui_type",
        {"session_id": "screen-session-1", "selector": "#message", "text": "hello"},
    )
    assert valid_ui_type.ok is True

    invalid_ui_type = validate_tool_call("aiopen", "ui_type", {"selector": "#message"})
    assert invalid_ui_type.ok is False
    assert invalid_ui_type.error_code == "schema_validation_failed"
    assert "text" in invalid_ui_type.message

    upload = specs[("aiopen", "ui_upload")].contract_samples[0]["input"]
    assert upload["files"][0] == {
        "name": "sample.txt",
        "text": "AIOPEN upload sample",
        "type": "text/plain",
    }
    assert validate_tool_call("aiopen", "ui_upload", upload).ok
    invalid_upload = validate_tool_call(
        "aiopen", "ui_upload", {"session_id": "screen-session-1", "files": [{"text": "sample"}]}
    )
    assert not invalid_upload.ok
    assert "name" in invalid_upload.message


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


@pytest.mark.parametrize(
    "payload, accepted",
    [
        ({"success": False, "message": "temporary database error"}, True),
        ({"success": True, "data": []}, True),
        ({"success": True, "data": {}}, False),
        ({"success": True, "data": None}, False),
        ({"success": True}, False),
    ],
)
def test_business_read_empty_data_is_present_but_still_typed(payload, accepted):
    assert validate_tool_result("business_db", "read", payload).ok is accepted


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


def test_agent_tool_executor_rejects_non_object_tool_result(trusted_actor, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["product.view"])
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
        result = AgentToolExecutor().execute(
            step, runtime_context={**actor.context, "run_id": "run_1"}
        )

    assert result["success"] is False
    assert result["error_code"] == "tool_result_not_object"
    assert result["tool_id"] == "business_db"
    assert result["action"] == "read"


@pytest.mark.parametrize(
    "mutation, uncertainty, unknown_io",
    [
        (False, {}, False),
        (False, {"outcome": "unknown"}, False),
        (False, {"requires_reconciliation": True}, False),
        (False, {"execution_status": "timeout"}, False),
        (False, {"outcome_unknown": True}, False),
        (False, {"error_code": "upstream_outcome_unknown"}, False),
        (False, {"result": {"status": "accepted"}}, False),
        (False, {}, True),
        (True, {}, False),
    ],
)
def test_schema_failure_only_releases_a_certain_read_claim(
    monkeypatch, tmp_path, trusted_actor, mutation, uncertainty, unknown_io
):
    import time
    from types import SimpleNamespace

    from app.application.agent_orchestrator import tool_permission
    from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline
    from app.application.tool_execution_deadline import invocation_deadline

    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)
    step = AgentStep(
        node_id="schema-contract",
        tool_id="generate_office_document" if mutation else "business_db",
        action="execute" if mutation else "read",
        params={"user_request": "Create a contract", "output_format": "docx"}
        if mutation
        else {"entity": "products"},
    )
    context = {"task_id": "schema-contract", "idempotency_key": "original-call"}
    if not mutation:
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
        context.update(trusted_actor(permissions=["product.view"]).context)
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    unknown = mutation or bool(uncertainty) or unknown_io
    raw_output = {"success": True, **uncertainty}

    def output(*_args):
        if unknown_io:
            with invocation_deadline(time.monotonic() + 60) as budget:
                budget.uncertain.append({"kind": "http_timeout", "method": "GET"})
        return raw_output

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=output,
    ) as dispatch:
        result = execute_with_tool_deadline(
            executor, step, runtime_context=context, timeout_seconds=60
        )
        evidence = result.get("reconciliation_evidence", result)
        assert evidence["error_code"] == "output_schema_validation_failed"
        assert evidence["raw_error_code"] == raw_output.get("error_code")
        assert result["success"] is False
        if unknown_io:
            assert result["error_code"] == "tool_timeout_unknown"
            assert result["io_reconciliation"] == [{"kind": "http_timeout", "method": "GET"}]
        elif not unknown:
            assert "reconciliation_evidence" not in result
        if unknown:
            assert result["outcome"] == "unknown" and result["retryable"] is False
            assert result["reconciliation_required"] is True
            if not unknown_io:
                assert result["error_code"] == "output_schema_validation_failed"
            tool_permission.drop_process_idempotency_memory()
            replay = execute_with_tool_deadline(
                executor, step, runtime_context=context, timeout_seconds=60
            )
            assert replay["outcome"] == "unknown" and replay["retryable"] is False
            assert replay["reconciliation_required"] is True
            assert replay["error_code"] == "output_schema_validation_failed"
            assert replay["raw_error_code"] == evidence["raw_error_code"]
            assert replay.get("reconciliation_evidence", replay) == evidence
        else:
            assert result["message"] == "工具输出 缺少字段：data"
            assert not result.get("reconciliation_required") and result.get("outcome") != "unknown"
        dispatch.assert_called_once()


@pytest.mark.parametrize(
    "value, valid",
    [
        ("a@b.c", True),
        ("first+tag@example.co.uk", True),
        ("a@b..c", True),
        ("@b.c", False),
        ("a@.c", False),
        ("a@b.", False),
        ("a@b", False),
        ("a@@b.c", False),
        ("a b@c.d", False),
        ("a@b.c\n", False),
    ],
)
def test_email_contract_keeps_validation_semantics(value, valid):
    assert (_string_constraint_error("email", value, {"format": "email"}) == "") is valid


def test_required_empty_array_is_present_and_a_missing_key_is_not():
    from app.application.agent_orchestrator.tool_spec import _validate_schema_payload

    schema = {
        "type": "object",
        "required": ["rows"],
        "properties": {"rows": {"type": "array", "items": {"type": "object"}}},
    }
    ok, message = _validate_schema_payload(schema, {"rows": []}, subject="LLM 输出")
    assert ok and message == ""
    ok, message = _validate_schema_payload(schema, {}, subject="LLM 输出")
    assert not ok and message == "LLM 输出 缺少字段：rows"


def test_finance_reference_id_accepts_the_numeric_order_id():
    params = {
        "transaction_type": "receivable",
        "amount": 200,
        "reference_type": "sales_order",
        "reference_id": 3,
    }
    result = validate_tool_call("finance", "create_transaction", params)
    assert result.ok, result.message


def test_email_contract_rejects_long_invalid_input_without_backtracking():
    started = perf_counter()
    assert _string_constraint_error("email", "x@" + "!" * 50_000, {"format": "email"})
    assert perf_counter() - started < 1


def test_materials_permissions_use_business_codes(monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert get_tool_action_spec("materials", "list").permission == "material.view"
    assert get_tool_action_spec("materials", "query").permission == "material.view"
    assert get_tool_action_spec("materials", "batch_delete").permission == "material.edit"


def test_template_permissions_use_elt_codes(monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert get_tool_action_spec("template_preview", "list").permission == "elt.read"
    assert get_tool_action_spec("template_preview", "create").permission == "elt.template.manage"
    assert get_tool_action_spec("document_template", "delete").permission == "elt.template.manage"
    assert get_tool_action_spec("document_template", "clear").permission == "elt.template.manage"


def test_template_permissions_match_seeded_elt_codes(monkeypatch):
    """模板工具声明的权限必须真实存在于种子权限，否则改名后无人能通过鉴权。"""
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    from app.db.models.permission import DEFAULT_PERMISSIONS

    seeded = {item["code"] for item in DEFAULT_PERMISSIONS}
    for tool_id, action in (
        ("template_preview", "list"),
        ("template_preview", "create"),
        ("document_template", "delete"),
        ("document_template", "clear"),
    ):
        assert get_tool_action_spec(tool_id, action).permission in seeded


def test_business_clear_permissions_use_edit_codes(monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert get_tool_action_spec("customers", "clear").permission == "customer.edit"
    assert get_tool_action_spec("products", "clear").permission == "product.edit"
    assert get_tool_action_spec("materials", "clear").permission == "material.edit"
    assert get_tool_action_spec("shipment_records", "clear").permission == "shipment.edit"
    assert get_tool_action_spec("customers", "clear").input_schema["required"] == []


def test_business_db_read_materials_accepts_material_view(trusted_actor, monkeypatch):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["material.view"])

    allowed = actor_tool_denial("business_db", "read", actor.context, {"entity": "materials"})
    denied = actor_tool_denial("business_db", "read", actor.context, {"entity": "customers"})

    assert allowed is None
    assert denied is not None and denied["error_code"] == "tool_permission_denied"


def test_shipment_order_generate_keeps_owned_tenant_authority(trusted_actor, monkeypatch):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    spec = get_tool_action_spec("shipment_orders", "generate")
    assert spec.permission == "shipment.create"
    assert spec.policy.get("data_scope") != "legacy_global"
    actor = trusted_actor(permissions=["shipment.create"])
    assert actor_tool_denial("shipment_orders", "generate", actor.context, {}) is None
    viewer = trusted_actor(permissions=["shipment.view"], role="viewer")
    denied = actor_tool_denial("shipment_orders", "generate", viewer.context, {})
    assert denied is not None and denied["reason"] == "permission_denied"


@pytest.mark.parametrize(
    "tool_id,action,permission",
    [
        ("shipment_records", "create", "shipment.edit"),
        ("shipment_records", "update", "shipment.edit"),
        ("shipment_records", "delete", "shipment.edit"),
        ("shipment_orders", "generate", "shipment.create"),
        ("shipment_orders", "generate_batch", "shipment.create"),
        ("shipment_orders", "print", "shipment.edit"),
        ("shipment_orders", "clear_shipment", "shipment.edit"),
        ("shipment_orders", "set_sequence", "shipment.edit"),
        ("shipment_orders", "reset_sequence", "shipment.edit"),
        ("shipment_orders", "clear_all", "shipment.edit"),
        ("shipment_orders", "delete", "shipment.edit"),
    ],
)
def test_shipment_action_permissions_use_the_live_seeded_business_grant(
    trusted_actor, monkeypatch, tool_id, action, permission
):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.db.models.permission import DEFAULT_PERMISSIONS
    from app.services.tools_execution.registry import get_workflow_tool_registry

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert permission in {row["code"] for row in DEFAULT_PERMISSIONS}
    assert get_workflow_tool_registry()[tool_id]["actions"][action]["permission"] == permission
    assert get_tool_action_spec(tool_id, action).permission == permission
    editor = trusted_actor(permissions=[permission])
    viewer = trusted_actor(role="viewer", permissions=["shipment.view"])
    assert actor_tool_denial(tool_id, action, editor.context, {}) is None
    denial = actor_tool_denial(tool_id, action, viewer.context, {})
    assert denial is not None and denial["reason"] == "permission_denied"
