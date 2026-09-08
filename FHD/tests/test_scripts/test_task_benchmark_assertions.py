import pytest

from scripts.dev.task_benchmark_assertions import check_returned_records


@pytest.mark.parametrize("amount, accepted", [(1099, True), (100, False)])
def test_spreadsheet_assertion_opens_file_and_checks_business_cells(
    tmp_path, monkeypatch, amount, accepted
):
    from io import BytesIO

    from openpyxl import Workbook

    from app.application.agent_orchestrator.artifact_files import store_spreadsheet
    from scripts.dev.task_benchmark_assertions import check_spreadsheets

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    workbook = Workbook()
    workbook.active.title = "sales"
    workbook.active.append(["product_name", "amount"])
    workbook.active.append(["测试产品", amount])
    stream = BytesIO()
    workbook.save(stream)
    artifact = store_spreadsheet("run_test", stream.getvalue())
    assertions = [
        {"sheet": "sales", "count": 1, "includes": [{"product_name": "测试产品", "amount": 1099}]}
    ]
    execution = {"run_id": "run_test", "artifacts": [artifact]}
    assert check_spreadsheets(execution, assertions)[0] is accepted
    assert (
        check_spreadsheets(
            execution, [{"sheet": "sales", "cells": {"A2": "测试产品", "B2": 1099}}]
        )[0]
        is accepted
    )
    assert check_spreadsheets(execution, [{"sheet": "sales", "cells": {"C99": 1099}}])[0] is False
    assert check_spreadsheets({"run_id": "run_test", "artifacts": []}, assertions)[0] is False


@pytest.mark.parametrize(
    "records, status, expected",
    [
        ([], "completed", False),
        ([{"customer_name": "错误客户"}], "completed", False),
        ([{"customer_name": "星光贸易"}], "failed", False),
        ([{"customer_name": "星光贸易"}, {"customer_name": "额外客户"}], "completed", False),
        ([{"customer_name": "星光贸易"}], "completed", True),
    ],
)
def test_lookup_requires_actual_completed_tool_output(records, status, expected):
    receipt = {
        "steps": [
            {
                "tool_id": "customers",
                "action": "query",
                "status": status,
                "output": {"success": True, "data": records},
            }
        ]
    }
    assertion = {
        "tool_id": "customers",
        "action": "query",
        "count": 1,
        "includes": [{"customer_name": "星光贸易"}],
    }
    assert check_returned_records(receipt, [assertion])[0] is expected


@pytest.mark.parametrize("value, accepted", [(0, False), (None, False), (True, False), (2, True)])
def test_report_metrics_must_match_seeded_values(value, accepted):
    execution = {
        "steps": [
            {
                "tool_id": "reports",
                "action": "dashboard",
                "status": "completed",
                "output": {"data": {"product_count": value}},
            }
        ]
    }
    assertions = [
        {
            "tool_id": "reports",
            "action": "dashboard",
            "path": ["data", "product_count"],
            "equals": 2,
        }
    ]
    assert check_returned_records(execution, assertions)[0] is accepted
