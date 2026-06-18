"""COVERAGE_RAMP Phase 2 (p2-p2): persistence, conversation handlers, kitten_report,
domain session_context, infrastructure rag/payment, ai_engines helpers (mocked I/O)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.ai_engines.rasa.nlu_service import (
    _find_latest_local_model,
    get_rasa_nlu_service,
    reset_rasa_nlu_service,
)
from app.domain.context.session_context import (
    detected_excel_header_row_1based,
    enrich_excel_tool_arguments,
    format_excel_analysis_for_llm,
    format_recent_messages_excerpt_for_llm,
    merge_system_prompt,
    planner_workflow_interrupt_reply,
    runtime_context_after_workflow_interrupt,
)
from app.infrastructure.cache.intent_cache import IntentCache, _default_should_cache_intent
from app.infrastructure.payment import alipay as alipay_mod
from app.infrastructure.payment.order_store import (
    count_orders,
    get_order,
    list_entitlements,
    record_checkout_pending,
    update_order_status,
)
from app.infrastructure.persistence.compat_db.writes import (
    _customer_pg_row_select_sql,
    _products_pg_col_names,
    products_pg_batch_delete_rows,
)
from app.infrastructure.rag.citation_tracker import CitationTracker
from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk
from app.infrastructure.rag.semantic_chunker import SemanticChunker
from app.services.conversation.handlers import HandlersMixin
from app.services.kitten_report.docx_export import _html_to_plain, build_kitten_docx
from app.services.kitten_report.financial_plugins import (
    FinancialReportPlugin,
    InventoryValuationPlugin,
)
from app.services.kitten_report.service import KittenReportExportService

# ---------------------------------------------------------------------------
# conversation handlers (hard rules + greeting/goodbye/help)
# ---------------------------------------------------------------------------


class _HandlerStub(HandlersMixin):
    def __init__(self) -> None:
        self.history: list[tuple[str, str, str]] = []

    def add_to_history(self, user_id: str, role: str, content: str) -> None:
        self.history.append((user_id, role, content))


@pytest.mark.parametrize(
    "message,action_type",
    [
        ("导出客户列表", "export_customers_xlsx"),
        ("进入工作模式", "set_work_mode"),
        ("退出工作模式", "set_work_mode"),
        ("查看客户列表", "show_customers"),
        ("产品列表", "show_products"),
        ("进入监控模式", "show_monitor"),
    ],
)
@pytest.mark.asyncio
async def test_handlers_hard_rules(message: str, action_type: str) -> None:
    svc = _HandlerStub()
    out = svc._check_hard_rules(message)
    assert out is not None
    assert out["action"] == "auto_action"
    assert out["data"]["type"] == action_type


@pytest.mark.asyncio
async def test_handlers_greeting_and_goodbye() -> None:
    svc = _HandlerStub()
    ctx = SimpleNamespace(user_id="u1")
    greet = await svc._handle_greeting("你好", ctx)
    assert greet["action"] == "greeting"
    bye = await svc._handle_goodbye("再见", ctx)
    assert bye["action"] == "goodbye"
    assert len(svc.history) == 4


@pytest.mark.asyncio
async def test_handlers_help() -> None:
    svc = _HandlerStub()
    ctx = SimpleNamespace(user_id="u2")
    out = await svc._handle_help("帮助", ctx)
    assert out["action"] == "help"
    assert "发货单" in out["text"]


# ---------------------------------------------------------------------------
# kitten_report service / docx / financial plugins
# ---------------------------------------------------------------------------


def test_kitten_collect_plugin_results() -> None:
    svc = KittenReportExportService()
    payload = {
        "dataset": {"rows": 5, "columns": 2, "preview": [[1, 2]]},
        "messages": [{"role": "user", "content": "分析"}],
        "result": {"title": "测试", "summary": "摘要"},
        "phase": "analyze",
        "industry": "涂料行业",
    }
    results = svc.collect_plugin_results(payload)
    assert len(results) >= 5
    keys = {r["key"] for r in results}
    assert "rule_stats" in keys
    assert "financial_report" in keys


def test_kitten_build_report_xlsx_bytes() -> None:
    svc = KittenReportExportService()
    out = svc.build_report(
        {
            "dataset": {"rows": 3, "columns": 2, "name": "demo.xlsx", "fieldNames": ["a", "b"]},
            "messages": [{"role": "user", "content": "<b>hi</b>", "time": "10:00"}],
            "result": {"title": "报告", "summary": "ok"},
            "phase": "done",
            "industry": "通用",
        }
    )
    assert out["file_name"].endswith(".xlsx")
    assert isinstance(out["content"], bytes)
    assert len(out["content"]) > 100


def test_kitten_html_to_plain() -> None:
    assert "hello" in _html_to_plain("<p>hello</p>")


@patch("docx.Document")
def test_build_kitten_docx(mock_doc_cls: MagicMock) -> None:
    doc = MagicMock()
    mock_doc_cls.return_value = doc
    doc.styles = {"Normal": MagicMock()}
    out = build_kitten_docx(
        {
            "dataset": {"rows": 2, "columns": 1, "name": "t.csv", "fields": ["x"]},
            "messages": [{"role": "user", "content": "问"}],
            "result": {"title": "T", "summary": "S"},
            "phase": "p1",
            "industry": "通用",
            "web_search_results": [{"title": "hit", "url": "http://x", "snippet": "snip"}],
        }
    )
    assert out["file_name"].endswith(".docx")
    assert isinstance(out["content"], bytes)


def _make_mock_get_db(query_result):
    @contextmanager
    def _mock_db_session():
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = query_result
        db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        db.query.return_value.filter.return_value.scalar.return_value = 0
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = []
        yield db

    return _mock_db_session


def test_financial_report_plugin_with_mock_db() -> None:
    row = SimpleNamespace(total_revenue=5000.0, order_count=3, avg_order=1666.0)
    with patch("app.db.session.get_db", _make_mock_get_db(row)):
        plugin = FinancialReportPlugin()
        with (
            patch.object(plugin, "_estimate_cost", return_value=1000.0),
            patch.object(plugin, "_get_monthly_breakdown", return_value=[]),
            patch.object(plugin, "_get_product_profitability", return_value=[]),
            patch.object(plugin, "_get_customer_analysis", return_value=[]),
        ):
            out = plugin.run({})
    assert out.key == "financial_report"
    assert "营收" in out.summary


def test_inventory_valuation_plugin_with_mock_db() -> None:
    with patch("app.db.session.get_db", _make_mock_get_db(None)):
        plugin = InventoryValuationPlugin()
        with (
            patch.object(
                plugin,
                "_get_material_valuation",
                return_value={"total_value": 100.0, "item_count": 1},
            ),
            patch.object(
                plugin,
                "_get_product_valuation",
                return_value={"total_value": 200.0, "item_count": 2},
            ),
            patch.object(
                plugin,
                "_get_low_stock_items",
                return_value={"count": 0, "items": []},
            ),
        ):
            out = plugin.run({})
    assert out.key == "inventory_valuation"
    assert "库存" in out.summary


# ---------------------------------------------------------------------------
# domain session_context
# ---------------------------------------------------------------------------


def test_detected_excel_header_row_from_grid_preview() -> None:
    ea = {"preview_data": {"grid_preview": {"header_row_index": 3}}}
    assert detected_excel_header_row_1based(ea) == 3


def test_detected_excel_header_row_preferred_sheet() -> None:
    ea = {
        "sheets": [
            {"sheet_name": "Sheet1", "tables": [{"header_row": 2}]},
            {"sheet_name": "数据", "grid_preview": {"header_row_index": 5}},
        ]
    }
    assert detected_excel_header_row_1based(ea, preferred_sheet_name="数据") == 5


def test_enrich_excel_tool_arguments_fills_path_and_header() -> None:
    ctx = {
        "excel_analysis": {
            "file_path": "/tmp/demo.xlsx",
            "sheets": [{"sheet_name": "S1", "tables": [{"header_row": 2}]}],
        },
        "preferred_sheet_name": "S1",
    }
    out = enrich_excel_tool_arguments("excel_analysis", {}, ctx)
    assert out["file_path"] == "/tmp/demo.xlsx"
    assert out.get("header_row") == 2


def test_format_recent_messages_excerpt() -> None:
    ctx = {
        "recent_messages": [{"role": "user", "content": "开单"}, {"role": "ai", "content": "好的"}]
    }
    txt = format_recent_messages_excerpt_for_llm(ctx)
    assert txt is not None
    assert "开单" in txt


def test_format_excel_analysis_for_llm_minimal() -> None:
    ctx = {
        "excel_analysis": {
            "file_name": "价目.xlsx",
            "preview_data": {"rows": 10, "columns": 4},
        }
    }
    txt = format_excel_analysis_for_llm(ctx)
    assert txt is not None
    assert "价目" in txt


def test_merge_system_prompt_appends_blocks() -> None:
    merged = merge_system_prompt("你是助手", runtime_context={"preferred_sheet_name": "S1"})
    assert "你是助手" in merged


def test_planner_workflow_interrupt_reply() -> None:
    assert planner_workflow_interrupt_reply("暂停流程") is not None
    assert planner_workflow_interrupt_reply("hello") is None


def test_runtime_context_after_workflow_interrupt() -> None:
    out = runtime_context_after_workflow_interrupt({"workflow_state": {"x": 1}, "keep": True})
    assert "workflow_state" not in out
    assert out["keep"] is True


# ---------------------------------------------------------------------------
# infrastructure rag / payment / cache
# ---------------------------------------------------------------------------


def test_semantic_chunker_fixed_fallback() -> None:
    chunker = SemanticChunker(embedder=None)
    chunks = chunker.split_by_fixed("第一句。第二句更长一些的内容。" * 5)
    assert chunks
    assert all(c.text for c in chunks)


def test_hybrid_retriever_bm25_only() -> None:
    retriever = HybridRetriever(embedder=None)
    retriever.index(
        [
            RetrievedChunk(text="发货单用于记录出货", score=0.0, chunk_index=0),
            RetrievedChunk(text="产品价目表导出", score=0.0, chunk_index=1),
        ]
    )
    hits = retriever.retrieve("发货单")
    assert hits
    assert hits[0].text


def test_hybrid_retriever_with_embedder() -> None:
    def _emb(text: str) -> list[float]:
        return [1.0, 0.0] if "发货" in text else [0.0, 1.0]

    retriever = HybridRetriever(embedder=_emb)
    retriever.index(
        [
            RetrievedChunk(text="发货单管理", score=0.0, chunk_index=0),
            RetrievedChunk(text="库存查询", score=0.0, chunk_index=1),
        ]
    )
    hits = retriever.retrieve("发货")
    assert hits[0].text == "发货单管理"


def test_citation_tracker_strips_markers() -> None:
    chunks = [
        RetrievedChunk(text="chunk one", score=1.0, chunk_index=0),
        RetrievedChunk(text="chunk two", score=0.5, chunk_index=1),
    ]
    tracker = CitationTracker(chunks)
    clean, cites = tracker.attach_citations("结论见[1]与[2]。")
    assert "[1]" not in clean
    assert len(cites) == 2


def test_intent_cache_should_cache_filters_unk() -> None:
    assert _default_should_cache_intent({"intent": "unk", "confidence": 0.9}) is False
    assert _default_should_cache_intent({"intent": "shipment", "confidence": 0.8}) is True


def test_intent_cache_invalidate() -> None:
    backend = MagicMock()
    cache = IntentCache(backend=backend, enabled=True)
    cache.invalidate("hello", mod_id="m1")
    backend.delete.assert_called_once()


def test_payment_order_store_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "orders.json"
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(store))
    record_checkout_pending(
        out_trade_no="T20260614001",
        plan_id="pro",
        amount_cents=9900,
        amount_yuan="99.00",
        local_user_id=1,
    )
    assert count_orders() == 1
    order = get_order("T20260614001")
    assert order is not None
    assert order["status"] == "pending_payment"
    update_order_status(out_trade_no="T20260614001", status="paid")
    assert get_order("T20260614001")["status"] == "paid"
    assert isinstance(list_entitlements(), list)


def test_alipay_env_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIPAY_DEBUG", "1")
    assert alipay_mod.alipay_debug() is True
    monkeypatch.delenv("ALIPAY_APP_ID", raising=False)
    assert alipay_mod.credentials_ready() is False


# ---------------------------------------------------------------------------
# persistence compat_db writes helpers
# ---------------------------------------------------------------------------


def test_products_pg_col_names_cached() -> None:
    eng = MagicMock()
    insp = MagicMock()
    insp.get_columns.return_value = [{"name": "id"}, {"name": "unit"}]
    with (
        patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng),
        patch("app.infrastructure.persistence.compat_db.writes.inspect", return_value=insp),
    ):
        cols = _products_pg_col_names()
    assert "id" in cols


def test_customer_pg_row_select_sql() -> None:
    insp = MagicMock()
    insp.get_columns.return_value = [
        {"name": "id"},
        {"name": "unit_name"},
        {"name": "contact_person"},
        {"name": "phone"},
    ]
    sql, fields = _customer_pg_row_select_sql(insp)
    assert "unit_name" in sql
    assert "id" in fields


def test_products_pg_batch_delete_rows_invalid_ids() -> None:
    eng = MagicMock()
    conn = MagicMock()
    eng.begin.return_value.__enter__ = MagicMock(return_value=conn)
    eng.begin.return_value.__exit__ = MagicMock(return_value=False)
    with (
        patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=eng),
        patch(
            "app.infrastructure.persistence.compat_db.writes._products_pg_col_names",
            return_value={"id", "mod_id"},
        ),
    ):
        deleted, skipped = products_pg_batch_delete_rows(["abc", "0", ""])
    assert deleted == 0
    assert skipped


# ---------------------------------------------------------------------------
# rasa singleton
# ---------------------------------------------------------------------------


def test_rasa_nlu_service_singleton() -> None:
    reset_rasa_nlu_service()
    a = get_rasa_nlu_service()
    b = get_rasa_nlu_service()
    assert a is b


def test_find_latest_local_model_returns_none_when_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.ai_engines.rasa.nlu_service.os.path.isdir",
        lambda _p: False,
    )
    assert _find_latest_local_model() is None
