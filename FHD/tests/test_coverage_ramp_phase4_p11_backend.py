"""COVERAGE_RAMP Phase 4 round 11: DeepSeekIntentRecognizer deep paths (24.7%→)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.services.deepseek_intent_service as ds
from app.services.deepseek_intent_service import (
    DeepSeekIntentRecognizer,
    _make_intent_cache_key,
)


@pytest.fixture
def rec() -> DeepSeekIntentRecognizer:
    return DeepSeekIntentRecognizer(api_key=None, max_retries=1)


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------


def test_get_api_key_explicit() -> None:
    r = DeepSeekIntentRecognizer(api_key="explicit")
    assert r._get_api_key() == "explicit"


def test_get_api_key_from_env(rec: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert rec._get_api_key() == "env-key"


def test_get_api_key_from_config_file(
    rec: DeepSeekIntentRecognizer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = tmp_path / "deepseek_config.py"
    cfg.write_text('DEEPSEEK_API_KEY = "from-config"\n', encoding="utf-8")
    with patch("app.utils.path_utils.get_resource_path", return_value=str(cfg)):
        assert rec._get_api_key() == "from-config"


def test_get_api_key_none(rec: DeepSeekIntentRecognizer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with patch("app.utils.path_utils.get_resource_path", return_value=None):
        assert rec._get_api_key() == ""


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_plain_json(rec: DeepSeekIntentRecognizer) -> None:
    content = json.dumps({"intent": "products", "confidence": 0.9, "slots": {}, "reasoning": "r"})
    out = rec._parse_response(content, "查产品")
    assert out["intent"] == "products"
    assert out["source"] == "deepseek"
    assert out["confidence"] == 0.9


def test_parse_response_code_fence(rec: DeepSeekIntentRecognizer) -> None:
    body = json.dumps({"intent": "customers", "confidence": 1.5, "slots": {}})
    content = f"```json\n{body}\n```"
    out = rec._parse_response(content, "查客户")
    assert out["intent"] == "customers"
    # confidence is clamped to 1.0
    assert out["confidence"] == 1.0


def test_parse_response_embedded_json(rec: DeepSeekIntentRecognizer) -> None:
    body = json.dumps({"intent": "materials", "confidence": 0.7, "slots": {}})
    content = f"分析结果如下：{body} 完毕"
    out = rec._parse_response(content, "查材料")
    assert out["intent"] == "materials"


def test_parse_response_unknown_intent_falls_back(rec: DeepSeekIntentRecognizer) -> None:
    content = json.dumps({"intent": "not_a_real_intent", "confidence": 0.9, "slots": {}})
    out = rec._parse_response(content, "原始消息")
    assert out["intent"] is None
    assert out["source"] == "deepseek"


def test_parse_response_garbage(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._parse_response("完全不是 JSON 的内容", "原始消息")
    assert out["intent"] is None


# ---------------------------------------------------------------------------
# _normalize_slots
# ---------------------------------------------------------------------------


def test_normalize_slots_quantity_digit(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"quantity_tins": "3桶"}, "要3桶")
    assert out["quantity_tins"] == 3


def test_normalize_slots_quantity_chinese(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"quantity_tins": "五桶"}, "来五桶")
    assert out["quantity_tins"] == 5


def test_normalize_slots_quantity_plain_int(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"quantity_tins": "数量7"}, "无桶字")
    assert out["quantity_tins"] == 7


def test_normalize_slots_quantity_raw(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"quantity_tins": "若干"}, "无数字")
    assert out["quantity_tins"] == "若干"


def test_normalize_slots_tin_spec_from_message(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"tin_spec": "x"}, "规格 28 的产品")
    assert out["tin_spec"] == 28.0


def test_normalize_slots_tin_spec_value_digit(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"tin_spec": "20kg"}, "无规格关键字")
    assert out["tin_spec"] == 20.0


def test_normalize_slots_unit_name_from_message(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots({"unit_name": "x"}, "给七彩乐园，发货单")
    assert out["unit_name"] == "七彩乐园"


def test_normalize_slots_contact_and_other(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._normalize_slots(
        {"contact_person": "向总", "keyword": "9803", "empty": ""}, "msg"
    )
    assert out["contact_person"] == "向总"
    assert out["keyword"] == "9803"
    assert "empty" not in out


# ---------------------------------------------------------------------------
# _cn_to_number
# ---------------------------------------------------------------------------


def test_cn_to_number_single(rec: DeepSeekIntentRecognizer) -> None:
    assert rec._cn_to_number("三") == 3
    assert rec._cn_to_number("两") == 2


def test_cn_to_number_multi(rec: DeepSeekIntentRecognizer) -> None:
    # loop accumulates digits: 二 -> 2, 三 -> 2*10+3 = 23
    assert rec._cn_to_number("二三") == 23


def test_cn_to_number_arabic_string(rec: DeepSeekIntentRecognizer) -> None:
    assert rec._cn_to_number("7") == 7


def test_cn_to_number_invalid(rec: DeepSeekIntentRecognizer) -> None:
    assert rec._cn_to_number("abc") == 0


# ---------------------------------------------------------------------------
# _fallback_result / cache key
# ---------------------------------------------------------------------------


def test_fallback_result(rec: DeepSeekIntentRecognizer) -> None:
    out = rec._fallback_result("msg", raw_response="raw")
    assert out["intent"] is None
    assert out["confidence"] == 0.0
    assert out["raw_response"] == "raw"


def test_make_intent_cache_key_stable() -> None:
    k1 = _make_intent_cache_key("  Hello ")
    k2 = _make_intent_cache_key("hello")
    assert k1 == k2  # normalized lower+strip


# ---------------------------------------------------------------------------
# recognize (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_cache_hit(rec: DeepSeekIntentRecognizer) -> None:
    key = _make_intent_cache_key("缓存命中消息")
    cached = {"intent": "products", "slots": {}, "confidence": 0.9}
    ds._intent_recognition_cache.set(key, cached)
    out = await rec.recognize("缓存命中消息")
    assert out == cached


@pytest.mark.asyncio
async def test_recognize_success(rec: DeepSeekIntentRecognizer) -> None:
    key = _make_intent_cache_key("查询产品库存唯一消息x1")
    ds._intent_recognition_cache.delete(key) if hasattr(
        ds._intent_recognition_cache, "delete"
    ) else None
    content = json.dumps({"intent": "products", "confidence": 0.95, "slots": {}})
    mock_call = AsyncMock(return_value={"choices": [{"message": {"content": content}}]})
    with patch("app.infrastructure.llm.invoke.chat_completion_openai_format", mock_call):
        out = await rec.recognize("查询产品库存唯一消息x1")
    assert out["intent"] == "products"
    assert out["source"] == "deepseek"


@pytest.mark.asyncio
async def test_recognize_all_attempts_fail(rec: DeepSeekIntentRecognizer) -> None:
    mock_call = AsyncMock(side_effect=ValueError("api boom"))
    with patch("app.infrastructure.llm.invoke.chat_completion_openai_format", mock_call):
        out = await rec.recognize("会失败的唯一消息x2")
    assert out["intent"] is None
    assert out["reasoning"] == "DeepSeek 识别失败"
