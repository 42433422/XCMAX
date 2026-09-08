import pytest

from scripts.dev.task_benchmark_assertions import check_returned_records


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
