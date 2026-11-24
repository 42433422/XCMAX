"""L4 relation policy and path evidence unit contracts."""

from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock

from app.application.user_memory.relation_retrieval import (
    parse_as_of,
    relation_paths,
    select_effective_records,
    validate_relation_value,
)
from app.application.user_memory.retrieve import filter_recalled_memories, relation_recall_hits


def fact(mid, subject, obj, *, predicate="employs", scope="owner", **extra):
    return {
        "memory_id": mid,
        "revision": 1,
        "scope": scope,
        "status": "active",
        "eligible_for_planner": True,
        "source_policy": "trusted_pending",
        "statement": f"{subject} {predicate} {obj}",
        "value": {
            "statement": f"{subject} {predicate} {obj}",
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "entities": [
                {"name": subject, "role": "subject", "type": "organization"},
                {"name": obj, "role": "object", "type": "organization"},
            ],
            **extra,
        },
    }


def test_effective_intervals_are_half_open_and_explicit():
    first = fact(
        "a",
        "Acme",
        "Alice",
        relation_validity={
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_until": "2026-07-01T00:00:00Z",
        },
    )
    second = fact("b", "Acme", "Bob")
    selected, conflicts, unknown = select_effective_records(
        [first, second], at=datetime(2026, 7, 1, tzinfo=UTC), require_explicit=True
    )
    assert selected == [] and conflicts == [] and unknown == 1
    selected, _, _ = select_effective_records(
        [first, second], at=datetime(2026, 1, 1, tzinfo=UTC), require_explicit=True
    )
    assert selected == [first]
    assert validate_relation_value({"relation_validity": {"effective_from": "2026-01-01"}})


def test_explicit_single_value_conflicts_are_withheld_per_scope():
    one = fact("a", "Acme", "Alice", relation_cardinality="one")
    two = fact("b", "Acme", "Bob")
    tenant = fact("c", "Acme", "Chris", scope="tenant")
    selected, conflicts, _ = select_effective_records([one, two, tenant])
    assert selected == [tenant]
    assert conflicts[0]["memory_ids"] == ["a", "b"]
    assert select_effective_records([fact("d", "Acme", "Alice"), two])[1] == []


def test_explicit_identifiers_never_merge_with_same_name_candidates():
    first = fact("a", "Acme", "Alice")
    second = fact("b", "Alice", "Phoenix")
    first["value"]["entities"][1]["entity_id"] = "person:1"
    second["value"]["entities"][0]["entity_id"] = "person:2"
    assert ("owner", "b") not in relation_paths("Acme", [first, second], max_hops=2)[0]
    second["value"]["entities"][0].pop("entity_id")
    assert ("owner", "b") not in relation_paths("Acme", [first, second], max_hops=2)[0]
    second["value"]["entities"][0]["entity_id"] = "person:1"
    assert ("owner", "b") in relation_paths("Acme", [first, second], max_hops=2)[0]


def test_agent_relation_path_rejects_revoked_or_changed_intermediate():
    owner = "personal-memory:v1:test"
    first = fact("a", "Acme", "Alice")
    second = fact("b", "Alice", "Phoenix")
    service = MagicMock()
    service.list_memories.return_value = [first, second]
    hits = relation_recall_hits(owner, "Acme", memory_service=service)
    assert [hit["metadata"]["source_memory_id"] for hit in hits] == ["b"]
    service.list_memories.return_value = [{**first, "revision": 2}, second]
    assert filter_recalled_memories(owner, hits, memory_service=service) == []
    service.list_memories.return_value = [{**first, "status": "deleted"}, second]
    assert filter_recalled_memories(owner, hits, memory_service=service) == []


@pytest.mark.parametrize(
    "timestamp",
    ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"],
)
def test_utc_conversion_overflow_stays_a_validation_error(timestamp):
    with pytest.raises(ValueError, match="UTC conversion is out of range"):
        parse_as_of(timestamp)
    outcome = validate_relation_value(
        {"relation_validity": {"effective_from": timestamp}}
    )
    assert outcome is not None
    assert outcome["success"] is False
    assert outcome["error_code"] == "memory_invalid_relation_validity"
