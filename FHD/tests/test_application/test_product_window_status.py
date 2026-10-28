"""Product query receipts do not authorize edits or acknowledge a displayed UI."""

from unittest.mock import Mock

import pytest

from app.application.normal_chat.product_queries import product_window


@pytest.mark.parametrize(
    "failure",
    [
        {
            "success": False,
            "message": "synthetic permission denied",
            "error_code": "permission_denied",
            "data": [{"id": "synthetic-partial"}],
        },
        None,
        {},
        RuntimeError("synthetic unavailable"),
        {"success": True, "data": [None]},
    ],
)
def test_query_failure_never_becomes_window_success(failure):
    query = (
        Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    )
    result = product_window(
        {"intent": "product_query", "slots": {"keyword": "synthetic"}}, query, Mock()
    )
    assert result["success"] is False
    assert result["data"]["query_status"] == "failed"
    assert "autoAction" not in result
    assert "已帮你打开" not in result["response"]
    assert "查看和修改" not in result["response"]
    if isinstance(failure, dict) and failure.get("success") is False:
        assert result["data"]["query_receipt"] == failure
    query.assert_called_once_with("synthetic", 5)


@pytest.mark.parametrize(
    "rows", [[], [{"model_number": "SYNTHETIC-1", "name": "fixture", "price": 1.25}]]
)
def test_success_preserves_preview_and_only_requests_window(rows):
    query = Mock(return_value={"success": True, "data": rows})
    result = product_window(
        {"intent": "product_query", "slots": {"keyword": "synthetic"}}, query, Mock()
    )
    assert result["success"] is True
    assert result["data"]["query_status"] == "succeeded"
    assert result["data"]["window_status"] == "requested"
    assert result["autoAction"] == {
        "type": "show_products_float",
        "feature": "products",
        "query": "synthetic",
    }
    assert "已请求" in result["response"]
    assert "已帮你打开" not in result["response"]
    assert "修改" not in result["response"]
    if rows:
        assert "SYNTHETIC-1 / fixture / ￥1.25" in result["response"]
        assert "预览命中 1 条" in result["response"]
    else:
        assert "未找到匹配项" in result["response"]
    query.assert_called_once_with("synthetic", 5)
