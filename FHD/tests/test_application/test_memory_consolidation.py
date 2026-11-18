"""MemoryV2 authority replaces autonomous ADD/NOOP/SUPERSEDE decisions."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from app.infrastructure.memory import mem0_backend
from app.infrastructure.memory.memory_units import is_active, lexical_overlap, rank_hits
from tests.fixtures.governed_memory_runtime import governed_memory as governed_memory
from tests.fixtures.governed_memory_runtime import owner_id


def test_is_active_filters_superseded_and_expired() -> None:
    assert is_active({"valid_from": "2026-01-01", "valid_to": "", "superseded_by": ""})
    assert not is_active({"superseded_by": "new"})
    assert not is_active({"valid_to": "2020-01-01"})
    assert not is_active({"expiration_date": "2020-01-01"})


def test_lexical_overlap_rewards_keyword_match() -> None:
    assert lexical_overlap("预算 80", "预算：80万元") > 0
    assert lexical_overlap("预算 80", "仓库：华东") == 0


def test_stale_projection_does_not_take_a_ranked_slot() -> None:
    hits = [
        {
            "chunk_id": "old",
            "content": "预算：50万元",
            "score": 0.99,
            "metadata": {"memory_type": "fact", "superseded_by": "new"},
        },
        {
            "chunk_id": "new",
            "content": "预算：80万元",
            "score": 0.5,
            "metadata": {"memory_type": "fact"},
        },
    ]
    assert [row["chunk_id"] for row in rank_hits(hits, query="预算 80", limit=3)] == ["new"]


def test_candidate_deduplication_and_reconfirmation_do_not_duplicate_projections(governed_memory):
    runtime = governed_memory
    first = runtime.propose()
    repeated = runtime.propose()
    assert first["memory_id"] == repeated["memory_id"]
    assert len(runtime.authority.list_memories(owner_id())) == 1
    assert runtime.native_rows() == [] and runtime.vector_rows() == []

    confirmed = runtime.confirm(first)
    native_id = runtime.native_rows()[0]["id"]
    vector_id = runtime.vector_rows()[0][0]
    repeated = runtime.confirm(first)
    assert repeated["revision"] == confirmed["revision"]
    assert [row["id"] for row in runtime.native_rows()] == [native_id]
    assert [row[0] for row in runtime.vector_rows()] == [vector_id]


def test_projection_metadata_cannot_confirm_a_pending_authority_record(governed_memory):
    runtime = governed_memory
    pending = runtime.propose()
    for provider in (runtime.backend, runtime.ingest):
        assert provider.upsert_governed(
            user_id=owner_id(),
            source_memory_id=pending["memory_id"],
            revision=pending["revision"],
            text="采购预算：50万元",
            metadata={"status": "active", "eligible_for_planner": True},
        )
    assert runtime.rag.query(owner_id(), "采购预算")["hits"] == []
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    assert runtime.authority.list_memories(owner_id())[0]["status"] == "pending"


def test_revision_upsert_cannot_restore_an_old_or_conflicting_value(governed_memory):
    runtime = governed_memory
    confirmed = runtime.confirm(runtime.propose())
    source_id = confirmed["memory_id"]
    native_id = runtime.native_rows()[0]["id"]
    vector_id = runtime.vector_rows()[0][0]
    old_hits = runtime.backend.recall(user_id=owner_id(), query="采购预算")
    changed = runtime.authority.correct_memory(
        owner_id(), source_id, value={"statement": "采购预算：80万元"}
    )
    assert changed["projection"] == {"user_vector": "current", "mem0": "current"}
    current = changed["memory"]
    assert current["memory_id"] == source_id
    assert current["revision"] > confirmed["revision"]
    assert "50万元" in json.dumps(current["history"], ensure_ascii=False)
    assert runtime.authority.filter_recalled_memories(owner_id(), old_hits) == []
    for provider in (runtime.backend, runtime.ingest):
        assert not provider.upsert_governed(
            user_id=owner_id(),
            source_memory_id=source_id,
            revision=confirmed["revision"],
            text="采购预算：50万元",
        )
        assert not provider.upsert_governed(
            user_id=owner_id(),
            source_memory_id=source_id,
            revision=current["revision"],
            text="same-revision-forgery",
        )
    assert [row["id"] for row in runtime.native_rows()] == [native_id]
    assert [row[0] for row in runtime.vector_rows()] == [vector_id]
    assert "80万元" in runtime.backend.recall(user_id=owner_id(), query="采购预算")[0]["content"]
    assert "80万元" in runtime.rag.query(owner_id(), "采购预算")["hits"][0]["content"]


def test_confirmation_correction_and_deletion_survive_reopening_all_disk_stores(governed_memory):
    runtime = governed_memory
    confirmed = runtime.confirm(runtime.propose())
    source_id = confirmed["memory_id"]
    assert source_id in (runtime.directory / "authority.json").read_text()

    runtime.restart()
    for hits in (
        runtime.backend.recall(user_id=owner_id(), query="采购预算"),
        runtime.rag.query(owner_id(), "采购预算")["hits"],
    ):
        assert hits and "50万元" in hits[0]["content"]
    changed = runtime.authority.correct_memory(
        owner_id(), source_id, value={"statement": "采购预算：80万元"}, reason="user correction"
    )["memory"]
    runtime.restart()
    for hits in (
        runtime.backend.recall(user_id=owner_id(), query="采购预算"),
        runtime.rag.query(owner_id(), "采购预算")["hits"],
    ):
        assert hits and "80万元" in hits[0]["content"]
        assert "50万元" not in str(hits)
        assert hits[0]["metadata"]["source_revision"] == changed["revision"]

    removed = runtime.authority.delete_memory(owner_id(), source_id, reason="user revocation")
    assert removed["projection"] == {"user_vector": "removed", "mem0": "removed"}
    runtime.restart()
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    assert runtime.rag.query(owner_id(), "采购预算")["hits"] == []
    assert runtime.native_rows() == [] and runtime.vector_rows() == []
    tombstone = runtime.authority.list_memories(owner_id(), status="deleted")[0]
    assert tombstone["memory_id"] == source_id and tombstone["history"]
    assert tombstone["revision"] > changed["revision"]


def test_failed_native_update_and_delete_are_fenced_then_retried_from_authority(
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
    source_id = confirmed["memory_id"]
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算")
    native = runtime.backend._active()

    def offline(*args, **kwargs):
        raise OSError("projection unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(native, "update", offline)
        changed = runtime.authority.correct_memory(
            owner_id(), source_id, value={"statement": "采购预算：80万元"}
        )
        assert changed["projection"]["mem0"] == "retry_required"
        assert "50万元" in runtime.native_rows()[0]["memory"]
        assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
        assert "80万元" in runtime.rag.query(owner_id(), "采购预算")["hits"][0]["content"]
    clock[0] += 31
    repaired = runtime.backend.recall(user_id=owner_id(), query="采购预算")
    assert repaired and "80万元" in repaired[0]["content"]
    assert "50万元" not in str(repaired)

    with monkeypatch.context() as fault:
        fault.setattr(native, "delete", offline)
        removed = runtime.authority.delete_memory(owner_id(), source_id)
        assert removed["projection"]["mem0"] == "retry_required"
        assert runtime.native_rows()
        assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    clock[0] += 31
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []
    assert runtime.native_rows() == []
    runtime.restart()
    assert runtime.backend.recall(user_id=owner_id(), query="采购预算") == []


def test_native_source_and_id_deletion_preserve_other_owners(governed_memory):
    runtime = governed_memory
    mine = runtime.confirm(runtime.propose())
    other = runtime.confirm(
        runtime.propose("他人的采购预算：90万元", owner=owner_id(8)), owner=owner_id(8)
    )
    my_id = runtime.native_rows()[0]["id"]
    foreign_before = runtime.native_rows(owner_id(8))[0]
    foreign_id = foreign_before["id"]

    assert (
        runtime.backend.forget_source(user_id=owner_id(), source_memory_id=other["memory_id"]) == 0
    )
    assert runtime.backend.forget(user_id=owner_id(), memory_ids=[foreign_id]) == 0
    assert runtime.backend.forget(user_id=owner_id(), memory_ids=[]) == 0
    assert runtime.native_rows(owner_id(8))[0] == foreign_before
    assert runtime.backend.forget(user_id=owner_id(), memory_ids=[my_id, foreign_id]) == 1
    assert runtime.native_rows() == []
    assert runtime.native_rows(owner_id(8))[0] == foreign_before
    assert runtime.authority.list_memories(owner_id())[0]["memory_id"] == mine["memory_id"]


def test_native_mod_archive_cleanup_preserves_other_mods_and_owners(governed_memory):
    runtime = governed_memory
    for owner, mod in [(owner_id(), "sales"), (owner_id(), "finance"), (owner_id(8), "sales")]:
        assert runtime.backend.remember(
            user_id=owner,
            user_message=f"{owner} {mod}",
            assistant_message="archived",
            metadata={"mod_id": mod},
        )
    assert runtime.backend.forget(user_id=owner_id(), mod_id="sales") == 1
    remaining = runtime.native_rows()
    foreign = runtime.native_rows(owner_id(8))
    assert len(remaining) == 1 and remaining[0]["metadata"]["mod_id"] == "finance"
    assert len(foreign) == 1 and foreign[0]["metadata"]["mod_id"] == "sales"
    assert runtime.backend.forget(user_id=owner_id(), mod_id="sales") == 0
    assert runtime.backend.recall(user_id=owner_id(), query="archived") == []


def test_fact_prompt_retains_its_label_and_history_warning() -> None:
    prompt = mem0_backend.format_recalled_memories(
        [{"content": "预算：80万元", "score": 0.8, "metadata": {"memory_type": "fact"}}]
    )
    assert "事实：预算：80万元" in prompt
    assert "不要当成本轮已核实的事实" in prompt
