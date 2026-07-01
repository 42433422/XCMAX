from __future__ import annotations

from app.application.excel_imports import _norm_model, _parse_price


def test_parse_price_accepts_common_legacy_values() -> None:
    assert _parse_price(None) == 0.0
    assert _parse_price("") == 0.0
    assert _parse_price("1,234.50") == 1234.5
    assert _parse_price("bad") == 0.0


def test_norm_model_uses_existing_or_generated_value() -> None:
    assert _norm_model(" abc-1 ") == "ABC-1"
    assert _norm_model("", "Widget A", "Spec 1") == "Widget-A-Spec-1"
