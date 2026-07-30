from __future__ import annotations

from app.application.agent_orchestrator.orchestration_evidence import (
    build_orchestration_evidence,
)


def test_database_read_names_runtime_database_tables_and_count() -> None:
    evidence = build_orchestration_evidence(
        "business_db",
        "read",
        {"entity": "products", "keyword": "XG-5003"},
        {"success": True, "data": [{"id": 7, "model_number": "XG-5003"}]},
    )

    assert evidence["kind"] == "database_read"
    assert evidence["databases"][0]["database_id"] == "products.db"
    assert evidence["databases"][0]["tables"] == "products"
    assert evidence["result_count"] == 1
    assert "database_url" not in evidence


def test_product_write_projects_added_record_and_malformed_counts_safely() -> None:
    evidence = build_orchestration_evidence(
        "business_db",
        "write",
        {
            "entity": "products",
            "operation": "create",
            "payload": {
                "model_number": "XG-5003",
                "product_name": "测试产品",
                "unit": "个",
            },
        },
        {"success": True, "created": True},
    )

    change = evidence["changes"][0]
    assert evidence["kind"] == "database_write"
    assert change["counts"] == {"created": 1, "updated": 0, "deleted": 0}
    assert change["items"][0]["change_type"] == "added"
    assert change["items"][0]["model_number"] == "XG-5003"


def test_product_update_and_delete_keep_specific_records_visible() -> None:
    update = build_orchestration_evidence(
        "products",
        "update",
        {"id": 7, "model_number": "XG-5003", "price": 12.5},
        {
            "success": True,
            "before": {"id": 7, "price": 10},
            "after": {"id": 7, "price": 12.5},
        },
    )
    delete = build_orchestration_evidence(
        "products",
        "delete",
        {"id": 8, "model_number": "XG-5004"},
        {"success": True},
    )

    assert update["changes"][0]["items"][0]["change_type"] == "updated"
    assert update["changes"][0]["field_changes"] == [
        {"field": "price", "before": "10", "after": "12.5"},
    ]
    assert delete["changes"][0]["items"][0]["change_type"] == "deleted"
    assert delete["changes"][0]["items"][0]["model_number"] == "XG-5004"


def test_employee_and_print_steps_explain_dependencies() -> None:
    employee = build_orchestration_evidence(
        "employee",
        "execute",
        {"employee_id": "sales_assistant", "employee_name": "销售助理", "task": "整理客户报价"},
        {"success": True},
    )
    printing = build_orchestration_evidence(
        "print",
        "workflow_label_dispatch",
        {"model_number": "XG-5003", "quantity": 3, "printer_name": "办公室标签机"},
        {"success": True, "job_id": "job-1"},
    )

    assert employee["kind"] == "employee"
    assert employee["employees"][0]["employee_name"] == "销售助理"
    assert printing["kind"] == "print"
    assert printing["databases"][0]["runtime_database"] == "products.db"
    assert printing["print"]["copies"] == 3
    assert printing["print"]["job_id"] == "job-1"
