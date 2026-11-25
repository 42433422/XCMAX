"""ERP memory claims cannot bypass source RBAC through legacy or vector recall."""

from __future__ import annotations

from types import SimpleNamespace

from app.application.user_memory import projections, retrieve
from app.application.user_memory.queries import MemoryQueries, QueryPorts
from app.domain.user_memory.policy import is_erp_bound_memory


OWNER = "personal-memory:v1:erp-recall-fence"


def _rows():
    erp = {
        "memory_id": "erp-1",
        "revision": 1,
        "status": "active",
        "eligible_for_planner": True,
        "source_policy": "needs_evidence",
        "source": "erp_authority",
        "key": "erp.customer.201.customer_name",
        "value": {"statement": "ERP customer#201.customer_name = secret"},
        "evidence": [{"kind": "erp_fact_reference_v1"}],
    }
    plain = {
        "memory_id": "plain-1",
        "revision": 1,
        "status": "active",
        "eligible_for_planner": True,
        "source_policy": "trusted_pending",
        "source": "user_explicit",
        "key": "preference",
        "value": {"statement": "用户偏好简洁报告"},
        "evidence": [{"source": "user_explicit"}],
    }
    return erp, plain


def test_legacy_and_vector_recall_exclude_erp_fact_without_actor_rbac(monkeypatch):
    erp, plain = _rows()
    assert is_erp_bound_memory(erp)
    assert not is_erp_bound_memory(plain)

    class Authority:
        def list_memories(self, owner, status=None):
            assert owner == OWNER
            return [erp, plain]

    authority = Authority()
    rows = [
        {
            "content": record["value"]["statement"],
            "metadata": {
                "source_memory_id": record["memory_id"],
                "source_owner_id": OWNER,
                "source_revision": record["revision"],
            },
            "score": 1.0,
        }
        for record in (erp, plain)
    ]
    hits = retrieve.filter_recalled_memories(OWNER, rows, memory_service=authority)
    assert len(hits) == 1
    assert hits[0]["metadata"]["source_memory_id"] == "plain-1"
    assert "secret" not in str(hits)

    # Direct compatibility reads also cannot bypass the source permission fence.
    store = SimpleNamespace(
        get_memory=lambda owner: SimpleNamespace(memory_v2_records=[erp, plain])
    )
    assert retrieve.search("secret", scope="user", owner_id=OWNER, store=store) == []
    context = retrieve.build_memory_context("secret", scope="user", owner_id=OWNER, store=store)
    assert "secret" not in context
    assert retrieve.search("简洁报告", scope="user", owner_id=OWNER, store=store)

    monkeypatch.setattr(
        "app.domain.shared_services.user_memory_service.get_user_memory_service",
        lambda: authority,
    )
    assert retrieve.recall_authoritative_memories(OWNER, "secret") == []
    related = retrieve.relation_recall_hits(OWNER, "secret", memory_service=authority)
    assert "secret" not in str(related)

    # The Agent's direct MemoryV2 formatter is another original recall path.
    formatter = MemoryQueries(
        access=SimpleNamespace(),
        ports=QueryPorts(
            normalize_type=lambda value: value,
            normalize_status=lambda value: value,
            list_memories=authority.list_memories,
        ),
    )
    prompt = formatter.format_memory_v2_for_prompt(OWNER)
    assert "secret" not in prompt
    assert "简洁报告" in prompt


def test_erp_bound_memory_is_removed_not_upserted_to_replicas(monkeypatch):
    erp, plain = _rows()

    class FakeProjection:
        enabled = True

        def __init__(self):
            self.removed = []

        def upsert_governed(self, **kwargs):
            raise AssertionError("ERP claims must never become unverified vector facts")

        def forget_source(self, *, user_id, source_memory_id):
            self.removed.append((user_id, source_memory_id))
            return 1

    vector, mem0 = FakeProjection(), FakeProjection()
    monkeypatch.setattr(
        "app.application.user_memory_vector_app_service.get_user_memory_vector_ingest_app_service",
        lambda: vector,
    )
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: mem0
    )
    actual = projections.sync_memory_projection(
        OWNER, erp, list_records=lambda owner: [erp, plain]
    )
    assert actual == {"user_vector": "removed", "mem0": "removed"}
    assert vector.removed == [(OWNER, "erp-1")]
    assert mem0.removed == [(OWNER, "erp-1")]
