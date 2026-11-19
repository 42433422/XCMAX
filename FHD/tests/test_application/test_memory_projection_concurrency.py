"""Real replicas converge when authority changes around an external write."""

from __future__ import annotations

import time
from types import SimpleNamespace

from app.application.user_memory import projections
from app.infrastructure.memory import mem0_backend
from tests.fixtures.governed_memory_runtime import governed_memory as governed_memory
from tests.fixtures.governed_memory_runtime import owner_id


def test_late_correction_callback_cannot_recreate_deleted_projections(governed_memory, monkeypatch):
    runtime = governed_memory
    confirmed = runtime.confirm(runtime.propose())
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算")
    sync = projections.sync_memory_projection
    delayed = []

    def capture_callback(*args, **kwargs):
        delayed.append((args, kwargs))
        return {"user_vector": "delayed", "mem0": "delayed"}

    with monkeypatch.context() as hold:
        hold.setattr(projections, "sync_memory_projection", capture_callback)
        runtime.authority.correct_memory(
            owner_id(), confirmed["memory_id"], value={"statement": "采购预算：80万元"}
        )
    deleted = runtime.authority.delete_memory(owner_id(), confirmed["memory_id"])
    assert deleted["projection"] == {"user_vector": "removed", "mem0": "removed"}
    assert runtime.native_rows() == [] and runtime.vector_rows() == []

    args, kwargs = delayed[0]
    assert sync(*args, **kwargs) == {"user_vector": "removed", "mem0": "removed"}
    assert runtime.native_rows() == [] and runtime.vector_rows() == []
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    assert runtime.authority.list_memories(owner_id())[0]["status"] == "deleted"


def test_revocation_during_projection_is_detected_by_the_final_authority_check(
    governed_memory, monkeypatch
):
    runtime = governed_memory
    confirmed = runtime.confirm(runtime.propose())
    upsert = runtime.backend.upsert_governed

    def revoke_then_finish_old_write(**kwargs):
        removed = runtime.authority.delete_memory(owner_id(), confirmed["memory_id"])
        assert removed["projection"] == {"user_vector": "removed", "mem0": "removed"}
        return upsert(**kwargs)

    monkeypatch.setattr(runtime.backend, "upsert_governed", revoke_then_finish_old_write)
    changed = runtime.authority.correct_memory(
        owner_id(), confirmed["memory_id"], value={"statement": "采购预算：80万元"}
    )
    assert changed["projection"] == {"user_vector": "removed", "mem0": "removed"}
    assert runtime.native_rows() == [] and runtime.vector_rows() == []
    assert runtime.rag.query(owner_id(), "采购预算")["hits"] == []


def test_repeated_authority_changes_bound_sync_and_retry_the_latest_revision(
    governed_memory, monkeypatch
):
    runtime = governed_memory
    clock = [time.monotonic()]
    monkeypatch.setattr(
        mem0_backend,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], perf_counter=time.perf_counter),
    )
    confirmed = runtime.confirm(runtime.propose())
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算")
    upsert = runtime.backend.upsert_governed
    writes = []

    def change_again_before_finishing(**kwargs):
        writes.append(kwargs["revision"])
        # The concurrent writer has committed; its indexing callback is delayed.
        with monkeypatch.context() as hold:
            hold.setattr(projections, "sync_memory_projection", lambda *args, **kwargs: {})
            runtime.authority.correct_memory(
                owner_id(),
                confirmed["memory_id"],
                value={"statement": f"采购预算：{100 + len(writes)}万元"},
            )
        return upsert(**kwargs)

    with monkeypatch.context() as racing:
        racing.setattr(runtime.backend, "upsert_governed", change_again_before_finishing)
        changed = runtime.authority.correct_memory(
            owner_id(), confirmed["memory_id"], value={"statement": "采购预算：80万元"}
        )
    assert len(writes) == 2
    assert changed["projection"] == {
        "user_vector": "retry_required",
        "mem0": "retry_required",
    }
    assert owner_id() not in runtime.backend._projected_owners
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    clock[0] += 31
    hits = runtime.backend.recall(user_id=owner_id(), query="采购预算")
    assert hits and "102万元" in hits[0]["content"]
    assert "102万元" in runtime.vector_rows()[0][1]


def test_missing_authority_record_is_removed_instead_of_projecting_a_captured_value(
    governed_memory,
):
    runtime = governed_memory
    captured = {
        "memory_id": "orphaned-memory",
        "revision": 2,
        "status": "active",
        "eligible_for_planner": True,
        "value": {"statement": "采购预算：50万元"},
    }
    for backend in (runtime.backend, runtime.ingest):
        assert backend.upsert_governed(
            user_id=owner_id(),
            source_memory_id=captured["memory_id"],
            revision=2,
            text="采购预算：50万元",
        )
    assert projections.sync_memory_projection(owner_id(), captured) == {
        "user_vector": "removed",
        "mem0": "removed",
    }
    assert runtime.native_rows() == [] and runtime.vector_rows() == []


def test_same_dimensional_collection_change_replays_confirmation_without_reconfirmation(
    governed_memory, monkeypatch
):
    runtime = governed_memory
    confirmed = runtime.confirm(runtime.propose())
    dimensions = runtime.backend._dims
    collection = runtime.backend._active().vector_store.collection_name
    monkeypatch.setenv("FHD_EMBEDDING_MODEL_REVISION", "next-governed-generation")
    runtime.restart()
    assert runtime.backend._dims == dimensions
    assert runtime.backend._active().vector_store.collection_name != collection
    assert runtime.native_rows() == []
    hits = runtime.backend.recall(user_id=owner_id(), query="采购预算")
    assert hits and "50万元" in hits[0]["content"]
    assert hits[0]["metadata"]["source_revision"] == confirmed["revision"]
    assert len(runtime.native_rows()) == 1
    assert runtime.authority.list_memories(owner_id())[0]["status"] == "active"
