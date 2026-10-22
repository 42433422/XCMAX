"""Memory snapshots, owned projections and independently assembled components."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import Mock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import user_memory_service as module
from app.services.user_memory.models import UserMemory
from app.services.user_memory.patterns import chronological_contexts
from app.services.user_memory.persistence import MemoryRepository
from app.services.user_memory.ports import MemoryAccess
from app.services.user_memory.preferences import PreferenceMemory

MemoryFactory = Callable[[str], module.UserMemoryService]


@pytest.fixture
def memory_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[MemoryFactory]:
    monkeypatch.delenv("XCAGI_USER_MEMORY_DIR", raising=False)
    monkeypatch.delenv("XCAGI_USER_MEMORY_JSON_PATH", raising=False)
    monkeypatch.setattr(module, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(module, "JSON_MEMORY_PATH", str(tmp_path / "memory.json"))
    module.reset_user_memory_service()
    yield lambda storage: module.UserMemoryService(storage_type=storage)
    module.reset_user_memory_service()


@pytest.mark.parametrize("correction", [{"key": "new-key"}, {"memory_type": "entity"}])
def test_confirm_correction_removes_its_previous_preference_projection(
    memory_factory: MemoryFactory, correction: dict[str, str]
) -> None:
    service = memory_factory("json")
    result = service.propose_memory_candidate(
        "alice", "preference", "old-key", "saved", source="user_explicit"
    )
    memory_id = result["candidate"]["memory_id"]
    assert service.confirm_memory_candidate("alice", memory_id)["success"]
    assert service.get_preference("alice", "old-key") == "saved"
    assert service.confirm_memory_candidate("alice", memory_id, correction=correction)["success"]
    assert "old-key" not in service.get_all_preferences("alice")
    assert service.delete_memory("alice", memory_id)["success"]
    assert service.get_all_preferences("alice") == {}


@pytest.mark.parametrize("surface", ["preference", "candidate"])
def test_mutating_input_cannot_change_stored_memory(
    memory_factory: MemoryFactory, surface: str
) -> None:
    service = memory_factory("memory")
    value = {"items": ["original"]}
    if surface == "preference":
        service.add_preference("alice", "options", value)
    else:
        service.propose_memory_candidate(
            "alice", "entity", "options", value, source="user_explicit"
        )
    value["items"].append("caller edit")
    stored = (
        service.get_preference("alice", "options")
        if surface == "preference"
        else service.list_memories("alice")[0]["value"]
    )
    assert stored == {"items": ["original"]}


@pytest.mark.parametrize(
    "surface", ["candidate", "confirmed", "listed", "preference", "preferences"]
)
def test_mutating_output_cannot_change_stored_memory(
    memory_factory: MemoryFactory, surface: str
) -> None:
    service = memory_factory("memory")
    result = service.propose_memory_candidate(
        "alice", "preference", "options", {"items": ["original"]}, source="user_explicit"
    )
    confirmed = service.confirm_memory_candidate("alice", result["candidate"]["memory_id"])
    value = {
        "candidate": lambda: result["candidate"]["value"],
        "confirmed": lambda: confirmed["memory"]["value"],
        "listed": lambda: service.list_memories("alice")[0]["value"],
        "preference": lambda: service.get_preference("alice", "options"),
        "preferences": lambda: service.get_all_preferences("alice")["options"],
    }[surface]()
    value["items"].append("caller edit")
    assert service.list_memories("alice")[0]["value"] == {"items": ["original"]}
    assert service.get_preference("alice", "options") == {"items": ["original"]}


def test_pattern_retrieval_does_not_persist_query_score(memory_factory: MemoryFactory) -> None:
    service = memory_factory("memory")
    service.record_action("alice", "shipment", {"unit_name": "ACME"})
    matched = service.get_similar_pattern("alice", "shipment", {"unit_name": "ACME"})
    assert matched is not None and matched["match_score"] == 1.0
    assert "match_score" not in service.get_recent_actions("alice")[0]


def test_habit_suggestions_follow_recorded_chronology(
    memory_factory: MemoryFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "MAX_CONTEXT_SUMMARIES", 50)
    timestamps = iter(datetime(2026, 10, 22, 12) + timedelta(seconds=i) for i in range(100))
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda: next(timestamps)))
    service = memory_factory("memory")
    for _ in range(6):
        service.record_action("alice", "create-shipment", {})
        service.record_action("alice", "print-label", {})
    suggestions = service.get_habit_suggestions("alice")
    assert [item["actions"] for item in suggestions] == [["create-shipment", "print-label"]]


def test_habit_history_uses_timestamps_instead_of_input_order(
    memory_factory: MemoryFactory,
) -> None:
    service = memory_factory("memory")
    memory = service._store.get_memory("alice")
    assert memory is not None
    start = datetime(2026, 10, 22, 12)
    records: list[dict[str, Any]] = [
        {
            "timestamp": (start + timedelta(seconds=i)).isoformat(),
            "intent": "create-shipment" if i % 2 == 0 else "print-label",
            "slots": {},
            "message": "",
        }
        for i in range(12)
    ]
    memory.historical_contexts = records[::2] + records[1::2]
    service._store.save_memory("alice", memory)
    suggestions = service.get_habit_suggestions("alice")
    assert [item["actions"] for item in suggestions] == [["create-shipment", "print-label"]]


def test_chronology_preserves_undated_positions_and_compares_offsets() -> None:
    records = [
        {"intent": "first", "timestamp": "2026-10-22T12:00:00+02:00"},
        {"intent": "undated", "timestamp": "legacy"},
        {"intent": "last", "timestamp": "2026-10-22T11:00:00Z"},
    ]
    before = json.dumps(records)
    assert [record["intent"] for record in chronological_contexts(records)] == [
        "first",
        "undated",
        "last",
    ]
    assert json.dumps(records) == before


def test_projection_changes_keep_a_newer_records_ownership(memory_factory: MemoryFactory) -> None:
    service = memory_factory("json")
    ids = [
        service.propose_memory_candidate(
            "alice", "preference", "shared-key", value, source="user_explicit"
        )["candidate"]["memory_id"]
        for value in ("first", "second")
    ]
    for memory_id in ids:
        assert service.confirm_memory_candidate("alice", memory_id)["success"]
    assert service.confirm_memory_candidate("alice", ids[0], correction={"key": "moved"})["success"]
    assert service.get_all_preferences("alice") == {"shared-key": "second", "moved": "first"}
    assert service.delete_memory("alice", ids[0])["success"]
    assert service.get_all_preferences("alice") == {"shared-key": "second"}


def test_lifecycle_commands_cannot_mutate_another_users_memory(
    memory_factory: MemoryFactory, tmp_path: Path
) -> None:
    service = memory_factory("json")
    memory_id = service.propose_memory_candidate(
        "alice", "preference", "private", "original", source="user_explicit"
    )["candidate"]["memory_id"]
    assert service.confirm_memory_candidate("alice", memory_id)["success"]
    path = tmp_path / "memory.json"
    before = path.read_bytes()
    attempts = [
        lambda: service.confirm_memory_candidate("bob", memory_id),
        lambda: service.correct_memory("bob", memory_id, value="other user's change"),
        lambda: service.reject_memory_candidate("bob", memory_id),
        lambda: service.delete_memory("bob", memory_id),
        lambda: service.record_memory_recall("bob", memory_id),
    ]
    for attempt in attempts:
        assert attempt()["success"] is False
        assert path.read_bytes() == before
    assert service.get_all_preferences("alice") == {"private": "original"}
    assert service.list_memories("bob") == []


def test_concurrent_candidate_proposals_are_deduplicated(memory_factory: MemoryFactory) -> None:
    service = memory_factory("json")
    barrier = Barrier(4, timeout=5)

    def propose() -> dict[str, Any]:
        barrier.wait()
        return service.propose_memory_candidate(
            "alice", "entity", "contact", {"name": "ACME"}, source="user_explicit"
        )

    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [workers.submit(propose) for _ in range(4)]
        results = [future.result(timeout=10) for future in futures]
    assert sum(result["created"] for result in results) == 1
    assert len({result["candidate"]["memory_id"] for result in results}) == 1
    assert len(service.list_memories("alice")) == 1


def test_late_helpers_preserve_argument_shapes_and_policy_replacement(
    memory_factory: MemoryFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = memory_factory("memory")
    lookup = Mock(side_effect=["ACME", "label"])
    monkeypatch.setattr(service, "get_preference", lookup)
    assert service.apply_preference_to_slots("alice", "shipment", {}) == {
        "unit_name": "ACME",
        "template": "label",
    }
    assert lookup.call_args_list == [
        call("alice", "favorite_customer"),
        call("alice", "default_template"),
    ]
    fingerprint = Mock(return_value="replacement fingerprint")
    monkeypatch.setattr(service, "_memory_v2_fingerprint", fingerprint)
    monkeypatch.setattr(module, "MEMORY_V2_BLOCKED_SOURCES", {"user_explicit"})
    candidate = service.propose_memory_candidate(
        "alice", "entity", "contact", "ACME", source="user_explicit"
    )["candidate"]
    fingerprint.assert_called_once_with("entity", "contact", "ACME")
    assert candidate["fingerprint"] == "replacement fingerprint"
    assert candidate["status"] == "rejected"
    assert candidate["source_policy"] == "blocked"


def _repository(path: Path) -> MemoryRepository:
    return MemoryRepository(
        storage_type="memory",
        memory_path=path,
        backend=None,
        new_memory=UserMemory,
        now=lambda: "2026-10-22T12:00:00",
        logger=logging.getLogger(__name__),
    )


def test_store_can_be_replaced_after_service_construction(
    memory_factory: MemoryFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = memory_factory("memory")
    service.add_preference("alice", "old", "original")
    original = service._store
    replacement = _repository(tmp_path / "replacement.json")
    monkeypatch.setattr(service, "_store", replacement)
    service.add_preference("alice", "new", "replacement")
    assert service.get_all_preferences("alice") == {"new": "replacement"}
    original_memory = original.get_memory("alice")
    assert original_memory is not None
    assert original_memory.preferences["old"]["value"] == "original"
    assert "new" not in original_memory.preferences


def test_preferences_work_with_an_independent_repository(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "independent.json")
    lookup = Mock(return_value="ACME")
    preferences = PreferenceMemory(
        MemoryAccess(
            repository.transaction,
            repository.get_memory,
            repository.save_memory,
            UserMemory,
            lambda: "2026-10-22T12:00:00",
        ),
        lookup,
        logging.getLogger(__name__),
    )
    value = {"nested": ["original"]}
    preferences.add_preference("alice", "saved", value)
    value["nested"].append("caller mutation")
    snapshot = repository.get_memory("alice")
    assert snapshot is not None
    snapshot.preferences["saved"]["value"]["nested"].append("reader mutation")
    assert preferences.get_preference("alice", "saved") == {"nested": ["original"]}
    assert preferences.apply_preference_to_slots("alice", "shipment", {"template": "label"}) == {
        "unit_name": "ACME",
        "template": "label",
    }
    lookup.assert_called_once_with("alice", "favorite_customer")


def test_components_import_without_the_service_facade() -> None:
    script = textwrap.dedent(
        """
        import importlib
        import importlib.abc
        import sys

        class BlockFacade(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.startswith("app.services.user_memory_service"):
                    raise AssertionError("component imported service facade")

        sys.meta_path.insert(0, BlockFacade())
        for name in ("models", "ports", "json_storage", "persistence", "policy",
                     "preferences", "candidates", "queries", "patterns", "feedback"):
            importlib.import_module("app.services.user_memory." + name)
        assert "app.services.user_memory_service" not in sys.modules
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr


def test_collision_does_not_remove_an_unowned_temporary_file(
    memory_factory: MemoryFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = memory_factory("json")
    temporary = tmp_path / ".memory.json.collision.tmp"
    temporary.write_text("owned elsewhere")
    monkeypatch.setattr(module.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    with pytest.raises(FileExistsError):
        service._store.save_memory("alice", module.UserMemory("alice"))
    assert temporary.read_text() == "owned elsewhere"


def test_failed_stream_wrapper_closes_its_owned_descriptor(
    memory_factory: MemoryFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = memory_factory("json")
    opened: list[int] = []

    def fail_fdopen(fd: int, *args: Any, **kwargs: Any) -> NoReturn:
        opened.append(fd)
        raise OSError("synthetic wrapper failure")

    monkeypatch.setattr(module.os, "fdopen", fail_fdopen)
    try:
        with pytest.raises(OSError, match="synthetic wrapper failure"):
            service._store.save_memory("alice", module.UserMemory("alice"))
        assert len(opened) == 1
        with pytest.raises(OSError):
            os.fstat(opened[0])
        assert list(tmp_path.glob(".*.tmp")) == []
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass


def test_failed_replace_preserves_bytes_and_releases_the_transaction(
    memory_factory: MemoryFactory, tmp_path: Path
) -> None:
    service = memory_factory("json")
    service.add_preference("alice", "value", "original")
    path = tmp_path / "memory.json"
    before = path.read_bytes()
    mode = path.stat().st_mode
    with patch.object(module.os, "replace", side_effect=OSError("synthetic replace failure")):
        with pytest.raises(OSError, match="synthetic replace failure"):
            service.add_preference("alice", "value", "failed write")
    assert path.read_bytes() == before
    assert path.stat().st_mode == mode
    assert list(tmp_path.glob(".*.tmp")) == []
    assert service.get_preference("alice", "value") == "original"
    service.add_preference("alice", "value", "next write")
    assert service.get_preference("alice", "value") == "next write"


def test_legacy_trace_noop_and_explicit_event_publisher_are_preserved(
    memory_factory: MemoryFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.neuro_bus import (
        event_publisher_mixin,
        neuro_service_instrumentation,
        neuro_trace_config,
    )

    trace = Mock()
    monkeypatch.setattr(neuro_trace_config, "should_sample_app_service", lambda: True)
    monkeypatch.setattr(neuro_service_instrumentation, "neuro_trace_service_call", trace)
    service = memory_factory("memory")
    service.add_preference("alice", "customer", "ACME")
    assert service.get_preference("alice", "customer") == "ACME"
    service.record_action("alice", "shipment", {})
    assert service.get_memory_summary("alice")["has_memory"] is True
    trace.assert_not_called()
    bus = Mock()
    monkeypatch.setattr(event_publisher_mixin, "get_neuro_bus", lambda: bus)
    event_id = service._publish_event("memory.test", {"isolated": True})
    bus.publish.assert_called_once()
    event = bus.publish.call_args.args[0]
    assert event.metadata.event_id == event_id
    assert event.payload == {"isolated": True, "source": "UserMemoryService"}


def test_actual_http_projection_changes_and_user_permissions(
    memory_factory: MemoryFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.application.dataset_rag_app_service import DatasetAccessContext
    from app.application.persy_memory_app_service import PersyMemoryApplicationService
    from app.fastapi_routes import knowledge_v1

    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")
    service = memory_factory("json")
    persy = PersyMemoryApplicationService(service)
    access = DatasetAccessContext(
        actor_id="alice", tenant_id="2", permissions=frozenset({"dataset.read", "dataset.write"})
    )
    captured = persy.capture_conversation_turn(access_context=access, user_message="我偏好下午沟通")
    memory_id = captured["candidates"][0]["memory_id"]
    headers = {
        "X-Dataset-Actor-ID": "alice",
        "X-Dataset-Tenant-ID": "2",
        "X-Dataset-Permissions": "dataset.read,dataset.write",
    }
    app = FastAPI()
    app.include_router(knowledge_v1.router)
    monkeypatch.setattr(knowledge_v1, "_persy_memory_service", lambda: persy)
    url = f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}"
    with TestClient(app) as client:
        confirmed = client.post(url + "/confirm", headers=headers, json={"key": "old-key"})
        assert confirmed.status_code == 200
        path = tmp_path / "memory.json"
        before_denial = path.read_bytes()
        forbidden = client.patch(
            url,
            headers={**headers, "X-Dataset-Permissions": "dataset.read"},
            json={"key": "forbidden"},
        )
        other_user = client.post(
            url + "/confirm", headers={**headers, "X-Dataset-Actor-ID": "bob"}, json={}
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["required_permission"] == "dataset.write"
        assert other_user.status_code == 404
        assert other_user.json()["error_code"] == "persy_memory_not_found"
        assert path.read_bytes() == before_denial
        renamed = client.post(url + "/confirm", headers=headers, json={"key": "new-key"})
        assert renamed.status_code == 200
        persisted = json.loads(path.read_text())
        owner = next(memory for memory in persisted.values() if memory["memory_v2_records"])
        assert set(owner["preferences"]) == {"new-key"}
        converted = client.post(url + "/confirm", headers=headers, json={"memory_type": "entity"})
        assert converted.status_code == 200
        persisted = json.loads(path.read_text())
        owner = next(memory for memory in persisted.values() if memory["memory_v2_records"])
        assert owner["preferences"] == {}
        assert client.delete(url, headers=headers).status_code == 200
