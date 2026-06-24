"""员工运行时 LLM 计费桥测试。"""

from __future__ import annotations

from typing import Any

import app.application.employee_runtime.billing as billing


class _FakeUsage:
    def __init__(self, p, c, t):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = t


class _FakeCompletion:
    def __init__(self, p, c, t, model):
        self.usage = _FakeUsage(p, c, t)
        self.model = model


def _capture(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.infrastructure.billing.model_usage.record_model_usage",
        lambda **kw: calls.append(kw) or {"usage_id": "x"},
    )
    return calls


def test_bill_from_dict_attributes_to_context_user(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    token = billing.begin_employee_billing(user_id=7, run_id="s1", employee_id="cs-officer")
    try:
        billing.bill_employee_llm_from_dict(
            {
                "model": "deepseek-chat",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
            source="employee_runtime.cognition",
        )
    finally:
        billing.end_employee_billing(token)

    assert len(calls) == 1
    kw = calls[0]
    assert kw["user_id"] == "7"
    assert kw["total_tokens"] == 30
    assert kw["model"] == "deepseek-chat"
    assert kw["source"] == "employee_runtime.cognition"
    assert kw["provider"] == "employee_runtime"


def test_bill_from_completion(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    token = billing.begin_employee_billing(user_id=42, run_id="s2", employee_id="emp")
    try:
        billing.bill_employee_llm_from_completion(_FakeCompletion(5, 7, 12, "gpt-x"))
    finally:
        billing.end_employee_billing(token)

    assert calls[0]["user_id"] == "42"
    assert calls[0]["total_tokens"] == 12
    assert calls[0]["model"] == "gpt-x"


def test_no_tokens_not_billed(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    token = billing.begin_employee_billing(user_id=7)
    try:
        billing.bill_employee_llm_from_dict({"error": "boom"})  # 出错响应无 usage
    finally:
        billing.end_employee_billing(token)
    assert calls == []


def test_context_resets_no_leak(monkeypatch) -> None:
    calls = _capture(monkeypatch)
    token = billing.begin_employee_billing(user_id=7, run_id="s1")
    billing.end_employee_billing(token)
    # 复位后再计费 → user_id 不应残留为 7
    billing.bill_employee_llm_from_dict({"usage": {"total_tokens": 5}})
    assert calls[0]["user_id"] == ""
