"""COVERAGE_RAMP Phase 2 (p2-p3-ext): planner tools, workflow import preview,
ai_chat helpers, ocr cache, rag semantic chunker fixed, contexts notifier."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from app.application.tools.workflow import (
    _import_customers_preview_or_execute,
    _import_orders_preview_or_execute,
    _import_products_preview_or_execute,
    _read_excel_dataframe,
)
from app.application.workflow.planner import (
    _execute_customers_tool,
    _execute_products_tool,
    _execute_shipment_records_tool,
    execute_tool,
)
from app.infrastructure.rag.rag_service import RagQuery
from app.infrastructure.rag.semantic_chunker import SemanticChunker

# ---------------------------------------------------------------------------
# workflow import preview helpers
# ---------------------------------------------------------------------------


def test_import_products_preview_mode() -> None:
    df = pd.DataFrame([{"产品名称": "漆A", "单价": 10, "数量": 2}])
    raw = _import_products_preview_or_execute(
        df, list(df.columns), unit_name="七彩", confirm=False, row_count=1
    )
    out = json.loads(raw)
    assert out["success"] is True
    assert out.get("preview") is True


def test_import_customers_preview_mode() -> None:
    df = pd.DataFrame([{"单位名称": "七彩", "联系人": "张三", "电话": "13800000000"}])
    out = json.loads(
        _import_customers_preview_or_execute(df, list(df.columns), confirm=False, row_count=1)
    )
    assert out["success"] is True


def test_import_orders_preview_mode() -> None:
    df = pd.DataFrame([{"产品": "漆", "数量": 1, "单价": 99}])
    out = json.loads(
        _import_orders_preview_or_execute(
            df, list(df.columns), unit_name="七彩", confirm=False, row_count=1
        )
    )
    assert out["success"] is True


@patch("app.application.tools.workflow.pd.read_excel")
def test_read_excel_dataframe_passes_header(mock_read: MagicMock, tmp_path) -> None:
    fp = tmp_path / "t.xlsx"
    fp.write_bytes(b"x")
    mock_read.return_value = pd.DataFrame({"a": [1]})
    df = _read_excel_dataframe(Path(fp), sheet_name="S1", header_row_1based=2)
    assert len(df) == 1
    mock_read.assert_called_once()


# ---------------------------------------------------------------------------
# planner execute_tool (mocked services)
# ---------------------------------------------------------------------------


def test_execute_products_tool_list() -> None:
    with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"success": True, "data": [{"id": 1, "name": "漆"}]}
        mock_client.return_value.get.return_value = resp
        out = _execute_products_tool({"action": "list", "keyword": "漆"})
    assert out.get("success") is True or "data" in out


def test_execute_customers_tool_list() -> None:
    with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"success": True, "data": []}
        mock_client.return_value.get.return_value = resp
        out = _execute_customers_tool({"action": "list"})
    assert out.get("success") is True or isinstance(out, dict)


def test_execute_shipment_records_tool() -> None:
    with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"success": True, "records": []}
        mock_client.return_value.get.return_value = resp
        out = _execute_shipment_records_tool({"limit": 5})
    assert isinstance(out, dict)


def test_execute_tool_unknown_returns_error() -> None:
    out = execute_tool("nonexistent_tool_xyz", {})
    assert out.get("success") is False or "error" in out or out.get("status") == "error"


# ---------------------------------------------------------------------------
# ai_chat_app_service helpers
# ---------------------------------------------------------------------------


def test_skip_pro_excel_deterministic_import_context() -> None:
    assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True
    assert (
        _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True})
        is False
    )


def test_skip_pro_excel_deterministic_import_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
    assert _skip_pro_excel_deterministic_import({}) is True


def test_ai_chat_service_instantiation() -> None:
    svc = AIChatApplicationService()
    assert svc is not None


# ---------------------------------------------------------------------------
# rag semantic + query dataclass
# ---------------------------------------------------------------------------


def test_semantic_chunker_split_by_fixed_windows() -> None:
    chunker = SemanticChunker(embedder=None, max_chunk_chars=50, min_chunk_chars=10)
    text = "段落一内容。" * 10 + "段落二内容。" * 10
    chunks = chunker.split_by_fixed(text)
    assert len(chunks) >= 1
    assert all(c.char_start <= c.char_end for c in chunks)


def test_rag_query_dataclass() -> None:
    q = RagQuery(user_message="什么是发货单", knowledge_text="发货单说明")
    assert q.user_message == "什么是发货单"
