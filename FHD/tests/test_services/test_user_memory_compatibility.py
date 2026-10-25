"""Legacy and canonical memory APIs share one lossless persistence protocol."""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from multiprocessing.synchronize import Barrier
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from app.services import user_memory_service as canonical
from app.utils import user_memory as legacy


@pytest.fixture
def shared_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "memory.json"
    monkeypatch.delenv("XCAGI_USER_MEMORY_DIR", raising=False)
    monkeypatch.delenv("XCAGI_USER_MEMORY_JSON_PATH", raising=False)
    for module in (canonical, legacy):
        monkeypatch.setattr(module, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(module, "JSON_MEMORY_PATH", str(path))
        module.UserMemoryStore._instance = None
        module.UserMemoryService._instance = None
        module.reset_user_memory_service()
    yield path
    for module in (canonical, legacy):
        module.UserMemoryStore._instance = None
        module.UserMemoryService._instance = None
        module.reset_user_memory_service()


def _confirm_preference(service: canonical.UserMemoryService) -> str:
    result = service.propose_memory_candidate(
        "alice", "preference", "favorite_customer", "ACME", source="user_explicit"
    )
    memory_id = str(result["candidate"]["memory_id"])
    assert service.confirm_memory_candidate("alice", memory_id)["success"]
    return memory_id


def test_cold_legacy_reader_accepts_canonical_v2_records(shared_path: Path) -> None:
    current = canonical.UserMemoryService()
    memory_id = _confirm_preference(current)
    before = shared_path.read_bytes()
    compatible = legacy.UserMemoryService()
    assert compatible.get_all_preferences("alice") == {"favorite_customer": "ACME"}
    compatible.add_preference("alice", "theme", "blue")
    data = json.loads(shared_path.read_text())
    assert data["alice"]["memory_v2_records"][0]["memory_id"] == memory_id
    assert current.get_all_preferences("alice") == {
        "favorite_customer": "ACME",
        "theme": "blue",
    }
    assert before != shared_path.read_bytes()


def test_warm_legacy_writer_keeps_canonical_users_and_records(shared_path: Path) -> None:
    compatible = legacy.UserMemoryService()
    current = canonical.UserMemoryService()
    memory_id = _confirm_preference(current)
    current.add_preference("charlie", "customer", "other")
    compatible.add_preference("bob", "theme", "blue")
    data = json.loads(shared_path.read_text())
    assert set(data) == {"alice", "bob", "charlie"}
    assert data["alice"]["memory_v2_records"][0]["memory_id"] == memory_id
    assert data["charlie"]["preferences"]["customer"]["value"] == "other"


def test_interleaved_writers_keep_same_users_changes(shared_path: Path) -> None:
    compatible = legacy.UserMemoryService()
    compatible.add_preference("alice", "older", "legacy")
    current = canonical.UserMemoryService()
    memory_id = _confirm_preference(current)
    current.add_preference("alice", "current", "canonical")
    compatible.add_preference("alice", "latest", "legacy")
    assert current.get_all_preferences("alice") == {
        "older": "legacy",
        "favorite_customer": "ACME",
        "current": "canonical",
        "latest": "legacy",
    }
    assert current.list_memories("alice")[0]["memory_id"] == memory_id


def test_legacy_permission_failure_propagates_and_preserves_file(shared_path: Path) -> None:
    compatible = legacy.UserMemoryService()
    compatible.add_preference("alice", "value", "original")
    before = shared_path.read_bytes()
    with patch.object(legacy.json, "dump", side_effect=PermissionError("synthetic permission")):
        with pytest.raises(PermissionError, match="synthetic permission"):
            compatible.add_preference("alice", "value", "failed write")
    assert legacy.UserMemoryStore()._cache_dirty["alice"] is True
    assert shared_path.read_bytes() == before
    assert list(shared_path.parent.glob(".*.tmp")) == []
    assert compatible.get_preference("alice", "value") == "original"
    compatible.add_preference("alice", "value", "retried")
    assert legacy.UserMemoryStore()._cache_dirty["alice"] is False
    assert compatible.get_preference("alice", "value") == "retried"


def test_preference_application_does_not_report_a_failed_write_as_success(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.application.user_preference_app_service import UserPreferenceApplicationService

    compatible = legacy.UserMemoryService()
    current = canonical.UserMemoryService()
    compatible.add_preference("alice", "value", "original")
    monkeypatch.setattr(legacy, "get_user_memory_service", lambda: compatible)
    monkeypatch.setattr(canonical, "get_user_memory_service", lambda: current)
    service = UserPreferenceApplicationService()
    before = shared_path.read_bytes()
    with patch.object(legacy.json, "dump", side_effect=PermissionError("synthetic permission")):
        assert service.set_preference("alice", "value", "failed write") is False
    assert shared_path.read_bytes() == before


def test_value_constructors_and_old_json_round_trip(shared_path: Path) -> None:
    old = legacy.UserMemory("alice", {"theme": {"value": "blue"}}, [], [], [], "old-time")
    assert old.updated_at == "old-time"
    assert old.memory_v2_records == []
    old_data = old.to_dict()
    old_data.pop("memory_v2_records")
    shared_path.write_text(json.dumps({"alice": old_data}))
    assert legacy.UserMemoryService().get_preference("alice", "theme") == "blue"
    assert canonical.UserMemoryService().get_preference("alice", "theme") == "blue"
    current = canonical.UserMemory("alice", {}, [], [], [], [{"memory_id": "v2"}], "new-time")
    copied = legacy.UserMemory.from_dict(current.to_dict())
    assert copied.updated_at == "new-time"
    assert copied.to_dict() == current.to_dict()
    assert legacy.ActionPattern is canonical.ActionPattern
    assert legacy.ContextSummary is canonical.ContextSummary
    assert legacy.FeedbackRecord is canonical.FeedbackRecord


def test_explicit_v1_snapshot_save_keeps_latest_governed_metadata(shared_path: Path) -> None:
    current = canonical.UserMemoryService()
    result = current.propose_memory_candidate(
        "alice", "entity", "warehouse", {"name": "A"}, source="user_explicit"
    )
    memory_id = result["candidate"]["memory_id"]
    assert current.confirm_memory_candidate("alice", memory_id)["success"]
    current.add_preference("alice", "replaced-by-snapshot", "old")
    store = legacy.UserMemoryStore()
    stale = store.get_memory("alice")
    assert stale is not None
    assert current.correct_memory("alice", memory_id, value={"name": "B"})["success"]
    assert current.record_memory_recall("alice", memory_id)["success"]
    latest_records = current.list_memories("alice")

    # A direct save deliberately replaces v1 state; it cannot roll back v2 state.
    stale.preferences = {"manual": {"value": "snapshot"}}
    store.save_memory("alice", stale)
    assert current.get_all_preferences("alice") == {"manual": "snapshot"}
    assert current.list_memories("alice") == latest_records
    old_constructor = legacy.UserMemory("alice", {}, [], [], [], "old-time")
    store.save_memory("alice", old_constructor)
    assert current.get_all_preferences("alice") == {}
    assert current.list_memories("alice") == latest_records


@pytest.mark.parametrize("storage_type", ["json", "sqlite"])
def test_legacy_snapshot_boundaries_isolate_nested_mutation(
    shared_path: Path, storage_type: str
) -> None:
    service = legacy.UserMemoryService(storage_type)
    value = {"nested": ["original"]}
    service.add_preference("alice", "value", value)
    value["nested"].append("caller mutation")
    returned = service.get_preference("alice", "value")
    returned["nested"].append("reader mutation")
    assert service.get_preference("alice", "value") == {"nested": ["original"]}
    memory = legacy.UserMemory("alice", {"value": {"value": {"nested": ["saved"]}}})
    service._store.save_memory("alice", memory)
    memory.preferences["value"]["value"]["nested"].append("snapshot mutation")
    assert service.get_preference("alice", "value") == {"nested": ["saved"]}
    if storage_type == "sqlite":
        assert not shared_path.exists()


def test_corrected_feedback_preserves_each_entry_points_policy(shared_path: Path) -> None:
    compatible = legacy.UserMemoryService()
    current = canonical.UserMemoryService()
    for service, user_id in ((compatible, "legacy"), (current, "canonical")):
        service.record_action(user_id, "recognized", {})
        service.record_action(user_id, "corrected", {})
        service.add_feedback(user_id, "correction", "recognized", "corrected", "corrected")
    legacy_weights = {
        row["intent"]: row["confidence"] for row in compatible.get_recent_actions("legacy")
    }
    current_weights = {
        row["intent"]: row["confidence"] for row in current.get_recent_actions("canonical")
    }
    assert legacy_weights == pytest.approx({"recognized": 0.5, "corrected": 0.4})
    assert current_weights == pytest.approx({"recognized": 0.4, "corrected": 0.6})


def test_legacy_clock_limits_and_value_factories_are_late_bound(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = legacy.UserMemoryService("sqlite")
    timestamp = datetime(2026, 10, 22, 3, 4, 5)
    monkeypatch.setattr(legacy, "datetime", SimpleNamespace(now=lambda: timestamp))
    for name in ("MAX_CONTEXT_SUMMARIES", "MAX_FREQUENT_ACTIONS", "MAX_FEEDBACK_HISTORY"):
        monkeypatch.setattr(legacy, name, 1)
    action_factory = Mock(wraps=legacy.ActionPattern)
    context_factory = Mock(wraps=legacy.ContextSummary)
    feedback_factory = Mock(wraps=legacy.FeedbackRecord)
    monkeypatch.setattr(legacy, "ActionPattern", action_factory)
    monkeypatch.setattr(legacy, "ContextSummary", context_factory)
    monkeypatch.setattr(legacy, "FeedbackRecord", feedback_factory)
    service.add_preference("alice", "theme", "blue")
    for intent in ("first", "last"):
        service.record_action("alice", intent, {}, "context")
        service.add_feedback("alice", "feedback", intent, "confirmed")
    memory = service._store.get_memory("alice")
    assert memory is not None
    assert memory.updated_at == timestamp.isoformat()
    assert memory.preferences["theme"]["updated_at"] == timestamp.isoformat()
    assert (
        len(memory.frequent_actions)
        == len(memory.historical_contexts)
        == len(memory.feedback_history)
        == 1
    )
    assert memory.frequent_actions[0]["intent"] == "last"
    for factory, field in (
        (action_factory, "last_used"),
        (context_factory, "timestamp"),
        (feedback_factory, "timestamp"),
    ):
        assert factory.call_count == 2
        assert factory.call_args.kwargs[field] == timestamp.isoformat()


def test_legacy_helpers_and_store_can_be_replaced_after_assembly(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = legacy.UserMemoryService("sqlite")
    previous_store = service._store
    legacy.UserMemoryStore._instance = None
    replacement = legacy.UserMemoryStore("sqlite")
    monkeypatch.setattr(service, "_store", replacement)
    key = Mock(return_value="patched-key")
    context = Mock()
    similarity = Mock(return_value=0.75)
    adjust = Mock()
    lookup = Mock(side_effect=["customer", "template"])
    monkeypatch.setattr(service, "_make_pattern_key", key)
    monkeypatch.setattr(service, "_save_context_summary", context)
    monkeypatch.setattr(service, "_calculate_similarity", similarity)
    monkeypatch.setattr(service, "_adjust_pattern_weights", adjust)
    monkeypatch.setattr(service, "get_preference", lookup)
    service.record_action("alice", "order", {"unit_name": "A"}, "text")
    key.assert_called_once_with("order", {"unit_name": "A"})
    assert context.call_args.args[1:] == ("order", {"unit_name": "A"}, "text")
    assert context.call_args.kwargs == {}
    match = service.get_similar_pattern("alice", "order", {"unit_name": "B"}, 0.7)
    assert match is not None and match["match_score"] == 0.75
    similarity.assert_called_once_with({"unit_name": "B"}, {"unit_name": "A"})
    service.add_feedback("alice", "text", "order", "confirmed")
    assert adjust.call_args.args[1:] == ("order", None, "confirmed")
    assert adjust.call_args.kwargs == {}
    assert service.apply_preference_to_slots("alice", "order", {}) == {
        "unit_name": "customer",
        "template": "template",
    }
    assert lookup.call_args_list == [
        call("alice", "favorite_customer"),
        call("alice", "default_template"),
    ]
    memory = previous_store.get_memory("alice")
    assert memory is not None and memory.frequent_actions == []


def test_legacy_analysis_exports_remain_late_patch_points(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = legacy.UserMemoryService("sqlite")
    for helper_name, method_name in (
        ("feedback_stats", "get_feedback_stats"),
        ("habit_suggestions", "get_habit_suggestions"),
        ("memory_summary", "get_memory_summary"),
        ("analyze_action_sequence", "_analyze_action_sequence"),
    ):
        sentinel = object()
        helper = Mock(return_value=sentinel)
        monkeypatch.setattr(legacy, helper_name, helper)
        argument = (
            legacy.UserMemory("alice") if helper_name == "analyze_action_sequence" else "alice"
        )
        assert getattr(service, method_name)(argument) is sentinel
        helper.assert_called_once()
        assert helper.call_args.args[0].user_id == "alice"
        assert helper.call_args.kwargs == {}


def test_legacy_habits_use_the_shared_chronology_for_unordered_records(shared_path: Path) -> None:
    service = legacy.UserMemoryService("sqlite")
    start = datetime(2026, 10, 22, 12)
    records = [
        {
            "timestamp": (start + timedelta(seconds=index)).isoformat(),
            "intent": "create-shipment" if index % 2 == 0 else "print-label",
        }
        for index in range(12)
    ]
    memory = legacy.UserMemory("alice", historical_contexts=records[::2] + records[1::2])
    service._store.save_memory("alice", memory)
    assert [item["actions"] for item in service.get_habit_suggestions("alice")] == [
        ["create-shipment", "print-label"]
    ]


def test_legacy_persistence_hooks_keep_late_calls_and_dirty_state(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = legacy.UserMemoryStore("sqlite")
    flush = Mock()
    policy = Mock(return_value=False)
    monkeypatch.setattr(store, "_save_all_memories", flush)
    monkeypatch.setattr(store, "_should_persist", policy)
    memory = legacy.UserMemory("alice")
    store.save_memory("alice", memory)
    assert store._cache_dirty["alice"] is True
    flush.assert_not_called()
    policy.return_value = True
    store.save_memory("alice", memory)
    flush.assert_called_once_with()
    assert store._cache_dirty["alice"] is False
    assert policy.call_args_list == [call(), call()]


def test_preference_application_and_package_use_canonical_service(
    shared_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services as services
    from app.application.user_preference_app_service import UserPreferenceApplicationService

    assert services.UserMemoryService is canonical.UserMemoryService
    assert services.get_user_memory_service is canonical.get_user_memory_service
    current = canonical.UserMemoryService()
    _confirm_preference(current)
    old_getter = Mock(side_effect=AssertionError("production called the legacy getter"))
    monkeypatch.setattr(legacy, "get_user_memory_service", old_getter)
    getter = Mock(return_value=current)
    monkeypatch.setattr(canonical, "get_user_memory_service", getter)
    application = UserPreferenceApplicationService()
    assert application.get_preference("alice", "favorite_customer") == "ACME"
    assert application.set_preference("alice", "theme", "blue") is True
    assert application.get_all_preferences("alice") == {
        "favorite_customer": "ACME",
        "theme": "blue",
    }
    assert getter.call_count == 3
    old_getter.assert_not_called()


@pytest.mark.parametrize(
    ("method", "arguments", "expected"),
    [
        ("get_preference", ("alice", "value", "fallback"), "fallback"),
        ("get_all_preferences", ("alice",), {}),
        ("set_preference", ("alice", "value", "failed"), False),
    ],
)
def test_preference_application_keeps_failure_contracts(
    shared_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    arguments: tuple[str, ...],
    expected: object,
) -> None:
    from app.application.user_preference_app_service import UserPreferenceApplicationService

    current = canonical.UserMemoryService()
    current.add_preference("alice", "value", "original")
    monkeypatch.setattr(canonical, "get_user_memory_service", lambda: current)
    application = UserPreferenceApplicationService()
    before = shared_path.read_bytes()
    with patch.object(canonical.json, "load", side_effect=PermissionError("read denied")):
        assert getattr(application, method)(*arguments) == expected
    assert shared_path.read_bytes() == before


def test_importing_legacy_values_does_not_initialize_the_service_package() -> None:
    script = """
import socket, sys
def deny(*args, **kwargs):
    raise AssertionError("unexpected external connection")
socket.socket.connect = deny
socket.create_connection = deny
class NoServices:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.services" or fullname.startswith("app.services."):
            raise AssertionError("legacy values initialized the service package")
sys.meta_path.insert(0, NoServices())
from app.utils.user_memory import UserMemory, feedback_stats
assert UserMemory("alice").user_id == "alice"
assert feedback_stats(None) == {"total": 0, "confirmed": 0, "negated": 0, "corrected": 0}
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("first", ["app.utils.user_memory", "app.domain.shared_services.user_memory_service"])
def test_cold_import_orders_preserve_exports_and_default_paths(first: str) -> None:
    script = """
import importlib, os, socket, sys
def deny(*args, **kwargs):
    raise AssertionError("unexpected external connection")
socket.socket.connect = deny
socket.create_connection = deny
importlib.import_module(sys.argv[1])
from app.utils import user_memory as legacy
from app.services import user_memory_service as canonical
import app.services as services
assert services.UserMemoryService is canonical.UserMemoryService
assert services.get_user_memory_service is canonical.get_user_memory_service
assert legacy.JSON_MEMORY_PATH == os.path.join(legacy.BASE_DIR, "user_memory", "memory_store.json")
assert canonical.JSON_MEMORY_PATH == legacy.JSON_MEMORY_PATH
assert legacy.UserMemoryService("sqlite")._store.storage_type == "sqlite"
assert canonical.UserMemoryService("sqlite")._store.storage_type == "sqlite"
"""
    environment = os.environ.copy()
    environment.pop("XCAGI_USER_MEMORY_DIR", None)
    environment.pop("XCAGI_USER_MEMORY_JSON_PATH", None)
    result = subprocess.run(
        [sys.executable, "-c", script, first],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr


def _mixed_memory_writer(path: str, use_legacy: bool, index: int, barrier: Barrier) -> None:
    with patch(
        "socket.socket.connect", side_effect=AssertionError("unexpected external connection")
    ):
        canonical.MEMORY_DIR = legacy.MEMORY_DIR = str(Path(path).parent)
        canonical.JSON_MEMORY_PATH = legacy.JSON_MEMORY_PATH = path
        for module in (canonical, legacy):
            module.UserMemoryStore._instance = None
            module.UserMemoryService._instance = None
            module.reset_user_memory_service()
        service = legacy.UserMemoryService() if use_legacy else canonical.UserMemoryService()
        barrier.wait(timeout=20)
        for _ in range(8):
            service.add_preference("alice", "counter", index)
        service.add_preference("alice", f"writer-{index}", index)
        service.add_preference(f"writer-{index}", "owned", index)


def test_mixed_process_writers_preserve_same_user_increments_and_other_users(
    shared_path: Path,
) -> None:
    current = canonical.UserMemoryService()
    memory_id = _confirm_preference(current)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    processes = [
        context.Process(
            target=_mixed_memory_writer, args=(str(shared_path), index != 1, index, barrier)
        )
        for index in range(3)
    ]
    started = []
    try:
        for process in processes:
            process.start()
            started.append(process)
        deadline = time.monotonic() + 45
        for process in started:
            process.join(max(0, deadline - time.monotonic()))
        assert not any(process.is_alive() for process in started)
        assert [process.exitcode for process in started] == [0, 0, 0]
    finally:
        for process in started:
            if process.is_alive():
                process.terminate()
                process.join(5)
            process.close()
    persisted = json.loads(shared_path.read_text())
    assert set(persisted) == {"alice", "writer-0", "writer-1", "writer-2"}
    assert persisted["alice"]["preferences"]["counter"]["count"] == 24
    for index in range(3):
        assert persisted["alice"]["preferences"][f"writer-{index}"]["value"] == index
        assert persisted[f"writer-{index}"]["preferences"]["owned"]["value"] == index
    assert current.get_preference("alice", "favorite_customer") == "ACME"
    assert current.list_memories("alice")[0]["memory_id"] == memory_id
