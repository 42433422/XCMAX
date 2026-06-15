"""COVERAGE_RAMP Phase 2 (p2-p2-ext): conversation context/intent, chart_data,
wechat_contact_store, deepseek/rasa, product_repository, semantic_chunker semantic path."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.ai_engines.deepseek.intent_service import DeepseekIntentClassifier, _IntentRecognitionCache
from app.ai_engines.rasa.nlu_service import RasaNLUService
from app.domain.context.session_context import (
    _sanitize_untrusted_context_line,
    format_runtime_context_for_llm,
)
from app.infrastructure.persistence.product_repository_impl import SQLAlchemyProductRepository
from app.infrastructure.persistence.wechat_contact_store_impl import (
    _read_rows_from_contact_db,
    resolve_decrypt_contact_db_path,
)
from app.infrastructure.rag.semantic_chunker import SemanticChunker
from app.services.conversation.context import ConversationContext, ContextMixin
from app.services.conversation.intent import IntentMixin
from app.services.kitten_report.chart_data_service import ChartDataService
from app.services.kitten_report.save_service import AnalysisSaveService


# ---------------------------------------------------------------------------
# conversation context + intent mixin helpers
# ---------------------------------------------------------------------------


class _ContextService(ContextMixin):
    def __init__(self) -> None:
        self.contexts: dict[str, ConversationContext] = {}


class _IntentStub(IntentMixin):
    pass


def test_conversation_context_defaults() -> None:
    ctx = ConversationContext(user_id="u1")
    assert ctx.user_id == "u1"
    assert ctx.conversation_history == []


def test_context_mixin_create_and_update() -> None:
    svc = _ContextService()
    ctx = svc.create_context("u1")
    assert ctx.user_id == "u1"
    updated = svc.update_context("u1", current_intent="shipment")
    assert updated is not None
    assert updated.current_intent == "shipment"


def test_intent_mixin_normalize_ai_mode() -> None:
    assert _IntentStub._normalize_ai_mode("offline") == "offline"
    assert _IntentStub._normalize_ai_mode("PRO") == "online"


def test_intent_rule_only_fast_greeting() -> None:
    stub = _IntentStub()
    stub.intent_service = lambda _m: {"is_greeting": True, "primary_intent": "greet"}
    out = stub._intent_rule_only_fast("你好")
    assert out.get("is_greeting") is True
    assert out["intent_source"] == "rule_only_fast"


# ---------------------------------------------------------------------------
# session_context sanitization + runtime format
# ---------------------------------------------------------------------------


def test_sanitize_untrusted_context_line_truncates() -> None:
    long = "a" * 500
    out = _sanitize_untrusted_context_line(long, max_len=100)
    assert len(out) <= 101
    assert out.endswith("…")


def test_format_runtime_context_for_llm_with_excel() -> None:
    ctx = {
        "excel_file_path": "/tmp/sales.xlsx",
        "preferred_sheet_name": "Sheet1",
    }
    txt = format_runtime_context_for_llm(ctx)
    assert txt is not None
    assert "sales.xlsx" in txt


# ---------------------------------------------------------------------------
# kitten chart_data + save_service
# ---------------------------------------------------------------------------


def _chart_db_factory(revenue: float = 1000.0, orders: int = 2):
    @contextmanager
    def _ctx():
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = (revenue, orders)
        db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = [
            SimpleNamespace(product_name="漆A", total=500.0)
        ]
        yield db

    return _ctx


def test_chart_data_revenue_with_mock_db() -> None:
    with patch("app.db.session.get_db", _chart_db_factory()):
        out = ChartDataService().get_revenue_chart_data(months=2)
    assert out["success"] is True
    assert out["type"] == "line"
    assert len(out["data"]["labels"]) == 2


def test_chart_data_product_pie_with_mock_db() -> None:
    with patch("app.db.session.get_db", _chart_db_factory()):
        out = ChartDataService().get_product_pie_chart_data()
    assert out["success"] is True
    assert out["type"] == "pie"


def test_analysis_save_service_roundtrip(tmp_path) -> None:
    svc = AnalysisSaveService(save_dir=str(tmp_path))
    saved = svc.save_analysis("kitten", {"rows": 1}, metadata={"tag": "t"})
    assert saved["success"] is True
    listed = svc.list_saved_analyses("kitten")
    assert len(listed) == 1
    got = svc.get_analysis(saved["id"])
    assert got is not None
    assert got["type"] == "kitten"


# ---------------------------------------------------------------------------
# wechat_contact_store sqlite helper
# ---------------------------------------------------------------------------


def test_read_rows_from_contact_db(tmp_path) -> None:
    db_path = tmp_path / "contact.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INT, delete_flag INT)"
    )
    conn.execute(
        "INSERT INTO contact VALUES ('u1', '张三', '备注', 0, 0)"
    )
    conn.commit()
    conn.close()
    rows = _read_rows_from_contact_db(str(db_path), limit=10)
    assert len(rows) == 1
    assert rows[0][1] == "张三"


def test_resolve_decrypt_contact_db_path_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "c.db"
    db_file.write_text("")
    monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", str(db_file))
    with patch("app.infrastructure.plugins.wechat_plugin.get_wechat_plugin") as mock_plugin:
        mock_plugin.return_value.is_available.return_value = False
        assert resolve_decrypt_contact_db_path() == str(db_file)


# ---------------------------------------------------------------------------
# product_repository helpers
# ---------------------------------------------------------------------------


def test_product_repository_product_to_dict() -> None:
    from app.db.models.product import Product

    product = Product(id=1, name="漆A", price=12.5, quantity=3)
    repo = SQLAlchemyProductRepository()
    out = repo._product_to_dict(product)
    assert out.get("product_name") == "漆A" or out.get("name") == "漆A"


# ---------------------------------------------------------------------------
# semantic chunker with fake embedder
# ---------------------------------------------------------------------------


def test_semantic_chunker_with_embedder() -> None:
    def _emb(text: str) -> list[float]:
        # 相似句向量接近，不同主题向量远离
        if "发货" in text:
            return [1.0, 0.0]
        if "库存" in text:
            return [0.0, 1.0]
        return [0.5, 0.5]

    chunker = SemanticChunker(embedder=_emb, threshold=0.3, min_chunk_chars=5, max_chunk_chars=200)
    text = "发货单用于出货。发货流程需要审核。库存查询在系统中。"
    chunks = chunker.split_by_semantic(text)
    assert len(chunks) >= 1
    assert sum(len(c.text) for c in chunks) >= len(text.strip()) - 5


# ---------------------------------------------------------------------------
# deepseek / rasa lightweight
# ---------------------------------------------------------------------------


def test_deepseek_intent_cache_lru_eviction() -> None:
    cache = _IntentRecognitionCache(max_size=2, ttl_seconds=3600)
    cache.set("a", {"intent": "x"})
    cache.set("b", {"intent": "y"})
    cache.set("c", {"intent": "z"})
    assert cache.get("a") is None
    assert cache.get("c") is not None


def test_deepseek_classifier_predict_stub() -> None:
    clf = DeepseekIntentClassifier(api_key="test")
    out = clf.predict("生成发货单")
    assert out["intent"] == "unk"
    assert out["source"] == "deepseek"


def test_rasa_service_disabled_when_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_RASA", "0")
    svc = RasaNLUService()
    assert svc.is_available() is False


def test_rasa_parse_returns_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_RASA", "0")
    svc = RasaNLUService()
    out = svc.parse("hello")
    assert out["intent"]["name"] is None
    assert out["message"] == "disabled"
