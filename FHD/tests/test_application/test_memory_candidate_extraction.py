"""Mature extraction/parsing must preserve pending facts and personal subjects."""

from __future__ import annotations

import json

import pytest

from app.infrastructure.memory.candidate_extraction import extract_candidates
from app.infrastructure.memory.mem0_backend import Mem0LongTermMemory


@pytest.fixture
def completion(monkeypatch):
    pytest.importorskip("mem0.configs.prompts")
    replies = {"raw": '{"memory": []}', "calls": []}
    provider = object()
    monkeypatch.setattr(
        "app.infrastructure.llm.knowledge_answer.platform_provider", lambda: provider
    )

    def complete(messages, **kwargs):
        assert kwargs["provider"] is provider
        replies["calls"].append(messages)
        return replies["raw"]

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_text_sync", complete)
    return replies


def test_native_prompt_preserves_separate_projects_and_only_receives_user_text(completion):
    completion["raw"] = json.dumps(
        {
            "memory": [
                {"text": "甲项目的预算是50万元", "memory_type": "entity", "subject": "甲项目"},
                {"text": "乙项目的预算是80万元", "memory_type": "entity", "subject": "乙项目"},
            ]
        },
        ensure_ascii=False,
    )
    result = Mem0LongTermMemory().extract_candidates(
        user_id="scoped-owner",
        user_message="甲项目预算50万元，乙项目预算80万元",
        assistant_message="未经确认的助手建议999万元",
    )
    assert len(result) == 2
    assert result[0]["key"] != result[1]["key"]
    assert [row["value"]["subject"] for row in result] == ["甲项目", "乙项目"]
    assert all(row["value"]["extraction_backend"] == "mem0" for row in result)
    prompt = str(completion["calls"])
    assert "甲项目预算50万元" in prompt
    assert "未经确认的助手建议999万元" not in prompt
    assert "hypothetical" in prompt


def test_personal_preference_keeps_explicit_subject(completion):
    completion["raw"] = json.dumps(
        {
            "memory": [
                {"text": "我喜欢简洁的报告", "memory_type": "preference", "subject": "user"},
                {"text": "客户甲喜欢详细报告", "memory_type": "preference", "subject": "客户甲"},
            ]
        },
        ensure_ascii=False,
    )
    result = extract_candidates("我喜欢简洁的报告，客户甲喜欢详细报告")
    assert result[0]["memory_type"] == "preference"
    assert result[0]["value"]["subject"] == "user"
    assert result[1]["value"]["subject"] == "客户甲"


def test_model_empty_result_is_distinct_from_unavailable(completion, monkeypatch):
    assert extract_candidates("预算是不是可以改成80万元？") == []
    monkeypatch.setattr("app.infrastructure.llm.knowledge_answer.platform_provider", lambda: None)
    assert extract_candidates("我的预算是80万元") is None


@pytest.mark.parametrize(
    "raw",
    [
        "invalid json",
        '{"memory":[{"text":42}]}',
        '{"memory":[{"text":"假设预算80万","event":"UPDATE"}]}',
        json.dumps({"memory": [{"text": "x"}] * 9}),
    ],
)
def test_invalid_model_output_does_not_become_a_candidate(completion, raw):
    completion["raw"] = raw
    assert extract_candidates("如果预算80万元怎么办") is None


def test_repeated_model_items_are_deduplicated(completion):
    completion["raw"] = '{"memory":[{"text":"预算80万元"},{"text":"预算80万元"}]}'
    result = extract_candidates("预算80万元")
    assert len(result) == 1
    assert result[0]["memory_type"] == "entity"


def test_provider_failure_allows_only_explicit_offline_fallback(completion, monkeypatch):
    def unavailable(*args, **kwargs):
        raise TimeoutError("configured provider unavailable")

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_text_sync", unavailable)
    assert extract_candidates("记住我的报告偏好") is None
