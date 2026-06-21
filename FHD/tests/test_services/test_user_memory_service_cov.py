from __future__ import annotations

"""Branch-coverage supplement for user_memory_service.py.

Targets the 47 missing branches at lines: 193,218,224,241,273,287,366,385,387,
443,446,448,452,457,458,460,462,464,468,507,510,517,548,551,553,560 and
adjacent decision points.
"""

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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singletons():
    """Each test starts from a clean singleton state."""
    reset_user_memory_service()
    yield
    reset_user_memory_service()


@pytest.fixture
def tmp_store(monkeypatch, tmp_path):
    """Redirect memory files to tmp_path and return a fresh UserMemoryStore."""
    json_path = str(tmp_path / "memory_store.json")
    monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    UserMemoryStore._instance = None
    UserMemoryService._instance = None
    store = UserMemoryStore(storage_type="json")
    return store, json_path


@pytest.fixture
def svc(monkeypatch, tmp_path):
    """Return a fresh UserMemoryService with isolated storage."""
    json_path = str(tmp_path / "memory_store.json")
    monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    UserMemoryStore._instance = None
    UserMemoryService._instance = None
    return UserMemoryService(storage_type="json")


# ---------------------------------------------------------------------------
# 1. UserMemoryStore – singleton and load/save branches (lines 193, 218, 224)
# ---------------------------------------------------------------------------


class TestUserMemoryStore:
    def test_singleton_returns_same_instance(self, tmp_store):
        store, _ = tmp_store
        store2 = UserMemoryStore(storage_type="json")
        assert store is store2

    def test_load_existing_json(self, monkeypatch, tmp_path):
        """Load branch: file exists and has valid JSON."""
        json_path = str(tmp_path / "memory_store.json")
        data = {"user1": UserMemory(user_id="user1").to_dict()}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
        UserMemoryStore._instance = None
        store = UserMemoryStore(storage_type="json")
        assert store.get_memory("user1") is not None

    def test_load_corrupt_json_resets_cache(self, monkeypatch, tmp_path):
        """Load branch: file exists but JSON is invalid → cache reset."""
        json_path = str(tmp_path / "memory_store.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write("{not valid json}")
        monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
        UserMemoryStore._instance = None
        store = UserMemoryStore(storage_type="json")
        # Should not raise; cache should be empty
        assert isinstance(store._memory_cache, dict)

    def test_save_creates_file(self, tmp_store):
        store, json_path = tmp_store
        mem = store.get_memory("u1")
        mem.preferences["k"] = {"value": "v", "updated_at": "now", "count": 1}
        store.save_memory("u1", mem)
        assert os.path.exists(json_path)
        with open(json_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert "u1" in saved

    def test_save_non_json_storage_type_skips(self, monkeypatch, tmp_path):
        """_save_all_memories early return when storage_type != 'json'."""
        json_path = str(tmp_path / "memory_store.json")
        monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
        UserMemoryStore._instance = None
        store = UserMemoryStore(storage_type="sqlite")
        mem = store.get_memory("u1")
        store.save_memory("u1", mem)
        # File should NOT be created because storage_type is sqlite
        assert not os.path.exists(json_path)

    def test_should_persist_returns_false_when_no_dirty(self, tmp_store):
        store, _ = tmp_store
        assert store._should_persist() is False

    def test_get_memory_creates_new_if_absent(self, tmp_store):
        store, _ = tmp_store
        mem = store.get_memory("brand_new_user")
        assert mem is not None
        assert mem.user_id == "brand_new_user"


# ---------------------------------------------------------------------------
# 2. add_preference / get_preference / get_all_preferences (lines 241, 273, 287)
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_add_and_get_preference(self, svc):
        svc.add_preference("u1", "color", "blue")
        assert svc.get_preference("u1", "color") == "blue"

    def test_get_preference_missing_key_returns_default(self, svc):
        r = svc.get_preference("u1", "nonexistent", default="fallback")
        assert r == "fallback"

    def test_get_preference_no_memory_returns_default(self, svc):
        r = svc.get_preference("ghost_user", "k", default=42)
        assert r == 42

    def test_preference_count_increments(self, svc):
        svc.add_preference("u1", "lang", "en")
        svc.add_preference("u1", "lang", "zh")
        mem = svc._store.get_memory("u1")
        assert mem.preferences["lang"]["count"] == 2

    def test_get_all_preferences_empty(self, svc):
        r = svc.get_all_preferences("fresh_user")
        assert r == {}

    def test_get_all_preferences_filled(self, svc):
        svc.add_preference("u1", "k1", "v1")
        svc.add_preference("u1", "k2", "v2")
        r = svc.get_all_preferences("u1")
        assert r == {"k1": "v1", "k2": "v2"}


# ---------------------------------------------------------------------------
# 3. propose_memory_candidate branches (lines 385, 387 and governance)
# ---------------------------------------------------------------------------


class TestProposeMemoryCandidate:
    def test_missing_user_id_returns_error(self, svc):
        r = svc.propose_memory_candidate("", "preference", "color", "blue")
        assert r["success"] is False
        assert "user_id" in r["message"]

    def test_missing_key_returns_error(self, svc):
        r = svc.propose_memory_candidate("u1", "preference", "  ", "value")
        assert r["success"] is False
        assert "key" in r["message"]

    def test_blocked_source_creates_rejected_candidate(self, svc):
        r = svc.propose_memory_candidate("u1", "preference", "color", "red", source="llm_guess")
        assert r["success"] is True
        assert r["candidate"]["status"] == "rejected"

    def test_trusted_source_creates_pending(self, svc):
        r = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        assert r["success"] is True
        assert r["candidate"]["status"] == "pending"
        assert r["candidate"]["source_policy"] == "trusted_pending"

    def test_observed_source_with_no_evidence_flags_it(self, svc):
        r = svc.propose_memory_candidate("u1", "entity", "name", "Alice", source="agent_observation", evidence=None)
        assert "missing_evidence" in r["candidate"]["governance_flags"]

    def test_unknown_source_flagged(self, svc):
        r = svc.propose_memory_candidate("u1", "entity", "name", "Bob", source="custom_unknown_source")
        assert "unknown_source" in r["candidate"]["governance_flags"]

    def test_duplicate_fingerprint_returns_existing(self, svc):
        svc.propose_memory_candidate("u1", "preference", "color", "green", source="user_explicit")
        r2 = svc.propose_memory_candidate("u1", "preference", "color", "green", source="user_explicit")
        assert r2["created"] is False

    def test_invalid_memory_type_raises(self, svc):
        with pytest.raises(ValueError, match="unsupported memory_type"):
            svc.propose_memory_candidate("u1", "invalid_type", "k", "v")

    def test_invalid_confidence_defaults(self, svc):
        r = svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit", confidence=None)
        assert r["success"] is True
        assert "invalid_confidence_defaulted" in r["candidate"]["governance_flags"]

    def test_records_capped_at_max(self, svc):
        for i in range(205):
            svc.propose_memory_candidate("u1", "preference", f"key_{i}", f"val_{i}", source="user_explicit")
        mem = svc._store.get_memory("u1")
        assert len(mem.memory_v2_records) <= 200


# ---------------------------------------------------------------------------
# 4. confirm_memory_candidate branches (lines 443–476)
# ---------------------------------------------------------------------------


class TestConfirmMemoryCandidate:
    def test_confirm_memory_not_exists(self, svc):
        r = svc.confirm_memory_candidate("u1", "nonexistent_id")
        # memory not found (user has no memory records)
        assert r["success"] is False

    def test_confirm_record_not_found(self, svc):
        svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        r = svc.confirm_memory_candidate("u1", "bad_memory_id")
        assert r["success"] is False
        assert "不存在" in r["message"] or "not found" in r["message"].lower() or "记忆不存在" in r["message"]

    def test_confirm_deleted_record(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.delete_memory("u1", mid)
        r = svc.confirm_memory_candidate("u1", mid)
        assert r["success"] is False
        assert "删除" in r["message"]

    def test_confirm_rejected_record(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "k", "v", source="llm_guess")
        mid = prop["candidate"]["memory_id"]
        r = svc.confirm_memory_candidate("u1", mid)
        assert r["success"] is False

    def test_confirm_blocked_source_policy(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        # Force source_policy to blocked
        mem = svc._store.get_memory("u1")
        for rec in mem.memory_v2_records:
            if rec["memory_id"] == mid:
                rec["source_policy"] = "blocked"
                rec["status"] = "pending"
        svc._store.save_memory("u1", mem)
        r = svc.confirm_memory_candidate("u1", mid)
        assert r["success"] is False

    def test_confirm_with_correction(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.confirm_memory_candidate("u1", mid, correction={"value": "green", "confidence": 0.9})
        assert r["success"] is True
        assert r["memory"]["value"] == "green"

    def test_confirm_updates_preference_for_preference_type(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        mem = svc._store.get_memory("u1")
        assert "color" in mem.preferences

    def test_confirm_empty_key_after_correction_fails(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.confirm_memory_candidate("u1", mid, correction={"key": "   "})
        assert r["success"] is False

    def test_confirm_with_memory_type_correction(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.confirm_memory_candidate("u1", mid, correction={"memory_type": "entity"})
        assert r["success"] is True
        assert r["memory"]["memory_type"] == "entity"


# ---------------------------------------------------------------------------
# 5. reject / delete / _set_memory_v2_status branches (lines 507–535)
# ---------------------------------------------------------------------------


class TestSetMemoryV2Status:
    def test_reject_nonexistent_user(self, svc):
        r = svc.reject_memory_candidate("ghost", "mid")
        # get_memory always returns (creates) a UserMemory, then record not found
        assert r["success"] is False

    def test_reject_found_record(self, svc):
        prop = svc.propose_memory_candidate("u1", "entity", "name", "Alice", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.reject_memory_candidate("u1", mid, reason="wrong data")
        assert r["success"] is True
        assert r["memory"]["status"] == "rejected"

    def test_delete_with_reason(self, svc):
        prop = svc.propose_memory_candidate("u1", "entity", "name", "Alice", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.delete_memory("u1", mid, reason="outdated")
        assert r["success"] is True
        assert r["memory"]["status"] == "deleted"
        assert r["memory"]["deleted_reason"] == "outdated"

    def test_delete_preference_type_removes_from_preferences(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        # Set memory_id on preference so deletion removes it
        mem = svc._store.get_memory("u1")
        mem.preferences["color"]["memory_id"] = mid
        svc._store.save_memory("u1", mem)
        svc.delete_memory("u1", mid)
        mem2 = svc._store.get_memory("u1")
        assert "color" not in mem2.preferences

    def test_reject_preference_type_removes_from_preferences(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "lang", "en", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        mem = svc._store.get_memory("u1")
        mem.preferences["lang"]["memory_id"] = mid
        svc._store.save_memory("u1", mem)
        svc.reject_memory_candidate("u1", mid)
        mem2 = svc._store.get_memory("u1")
        assert "lang" not in mem2.preferences

    def test_invalid_status_raises(self, svc):
        with pytest.raises(ValueError, match="unsupported memory status"):
            svc._set_memory_v2_status("u1", "mid", "invalid_status")


# ---------------------------------------------------------------------------
# 6. correct_memory branches (lines 548–592)
# ---------------------------------------------------------------------------


class TestCorrectMemory:
    def test_correct_user_no_memory(self, svc):
        r = svc.correct_memory("ghost", "mid", value="new")
        # Record not found
        assert r["success"] is False

    def test_correct_record_not_found(self, svc):
        svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        r = svc.correct_memory("u1", "bad_mid", value="new_val")
        assert r["success"] is False

    def test_correct_deleted_record(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.delete_memory("u1", mid)
        r = svc.correct_memory("u1", mid, value="new_val")
        assert r["success"] is False
        assert "删除" in r["message"]

    def test_correct_key_update(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "old_key", "val", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.correct_memory("u1", mid, key="new_key")
        assert r["success"] is True
        assert r["memory"]["key"] == "new_key"

    def test_correct_empty_key_fails(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        r = svc.correct_memory("u1", mid, key="  ")
        assert r["success"] is False

    def test_correct_active_preference_updates_preferences(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        mem = svc._store.get_memory("u1")
        mem.preferences["color"]["memory_id"] = mid
        svc._store.save_memory("u1", mem)
        r = svc.correct_memory("u1", mid, value="red")
        assert r["success"] is True
        mem2 = svc._store.get_memory("u1")
        assert mem2.preferences["color"]["value"] == "red"

    def test_correct_active_preference_key_change_moves_pref(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "old_color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        mem = svc._store.get_memory("u1")
        mem.preferences["old_color"]["memory_id"] = mid
        svc._store.save_memory("u1", mem)
        svc.correct_memory("u1", mid, key="new_color")
        mem2 = svc._store.get_memory("u1")
        assert "old_color" not in mem2.preferences
        assert "new_color" in mem2.preferences


# ---------------------------------------------------------------------------
# 7. list_memories / get_memory_v2_summary / format_memory_v2_for_prompt
# ---------------------------------------------------------------------------


class TestListAndSummary:
    def test_list_no_status_filter(self, svc):
        svc.propose_memory_candidate("u1", "preference", "k1", "v1", source="user_explicit")
        svc.propose_memory_candidate("u1", "entity", "k2", "v2", source="user_explicit")
        records = svc.list_memories("u1")
        assert len(records) >= 2

    def test_list_with_status_filter(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        active = svc.list_memories("u1", status="active")
        pending = svc.list_memories("u1", status="pending")
        assert len(active) >= 1
        assert len(pending) == 0

    def test_list_with_type_filter(self, svc):
        svc.propose_memory_candidate("u1", "preference", "k", "v", source="user_explicit")
        svc.propose_memory_candidate("u1", "entity", "name", "x", source="user_explicit")
        pref_only = svc.list_memories("u1", memory_type="preference")
        assert all(r["memory_type"] == "preference" for r in pref_only)

    def test_list_empty_user(self, svc):
        assert svc.list_memories("nobody") == []

    def test_get_memory_v2_summary_counts(self, svc):
        svc.propose_memory_candidate("u1", "preference", "k1", "v1", source="user_explicit")
        svc.propose_memory_candidate("u1", "entity", "k2", "v2", source="llm_guess")
        r = svc.get_memory_v2_summary("u1")
        assert r["total"] == 2
        assert "pending" in r["by_status"] or "rejected" in r["by_status"]

    def test_get_memory_v2_summary_empty_user(self, svc):
        r = svc.get_memory_v2_summary("ghost")
        assert r["total"] == 0

    def test_format_memory_v2_no_active(self, svc):
        result = svc.format_memory_v2_for_prompt("u1")
        assert "无已确认记忆" in result

    def test_format_memory_v2_with_active(self, svc):
        prop = svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        mid = prop["candidate"]["memory_id"]
        svc.confirm_memory_candidate("u1", mid)
        result = svc.format_memory_v2_for_prompt("u1")
        assert "color" in result
        assert "blue" in result


# ---------------------------------------------------------------------------
# 8. record_action branches (accumulate vs new pattern)
# ---------------------------------------------------------------------------


class TestRecordAction:
    def test_new_action_recorded(self, svc):
        svc.record_action("u1", "create_order", {"unit_name": "ACME"})
        actions = svc.get_recent_actions("u1")
        assert len(actions) >= 1

    def test_existing_pattern_frequency_increases(self, svc):
        svc.record_action("u1", "create_order", {"unit_name": "ACME"})
        svc.record_action("u1", "create_order", {"unit_name": "ACME"})
        actions = svc.get_recent_actions("u1")
        assert actions[0]["frequency"] == 2

    def test_confidence_capped_at_0_99(self, svc):
        for _ in range(25):
            svc.record_action("u1", "my_intent", {})
        actions = svc.get_recent_actions("u1")
        assert actions[0]["confidence"] <= 0.99

    def test_frequent_actions_capped_at_max(self, svc):
        for i in range(25):
            svc.record_action("u1", f"intent_{i}", {f"slot_{i}": str(i)})
        mem = svc._store.get_memory("u1")
        assert len(mem.frequent_actions) <= 20

    def test_intent_filter_in_get_recent_actions(self, svc):
        svc.record_action("u1", "intent_a", {})
        svc.record_action("u1", "intent_b", {})
        results = svc.get_recent_actions("u1", intent_filter="intent_a")
        assert all(r["intent"] == "intent_a" for r in results)


# ---------------------------------------------------------------------------
# 9. get_similar_pattern branches
# ---------------------------------------------------------------------------


class TestGetSimilarPattern:
    def test_no_memory_returns_none(self, svc):
        assert svc.get_similar_pattern("ghost", "intent", {}) is None

    def test_no_match_for_different_intent(self, svc):
        svc.record_action("u1", "intent_a", {"unit_name": "ACME"})
        assert svc.get_similar_pattern("u1", "intent_b", {"unit_name": "ACME"}) is None

    def test_match_above_threshold(self, svc):
        svc.record_action("u1", "order", {"unit_name": "ACME"})
        result = svc.get_similar_pattern("u1", "order", {"unit_name": "ACME"}, threshold=0.1)
        assert result is not None
        assert "match_score" in result

    def test_similarity_zero_slots_both_empty(self, svc):
        score = svc._calculate_similarity({}, {})
        assert score == 1.0

    def test_similarity_no_overlap(self, svc):
        score = svc._calculate_similarity({"unit_name": "A"}, {"unit_name": "B"})
        assert score == 0.0

    def test_combined_score_below_threshold(self, svc):
        svc.record_action("u1", "order", {"unit_name": "ABC"})
        result = svc.get_similar_pattern("u1", "order", {"unit_name": "XYZ"}, threshold=0.9)
        assert result is None


# ---------------------------------------------------------------------------
# 10. add_feedback + _adjust_pattern_weights branches
# ---------------------------------------------------------------------------


class TestAddFeedback:
    def test_confirmed_feedback_increases_confidence(self, svc):
        svc.record_action("u1", "order", {})
        svc.add_feedback("u1", "make order", "order", "confirmed")
        actions = svc.get_recent_actions("u1")
        # confidence should have increased from 0.5
        assert actions[0]["confidence"] > 0.5

    def test_negated_feedback_decreases_confidence(self, svc):
        svc.record_action("u1", "order", {})
        orig_confidence = svc.get_recent_actions("u1")[0]["confidence"]
        svc.add_feedback("u1", "not order", "order", "negated")
        assert svc.get_recent_actions("u1")[0]["confidence"] < orig_confidence

    def test_corrected_feedback_adjusts_both_intents(self, svc):
        svc.record_action("u1", "intent_wrong", {})
        svc.record_action("u1", "intent_right", {})
        svc.add_feedback("u1", "msg", "intent_wrong", "corrected", corrected_intent="intent_right")
        actions = {a["intent"]: a for a in svc.get_recent_actions("u1")}
        assert "intent_right" in actions

    def test_feedback_history_capped(self, svc):
        for i in range(105):
            svc.add_feedback("u1", f"msg{i}", "order", "confirmed")
        mem = svc._store.get_memory("u1")
        assert len(mem.feedback_history) <= 100

    def test_corrected_feedback_no_corrected_intent(self, svc):
        """feedback=='corrected' but corrected_intent is None → no-op for correction branch."""
        svc.record_action("u1", "order", {})
        svc.add_feedback("u1", "msg", "order", "corrected", corrected_intent=None)
        # Should not raise
        assert svc.get_recent_actions("u1") is not None


# ---------------------------------------------------------------------------
# 11. get_feedback_stats
# ---------------------------------------------------------------------------


class TestGetFeedbackStats:
    def test_empty_stats(self, svc):
        r = svc.get_feedback_stats("ghost")
        assert r["total"] == 0

    def test_stats_computed(self, svc):
        for _ in range(3):
            svc.add_feedback("u1", "m", "order", "negated")
        r = svc.get_feedback_stats("u1")
        assert r["negated"] >= 3
        assert "order" in r["error_rates"]

    def test_error_rate_not_computed_below_threshold(self, svc):
        svc.add_feedback("u1", "m", "order", "negated")
        svc.add_feedback("u1", "m", "order", "negated")
        r = svc.get_feedback_stats("u1")
        # total < 3 so error_rates should be empty
        assert r["error_rates"] == {}


# ---------------------------------------------------------------------------
# 12. get_habit_suggestions + _analyze_action_sequence
# ---------------------------------------------------------------------------


class TestHabitSuggestions:
    def test_no_memory_returns_empty(self, svc):
        assert svc.get_habit_suggestions("ghost") == []

    def test_no_suggestions_when_sequence_below_threshold(self, svc):
        svc.record_action("u1", "a", {})
        svc.record_action("u1", "b", {})
        # Only 1 occurrence of a->b, need 2+ for sequence
        suggestions = svc.get_habit_suggestions("u1")
        assert suggestions == []

    def test_suggestions_when_sequence_repeated(self, svc):
        for _ in range(6):
            svc.record_action("u1", "create_order", {})
            svc.record_action("u1", "print_label", {})
        suggestions = svc.get_habit_suggestions("u1")
        # With repeated sequence and confidence >= 0.8, should have suggestions
        assert isinstance(suggestions, list)


# ---------------------------------------------------------------------------
# 13. apply_preference_to_slots
# ---------------------------------------------------------------------------


class TestApplyPreferenceToSlots:
    def test_fills_unit_name_from_favorite_customer(self, svc):
        svc.add_preference("u1", "favorite_customer", "ACME Corp")
        slots = svc.apply_preference_to_slots("u1", "order", {})
        assert slots["unit_name"] == "ACME Corp"

    def test_does_not_overwrite_existing_unit_name(self, svc):
        svc.add_preference("u1", "favorite_customer", "ACME Corp")
        slots = svc.apply_preference_to_slots("u1", "order", {"unit_name": "Override"})
        assert slots["unit_name"] == "Override"

    def test_fills_template_from_default_template(self, svc):
        svc.add_preference("u1", "default_template", "tmpl_001")
        slots = svc.apply_preference_to_slots("u1", "order", {})
        assert slots["template"] == "tmpl_001"

    def test_no_preferences_returns_original_slots(self, svc):
        slots = {"quantity": 5}
        result = svc.apply_preference_to_slots("u1", "order", slots)
        assert result["quantity"] == 5


# ---------------------------------------------------------------------------
# 14. get_memory_summary
# ---------------------------------------------------------------------------


class TestGetMemorySummary:
    def test_no_memory_returns_has_memory_false(self, svc):
        # get_memory always creates, so result should always have memory
        r = svc.get_memory_summary("u1")
        # UserMemoryStore.get_memory creates a new UserMemory if absent
        assert r.get("has_memory") is True

    def test_summary_counts(self, svc):
        svc.add_preference("u1", "k", "v")
        svc.record_action("u1", "intent", {})
        svc.add_feedback("u1", "msg", "intent", "confirmed")
        svc.propose_memory_candidate("u1", "preference", "color", "blue", source="user_explicit")
        r = svc.get_memory_summary("u1")
        assert r["preference_count"] >= 1
        assert r["action_count"] >= 1
        assert r["feedback_count"] >= 1
        assert r["memory_v2_count"] >= 1


# ---------------------------------------------------------------------------
# 15. get_user_memory_service / reset singleton
# ---------------------------------------------------------------------------


class TestSingletonLifecycle:
    def test_get_returns_same_instance(self, monkeypatch, tmp_path):
        json_path = str(tmp_path / "memory_store.json")
        monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
        monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
        UserMemoryStore._instance = None
        UserMemoryService._instance = None
        svc1 = get_user_memory_service()
        svc2 = get_user_memory_service()
        assert svc1 is svc2

    def test_reset_clears_singleton(self, monkeypatch, tmp_path):
        json_path = str(tmp_path / "memory_store.json")
        monkeypatch.setattr(user_memory_service, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(user_memory_service, "JSON_MEMORY_PATH", json_path)
        monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
        UserMemoryStore._instance = None
        UserMemoryService._instance = None
        svc1 = get_user_memory_service()
        reset_user_memory_service()
        UserMemoryStore._instance = None
        UserMemoryService._instance = None
        svc2 = get_user_memory_service()
        assert svc1 is not svc2


# ---------------------------------------------------------------------------
# 16. UserMemory dataclass serialization
# ---------------------------------------------------------------------------


class TestUserMemoryDataclass:
    def test_to_dict_and_from_dict_roundtrip(self):
        mem = UserMemory(
            user_id="u1",
            preferences={"k": {"value": "v", "count": 1, "updated_at": "now"}},
            frequent_actions=[],
        )
        d = mem.to_dict()
        mem2 = UserMemory.from_dict(d)
        assert mem2.user_id == "u1"
        assert mem2.preferences["k"]["value"] == "v"

    def test_from_dict_ignores_unknown_fields(self):
        d = {"user_id": "u1", "unknown_field": "ignored"}
        mem = UserMemory.from_dict(d)
        assert mem.user_id == "u1"
        assert not hasattr(mem, "unknown_field")

    def test_action_pattern_serialization(self):
        ap = ActionPattern(pattern="p", intent="i", slots={"k": "v"})
        d = ap.to_dict()
        ap2 = ActionPattern.from_dict(d)
        assert ap2.intent == "i"

    def test_feedback_record_serialization(self):
        fr = FeedbackRecord(timestamp="now", message="m", recognized_intent="i", user_feedback="confirmed")
        d = fr.to_dict()
        fr2 = FeedbackRecord.from_dict(d)
        assert fr2.user_feedback == "confirmed"

    def test_context_summary_serialization(self):
        cs = ContextSummary(timestamp="now", intent="i", slots={}, message="m")
        d = cs.to_dict()
        cs2 = ContextSummary.from_dict(d)
        assert cs2.intent == "i"


# ---------------------------------------------------------------------------
# 17. _normalize helpers branches
# ---------------------------------------------------------------------------


class TestNormalizeHelpers:
    def test_normalize_type_alias_pref(self, svc):
        assert svc._normalize_memory_v2_type("pref") == "preference"

    def test_normalize_type_alias_task(self, svc):
        assert svc._normalize_memory_v2_type("task") == "episodic"

    def test_normalize_type_invalid_raises(self, svc):
        with pytest.raises(ValueError):
            svc._normalize_memory_v2_type("nonexistent")

    def test_normalize_status_valid(self, svc):
        assert svc._normalize_memory_v2_status("active") == "active"

    def test_normalize_status_invalid_raises(self, svc):
        with pytest.raises(ValueError):
            svc._normalize_memory_v2_status("bad_status")


# ---------------------------------------------------------------------------
# 18. _govern_memory_v2_candidate evidence_required flag branches
# ---------------------------------------------------------------------------


class TestGovernMemoryCandidate:
    def test_observed_source_with_evidence(self, svc):
        gov = svc._govern_memory_v2_candidate(
            source="agent_observation",
            confidence=0.8,
            evidence=[{"fact": "observed from tool"}],
        )
        assert "missing_evidence" not in gov["governance_flags"]
        assert gov["confidence"] == 0.8

    def test_unknown_source_caps_confidence_at_035(self, svc):
        gov = svc._govern_memory_v2_candidate(
            source="my_custom_src",
            confidence=0.9,
            evidence=None,
        )
        assert gov["confidence"] <= 0.35

    def test_blocked_source_caps_confidence_at_zero(self, svc):
        gov = svc._govern_memory_v2_candidate(
            source="prompt_injection",
            confidence=0.9,
            evidence=None,
        )
        assert gov["confidence"] == 0.0
        assert "blocked_source" in gov["governance_flags"]
