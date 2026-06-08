"""Knowledge / RAG service port.

The next domain on the split roadmap (after notification). Today it
delegates to :mod:`modstore_server.rag_service` so behaviour is preserved;
when knowledge graduates to its own process the only thing that swaps is
the implementation registered via :func:`set_default_knowledge_client`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class KnowledgeSearchRequest:
    user_id: int
    query: str
    employee_id: Optional[int] = None
    workflow_id: Optional[int] = None
    org_id: Optional[str] = None
    extra_collection_ids: List[int] = field(default_factory=list)
    top_k: int = 5


@dataclass(frozen=True)
class KnowledgeSearchHit:
    collection_id: int
    collection_name: str
    doc_id: str
    chunk_id: str
    content: str
    score: float
    extras: Dict[str, Any] = field(default_factory=dict)


class KnowledgeClient(ABC):
    @abstractmethod
    def search(self, request: KnowledgeSearchRequest) -> List[KnowledgeSearchHit]: ...

    def index_text_chunks(
        self,
        *,
        collection_id: int,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Upsert vector chunks into the backing store (Chroma / Redis 等由实现决定)。"""
        raise NotImplementedError

    def delete_vectors(self, *, collection_id: int, ids: Optional[List[str]] = None) -> int:
        """Delete vectors by id list; returns best-effort removed count."""

        raise NotImplementedError


class InProcessKnowledgeClient(KnowledgeClient):
    """Default port wired to the current ``rag_service`` implementation."""

    def index_text_chunks(
        self,
        *,
        collection_id: int,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        from modstore_server.vector_engine import kb_collection_name, upsert

        name = kb_collection_name(int(collection_id))
        return int(
            upsert(
                name,
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        )

    def delete_vectors(self, *, collection_id: int, ids: Optional[List[str]] = None) -> int:
        from modstore_server.vector_engine import delete as vec_delete
        from modstore_server.vector_engine import kb_collection_name

        name = kb_collection_name(int(collection_id))
        return int(vec_delete(name, ids=ids))

    def search(self, request: KnowledgeSearchRequest) -> List[KnowledgeSearchHit]:
        from modstore_server.rag_service import retrieve_for_subject

        chunks = (
            retrieve_for_subject(
                user_id=request.user_id,
                query=request.query,
                employee_id=request.employee_id,
                workflow_id=request.workflow_id,
                org_id=request.org_id,
                extra_collection_ids=request.extra_collection_ids,
                top_k=request.top_k,
            )
            or []
        )
        hits: List[KnowledgeSearchHit] = []
        for c in chunks:
            hits.append(
                KnowledgeSearchHit(
                    collection_id=int(getattr(c, "collection_id", 0) or 0),
                    collection_name=str(getattr(c, "collection_name", "") or ""),
                    doc_id=str(getattr(c, "doc_id", "") or ""),
                    chunk_id=str(getattr(c, "chunk_id", "") or ""),
                    content=str(getattr(c, "content", "") or ""),
                    score=float(getattr(c, "score", 0.0) or 0.0),
                    extras={
                        "filename": getattr(c, "filename", ""),
                        "page_no": getattr(c, "page_no", None),
                        "distance": getattr(c, "distance", None),
                    },
                )
            )
        return hits


_LOCK = Lock()
_default: KnowledgeClient | None = None


def get_default_knowledge_client() -> KnowledgeClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessKnowledgeClient()
        return _default


def set_default_knowledge_client(client: Optional[KnowledgeClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "InProcessKnowledgeClient",
    "KnowledgeClient",
    "KnowledgeSearchHit",
    "KnowledgeSearchRequest",
    "get_default_knowledge_client",
    "set_default_knowledge_client",
]
