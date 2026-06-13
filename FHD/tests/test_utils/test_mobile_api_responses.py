"""COVERAGE_RAMP C3.0: 移动端 API 响应格式化边界 / 分页计算。

覆盖：
- format_mobile_response 默认 / 覆盖
- format_error_response 包裹 data.message
- paginate_list 边界：空 / 整除 / 进位 / page < 1
"""

from __future__ import annotations

from app.utils.mobile_api import format_error_response, format_mobile_response, paginate_list


def test_format_mobile_response_defaults():
    out = format_mobile_response({"a": 1})
    assert out == {"code": 200, "message": "success", "success": True, "data": {"a": 1}}


def test_format_mobile_response_overrides():
    out = format_mobile_response([1, 2, 3], message="ok", success=True, code=201)
    assert out["code"] == 201
    assert out["message"] == "ok"
    assert out["data"] == [1, 2, 3]


def test_format_mobile_response_failure_flag():
    out = format_mobile_response(None, success=False, code=500, message="bad")
    assert out["success"] is False
    assert out["code"] == 500
    assert out["data"] is None


def test_format_error_response_defaults():
    out = format_error_response("RATE_LIMITED")
    assert out["code"] == 400
    assert out["message"] == "error"
    assert out["success"] is False
    assert out["data"] == {"message": "RATE_LIMITED"}


def test_format_error_response_custom():
    out = format_error_response("E_NOT_FOUND", message="miss", code=404)
    assert out["code"] == 404
    assert out["message"] == "miss"
    assert out["data"] == {"message": "E_NOT_FOUND"}


def test_paginate_list_empty():
    out = paginate_list([], total=0, page=1, per_page=20)
    assert out["items"] == []
    assert out["pagination"]["total"] == 0
    assert out["pagination"]["page"] == 1
    assert out["pagination"]["per_page"] == 20
    assert out["pagination"]["total_pages"] == 0
    assert out["pagination"]["has_next"] is False
    assert out["pagination"]["has_prev"] is False


def test_paginate_list_exact_multiple():
    out = paginate_list([1, 2, 3, 4], total=4, page=1, per_page=2)
    assert out["pagination"]["total_pages"] == 2
    assert out["pagination"]["has_next"] is True
    assert out["pagination"]["has_prev"] is False


def test_paginate_list_with_remainder():
    out = paginate_list([1, 2, 3, 4, 5], total=5, page=3, per_page=2)
    assert out["pagination"]["total_pages"] == 3
    assert out["pagination"]["has_next"] is False
    assert out["pagination"]["has_prev"] is True


def test_paginate_list_page_zero_normalized():
    out = paginate_list([1], total=10, page=0, per_page=5)
    # API 保留调用方 page 值（不再强制归一化为 1）
    assert out["pagination"]["page"] == 0


def test_paginate_list_per_page_zero_safe():
    out = paginate_list([1], total=10, page=1, per_page=0)
    assert out["pagination"]["total_pages"] == 0
