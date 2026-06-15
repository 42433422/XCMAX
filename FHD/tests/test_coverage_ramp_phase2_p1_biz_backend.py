"""COVERAGE_RAMP Phase 2 (p2-p1-biz): application / infrastructure / domain / ai_engines helpers."""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.responses import JSONResponse

from app.ai_engines.deepseek.intent_service import INTENT_DESCRIPTIONS, _IntentRecognitionCache
from app.application import aibiz_web_terminal_service as aibiz_mod
from app.application.rbac_app_service import RbacAppService, get_rbac_app_service
from app.domain.services.unified_intent_recognizer import _env_flag
from app.infrastructure.documents.price_list_export import (
    _detect_header_row_count,
    _format_price_cell,
    _header_text,
    _parse_header_serial_and_column_map,
    _product_row_cell_values,
    _row_keyword_score,
    build_price_list_template_preview_json,
)
from app.infrastructure.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.infrastructure.persistence.compat_db.writes import (
    _customers_delete_by_norm_name_pg,
    _products_delete_by_unit_pg,
    _purchase_units_delete_by_norm_unit_pg,
)
from app.infrastructure.persistence.product_repository_impl import SQLAlchemyProductRepository
from app.infrastructure.persistence.sqlite_vector_store import SQLiteVectorStore
from app.infrastructure.rag.rag_service import RagService, is_rag_enabled
from app.services.deepseek_intent_service import _make_intent_cache_key, cn_to_number


# ---------------------------------------------------------------------------
# price_list_export helpers
# ---------------------------------------------------------------------------


class _MockCell:
    def __init__(self, text: str = "") -> None:
        self.text = text


class _MockRow:
    def __init__(self, texts: list[str]) -> None:
        self.cells = [_MockCell(t) for t in texts]


class _MockTable:
    def __init__(self, rows: list[_MockRow]) -> None:
        self.rows = rows


def test_format_price_cell_variants() -> None:
    assert _format_price_cell(None) == ""
    assert _format_price_cell(12.0) == "12"
    assert _format_price_cell(12.5) == "12.50"
    assert _format_price_cell("abc") == "abc"


def test_product_row_cell_values_cn_keys() -> None:
    vals = _product_row_cell_values(
        {"型号": "M1", "产品名称": "漆", "规格": "5L", "单价": 99}
    )
    assert vals == ["M1", "漆", "5L", "99"]


def test_row_keyword_score_counts_headers() -> None:
    row = _MockRow(["序号", "型号", "名称", "规格", "单价"])
    assert _row_keyword_score(row.cells) >= 4


def test_detect_header_row_count_single() -> None:
    table = _MockTable([_MockRow(["产品价目表"])])
    assert _detect_header_row_count(table) == 1


def test_detect_header_row_count_two_rows() -> None:
    table = _MockTable(
        [
            _MockRow(["2026年度价目表"]),
            _MockRow(["序号", "型号", "名称", "规格", "单价"]),
        ]
    )
    assert _detect_header_row_count(table) == 2


def test_parse_header_serial_and_column_map() -> None:
    cells = [_MockCell("序号"), _MockCell("型号"), _MockCell("名称"), _MockCell("规格"), _MockCell("单价")]
    with_serial, col_map = _parse_header_serial_and_column_map(cells)
    assert with_serial is True
    assert col_map["price"] == 4


def test_header_text_strips() -> None:
    assert _header_text(_MockCell("  hello ")) == "hello"


@patch("app.infrastructure.documents.price_list_export.resolve_price_list_docx_template")
def test_build_price_list_template_preview_json(mock_resolve: MagicMock) -> None:
    mock_resolve.return_value = ("/tmp/t.docx", "templates/t.docx")
    out = build_price_list_template_preview_json()
    assert out["success"] is True
    assert "headers" in out


# ---------------------------------------------------------------------------
# aibiz_web_terminal_service surface helpers
# ---------------------------------------------------------------------------


def test_aibiz_unwrap_json_response() -> None:
    resp = JSONResponse({"err": True})
    out = aibiz_mod._unwrap(resp)
    assert "_error_response" in out


def test_aibiz_strip_b64_attach_image_urls_web() -> None:
    surface = {
        "captured_at": "2026-06-14T10:00:00Z",
        "pages": [
            {"id": "home", "name": "首页", "preview": True, "screenshot_b64": "xxx"},
            {"id": "chat", "name": "智能对话"},
        ],
    }
    out = aibiz_mod._strip_b64_attach_image_urls(surface, terminal="web")
    assert "screenshot_b64" not in out["pages"][0]
    assert "image_url" in out["pages"][0]
    assert out["preview_index"] == 0


def test_aibiz_strip_b64_software_skips_admin() -> None:
    surface = {
        "cached_at": "2026-06-14",
        "pages": [
            {"id": "admin_users", "name": "管理"},
            {"id": "chat", "name": "智能对话"},
        ],
    }
    out = aibiz_mod._strip_b64_attach_image_urls(surface, terminal="software")
    assert out["preview_index"] == 1


def test_aibiz_compact_surface_pages_passthrough() -> None:
    s = {"pages": []}
    assert aibiz_mod._compact_surface_pages(s, compact=True) is s


# ---------------------------------------------------------------------------
# product_repository _api_scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (float("nan"), None),
        ("nan", None),
        ("  hello ", "hello"),
        (42, 42),
    ],
)
def test_product_repository_api_scalar(value, expected) -> None:
    assert SQLAlchemyProductRepository._api_scalar(value) == expected


# ---------------------------------------------------------------------------
# compat_db writes early returns
# ---------------------------------------------------------------------------


def test_products_delete_by_unit_pg_empty() -> None:
    assert _products_delete_by_unit_pg(MagicMock(), "") == 0
    assert _products_delete_by_unit_pg(MagicMock(), "   ") == 0


def test_purchase_units_delete_by_norm_unit_pg_empty() -> None:
    assert _purchase_units_delete_by_norm_unit_pg(MagicMock(), "") == 0


def test_customers_delete_by_norm_name_pg_empty() -> None:
    eng = MagicMock()
    insp = MagicMock()
    assert _customers_delete_by_norm_name_pg(eng, insp, "") == 0


# ---------------------------------------------------------------------------
# rag_service
# ---------------------------------------------------------------------------


def test_rag_service_answer_fixed_chunks() -> None:
    svc = RagService(embedder=None)
    out = svc.answer(
        user_message="什么是发货单",
        knowledge_text="发货单用于记录出货。\n第二段说明。",
        llm_call=lambda _u, _p: "发货单是出货凭证。",
        chunk_strategy="fixed",
    )
    assert "answer" in out
    assert out["chunks"]


def test_is_rag_enabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_RAG_ENABLED", "true")
    assert is_rag_enabled() is True
    monkeypatch.setenv("XCAGI_RAG_ENABLED", "0")
    assert is_rag_enabled() is False


# ---------------------------------------------------------------------------
# unified_intent / deepseek / ai_engines
# ---------------------------------------------------------------------------


def test_env_flag_truthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_TEST_FLAG", "yes")
    assert _env_flag("XCAGI_TEST_FLAG") is True


def test_deepseek_cn_to_number() -> None:
    assert cn_to_number("五") == 5
    assert cn_to_number("abc3") == 3


def test_make_intent_cache_key_stable() -> None:
    k1 = _make_intent_cache_key(" Hello ")
    k2 = _make_intent_cache_key("hello")
    assert k1 == k2
    assert len(k1) == 64


def test_intent_descriptions_has_shipment() -> None:
    assert "shipment_generate" in INTENT_DESCRIPTIONS
    assert len(INTENT_DESCRIPTIONS) > 10


def test_deepseek_intent_cache_ttl() -> None:
    cache = _IntentRecognitionCache(max_size=2, ttl_seconds=0)
    cache.set("hi", {"intent": "greet"})
    assert cache.get("hi") is None


# ---------------------------------------------------------------------------
# sqlite_vector_store cosine
# ---------------------------------------------------------------------------


def test_sqlite_vector_cosine_similarity(tmp_path) -> None:
    store = SQLiteVectorStore(str(tmp_path / "vec.db"))
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0], dtype=np.float32)
    assert math.isclose(store._cosine_similarity(a, b), 1.0)
    zero = np.array([0.0, 0.0], dtype=np.float32)
    assert store._cosine_similarity(a, zero) == 0.0


# ---------------------------------------------------------------------------
# llm provider + rbac application
# ---------------------------------------------------------------------------


def test_openai_compatible_provider_configured_with_adapter() -> None:
    adapter = MagicMock()
    adapter.is_configured = True
    provider = OpenAICompatibleProvider(adapter=adapter)
    assert provider.is_configured is True


def test_rbac_app_service_crud_shapes() -> None:
    svc = RbacAppService()
    role = svc.create_role("admin", "管理员", ["read"])
    assert role["name"] == "admin"
    assert svc.get_role(1)["id"] == 1
    assert get_rbac_app_service() is get_rbac_app_service()
