"""COVERAGE_RAMP C3.1: UserMemoryService 持久化失败 / 反馈统计 / 习惯建议。

覆盖：
- UserMemoryStore 单例化 + 缓存读写
- JSON 加载 / 保存异常回退
- save_memory 触发持久化 (storage_type='json')
- add_preference / get_preference / get_all_preferences
- record_action 创建 / 累加 / 截断到 MAX
- get_recent_actions + intent_filter
- get_similar_pattern：threshold 边界 / 相似度计算
- add_feedback + _adjust_pattern_weights (confirmed/negated/corrected)
- get_feedback_stats（含 error_rates）
- get_habit_suggestions（含 action_sequence）
- apply_preference_to_slots
- get_memory_summary
- get_user_memory_service / reset_user_memory_service
- UserMemory dataclass 序列化 / 反序列化
"""

from __future__ import annotations

import json
import os

import pytest

from app.services import user_memory_service
from app.services.user_memory_service import (
    ActionPattern,
    ContextSummary,
    FeedbackRecord,
    UserMemory,
    UserMemoryService,
    UserMemoryStore,
    get_user_memory_service,
    reset_user_memory_service,
)


@pytest.fixture
def tmp_memory_dir(monkeypatch, tmp_path):
    """重定向 MEMORY_DIR 到 tmp，隔离持久化文件。"""
    monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(
        user_memory_service,
        "JSON_MEMORY_PATH",
        os.path.join(str(tmp_path), "memory_store.json"),
    )
    # 重置单例以使新路径生效
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    yield tmp_path
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)


@pytest.fixture
def fresh_service():
    """重置 user_memory_service 单例。"""
    user_memory_service._user_memory_service = None
    user_memory_service.UserMemoryService._instance = None
    user_memory_service.UserMemoryStore._instance = None
    yield
    user_memory_service._user_memory_service = None
    user_memory_service.UserMemoryService._instance = None
    user_memory_service.UserMemoryStore._instance = None


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


def test_get_and_reset_user_memory_service():
    reset_user_memory_service()
    a = get_user_memory_service()
    b = get_user_memory_service()
    assert a is b
    reset_user_memory_service()
    c = get_user_memory_service()
    assert c is not a


# ---------------------------------------------------------------------------
# UserMemoryStore
# ---------------------------------------------------------------------------


def test_store_loads_from_missing_file(tmp_memory_dir):
    store = UserMemoryStore(storage_type="json")
    assert store._memory_cache == {}


def test_store_loads_corrupt_file_falls_back_to_empty(tmp_memory_dir, caplog):
    p = os.path.join(str(tmp_memory_dir), "memory_store.json")
    with open(p, "w") as f:
        f.write("{not valid json")
    store = UserMemoryStore(storage_type="json")
    assert store._memory_cache == {}


def test_store_saves_to_disk(tmp_memory_dir):
    store = UserMemoryStore(storage_type="json")
    mem = UserMemory(user_id="u-1", preferences={"x": {"value": 1, "updated_at": "t", "count": 1}})
    store.save_memory("u-1", mem)
    # 显式触发 _should_persist
    store._save_all_memories()
    assert os.path.exists(os.path.join(str(tmp_memory_dir), "memory_store.json"))
    with open(os.path.join(str(tmp_memory_dir), "memory_store.json")) as f:
        data = json.load(f)
    assert "u-1" in data


def test_store_non_json_storage_skips_save(tmp_memory_dir):
    store = UserMemoryStore(storage_type="sqlite")
    store._save_all_memories()  # 不写文件
    assert not os.path.exists(os.path.join(str(tmp_memory_dir), "memory_store.json"))


def test_store_get_memory_creates_if_missing(tmp_memory_dir):
    store = UserMemoryStore(storage_type="json")
    mem = store.get_memory("u-new")
    assert mem is not None
    assert mem.user_id == "u-new"


def test_store_singleton(tmp_memory_dir):
    a = UserMemoryStore()
    b = UserMemoryStore()
    assert a is b


# ---------------------------------------------------------------------------
# UserMemory dataclass
# ---------------------------------------------------------------------------


def test_user_memory_to_from_dict():
    m = UserMemory(user_id="u", preferences={"k": {"value": 1, "updated_at": "t", "count": 1}})
    d = m.to_dict()
    assert d["user_id"] == "u"
    m2 = UserMemory.from_dict(d)
    assert m2.user_id == "u"


def test_action_pattern_to_from_dict():
    ap = ActionPattern(pattern="p", intent="i", slots={})
    d = ap.to_dict()
    ap2 = ActionPattern.from_dict(d)
    assert ap2.pattern == "p"


def test_feedback_record_to_from_dict():
    fr = FeedbackRecord(
        timestamp="t", message="m", recognized_intent="i", user_feedback="confirmed"
    )
    d = fr.to_dict()
    fr2 = FeedbackRecord.from_dict(d)
    assert fr2.message == "m"


def test_context_summary_to_from_dict():
    cs = ContextSummary(timestamp="t", intent="i", slots={"k": 1}, message="m")
    d = cs.to_dict()
    cs2 = ContextSummary.from_dict(d)
    assert cs2.slots == {"k": 1}


# ---------------------------------------------------------------------------
# UserMemoryService.add_preference / get_preference
# ---------------------------------------------------------------------------


def test_add_and_get_preference(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "favorite_customer", "ACME")
    assert svc.get_preference("u1", "favorite_customer") == "ACME"


def test_get_preference_default(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    assert svc.get_preference("u1", "missing", default="d") == "d"


def test_get_all_preferences(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "k1", "v1")
    svc.add_preference("u1", "k2", "v2")
    prefs = svc.get_all_preferences("u1")
    assert prefs == {"k1": "v1", "k2": "v2"}


def test_get_all_preferences_empty(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    assert svc.get_all_preferences("never_used") == {}


# ---------------------------------------------------------------------------
# record_action
# ---------------------------------------------------------------------------


def test_record_action_creates_and_accumulates(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"unit_name": "ACME"}, "msg")
    svc.record_action("u1", "shipment_generate", {"unit_name": "ACME"}, "msg")
    actions = svc.get_recent_actions("u1", limit=5)
    assert len(actions) == 1
    assert actions[0]["frequency"] == 2
    assert actions[0]["confidence"] > 0.5


def test_record_action_caps_at_max(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    for i in range(user_memory_service.MAX_FREQUENT_ACTIONS + 5):
        svc.record_action("u1", "int", {"unit_name": str(i)}, f"m{i}")
    actions = svc.get_recent_actions("u1", limit=100)
    assert len(actions) == user_memory_service.MAX_FREQUENT_ACTIONS


def test_get_recent_actions_with_intent_filter(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"x": "1"}, "m")
    svc.record_action("u1", "product_query", {"x": "2"}, "m")
    out = svc.get_recent_actions("u1", limit=10, intent_filter="product_query")
    assert len(out) == 1
    assert out[0]["intent"] == "product_query"


def test_get_recent_actions_empty(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    assert svc.get_recent_actions("never_used") == []


# ---------------------------------------------------------------------------
# get_similar_pattern
# ---------------------------------------------------------------------------


def test_get_similar_pattern_match_high(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"unit_name": "ACME", "model_number": "M-1"}, "m")
    out = svc.get_similar_pattern(
        "u1", "shipment_generate", {"unit_name": "ACME", "model_number": "M-1"}
    )
    assert out is not None
    assert "match_score" in out


def test_get_similar_pattern_no_match_below_threshold(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"unit_name": "A"}, "m")
    out = svc.get_similar_pattern("u1", "shipment_generate", {"unit_name": "B"}, threshold=0.99)
    assert out is None


def test_get_similar_pattern_different_intent_returns_none(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"unit_name": "A"}, "m")
    out = svc.get_similar_pattern("u1", "product_query", {"unit_name": "A"})
    assert out is None


def test_get_similar_pattern_no_user_returns_none(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    out = svc.get_similar_pattern("never_used", "x", {})
    assert out is None


# ---------------------------------------------------------------------------
# add_feedback + _adjust_pattern_weights
# ---------------------------------------------------------------------------


def test_add_feedback_confirmed_increases_confidence(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"x": "1"}, "m")
    svc.add_feedback("u1", "msg", "shipment_generate", "confirmed")
    actions = svc.get_recent_actions("u1", limit=10)
    assert actions[0]["confidence"] > 0.5


def test_add_feedback_negated_decreases_confidence(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"x": "1"}, "m")
    initial_conf = svc.get_recent_actions("u1", limit=10)[0]["confidence"]
    svc.add_feedback("u1", "msg", "shipment_generate", "negated")
    new_conf = svc.get_recent_actions("u1", limit=10)[0]["confidence"]
    assert new_conf < initial_conf


def test_add_feedback_corrected_changes_target(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"x": "1"}, "m")
    svc.add_feedback(
        "u1", "msg", "shipment_generate", "corrected", corrected_intent="product_query"
    )
    actions = svc.get_recent_actions("u1", limit=10)
    assert actions[0]["confidence"] <= 0.5  # 因 weight_delta=-0.1（0.6→0.5）


def test_add_feedback_unknown_type_no_change(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.record_action("u1", "shipment_generate", {"x": "1"}, "m")
    initial_conf = svc.get_recent_actions("u1", limit=10)[0]["confidence"]
    svc.add_feedback("u1", "msg", "shipment_generate", "weird_type")
    new_conf = svc.get_recent_actions("u1", limit=10)[0]["confidence"]
    assert new_conf == initial_conf


def test_add_feedback_no_user_creates_memory(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_feedback("new-u", "msg", "i", "confirmed")
    assert svc.get_feedback_stats("new-u")["total"] == 1


# ---------------------------------------------------------------------------
# get_feedback_stats
# ---------------------------------------------------------------------------


def test_get_feedback_stats_no_user(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    out = svc.get_feedback_stats("never_used")
    assert out["total"] == 0
    assert out["confirmed"] == 0
    assert out["negated"] == 0
    assert out["corrected"] == 0


def test_get_feedback_stats_with_intent_error_rate(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    for _ in range(3):
        svc.add_feedback("u1", "msg", "intent-x", "confirmed")
    for _ in range(2):
        svc.add_feedback("u1", "msg", "intent-x", "negated")
    stats = svc.get_feedback_stats("u1")
    assert stats["total"] == 5
    assert stats["confirmed"] == 3
    assert stats["negated"] == 2
    # intent-x: total=5, errors=2 → error_rate=0.4 (>= 3 总数才计算)
    assert "intent-x" in stats["error_rates"]


def test_get_feedback_stats_skips_intent_below_min_total(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_feedback("u1", "msg", "rare", "negated")
    stats = svc.get_feedback_stats("u1")
    # total < 3 -> 不会进 error_rates
    assert "rare" not in stats["error_rates"]


# ---------------------------------------------------------------------------
# get_habit_suggestions / _analyze_action_sequence
# ---------------------------------------------------------------------------


def test_get_habit_suggestions_no_user(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    assert svc.get_habit_suggestions("never_used") == []


def test_get_habit_suggestions_with_sequence(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    # 模拟两个连续动作 (出现在 historical_contexts)
    svc.record_action("u1", "intent-a", {"x": "1"}, "m1")
    svc.record_action("u1", "intent-b", {"x": "2"}, "m2")
    # 再次触发使其计数 2
    svc.record_action("u1", "intent-a", {"x": "1"}, "m1")
    svc.record_action("u1", "intent-b", {"x": "2"}, "m2")
    suggestions = svc.get_habit_suggestions("u1")
    # 至少有一条 action_sequence 建议（conf 0.3 < 0.8 时不返回；count=2 时 conf=0.3）
    # 实现：seq["confidence"] = min(0.95, 2 * 0.15) = 0.3
    # 0.3 < 0.8 阈值 → 不会出
    assert suggestions == []


def test_get_habit_suggestions_high_confidence(fresh_service, tmp_memory_dir, monkeypatch):
    """手动构造 high-confidence 序列。"""
    monkeypatch.setattr(user_memory_service, "MAX_CONTEXT_SUMMARIES", 50)
    svc = UserMemoryService(storage_type="json")
    for _ in range(6):
        svc.record_action("u1", "intent-a", {"x": "1"}, "m1")
        svc.record_action("u1", "intent-b", {"x": "2"}, "m2")
    suggestions = svc.get_habit_suggestions("u1")
    # count=6 → conf = min(0.95, 6*0.15) = 0.9 ≥ 0.8
    assert any("intent-b" in s["actions"] for s in suggestions)


# ---------------------------------------------------------------------------
# apply_preference_to_slots
# ---------------------------------------------------------------------------


def test_apply_preference_to_slots_fills_missing(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "favorite_customer", "ACME")
    out = svc.apply_preference_to_slots("u1", "shipment_generate", {})
    assert out["unit_name"] == "ACME"


def test_apply_preference_to_slots_keeps_existing(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "favorite_customer", "ACME")
    out = svc.apply_preference_to_slots("u1", "shipment_generate", {"unit_name": "EXIST"})
    assert out["unit_name"] == "EXIST"


def test_apply_preference_to_slots_fills_template(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "default_template", "TPL-001")
    out = svc.apply_preference_to_slots("u1", "x", {"unit_name": "A"})
    assert out["template"] == "TPL-001"


# ---------------------------------------------------------------------------
# get_memory_summary
# ---------------------------------------------------------------------------


def test_get_memory_summary_no_user(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    out = svc.get_memory_summary("never_used")
    # get_memory() JIT-creates an empty UserMemory for unknown ids
    assert out["has_memory"] is True
    assert out["preference_count"] == 0
    assert out["action_count"] == 0
    assert out["feedback_count"] == 0


def test_get_memory_summary_with_data(fresh_service, tmp_memory_dir):
    svc = UserMemoryService(storage_type="json")
    svc.add_preference("u1", "k1", "v1")
    svc.record_action("u1", "i1", {"x": "1"}, "m1")
    out = svc.get_memory_summary("u1")
    assert out["has_memory"] is True
    assert out["preference_count"] == 1
    assert out["action_count"] == 1
    assert "i1" in out["top_intents"]
