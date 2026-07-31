from __future__ import annotations

from pathlib import Path

from app.application.dataset_rag_app_service import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
    DatasetRagApplicationService,
)
from public_knowledge.publisher import (
    PUBLIC_DATASET_ID,
    PUBLIC_OWNER_ID,
    load_public_knowledge_corpus,
    publish_public_knowledge,
)


def _access() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="test-public-publisher",
        tenant_id="",
        permissions=frozenset(
            {DATASET_READ_PERMISSION, DATASET_WRITE_PERMISSION, DATASET_ADMIN_PERMISSION}
        ),
        is_admin=True,
    )


def _embed(text: str) -> list[float]:
    return [
        float(len(text) % 17),
        float(text.count("客来来")),
        float(text.count("XCAGI")),
        float(text.count("生产")),
    ]


def test_public_corpus_is_complete_and_governed() -> None:
    corpus = load_public_knowledge_corpus()

    assert corpus.dataset_id == PUBLIC_DATASET_ID
    assert len(corpus.documents) == 13
    assert len(corpus.quality_queries) >= 8
    assert {document.category for document in corpus.documents} >= {
        "company",
        "product",
        "solution",
        "trust",
        "delivery",
        "commercial",
        "scenario",
        "faq",
        "navigation",
    }
    assert all(document.reply_excerpt for document in corpus.documents)


def test_publish_replaces_public_documents_and_preserves_private_knowledge(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "datasets.json"
    service = DatasetRagApplicationService(
        storage_path=storage,
        vector_index_backend_name="none",
        rebuild_workers_enabled=False,
        embedder=_embed,
    )
    access = _access()
    dirty_public = service.ingest_document(
        dataset_id=PUBLIC_DATASET_ID,
        source="old-public.md",
        text="outdated public knowledge that must be replaced",
        tenant_id="public",
        metadata={
            "audience": "public",
            "publication_status": "published",
        },
        access_context=access,
    )
    same_dataset_private = service.ingest_document(
        dataset_id=PUBLIC_DATASET_ID,
        source="private-policy.md",
        text="customer-a private material must remain isolated in the shared dataset",
        tenant_id="customer-a",
        access_context=access,
    )
    private = service.ingest_document(
        dataset_id="user_customer-a",
        source="private.md",
        text="customer private material must remain isolated",
        tenant_id="customer-a",
        access_context=access,
    )
    assert dirty_public["success"] is True
    assert same_dataset_private["success"] is True
    assert private["success"] is True

    result = publish_public_knowledge(
        storage_path=storage,
        vector_backend_name="none",
        embedder=_embed,
    )

    assert result["success"] is True
    assert result["removed_document_count"] == 1
    assert result["published_document_count"] == 13
    assert result["document_count"] == 13
    assert all(item["passed"] for item in result["quality"])

    reloaded = DatasetRagApplicationService(
        storage_path=storage,
        vector_index_backend_name="none",
        rebuild_workers_enabled=False,
        embedder=_embed,
    )
    public_status = reloaded.status(
        PUBLIC_DATASET_ID,
        tenant_id="public",
        access_context=access,
    )
    assert public_status["document_count"] == 13
    assert {document["tenant_id"] for document in public_status["documents"]} == {"public"}
    assert {
        document["metadata"]["knowledge_owner"] for document in public_status["documents"]
    } == {PUBLIC_OWNER_ID}
    assert {
        document["metadata"]["publication_status"] for document in public_status["documents"]
    } == {"published"}
    assert all(
        document["metadata"]["reply_excerpt"] for document in public_status["documents"]
    )
    industry_document = next(
        document
        for document in public_status["documents"]
        if document["document_id"] == "public-ai-industry-guide-v1"
    )
    assert "梁文锋" in industry_document["metadata"]["reply_excerpt"]
    same_dataset_private_status = reloaded.status(
        PUBLIC_DATASET_ID,
        tenant_id="customer-a",
        access_context=access,
    )
    assert same_dataset_private_status["document_count"] == 1
    assert same_dataset_private_status["documents"][0]["source"] == "private-policy.md"
    all_shared_status = reloaded.status(PUBLIC_DATASET_ID, access_context=access)
    assert all_shared_status["document_count"] == 14
    assert {document["tenant_id"] for document in all_shared_status["documents"]} == {
        "public",
        "customer-a",
    }
    assert reloaded.status("user_customer-a", access_context=access)["document_count"] == 1
