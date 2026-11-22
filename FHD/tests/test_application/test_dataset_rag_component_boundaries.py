"""Dataset components retain durable state across independently composed services."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.application.dataset_rag.document_lifecycle import DocumentLifecycle
from app.application.dataset_rag.document_parser import DocumentParser
from app.application.dataset_rag.models import _renumber_chunks
from app.application.dataset_rag.repository import DatasetRepository
from app.application.dataset_rag.retrieval import DatasetRetrieval
from app.application.dataset_rag.vector_index import VectorIndexService
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.rag import SemanticChunker
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def verified_inline_ingest(tmp_path, monkeypatch, trusted_actor, local_tools):
    from app.application import dataset_rag_app_service as service_module
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor = trusted_actor(role="knowledge-writer", permissions=["dataset.read", "dataset.write"])
    service = DatasetRagApplicationService(
        storage_path=tmp_path / "verified-documents.json",
        embedder=lambda text: [1.0],
        vector_index_backend_name="none",
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(service_module, "_dataset_rag_app_service", service)
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "document-claims.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    plan = PlanGraph(
        plan_id="inline-proof",
        intent="dataset-ingest",
        nodes=[
            WorkflowNode(
                node_id="ingest",
                tool_id="dataset_rag",
                action="ingest_document",
                params={
                    "dataset_id": "verified",
                    "source": "policy.txt",
                    "text": "Approved inline policy. Human review is required. Evidence remains tenant scoped.",
                    "chunk_strategy": "fixed",
                    "chunk_size": 35,
                    "chunk_overlap": 5,
                },
            )
        ],
    )
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="Store approved policy",
        plan=plan,
        runtime_context=actor.context,
    )
    assert run.status == "waiting_user"
    run = orchestrator.continue_run(
        run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
    )
    assert run is not None and run.status == "completed", run.error if run else "missing run"
    return actor, service, repo, run


def _recheck_inline(run):
    from app.application.agent_orchestrator.result_verification import verify_step_result
    from app.application.agent_orchestrator.task_background import task_execution_context

    step = run.steps[0]
    return verify_step_result(
        run=run,
        step=step,
        call=run.tool_calls[0],
        context={
            **run.metadata["runtime_context"],
            "run_id": run.run_id,
            "step_id": step.step_id,
            **task_execution_context(run, step),
        },
    )


def test_inline_ingest_verifies_committed_chunks_without_writer_initialization(
    verified_inline_ingest, monkeypatch
):
    import copy

    _actor, service, _repo, run = verified_inline_ingest
    stored = service._storage_path.read_bytes()
    original = copy.deepcopy(run.tool_calls[0].output)
    service._repository.datasets = {}
    for target, name in (
        (service, "ingest_document"),
        (service._repository, "_persist_locked"),
        (service._repository, "_load_persisted_state"),
        (service._vector, "_sync_vector_index_locked"),
    ):
        monkeypatch.setattr(
            target, name, lambda *args, **kwargs: pytest.fail("readback must not run writers")
        )
    report = _recheck_inline(run)
    assert report["accepted"] is True
    evidence = report["checks"][0]["evidence"]
    assert evidence["scope"] == "current_inline_document_storage"
    assert evidence["vector_index_verified"] is False and evidence["chunk_count"] > 1
    assert service._storage_path.read_bytes() == stored
    assert run.tool_calls[0].output == original and len(run.tool_calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "tenant",
        "version",
        "chunk_text",
        "missing_chunk",
        "source_hash",
        "read_permission",
        "store_path",
        "missing_claim",
        "file_corruption",
    ],
)
def test_inline_ingest_rejects_changed_or_unavailable_evidence(
    verified_inline_ingest, monkeypatch, tmp_path, change
):
    import copy
    import json
    import os
    import sqlite3

    actor, service, _repo, run = verified_inline_ingest
    original = copy.deepcopy(run.tool_calls[0].output)
    if change == "read_permission":
        from app.db.models.permission import Role

        with actor.factory.begin() as db:
            role = db.query(Role).filter_by(name="knowledge-writer").one()
            role.permissions = [
                permission for permission in role.permissions if permission.code != "dataset.read"
            ]
    elif change == "missing_claim":
        with sqlite3.connect(os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"]) as db:
            db.execute("delete from tool_idempotency")
    elif change == "store_path":
        copied = tmp_path / "another-store.json"
        copied.write_bytes(service._storage_path.read_bytes())
        monkeypatch.setattr(service._repository, "storage_path", copied)
    elif change == "file_corruption":
        service._storage_path.write_bytes(b"not a committed JSON document")
    else:
        stored = json.loads(service._storage_path.read_text())
        dataset = stored["datasets"]["verified"]
        document = dataset["documents"][original["document"]["document_id"]]
        if change == "tenant":
            document["tenant_id"] = "another-tenant"
        elif change == "version":
            document["version"] += 1
        elif change == "source_hash":
            document["metadata"]["document_content_hash"] = "0" * 64
        elif change == "chunk_text":
            dataset["chunks"][0]["text"] = "forged policy"
        else:
            dataset["chunks"].pop()
        service._storage_path.write_text(json.dumps(stored))
    report = _recheck_inline(run)
    assert report["accepted"] is False, report
    assert run.tool_calls[0].output == original and len(run.tool_calls) == 1


def test_inline_ingest_rejects_forged_success_borrowing_an_old_document(verified_inline_ingest):
    import copy
    from unittest.mock import MagicMock

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import plan_from_dict

    actor, _service, repo, original = verified_inline_ingest
    executor = MagicMock()
    executor.execute_with_deadline.return_value = {
        **copy.deepcopy(original.tool_calls[0].output),
        "verification": {"verified": True},
    }
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=executor)
    plan = plan_from_dict(original.metadata["plan"])
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="forged new request",
        plan=plan,
        runtime_context=actor.context,
    )
    run = orchestrator.continue_run(
        run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
    )
    assert run.status == "blocked"
    assert run.tool_calls[0].metadata["verification"]["code"] == "result_receipt_unavailable"


@pytest.mark.parametrize(
    "change", [None, "old_document", "old_chunk", "new_chunk", "missing_baseline"]
)
def test_rollback_verifies_the_original_target_and_new_document_without_replay(
    verified_inline_ingest, monkeypatch, change
):
    import copy
    import json

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor, service, repo, initial = verified_inline_ingest
    original_id = initial.tool_calls[0].output["document"]["document_id"]
    orchestrator = AgentOrchestrator(repository=repo)
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="Restore approved original policy",
        runtime_context=actor.context,
        plan=PlanGraph(
            plan_id="rollback-proof",
            intent="dataset-rollback",
            nodes=[
                WorkflowNode(
                    node_id="rollback",
                    tool_id="dataset_rag",
                    action="rollback_version",
                    params={
                        "dataset_id": "verified",
                        "source": "policy.txt",
                        "target_version": "1",
                    },
                )
            ],
        ),
    )
    assert run.status == "waiting_user"
    run = orchestrator.continue_run(
        run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
    )
    assert run.status == "completed", run.error
    original = copy.deepcopy(run.tool_calls[0].output)
    assert original["rolled_back_from"]["document_id"] == original_id
    monkeypatch.setattr(
        service,
        "rollback_document_version",
        lambda **kwargs: pytest.fail("verification cannot roll back again"),
    )
    if change == "missing_baseline":
        # A host contract produced before target-baseline support has no proof
        # of which version existed before the write, even with a real receipt.
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash

        contract = run.tool_calls[0].metadata["verification_contract"]
        contract.pop("rollback_target")
        contract["contract_sha256"] = canonical_hash(
            {key: value for key, value in contract.items() if key != "contract_sha256"}
        )
    elif change:
        raw = json.loads(service._storage_path.read_text())
        dataset = raw["datasets"]["verified"]
        if change == "old_document":
            dataset["documents"][original_id]["metadata"]["document_content_hash"] = "0" * 64
        else:
            target = original_id if change == "old_chunk" else original["document"]["document_id"]
            next(
                chunk for chunk in dataset["chunks"] if chunk["metadata"]["document_id"] == target
            )["text"] = "changed"
        service._storage_path.write_text(json.dumps(raw))
    report = _recheck_inline(run)
    assert report["accepted"] is (change is None)
    if change is None:
        evidence = report["checks"][0]["evidence"]
        assert evidence["scope"] == "current_rollback_document_storage"
        assert evidence["target_document_id"] == original_id
        assert evidence["vector_index_verified"] is False
    assert run.tool_calls[0].output == original and len(run.tool_calls) == 1


def _overlapping_ingests(tmp_path, *, slow_request, concurrent_request):
    started, release = Event(), Event()
    storage = tmp_path / "shared-datasets.json"

    def delayed_embedding(text):
        started.set()
        assert release.wait(5), "test writer was not released"
        return [float(len(text)), 1.0]

    slow = DatasetRagApplicationService(
        storage_path=storage,
        embedder=delayed_embedding,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    concurrent = DatasetRagApplicationService(
        storage_path=storage,
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            slow.ingest_document,
            dataset_id="shared",
            source="policy.md",
            chunk_strategy="fixed",
            **slow_request,
        )
        assert started.wait(5), "slow writer never reached embedding"
        try:
            first = concurrent.ingest_document(
                dataset_id="shared",
                source="policy.md",
                chunk_strategy="fixed",
                **concurrent_request,
            )
        finally:
            release.set()
        second = pending.result(timeout=5)

    reloaded = DatasetRagApplicationService(
        storage_path=storage,
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )
    return first, second, reloaded.status("shared")


@pytest.mark.parametrize("same_content", [False, True])
def test_ingest_reloads_the_dataset_after_a_concurrent_embedding_window(tmp_path, same_content):
    first, second, status = _overlapping_ingests(
        tmp_path,
        slow_request={"text": "same content" if same_content else "slower writer"},
        concurrent_request={"text": "same content" if same_content else "first commit"},
    )
    assert first["success"] is True and second["success"] is True
    assert first["document"]["version"] == 1
    assert second["document"]["version"] == 2
    assert first["document"]["document_id"] != second["document"]["document_id"]
    assert status["document_count"] == 2
    assert {document["version"] for document in status["documents"]} == {1, 2}


def test_ingest_compare_and_swap_observes_the_concurrent_commit(tmp_path):
    first, second, status = _overlapping_ingests(
        tmp_path,
        slow_request={"text": "stale writer", "expected_source_version": 0},
        concurrent_request={"text": "committed writer"},
    )
    assert first["success"] is True
    assert second == {"success": False, "error_code": "dataset_source_version_conflict"}
    assert status["documents"] == [first["document"]]


def test_concurrent_explicit_id_cannot_replace_another_tenants_document(tmp_path):
    first, second, status = _overlapping_ingests(
        tmp_path,
        slow_request={
            "text": "tenant one",
            "document_id": "shared-id",
            "tenant_id": "one",
            "access_context": {"tenant_id": "one", "is_admin": True},
        },
        concurrent_request={
            "text": "tenant two",
            "document_id": "shared-id",
            "tenant_id": "two",
        },
    )
    assert first["success"] is True
    assert second == {"success": False, "error_code": "dataset_document_conflict"}
    assert status["documents"] == [first["document"]]


@pytest.mark.parametrize("identity", [{"document_id": "actual-document"}, {"version": 2}])
def test_document_metadata_cannot_break_chunk_ownership_and_deletion(tmp_path, identity):
    service = DatasetRagApplicationService(
        storage_path=tmp_path / "identity.json",
        embedder=lambda text: [1.0],
        vector_index_backend_name="none",
        rebuild_workers_enabled=False,
    )
    ingested = service.ingest_document(
        dataset_id="ds",
        text="evidence that must disappear when its document is deleted",
        metadata={"document_id": "forged-owner"},
        chunk_strategy="fixed",
        **identity,
    )
    assert ingested["success"] is True
    document_id = ingested["document"]["document_id"]
    deleted = service.delete_document("ds", document_id)
    assert deleted["success"] is True
    assert deleted["deleted_chunks"] == ingested["chunk_count"]
    assert service.query(dataset_id="ds", query="evidence")["chunks"] == []
    assert service.status("ds")["chunk_count"] == 0


def test_document_and_retrieval_components_use_injected_ports_without_application_service(tmp_path):
    repository = DatasetRepository(
        tmp_path / "independent.json", prepare_loaded_state=_renumber_chunks
    )
    vector = VectorIndexService(backend=None, embedder=None)
    parser = DocumentParser(
        chunker=SemanticChunker(embedder=None),
        allowed_roots=[tmp_path],
        default_roots=lambda: [],
    )
    lifecycle = DocumentLifecycle(
        repository=repository, parser=parser, vector=vector, renumber=_renumber_chunks
    )
    for tenant, content in [
        ("one", "old policy"),
        ("two", "foreign policy"),
        ("one", "new policy"),
    ]:
        result = lifecycle.ingest_document(
            dataset_id="ds",
            source="policy.md",
            tenant_id=tenant,
            text=content,
            chunk_strategy="fixed",
        )
        assert result["success"] is True

    indexed = []
    calls = []

    class Retriever:
        def index(self, chunks):
            indexed.extend(chunks)

        def retrieve(self, query):
            calls.append(query)
            return indexed

    def factory(*, embedder, top_k):
        assert embedder is None
        assert top_k == 3
        return Retriever()

    retrieval = DatasetRetrieval(repository=repository, vector=vector, retriever_factory=factory)
    result = retrieval.query(
        dataset_id="ds",
        query="policy",
        version="latest",
        top_k=3,
        access_context={"tenant_id": "one", "permissions": ["dataset.read"]},
    )
    assert calls == ["policy"]
    assert [chunk.text for chunk in indexed] == ["new policy"]
    assert result["chunks"][0]["metadata"]["tenant_id"] == "one"
    assert result["chunks"][0]["metadata"]["document_version"] == 2
