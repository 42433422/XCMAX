"""Authority-level tests for overlapping single-valued memory relations."""

from concurrent.futures import ThreadPoolExecutor

from app.application.dataset_rag_app_service import DatasetAccessContext
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.application.persy_memory_utils import _memory_owner_id
from app.application.user_memory.relation_retrieval import relation_write_conflicts
from tests.fixtures.governed_memory_runtime import governed_memory as governed_memory
from tests.fixtures.governed_memory_runtime import owner_id


def _value(person, *, start=None, end=None, cardinality="one"):
    value = {
        "statement": f"Northwind contact {person}",
        "subject": "Northwind",
        "predicate": "contact",
        "object": person,
        "relation_cardinality": cardinality,
        "entities": [
            {
                "name": "Northwind",
                "type": "organization",
                "role": "subject",
                "entity_id": "customer:17",
            },
            {"name": person, "type": "person", "role": "object"},
        ],
    }
    if start or end:
        value["relation_validity"] = {
            **({"effective_from": start} if start else {}),
            **({"effective_until": end} if end else {}),
        }
    return value


def _propose(runtime, value, owner):
    result = runtime.authority.propose_memory_candidate(
        owner,
        "entity",
        "contact",
        value,
        source="user_explicit",
        evidence=[{"source": "reviewed_business_record"}],
    )
    assert result["success"]
    return result["candidate"]


def test_overlap_requires_review_and_half_open_successor_can_activate(governed_memory):
    runtime = governed_memory
    owner = owner_id()
    boundary = "2027-01-01T00:00:00Z"
    first = runtime.confirm(_propose(runtime, _value("Alice"), owner))
    second = _propose(runtime, _value("Bob", start=boundary), owner)
    assert second["status"] == "pending"
    assert second["conflict_review"] == [
        {"memory_id": first["memory_id"], "revision": first["revision"]}
    ]
    refused = runtime.authority.confirm_memory_candidate(owner, second["memory_id"])
    assert refused["error_code"] == "memory_relation_review_required"
    assert [
        row["memory_id"] for row in runtime.authority.list_memories(owner, status="active")
    ] == [first["memory_id"]]

    corrected = runtime.authority.correct_memory(
        owner,
        first["memory_id"],
        value=_value("Alice", end=boundary),
        reason="reviewed end date",
    )
    assert corrected["success"]
    accepted = runtime.confirm(second)
    assert "conflict_review" not in accepted
    assert len(runtime.authority.list_memories(owner, status="active")) == 2


def test_two_pending_confirms_cannot_both_win(governed_memory, monkeypatch):
    runtime = governed_memory
    owner = owner_id()
    first = _propose(runtime, _value("Alice"), owner)
    second = _propose(runtime, _value("Bob"), owner)
    # Isolate the transactional authority from external indexing in this race.
    monkeypatch.setattr(
        "app.application.user_memory.projections.sync_memory_projection",
        lambda *args, **kwargs: {"user_vector": "current", "mem0": "current"},
    )

    def confirm(row):
        return runtime.authority.confirm_memory_candidate(owner, row["memory_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, [first, second]))
    assert sum(result["success"] for result in results) == 1
    assert (
        sum(result.get("error_code") == "memory_relation_review_required" for result in results)
        == 1
    )
    assert len(runtime.authority.list_memories(owner, status="active")) == 1


def test_many_valued_relations_do_not_require_singleton_review():
    first = {
        "memory_id": "first",
        "revision": 1,
        "status": "active",
        "eligible_for_planner": True,
        "value": _value("Alice", cardinality="many"),
    }
    second = {"memory_id": "second", "value": _value("Bob", cardinality="many")}
    assert relation_write_conflicts([first], second) == []


def test_shared_memory_review_and_revocation_cross_actor_but_not_mod(governed_memory):
    runtime = governed_memory
    service = PersyMemoryApplicationService(runtime.authority)

    def access(actor, *, tenant="2", mod="sales"):
        return DatasetAccessContext(
            actor_id=actor,
            tenant_id=tenant,
            mod_id=mod,
            permissions=frozenset({"dataset.read", "dataset.write"}),
        )

    alice, bob = access("7"), access("8")
    tenant_owner = _memory_owner_id(alice, "tenant")
    private_owner = _memory_owner_id(alice, "user")
    private = _propose(runtime, _value("PrivateContact"), private_owner)
    runtime.confirm(private, owner=private_owner)
    shared = _propose(runtime, _value("Alice"), tenant_owner)
    assert service.query(access_context=bob, query="Northwind")["chunks"] == []
    confirmed = service.mutate(
        access_context=alice,
        memory_id=shared["memory_id"],
        action="confirm",
    )
    assert confirmed["success"]
    ids = {
        row["metadata"]["memory_id"]
        for row in service.query(access_context=bob, query="Northwind")["chunks"]
    }
    assert ids == {shared["memory_id"]}
    for outsider in (access("8", tenant="3"), access("8", mod="finance")):
        assert service.query(access_context=outsider, query="Northwind")["chunks"] == []
    correction = service.mutate(
        access_context=alice,
        memory_id=shared["memory_id"],
        action="correct",
        patch={"value": _value("Bob")},
        reason="reviewed change",
    )
    assert correction["success"]
    latest = service.query(access_context=bob, query="Northwind")["chunks"]
    assert len(latest) == 1 and "Bob" in latest[0]["text"]
    assert latest[0]["metadata"]["source_revision"] == correction["memory"]["revision"]
    assert service.mutate(access_context=alice, memory_id=shared["memory_id"], action="delete")[
        "success"
    ]
    assert service.query(access_context=bob, query="Northwind")["chunks"] == []
