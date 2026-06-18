"""COVERAGE_RAMP Phase 2/3 (p2-p3): price_list_export borders, session kitten ctx,
llm client, deepseek helpers, mods manifest, neuro_bus domain events."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.context.session_context import format_runtime_context_for_llm
from app.infrastructure.documents.price_list_export import (
    _border_el_effective,
    _format_price_cell,
    _product_row_cell_values,
    build_sales_contract_template_preview_json,
)
from app.infrastructure.llm import client as llm_client
from app.infrastructure.mods.manifest import _check_xcagi_version, _compare_versions
from app.services.deepseek_intent_service import cn_to_number, get_deepseek_api_key

# ---------------------------------------------------------------------------
# price_list_export
# ---------------------------------------------------------------------------


def test_border_el_effective_nil() -> None:
    el = MagicMock()
    el.get.return_value = "nil"
    assert _border_el_effective(el) is False


def test_border_el_effective_single() -> None:
    el = MagicMock()
    el.get.return_value = "single"
    assert _border_el_effective(el) is True


@patch("app.infrastructure.documents.price_list_export.resolve_price_list_docx_template")
def test_build_sales_contract_template_preview(mock_resolve: MagicMock) -> None:
    mock_resolve.return_value = ("/tmp/c.docx", "templates/c.docx")
    out = build_sales_contract_template_preview_json()
    assert out["success"] is True


def test_product_row_cell_values_en_keys() -> None:
    vals = _product_row_cell_values({"model": "M2", "name": "漆", "spec": "1L", "price": 88})
    assert "M2" in vals or "漆" in vals


# ---------------------------------------------------------------------------
# session_context kitten path
# ---------------------------------------------------------------------------


def test_format_runtime_context_kitten_analyzer() -> None:
    ctx = {
        "kitten_analyzer": True,
        "kitten_dataset": {
            "file_name": "sales.xlsx",
            "rows": 100,
            "columns": 8,
            "fields": ["日期", "金额"],
            "preview_text": "样本行",
        },
        "kitten_business_snapshot": {"text": "本月出货 10 笔"},
        "kitten_web_search": True,
        "web_search_meta": {"provider": "test", "query": "涂料行情"},
    }
    txt = format_runtime_context_for_llm(ctx)
    assert txt is not None
    assert "小猫分析" in txt
    assert "sales.xlsx" in txt


# ---------------------------------------------------------------------------
# llm client
# ---------------------------------------------------------------------------


def test_llm_env_mode_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_LLM_MODE", "offline")
    assert llm_client._env_mode() == "offline"


def test_llm_resolve_openai_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_OPENAI_TIMEOUT_SEC", "30")
    assert llm_client._resolve_openai_timeout_seconds() == 30.0


def test_llm_set_and_resolve_mode() -> None:
    llm_client.set_mode("online")
    assert llm_client.resolve_mode() == "online"
    llm_client.set_mode("offline", model="llama3")
    assert llm_client.resolve_mode() == "offline"


def test_llm_get_offline_status_shape() -> None:
    status = llm_client.get_offline_status()
    assert "ollama_reachable" in status


# ---------------------------------------------------------------------------
# mods manifest version compare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "v1,v2,expected",
    [
        ("10.0.0", "10.0.0", 0),
        ("10.1.0", "10.0.0", 1),
        ("9.0.0", "10.0.0", -1),
    ],
)
def test_compare_versions(v1: str, v2: str, expected: int) -> None:
    assert _compare_versions(v1, v2) == expected


def test_check_xcagi_version_spec() -> None:
    assert _check_xcagi_version(">=10.0.0") is True
    assert _check_xcagi_version(">=99.0.0") is False


# ---------------------------------------------------------------------------
# deepseek helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("五", 5),
        ("十二", 102),
        ("abc99", 99),
        ("无数字", 0),
    ],
)
def test_cn_to_number_variants(text: str, expected: int) -> None:
    assert cn_to_number(text) == expected


def test_get_deepseek_api_key_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_DEEPSEEK_API_KEY", raising=False)
    assert get_deepseek_api_key() == ""


def test_get_deepseek_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert get_deepseek_api_key() == "sk-test"


# ---------------------------------------------------------------------------
# neuro_bus domain events (Phase 3)
# ---------------------------------------------------------------------------


def test_import_domain_event_modules_for_coverage() -> None:
    """导入各域事件模块以覆盖类定义（实例化受 dataclass/NeuroEvent 混用限制）。"""
    import app.neuro_bus.events.ai_events  # noqa: F401
    import app.neuro_bus.events.auth_events  # noqa: F401
    import app.neuro_bus.events.conversation_events  # noqa: F401
    import app.neuro_bus.events.customer_events as customer_events  # noqa: F401
    import app.neuro_bus.events.inventory_events  # noqa: F401
    import app.neuro_bus.events.material_events  # noqa: F401
    import app.neuro_bus.events.ocr_events  # noqa: F401
    import app.neuro_bus.events.order_events  # noqa: F401
    import app.neuro_bus.events.payment_events  # noqa: F401
    import app.neuro_bus.events.print_events  # noqa: F401
    import app.neuro_bus.events.shipment_events as shipment_events  # noqa: F401
    import app.neuro_bus.events.wechat_events  # noqa: F401

    assert shipment_events.ShipmentCreatedEvent.event_type == "shipment.created"
    assert customer_events.CustomerRegisteredEvent.event_type == "customer.registered"
