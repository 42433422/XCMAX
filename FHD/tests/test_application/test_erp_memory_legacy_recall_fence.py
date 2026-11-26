"""ERP memory recall fences and verification against committed source rows."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.application.user_memory import projections, retrieve
from app.application.user_memory.queries import MemoryQueries, QueryPorts
from app.db.models import (
    Customer,
    EnterpriseEventCursor,
    EnterpriseStateProjection,
    FinancialTransaction,
    SalesOrder,
    SalesOrderItem,
)
from app.domain.user_memory.policy import is_erp_bound_memory
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_enterprise_projection import get
from tests.test_application.test_enterprise_projection import world as world

OWNER = "personal-memory:v1:erp-recall-fence"


def _rows():
    erp = {
        "memory_id": "erp-1",
        "memory_type": "entity",
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
        "memory_type": "preference",
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
        def list_memories(self, user_id, *, status=None, memory_type=None):
            assert user_id == OWNER
            return [
                row
                for row in (erp, plain)
                if (status is None or row["status"] == status)
                and (memory_type is None or row["memory_type"] == memory_type)
            ]

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
    assert "secret" not in formatter.format_memory_v2_for_prompt(OWNER, memory_type="entity")
    assert "简洁报告" in formatter.format_memory_v2_for_prompt(OWNER, memory_type="preference")


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
    monkeypatch.setattr("app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: mem0)
    actual = projections.sync_memory_projection(OWNER, erp, list_records=lambda owner: [erp, plain])
    assert actual == {"user_vector": "removed", "mem0": "removed"}
    assert vector.removed == [(OWNER, "erp-1")]
    assert mem0.removed == [(OWNER, "erp-1")]


@pytest.mark.parametrize(
    "entity_type,entity_id,model,field,replacement",
    [
        ("customer", "201", Customer, "customer_name", "Customer A corrected"),
        ("fund", "301", FinancialTransaction, "amount", Decimal(95)),
    ],
)
def test_customer_and_finance_remembered_facts_are_superseded_by_erp(
    world, entity_type, entity_id, model, field, replacement
):
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    service, sessions, clock, _ = world
    before = get(service, entity_type, entity_id)
    assert before["knowledge_kind"] == "fact"
    with sessions.begin() as db:
        setattr(db.get(model, int(entity_id)), field, replacement)
    clock[0] += 1  # preserve observation ordering, but stay within the 30s TTL
    after = get(service, entity_type, entity_id, force_refresh=True)
    assert after["retrieved_from"] == "authority"
    assert after["source_version"] != before["source_version"]
    superseded = verify_source_reference(
        after, before["source_version"], make_fact_reference(before)["fact_token"]
    )
    assert superseded["status"] == "superseded"
    assert superseded["memory_reuse_allowed"] is False
    assert superseded["requires_reconciliation"] is True
    assert (
        verify_source_reference(
            after, after["source_version"], make_fact_reference(after)["fact_token"]
        )["status"]
        == "current"
    )


def test_source_verification_never_writes_derived_cache_or_history(world):
    service, sessions, clock, _ = world
    baseline = get(service)
    assert baseline["retrieved_from"] == "authority"
    with sessions() as db:
        projection = db.scalar(
            select(EnterpriseStateProjection).where(
                EnterpriseStateProjection.entity_type == "order",
                EnterpriseStateProjection.entity_id == "101",
            )
        )
        prior_json = projection.snapshot_json
        prior_expiry = projection.expires_at
        prior_generation = db.scalar(select(EnterpriseEventCursor)).generation

    # Repeated source-version checks are read-only and never churn history.
    for _ in range(3):
        checked = get(service, verify_only=True)
        assert checked["retrieved_from"] == "authority"
        assert checked["source_version"] == baseline["source_version"]
        with sessions() as db:
            same = db.scalar(
                select(EnterpriseStateProjection).where(
                    EnterpriseStateProjection.entity_type == "order",
                    EnterpriseStateProjection.entity_id == "101",
                )
            )
            assert same.snapshot_json == prior_json
            assert same.expires_at == prior_expiry
            assert db.scalar(select(EnterpriseEventCursor)).generation == prior_generation
    with sessions.begin() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = Decimal(9)
    clock[0] += 1
    revised = get(service, verify_only=True)
    assert revised["source_version"] != baseline["source_version"]
    assert revised["state"]["remaining_quantity"] == "1.0000"
    with sessions() as db:
        assert (
            db.scalar(
                select(EnterpriseStateProjection).where(
                    EnterpriseStateProjection.entity_type == "order",
                    EnterpriseStateProjection.entity_id == "101",
                )
            ).snapshot_json
            == prior_json
        )
    # A read-through verification cannot silently alter the ordinary TTL contract.
    assert get(service)["source_version"] == baseline["source_version"]
    with pytest.raises(ValueError, match="source_verification_requires_current_authority"):
        get(service, verify_only=True, as_of=baseline["observed_at"])


def test_verify_only_first_read_does_not_create_derived_cursor(world):
    service, sessions, _, _ = world
    result = get(service, "customer", "201", verify_only=True)
    assert result["knowledge_kind"] == "fact"
    assert result["last_event_id"] is None
    with sessions() as db:
        assert not db.scalars(
            select(EnterpriseEventCursor).where(EnterpriseEventCursor.entity_type == "customer")
        ).all()
        assert not db.scalars(
            select(EnterpriseStateProjection).where(
                EnterpriseStateProjection.entity_type == "customer"
            )
        ).all()


def test_cancelled_erp_order_invalidates_fact_reference_without_delivered_event(world):
    """The committed sales row, not memory deletion or bus notification, is authority."""
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    service, sessions, clock, _ = world
    before = get(service, verify_only=True)
    token = make_fact_reference(before)
    assert token is not None
    with tenant_scope(11), sessions.begin() as db:
        db.get(SalesOrder, 101).state = "cancel"
    clock[0] += 1
    current = get(service, verify_only=True)
    assert current["retrieved_from"] == "authority"
    assert current["state"]["state"] == "cancel"
    assert current["source_version"] != before["source_version"]
    old = verify_source_reference(current, token["source_version"], token["fact_token"])
    assert old["status"] == "superseded"
    assert old["memory_reuse_allowed"] is False
    assert old["requires_reconciliation"] is True
    with tenant_scope(11), sessions() as db:
        assert db.get(SalesOrder, 101).state == "cancel"


def test_separate_source_commits_never_restore_an_old_fact_token(world):
    """Two independent committed changes must both invalidate a stale memory token.

    These are separate SQLAlchemy sessions; a PostgreSQL simultaneous-write
    CAS test is still required before claiming multi-process ERP protection.
    """
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    service, sessions, clock, _ = world
    baseline = get(service, verify_only=True)
    reference = make_fact_reference(baseline)
    assert reference is not None
    with tenant_scope(11):
        with sessions() as first, sessions() as second:
            first_order = first.get(SalesOrder, 101)
            second_order = second.get(SalesOrder, 101)
            first_order.state = "sent"
            first.commit()
            second_order.payment_state = "partial"
            second.commit()
    clock[0] += 2
    updated = get(service, verify_only=True)
    assert updated["state"]["state"] == "sent"
    assert updated["state"]["payment_state"] == "partial"
    assert (
        verify_source_reference(updated, reference["source_version"], reference["fact_token"])[
            "status"
        ]
        == "superseded"
    )
    with tenant_scope(11), sessions() as db:
        order = db.get(SalesOrder, 101)
        assert order.state == "sent"
        assert order.payment_state == "partial"


def test_persy_memoryv2_sql_authority_revokes_recall_without_bus_event(world, monkeypatch):
    """Real SQL source changes invalidate MemoryV2/Persy reuse, not history itself."""
    from app.application.dataset_rag_app_service import DatasetAccessContext
    from app.application.persy_memory_app_service import PersyMemoryApplicationService
    from app.application.persy_memory_utils import _memory_owner_id
    from app.application.user_memory.retrieve import filter_recalled_memories
    from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore

    projection, sessions, clock, permissions = world
    monkeypatch.setattr(UserMemoryStore, "_instance", None)
    monkeypatch.setattr(UserMemoryService, "_instance", None)
    memory = UserMemoryService(storage_type="memory")
    persy = PersyMemoryApplicationService(memory)
    monkeypatch.setattr(
        "app.application.enterprise_cognition.projection.get_projection_service",
        lambda: projection,
    )
    access = DatasetAccessContext(
        actor_id="1",
        tenant_id="11",
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )
    owner = _memory_owner_id(access)

    def capture_and_confirm():
        result = persy.capture_erp_field(
            access_context=access,
            entity_type="customer",
            entity_id="201",
            field="customer_name",
        )
        assert result["success"] is True
        candidate = result["candidate"]
        assert candidate["status"] == "pending"
        approved = persy.mutate(
            access_context=access, memory_id=candidate["memory_id"], action="confirm"
        )
        assert approved["success"] is True
        return candidate["memory_id"]

    original_id = capture_and_confirm()
    assert any(
        row["memory_id"] == original_id and row["status"] == "active"
        for row in memory.list_memories(owner)
    )
    before = persy.query(access_context=access, query="ERP customer")
    assert any("Customer A" in row["text"] for row in before["chunks"])

    # No memory mutation or bus delivery: read the committed business row again.
    with sessions.begin() as db:
        db.get(Customer, 201).customer_name = "Customer B"
    clock[0] += 1
    assert any(row["memory_id"] == original_id for row in memory.list_memories(owner))
    stale = persy.query(access_context=access, query="ERP customer")
    assert stale["chunks"] == []
    assert stale["erp_revalidation_dropped"] >= 1
    assert "Customer A" not in repr(persy.list_memories(access_context=access))
    legacy_hits = [
        {
            "content": "Customer A",
            "metadata": {
                "source_memory_id": original_id,
                "source_owner_id": owner,
                "source_revision": row["revision"],
            },
            "score": 1.0,
        }
        for row in memory.list_memories(owner)
        if row["memory_id"] == original_id
    ]
    assert legacy_hits
    assert filter_recalled_memories(owner, legacy_hits, memory_service=memory) == []

    current_id = capture_and_confirm()
    assert current_id != original_id
    current = persy.query(access_context=access, query="ERP customer")
    assert any("Customer B" in row["text"] for row in current["chunks"])
    permissions.remove("customer.view")
    denied = persy.query(access_context=access, query="ERP customer")
    assert denied["chunks"] == []
    assert "Customer B" not in repr(persy.list_memories(access_context=access))
    with sessions() as db:
        assert db.get(Customer, 201).customer_name == "Customer B"
