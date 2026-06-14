"""COVERAGE_RAMP Phase 56: persistence compat_db, extract_log, ai_chat helpers,
workflow types, conversation/misc helpers (mocked I/O)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from app.application.workflow.planner import get_tool_registry
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph
from app.fastapi_routes.domains.conversation.helpers import (
    XcagiCompatChatBody,
    _extract_excel_paths_from_message,
    _looks_like_vector_request,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _xcagi_chat_http_exc,
    _xcagi_compat_reply_payload,
)
from app.fastapi_routes.domains.misc.helpers import (
    _http_exception_to_json,
    _message_to_dict,
    _session_to_dict,
)
from app.infrastructure.persistence.compat_db.base import (
    _customer_body_name_contact,
    _exc_chain_has_undefined_table,
    _product_parse_id,
    _product_parse_is_active,
    _product_parse_quantity,
    _sql_ident,
    _sql_insert_returning,
    _sql_select_from_where,
    _sql_statement_timeout_ms,
    _validate_order_clause,
)
from app.infrastructure.persistence.extract_log_store_impl import SQLAlchemyExtractLogStore


def _http_request(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": hdrs,
        "query_string": b"",
        "client": ("10.0.0.1", 8080),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# compat_db/base helpers
# ---------------------------------------------------------------------------


def test_sql_ident_and_order_validation() -> None:
    assert '"products"' == _sql_ident("products")
    assert '"name" ASC' == _validate_order_clause("name ASC")
    with pytest.raises(ValueError, match="invalid ORDER BY"):
        _validate_order_clause("DROP TABLE users")


def test_product_parse_helpers() -> None:
    assert _product_parse_id("42") == 42
    assert _product_parse_id("0") is None
    assert _product_parse_quantity("3.5") == 3
    assert _product_parse_is_active("yes") is True
    assert _product_parse_is_active("off") is False


def test_customer_body_name_contact() -> None:
    name, cp, ph, addr = _customer_body_name_contact(
        {"unit_name": " 七彩 ", "contact_person": "张三", "address": "成都"}
    )
    assert name == "七彩"
    assert cp == "张三"
    assert addr == "成都"


def test_sql_builder_helpers() -> None:
    assert "SELECT id FROM products" in _sql_select_from_where("id", "products", "id=1")
    assert "INSERT INTO products" in _sql_insert_returning("products", "name", ":name")
    assert _sql_statement_timeout_ms(5000) == "SET statement_timeout TO 5000"


def test_exc_chain_has_undefined_table() -> None:
  class UndefinedTable(Exception):
      pass

  inner = UndefinedTable("missing")
  outer = RuntimeError("wrap")
  outer.__cause__ = inner
  assert _exc_chain_has_undefined_table(outer) is True
  assert _exc_chain_has_undefined_table(RuntimeError("x")) is False


# ---------------------------------------------------------------------------
# extract_log_store_impl (mocked DB)
# ---------------------------------------------------------------------------


def _fake_row(**kwargs):
    defaults = {
        "id": 1,
        "file_name": "demo.xlsx",
        "file_path": "/tmp/demo.xlsx",
        "data_type": "product",
        "total_rows": 10,
        "valid_rows": 8,
        "imported_rows": 7,
        "skipped_rows": 1,
        "failed_rows": 0,
        "status": "done",
        "error_message": None,
        "field_mapping": json.dumps({"a": "b"}),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@contextmanager
def _mock_db(*, fetchall=None, fetchone=None, lastrowid=99, rowcount=3):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall or []
    result.fetchone.return_value = fetchone
    result.lastrowid = lastrowid
    result.rowcount = rowcount
    db.execute.return_value = result

    @contextmanager
    def fake_get_db():
        yield db

    with patch("app.infrastructure.persistence.extract_log_store_impl.get_db", fake_get_db):
        yield db


def test_extract_log_find_all_paginated() -> None:
    rows = [_fake_row(id=i, file_name=f"f{i}.xlsx") for i in range(1, 4)]
    with _mock_db(fetchall=rows):
        out = SQLAlchemyExtractLogStore().find_all(page=1, per_page=2)
    assert out["success"] is True
    assert out["total"] == 3
    assert len(out["data"]) == 2


def test_extract_log_find_by_id() -> None:
    with _mock_db(fetchone=_fake_row()):
        row = SQLAlchemyExtractLogStore().find_by_id(1)
    assert row is not None
    assert row["file_name"] == "demo.xlsx"


def test_extract_log_create_and_delete() -> None:
    with _mock_db():
        created = SQLAlchemyExtractLogStore().create({"file_name": "n.xlsx", "data_type": "x"})
    assert created["success"] is True
    assert created["log_id"] == 99

    with _mock_db():
        deleted = SQLAlchemyExtractLogStore().delete(1)
    assert deleted["success"] is True


def test_extract_log_clear_old() -> None:
    with _mock_db(rowcount=5):
        out = SQLAlchemyExtractLogStore().clear_old(days=7)
    assert out["success"] is True
    assert out["deleted_count"] == 5


def test_extract_log_db_error_returns_failure() -> None:
    with patch(
        "app.infrastructure.persistence.extract_log_store_impl.get_db",
        side_effect=RuntimeError("db down"),
    ):
        out = SQLAlchemyExtractLogStore().find_all()
    assert out["success"] is False
    assert out["data"] == []


# ---------------------------------------------------------------------------
# ai_chat_app_service helpers
# ---------------------------------------------------------------------------


def test_skip_pro_excel_deterministic_import_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True
    assert _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True}) is False
    monkeypatch.setenv("XCAGI_EXCEL_IMPORT_AI_DECIDES", "1")
    assert _skip_pro_excel_deterministic_import({}) is True


def test_ai_chat_is_pro_source_and_merge_context() -> None:
    assert AIChatApplicationService._is_pro_source("xcagi-pro") is True
    assert AIChatApplicationService._is_pro_source("basic") is False
    ctx = AIChatApplicationService._merge_tool_runtime_context(
        "u1",
        "查产品",
        {"ui_surface": "chat", "excel_analysis": {"sheet": "S1"}},
    )
    assert ctx["user_id"] == "u1"
    assert ctx["excel_analysis"]["sheet"] == "S1"


# ---------------------------------------------------------------------------
# workflow types / planner registry
# ---------------------------------------------------------------------------


def test_validate_plan_graph_errors() -> None:
    bad = PlanGraph(plan_id="", intent="", nodes=[])
    assert validate_plan_graph(bad) == "plan_id 不能为空"

    dup = PlanGraph(
        plan_id="p1",
        intent="报价",
        nodes=[
            WorkflowNode(node_id="a", tool_id="t", action="run"),
            WorkflowNode(node_id="a", tool_id="t", action="run"),
        ],
    )
    assert "不能重复" in (validate_plan_graph(dup) or "")

    ok = PlanGraph(
        plan_id="p1",
        intent="报价",
        nodes=[WorkflowNode(node_id="n1", tool_id="price_list", action="export")],
    )
    assert validate_plan_graph(ok) is None


def test_get_tool_registry_has_core_tools() -> None:
    reg = get_tool_registry()
    assert "price_list" in reg
    assert "products" in reg
    assert reg["customers"]["actions"]["query"]["risk"] == "low"


# ---------------------------------------------------------------------------
# conversation helpers
# ---------------------------------------------------------------------------


def test_message_requires_db_read_token() -> None:
    assert _message_requires_db_read_token("查看数据库产品库") is True
    assert _message_requires_db_read_token("你好") is False


def test_extract_excel_paths_and_merge_context() -> None:
    paths = _extract_excel_paths_from_message("请分析 /tmp/a.xlsx 和 b.xlsm")
    assert "/tmp/a.xlsx" in paths
    merged, found = _merge_runtime_context_with_message_paths(
        {"excel_analysis": {"file_path": "/data/c.xlsx"}},
        "处理 c.xlsx",
    )
    assert merged["excel_file_path"]
    assert found


def test_looks_like_vector_request() -> None:
    assert _looks_like_vector_request("建立向量索引") is True
    assert _looks_like_vector_request("普通聊天") is False


def test_xcagi_compat_reply_payload_plain_text() -> None:
    out = _xcagi_compat_reply_payload("你好")
    assert out["success"] is True
    assert out["response"] == "你好"


def test_xcagi_chat_http_exc_timeout() -> None:
    exc = _xcagi_chat_http_exc(TimeoutError("slow"))
    assert exc.status_code == 504


def test_xcagi_compat_chat_body_aliases() -> None:
    body = XcagiCompatChatBody.model_validate({"content": "查库存", "runtime_context": {"k": 1}})
    assert body.message == "查库存"
    assert body.context == {"k": 1}


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------


def test_session_and_message_to_dict_variants() -> None:
    sess = _session_to_dict(
        {
            "session_id": "s1",
            "user_id": 1,
            "title": "",
            "message_count": 2,
        }
    )
    assert sess["title"] == "新会话"
    msg = _message_to_dict(("mid", "s1", 1, "user", "hi", "intent", "{}", None))
    assert msg["content"] == "hi"


def test_http_exception_to_json() -> None:
    resp = _http_exception_to_json(HTTPException(status_code=403, detail={"message": "拒绝"}))
    assert resp.status_code == 403
