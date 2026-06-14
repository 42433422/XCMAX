"""COVERAGE_RAMP Phase 4 round 18: user_memory store + service (21.5%→)."""

from __future__ import annotations

import os

import pytest

import app.utils.user_memory as um
from app.utils.user_memory import (
    ActionPattern,
    ContextSummary,
    FeedbackRecord,
    UserMemory,
)


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(um, "MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setattr(um, "JSON_MEMORY_PATH", str(tmp_path / "mem" / "store.json"))
    um.UserMemoryStore._instance = None
    um.UserMemoryService._instance = None
    um.reset_user_memory_service()
    svc = um.UserMemoryService(storage_type="json")
    yield svc
    um.UserMemoryStore._instance = None
    um.UserMemoryService._instance = None
    um.reset_user_memory_service()


# ---------------------------------------------------------------------------
# dataclasses
# ---------------------------------------------------------------------------


def test_action_pattern_roundtrip() -> None:
    p = ActionPattern(pattern="k", intent="order", slots={"a": 1}, frequency=2, confidence=0.7)
    d = p.to_dict()
    assert d["intent"] == "order"
    assert ActionPattern.from_dict(d).pattern == "k"


def test_feedback_record_roundtrip() -> None:
    r = FeedbackRecord(
        timestamp="t", message="m", recognized_intent="order", user_feedback="confirmed"
    )
    assert FeedbackRecord.from_dict(r.to_dict()).user_feedback == "confirmed"


def test_context_summary_roundtrip() -> None:
    c = ContextSummary(timestamp="t", intent="order", slots={}, message="hi")
    assert ContextSummary.from_dict(c.to_dict()).intent == "order"


def test_user_memory_roundtrip() -> None:
    m = UserMemory(user_id="u1")
    assert UserMemory.from_dict(m.to_dict()).user_id == "u1"


# ---------------------------------------------------------------------------
# preferences
# ---------------------------------------------------------------------------


def test_preferences_add_get_all(mem) -> None:
    mem.add_preference("u1", "favorite_customer", "七彩")
    assert mem.get_preference("u1", "favorite_customer") == "七彩"
    assert mem.get_preference("u1", "missing", default="d") == "d"
    mem.add_preference("u1", "default_template", "T1")
    allp = mem.get_all_preferences("u1")
    assert allp["favorite_customer"] == "七彩"
    assert allp["default_template"] == "T1"


def test_preferences_count_increments(mem) -> None:
    mem.add_preference("u1", "k", "v1")
    mem.add_preference("u1", "k", "v2")
    memory = mem._store.get_memory("u1")
    assert memory.preferences["k"]["count"] == 2


def test_preferences_persisted_to_disk(mem) -> None:
    mem.add_preference("u1", "k", "v")
    assert os.path.exists(um.JSON_MEMORY_PATH)


# ---------------------------------------------------------------------------
# record_action / recent / pattern key
# ---------------------------------------------------------------------------


def test_record_action_new_and_existing(mem) -> None:
    mem.record_action("u1", "order", {"unit_name": "七彩"}, message="买货")
    mem.record_action("u1", "order", {"unit_name": "七彩"}, message="再买")
    actions = mem.get_recent_actions("u1")
    assert len(actions) == 1
    assert actions[0]["frequency"] == 2
    assert actions[0]["confidence"] > 0.5


def test_get_recent_actions_intent_filter(mem) -> None:
    mem.record_action("u1", "order", {"product_name": "A"})
    mem.record_action("u1", "shipment", {"product_name": "B"})
    assert len(mem.get_recent_actions("u1", intent_filter="order")) == 1
    assert len(mem.get_recent_actions("u1", limit=10)) == 2


def test_make_pattern_key_stable(mem) -> None:
    k1 = mem._make_pattern_key("order", {"unit_name": "X", "product_name": "Y"})
    k2 = mem._make_pattern_key("order", {"unit_name": "X", "product_name": "Y"})
    assert k1 == k2 and len(k1) == 16


# ---------------------------------------------------------------------------
# similar pattern + similarity
# ---------------------------------------------------------------------------


def test_get_similar_pattern_match(mem) -> None:
    mem.record_action("u1", "order", {"unit_name": "七彩", "product_name": "苹果"})
    match = mem.get_similar_pattern("u1", "order", {"unit_name": "七彩", "product_name": "苹果"})
    assert match is not None
    assert match["match_score"] >= 0.2


def test_get_similar_pattern_no_match(mem) -> None:
    mem.record_action("u1", "order", {"unit_name": "七彩"})
    assert mem.get_similar_pattern("u1", "shipment", {"unit_name": "七彩"}) is None


def test_calculate_similarity_variants(mem) -> None:
    assert mem._calculate_similarity({}, {}) == 1.0
    assert mem._calculate_similarity({"x": 1}, {"y": 2}) == 0.5  # no important-key overlap
    full = mem._calculate_similarity({"unit_name": "A"}, {"unit_name": "A"})
    assert full == 1.0
    half = mem._calculate_similarity(
        {"unit_name": "A", "spec": "S1"}, {"unit_name": "A", "spec": "S2"}
    )
    assert half == 0.5


# ---------------------------------------------------------------------------
# feedback + stats + weight adjust
# ---------------------------------------------------------------------------


def test_add_feedback_and_stats(mem) -> None:
    mem.record_action("u1", "order", {"unit_name": "七彩"})
    for _ in range(3):
        mem.add_feedback("u1", "买货", "order", "negated", slots={"unit_name": "七彩"})
    stats = mem.get_feedback_stats("u1")
    assert stats["total"] == 3
    assert stats["negated"] == 3
    assert stats["error_rates"]["order"] == 1.0


def test_add_feedback_confirmed_and_corrected(mem) -> None:
    mem.record_action("u1", "order", {"unit_name": "七彩"})
    mem.add_feedback("u1", "m", "order", "confirmed")
    mem.add_feedback("u1", "m", "order", "corrected", corrected_intent="shipment")
    stats = mem.get_feedback_stats("u1")
    assert stats["confirmed"] == 1
    assert stats["corrected"] == 1


# ---------------------------------------------------------------------------
# habit suggestions / sequence
# ---------------------------------------------------------------------------


def test_analyze_action_sequence_and_suggestions(mem) -> None:
    memory = mem._store.get_memory("u1")
    memory.historical_contexts = [
        {"intent": "order"} if i % 2 == 0 else {"intent": "print"} for i in range(14)
    ]
    seqs = mem._analyze_action_sequence(memory)
    assert any(s["count"] >= 2 for s in seqs)
    suggestions = mem.get_habit_suggestions("u1")
    assert suggestions
    assert suggestions[0]["type"] == "action_sequence"


def test_get_habit_suggestions_empty(mem) -> None:
    mem.record_action("u1", "order", {})
    assert mem.get_habit_suggestions("u1") == []


# ---------------------------------------------------------------------------
# apply preference / summary
# ---------------------------------------------------------------------------


def test_apply_preference_to_slots(mem) -> None:
    mem.add_preference("u1", "favorite_customer", "七彩")
    mem.add_preference("u1", "default_template", "T1")
    filled = mem.apply_preference_to_slots("u1", "order", {})
    assert filled["unit_name"] == "七彩"
    assert filled["template"] == "T1"


def test_apply_preference_keeps_existing(mem) -> None:
    mem.add_preference("u1", "favorite_customer", "七彩")
    filled = mem.apply_preference_to_slots("u1", "order", {"unit_name": "已有"})
    assert filled["unit_name"] == "已有"


def test_get_memory_summary(mem) -> None:
    mem.add_preference("u1", "k", "v")
    mem.record_action("u1", "order", {"unit_name": "X"})
    summary = mem.get_memory_summary("u1")
    assert summary["has_memory"] is True
    assert summary["preference_count"] == 1
    assert summary["action_count"] == 1
    assert "order" in summary["top_intents"]


# ---------------------------------------------------------------------------
# singleton accessors + non-json backend
# ---------------------------------------------------------------------------


def test_get_user_memory_service_singleton(mem) -> None:
    a = um.get_user_memory_service()
    b = um.get_user_memory_service()
    assert a is b
    um.reset_user_memory_service()
    assert um._user_memory_service is None


def test_non_json_backend_skips_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(um, "MEMORY_DIR", str(tmp_path / "m2"))
    monkeypatch.setattr(um, "JSON_MEMORY_PATH", str(tmp_path / "m2" / "store.json"))
    um.UserMemoryStore._instance = None
    um.UserMemoryService._instance = None
    um.reset_user_memory_service()
    try:
        svc = um.UserMemoryService(storage_type="sqlite")
        svc.add_preference("u1", "k", "v")
        assert not os.path.exists(um.JSON_MEMORY_PATH)
    finally:
        um.UserMemoryStore._instance = None
        um.UserMemoryService._instance = None
        um.reset_user_memory_service()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
