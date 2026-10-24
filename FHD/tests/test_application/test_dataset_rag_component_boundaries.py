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
