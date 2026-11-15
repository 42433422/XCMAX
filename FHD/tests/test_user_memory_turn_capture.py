"""回合记忆捕获：只沉淀显性长期偏好，重复内容合并。"""

from __future__ import annotations

import pytest

from app.application.user_memory import turn_capture
from app.application.user_memory.retrieve import search


def test_extracts_only_explicit_preference_sentences():
    facts = turn_capture.extract_fact_candidates(
        "我们公司的默认币种是 CNY。帮我看下这张表。以后对账单都按客户名分类。"
    )
    assert facts == ["我们公司的默认币种是 CNY", "以后对账单都按客户名分类"]


def test_caps_at_two_and_ignores_short_or_unmarked():
    facts = turn_capture.extract_fact_candidates(
        "记住。记住客户A按对账单分类。记住客户B按出货单分类。记住客户C按回款分类。"
    )
    assert len(facts) == 2
    assert facts == ["记住客户A按对账单分类", "记住客户B按出货单分类"]


def test_empty_message_returns_nothing():
    assert turn_capture.extract_fact_candidates("") == []
    assert turn_capture.extract_fact_candidates("这张表有多少行？") == []


def test_capture_merges_duplicates(monkeypatch, tmp_path):
    monkeypatch.delenv("XCAGI_MEMORY_CAPTURE", raising=False)
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memory.json"))

    first = turn_capture.capture_turn(user_message="以后对账单都按客户名分类。", owner_id="u1")
    second = turn_capture.capture_turn(user_message="以后对账单都按客户名分类。", owner_id="u1")

    assert len(first) == 1 and first[0]["created"] is True
    assert len(second) == 1 and second[0]["merged"] is True
    hits = search("对账单 客户名 分类", scope="global", owner_id="u1", min_score=0)
    assert len(hits) == 1
    assert hits[0]["text"] == "以后对账单都按客户名分类"


def test_capture_is_disabled_by_flag(monkeypatch):
    monkeypatch.setenv("XCAGI_MEMORY_CAPTURE", "off")
    assert turn_capture.capture_turn(user_message="以后都这样做。", owner_id="u1") == []


def test_capture_requires_owner(monkeypatch):
    monkeypatch.delenv("XCAGI_MEMORY_CAPTURE", raising=False)
    assert turn_capture.capture_turn(user_message="以后都这样做。", owner_id="") == []


def test_capture_swallows_store_failure(monkeypatch):
    monkeypatch.delenv("XCAGI_MEMORY_CAPTURE", raising=False)

    class Boom:
        def get_memory(self, owner):
            raise RuntimeError("disk full")

    assert (
        turn_capture.capture_turn(
            user_message="以后都这样做。", owner_id="u1", store=Boom()
        )
        == []
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
