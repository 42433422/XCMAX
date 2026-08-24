"""P1 行为契约测试：conversation helpers + compat_db + app_service helpers。

B2 转正（2026-08-24，见 docs/coverage-ramp-retirement-plan.md）：原
``test_coverage_ramp_phase1_p1_helpers_services.py`` 断言为真实行为契约
（SSE 格式、session/message 序列化、SQL builder、compat_db 解析），
仅因文件名前缀被误归入 ``coverage_ramp`` marker，现改名脱离该 marker，
计入行为覆盖率口径。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.fastapi_routes.domains.conversation.helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _extract_excel_paths_from_context,
    _extract_excel_paths_from_message,
    _looks_like_vector_request,
    _merge_runtime_context_with_message_paths,
    _sse_event_line,
    _thinking_steps_from_planner_stream_text,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_stream_first_token_timeout_seconds,
    _xcagi_stream_idle_notice_seconds,
)
from app.fastapi_routes.domains.misc.helpers import (
    _dispatch_tool_for_approval,
    _http_exception_to_json,
    _message_to_dict,
    _require_login_user,
    _session_to_dict,
)
from app.infrastructure.persistence.compat_db.base import (
    _customer_body_name_contact,
    _exc_chain_has_undefined_table,
    _pg_expr_norm_unit,
    _product_parse_id,
    _product_parse_is_active,
    _product_parse_quantity,
    _sql_delete_where,
    _sql_update_set_where,
    _validate_order_clause,
)


def _http_request(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": hdrs,
        "query_string": b"",
        "client": ("127.0.0.1", 8080),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# conversation helpers (extended)
# ---------------------------------------------------------------------------


def test_xcagi_compat_chat_body_aliases() -> None:
    body = XcagiCompatChatBody.model_validate({"content": "hello"})
    assert body.message == "hello"
    batch = XcagiCompatChatBatchBody.model_validate({"messages": ["a", "b"]})
    assert len(batch.messages) == 2


def test_extract_excel_paths_from_message() -> None:
    paths = _extract_excel_paths_from_message("请分析 @报价单.xlsx 和 清单.xls")
    assert any(p.endswith(".xlsx") for p in paths)


def test_extract_excel_paths_from_context() -> None:
    # 契约：从 excel_file_path / excel_file_paths 键提取，去重且只收 Excel 后缀
    ctx = {"excel_file_path": "/tmp/a.xlsx", "excel_file_paths": ["/tmp/b.xls", "/tmp/a.xlsx"]}
    paths = _extract_excel_paths_from_context(ctx)
    assert paths == ["/tmp/a.xlsx", "/tmp/b.xls"]
    # 非 Excel 路径与空上下文不产出
    assert _extract_excel_paths_from_context({"excel_file_path": "/tmp/readme.txt"}) == []
    assert _extract_excel_paths_from_context({}) == []


def test_merge_runtime_context_with_message_paths() -> None:
    merged, found = _merge_runtime_context_with_message_paths({"foo": 1}, "打开 数据.xlsx")
    assert merged.get("foo") == 1
    assert isinstance(found, list)


def test_looks_like_vector_request() -> None:
    assert _looks_like_vector_request("向量检索产品") is True
    assert _looks_like_vector_request("你好") is False


def test_xcagi_timeout_helpers() -> None:
    assert _xcagi_chat_timeout_seconds() > 0
    assert _xcagi_stream_first_token_timeout_seconds() > 0
    assert _xcagi_stream_idle_notice_seconds() > 0
    payload = _xcagi_chat_timeout_error_payload(30.0)
    assert payload["success"] is False


def test_sse_event_line() -> None:
    line = _sse_event_line({"event": "token", "data": "hi"})
    assert line.startswith(b"data:")


def test_thinking_steps_from_planner_stream_text() -> None:
    text = 'data: {"type":"thinking","content":"step1"}\n\n'
    # thinking 类型事件由专用解析路径处理，通用提取返回 None
    assert _thinking_steps_from_planner_stream_text(text) is None


def test_xcagi_compat_reply_plain_text() -> None:
    out = _xcagi_compat_reply_payload("回复文本")
    assert out["success"] is True
    assert out["response"] == "回复文本"


def test_xcagi_compat_reply_dict() -> None:
    out = _xcagi_compat_reply_payload({"response": "dict回复", "thinking_steps": "s1"})
    assert out["data"]["thinking_steps"] == "s1"


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------


def test_session_to_dict_variants() -> None:
    d = _session_to_dict({"session_id": "s1", "title": "T"})
    assert d["session_id"] == "s1"
    tup = _session_to_dict(("x", "s2", 1, "标题", "", 0, None, None))
    assert tup["session_id"] == "s2"
    obj = SimpleNamespace(
        session_id="s3",
        user_id=2,
        title="",
        summary="",
        message_count=1,
        last_message_at=None,
        created_at=None,
    )
    assert _session_to_dict(obj)["session_id"] == "s3"


def test_message_to_dict_variants() -> None:
    d = _message_to_dict({"id": 1, "role": "user", "content": "hi"})
    assert d["role"] == "user"
    tup = _message_to_dict((1, "s", 1, "assistant", "ok", "", "", None))
    assert tup["role"] == "assistant"


def test_http_exception_to_json() -> None:
    exc = HTTPException(status_code=401, detail={"message": "未登录"})
    resp = _http_exception_to_json(exc)
    assert resp.status_code == 401


def test_require_login_user_authenticated() -> None:
    req = _http_request()
    with patch(
        "app.fastapi_routes.domains.misc.helpers.resolve_session_user",
        return_value=SimpleNamespace(id=1),
    ):
        user, err = _require_login_user(req)
    assert user is not None
    assert err is None


@patch("app.application.facades.tools_facade.execute_registered_workflow_tool")
def test_dispatch_tool_for_approval(mock_exec: MagicMock) -> None:
    mock_exec.return_value = {"success": True}
    out = _dispatch_tool_for_approval(tool_id="t1", action="run", params={})
    assert out["success"] is True


# ---------------------------------------------------------------------------
# compat_db extended
# ---------------------------------------------------------------------------


def test_customer_body_name_contact() -> None:
    name, contact, phone, addr = _customer_body_name_contact(
        {"name": "甲", "contact_person": "张", "contact_phone": "1", "address": "成都"}
    )
    assert name == "甲"
    assert contact == "张"


def test_sql_builder_helpers() -> None:
    assert "DELETE" in _sql_delete_where("customers", "id = 1")
    assert "UPDATE" in _sql_update_set_where("products", "name = 'x'", "id = 1")


def test_pg_expr_norm_unit() -> None:
    expr = _pg_expr_norm_unit('"unit"')
    assert "unit" in expr.lower()


def test_exc_chain_has_undefined_table() -> None:
    # 仅当异常链中存在类名为 UndefinedTable 的异常时返回 True
    class UndefinedTable(Exception):
        pass

    chained = RuntimeError("wrapper")
    chained.__cause__ = UndefinedTable("relation missing")
    assert _exc_chain_has_undefined_table(chained) is True
    assert _exc_chain_has_undefined_table(RuntimeError("other")) is False


def test_validate_order_desc_nulls() -> None:
    clause = _validate_order_clause('"created_at" DESC NULLS LAST')
    assert "DESC" in clause


def test_product_parse_edge_cases() -> None:
    assert _product_parse_id(None) is None
    assert _product_parse_quantity("abc") == 0
    assert _product_parse_is_active("true") is True
    assert _product_parse_is_active("0") is False


# ---------------------------------------------------------------------------
# approval_workspace app_service snippets
# ---------------------------------------------------------------------------


def test_approval_workspace_normalize_statuses() -> None:
    from app.application.approval_workspace_app_service import _normalize_statuses

    out = _normalize_statuses("approved,rejected")
    assert isinstance(out, list)


def test_surface_audit_service_helpers() -> None:
    from app.application.surface_audit_service import _today_key, list_configured_lanes

    assert len(_today_key()) == 10
    assert isinstance(list_configured_lanes(), list)
