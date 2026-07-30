"""Governed publisher for the customer-facing Persy knowledge corpus."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

PUBLIC_DATASET_ID = "persy-knowledge"
PUBLIC_TENANT_ID = "public"
PUBLIC_OWNER_ID = "chengdu-xiuci-technology"
REQUIRED_CATEGORIES = frozenset(
    {"company", "product", "solution", "trust", "delivery", "commercial", "scenario", "faq", "navigation"}
)
CONTAMINATION_MARKERS = (
    "Generated contract",
    "ACME Trading",
    "shipment-template.xlsx",
    "eval-user",
    "tenant-a",
    '"artifact_source"',
)
TRUSTED_PUBLIC_SOURCE_HOSTS = frozenset(
    {
        "ai.tencent.com",
        "apnews.com",
        "cdn.deepseek.com",
        "deepseek.com",
        "doubao.com",
        "www.deepseek.com",
        "www.doubao.com",
        "www.tencent.com",
        "www.xiu-ci.com",
        "xiu-ci.com",
    }
)


@dataclass(frozen=True)
class PublicKnowledgeDocument:
    document_id: str
    title: str
    source: str
    category: str
    source_urls: tuple[str, ...]
    keywords: tuple[str, ...]
    reply_excerpt: str
    text: str
    content_sha256: str


@dataclass(frozen=True)
class PublicKnowledgeCorpus:
    dataset_id: str
    revision: str
    owner: str
    audience: str
    documents: tuple[PublicKnowledgeDocument, ...]
    quality_queries: tuple[dict[str, Any], ...]


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parent / "manifest.json"


def load_public_knowledge_corpus(manifest_path: str | Path | None = None) -> PublicKnowledgeCorpus:
    path = Path(manifest_path or default_manifest_path()).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent.resolve()
    documents: list[PublicKnowledgeDocument] = []
    for row in payload.get("documents") or []:
        file_path = (root / str(row.get("file") or "")).resolve()
        if root not in file_path.parents:
            raise ValueError(f"knowledge file escapes corpus root: {file_path}")
        text = file_path.read_text(encoding="utf-8").strip()
        documents.append(
            PublicKnowledgeDocument(
                document_id=str(row.get("document_id") or "").strip(),
                title=str(row.get("title") or "").strip(),
                source=f"public/{file_path.name}",
                category=str(row.get("category") or "").strip(),
                source_urls=tuple(str(item).strip() for item in row.get("source_urls") or []),
                keywords=tuple(str(item).strip() for item in row.get("keywords") or []),
                reply_excerpt=str(row.get("reply_excerpt") or "").strip(),
                text=text,
                content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    corpus = PublicKnowledgeCorpus(
        dataset_id=str(payload.get("dataset_id") or "").strip(),
        revision=str(payload.get("revision") or "").strip(),
        owner=str(payload.get("owner") or "").strip(),
        audience=str(payload.get("audience") or "").strip(),
        documents=tuple(documents),
        quality_queries=tuple(payload.get("quality_queries") or []),
    )
    validate_public_knowledge_corpus(corpus)
    return corpus


def validate_public_knowledge_corpus(corpus: PublicKnowledgeCorpus) -> None:
    if corpus.dataset_id != PUBLIC_DATASET_ID:
        raise ValueError(f"public corpus must target {PUBLIC_DATASET_ID}")
    if corpus.audience != "public":
        raise ValueError("public corpus audience must be public")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", corpus.revision):
        raise ValueError("public corpus revision must use YYYY-MM-DD")
    if len(corpus.documents) < 10:
        raise ValueError("public corpus must include at least 10 governed documents")
    ids = [document.document_id for document in corpus.documents]
    if len(ids) != len(set(ids)):
        raise ValueError("public corpus document_id values must be unique")
    categories = {document.category for document in corpus.documents}
    missing_categories = REQUIRED_CATEGORIES - categories
    if missing_categories:
        raise ValueError(f"public corpus missing categories: {sorted(missing_categories)}")
    combined = "\n".join(document.text for document in corpus.documents)
    for marker in CONTAMINATION_MARKERS:
        if marker.casefold() in combined.casefold():
            raise ValueError(f"public corpus contains contamination marker: {marker}")
    for document in corpus.documents:
        if not re.fullmatch(r"[a-z0-9-]+", document.document_id):
            raise ValueError(f"invalid public document_id: {document.document_id}")
        if len(document.text) < 300:
            raise ValueError(f"public document is too short: {document.document_id}")
        if document.title not in document.text:
            raise ValueError(f"public document title missing from content: {document.document_id}")
        if not document.source_urls or any(
            urlsplit(source_url).scheme != "https"
            or str(urlsplit(source_url).hostname or "").casefold()
            not in TRUSTED_PUBLIC_SOURCE_HOSTS
            for source_url in document.source_urls
        ):
            raise ValueError(f"public document has invalid source URL: {document.document_id}")
        if not document.keywords:
            raise ValueError(f"public document has no keywords: {document.document_id}")
        if not document.reply_excerpt:
            raise ValueError(f"public document has no approved reply excerpt: {document.document_id}")
        if len(document.reply_excerpt) > 600:
            raise ValueError(f"public document reply excerpt is too long: {document.document_id}")
    known_ids = set(ids)
    if len(corpus.quality_queries) < 8:
        raise ValueError("public corpus must define at least 8 quality queries")
    for row in corpus.quality_queries:
        if not str(row.get("query") or "").strip():
            raise ValueError("quality query text is required")
        expected_ids = [str(item) for item in row.get("expected_document_ids") or []]
        if not expected_ids or any(item not in known_ids for item in expected_ids):
            raise ValueError("quality query references an unknown document")
        if not row.get("must_contain"):
            raise ValueError("quality query must define expected terms")


def publication_metadata(
    corpus: PublicKnowledgeCorpus, document: PublicKnowledgeDocument
) -> dict[str, Any]:
    metadata = {
        "audience": "public",
        "publication_status": "published",
        "knowledge_owner": PUBLIC_OWNER_ID,
        "publisher": corpus.owner,
        "corpus_revision": corpus.revision,
        "category": document.category,
        "title": document.title,
        "source_urls": list(document.source_urls),
        "keywords": list(document.keywords),
        "content_sha256": document.content_sha256,
    }
    metadata["reply_excerpt"] = document.reply_excerpt
    return metadata


def publish_public_knowledge(
    *,
    manifest_path: str | Path | None = None,
    storage_path: str | Path | None = None,
    vector_backend_name: str | None = None,
    embedder: Callable[[str], list[float]] | None = None,
    create_backup: bool = True,
) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import (
        DATASET_ADMIN_PERMISSION,
        DATASET_READ_PERMISSION,
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
        DatasetRagApplicationService,
    )
    from app.infrastructure.rag.dataset_vector_index import default_dataset_vector_index_path

    corpus = load_public_knowledge_corpus(manifest_path)
    resolved_storage = (
        Path(storage_path).expanduser().resolve()
        if storage_path
        else Path("dataset_rag/datasets.json").resolve()
    )
    resolved_storage.parent.mkdir(parents=True, exist_ok=True)
    vector_path = default_dataset_vector_index_path(resolved_storage)
    backup_paths: dict[Path, Path] = {}
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if create_backup:
        backup_dir = resolved_storage.parent / "backups" / f"public-kb-{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        for source_path in (resolved_storage, vector_path):
            if source_path.exists():
                target = backup_dir / source_path.name
                shutil.copy2(source_path, target)
                backup_paths[source_path] = target

    access = DatasetAccessContext(
        actor_id="public-knowledge-publisher",
        tenant_id="",
        permissions=frozenset(
            {DATASET_READ_PERMISSION, DATASET_WRITE_PERMISSION, DATASET_ADMIN_PERMISSION}
        ),
        is_admin=True,
    )
    service_kwargs: dict[str, Any] = {
        "storage_path": resolved_storage,
        "vector_index_backend_name": vector_backend_name,
        "rebuild_workers_enabled": False,
    }
    if embedder is not None:
        service_kwargs["embedder"] = embedder
    try:
        service = DatasetRagApplicationService(**service_kwargs)
        before = service.status(
            corpus.dataset_id, access_context=access, include_documents=True
        )
        public_documents = [
            document
            for document in before.get("documents") or []
            if str(document.get("tenant_id") or "") == PUBLIC_TENANT_ID
        ]
        for document in public_documents:
            result = service.delete_document(
                corpus.dataset_id,
                str(document.get("document_id") or ""),
                access_context=access,
            )
            if not result.get("success"):
                raise RuntimeError(f"failed to remove old public document: {result}")

        published: list[dict[str, Any]] = []
        for document in corpus.documents:
            result = service.ingest_document(
                dataset_id=corpus.dataset_id,
                source=document.source,
                text=document.text,
                document_id=document.document_id,
                chunk_strategy="fixed",
                chunk_size=900,
                chunk_overlap=100,
                metadata=publication_metadata(corpus, document),
                tenant_id=PUBLIC_TENANT_ID,
                version=1,
                version_label=corpus.revision,
                access_context=access,
            )
            if not result.get("success"):
                raise RuntimeError(f"failed to publish {document.document_id}: {result}")
            published.append(result)

        quality = evaluate_public_knowledge(service, corpus, access_context=access)
        failed = [item for item in quality if not item["passed"]]
        if failed:
            raise RuntimeError(f"public knowledge quality gate failed: {failed}")
        after = service.status(
            corpus.dataset_id,
            tenant_id=PUBLIC_TENANT_ID,
            access_context=access,
            include_documents=True,
        )
        return {
            "success": True,
            "dataset_id": corpus.dataset_id,
            "revision": corpus.revision,
            "removed_document_count": len(public_documents),
            "published_document_count": len(published),
            "document_count": int(after.get("document_count") or 0),
            "chunk_count": int(after.get("chunk_count") or 0),
            "embedding_count": int((after.get("index") or {}).get("embedding_count") or 0),
            "quality": quality,
            "backup_dir": str(next(iter(backup_paths.values())).parent)
            if backup_paths
            else "",
        }
    except Exception:
        for source_path, backup_path in backup_paths.items():
            shutil.copy2(backup_path, source_path)
        raise


def evaluate_public_knowledge(
    service: Any,
    corpus: PublicKnowledgeCorpus,
    *,
    access_context: Any,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in corpus.quality_queries:
        query = str(row.get("query") or "")
        expected_document_ids = [str(item) for item in row.get("expected_document_ids") or []]
        required_terms = [str(term) for term in row.get("must_contain") or []]
        response = service.query(
            dataset_id=corpus.dataset_id,
            query=query,
            top_k=15,
            tenant_id=PUBLIC_TENANT_ID,
            metadata_filter={"publication_status": "published"},
            rerank=True,
            access_context=access_context,
        )
        chunks = response.get("chunks") if isinstance(response, dict) else []
        chunks = chunks if isinstance(chunks, list) else []
        chunks = chunks[:5]
        document_ids = [
            str((chunk.get("metadata") or {}).get("document_id") or "")
            for chunk in chunks
            if isinstance(chunk, dict)
        ]
        combined_text = "\n".join(
            str(chunk.get("text") or "") for chunk in chunks if isinstance(chunk, dict)
        )
        passed = any(item in document_ids for item in expected_document_ids) and all(
            term in combined_text for term in required_terms
        )
        results.append(
            {
                "query": query,
                "expected_document_ids": expected_document_ids,
                "top_document_ids": document_ids,
                "passed": passed,
            }
        )
    return results
