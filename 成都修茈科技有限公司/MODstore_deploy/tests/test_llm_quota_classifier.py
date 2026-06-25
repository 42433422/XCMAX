"""Tests for modstore_server.llm_quota.is_quota_exhausted.

Guards the regression that caused the production malignant idle spin: LLM quota
403s being read as prompt-quality failures by the evolution engine.
"""

from __future__ import annotations

from modstore_server.llm_quota import is_quota_exhausted


def test_canonical_production_403_message():
    # quota_middleware.require_llm_credit raises HTTPException(403, "配额不足: llm_calls")
    assert is_quota_exhausted("配额不足: llm_calls") is True


def test_proxy_result_dict_status_403():
    assert is_quota_exhausted({"ok": False, "status": 403, "error": "forbidden"}) is True


def test_proxy_result_dict_status_402_payment_required():
    assert is_quota_exhausted({"ok": False, "status": 402, "error": "billing"}) is True


def test_english_insufficient_quota():
    assert is_quota_exhausted("Error: insufficient_quota — exceeded your current quota") is True


def test_exception_with_status_code_attribute():
    exc = RuntimeError("nope")
    exc.status_code = 403  # type: ignore[attr-defined]
    assert is_quota_exhausted(exc) is True


def test_runtime_error_carrying_quota_text():
    # _PlatformBenchLlmClient.chat() raises RuntimeError(str(out["error"]))
    assert is_quota_exhausted(RuntimeError("配额不足: llm_calls")) is True


def test_genuine_prompt_failure_is_not_quota():
    # A real refine/parse failure must NOT be classified as quota — otherwise the
    # engine would stop refining prompts it actually should refine.
    assert is_quota_exhausted("JSON 解析失败: unexpected token at line 3") is False


def test_ordinary_5xx_is_not_quota():
    assert is_quota_exhausted({"ok": False, "status": 503, "error": "upstream down"}) is False


def test_none_and_empty_are_not_quota():
    assert is_quota_exhausted(None) is False
    assert is_quota_exhausted("") is False
    assert is_quota_exhausted({}) is False
