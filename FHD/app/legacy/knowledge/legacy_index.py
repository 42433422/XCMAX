"""An explicitly constructed, tenant-filtered legacy retrieval index."""

from __future__ import annotations

import threading
from typing import Protocol

from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.infrastructure.rag.semantic_chunker import Chunk


class Chunker(Protocol):
    def split_by_semantic(self, text: str) -> list[Chunk]: ...
    def split_by_fixed(self, text: str, *, chunk_size: int, chunk_overlap: int) -> list[Chunk]: ...


class Retriever(Protocol):
    def index(self, chunks: list[RetrievedChunk]) -> None: ...
    def retrieve(self, query: str) -> list[RetrievedChunk]: ...


class KnowledgeIndex:
    """Tenant-filtered in-process chunks, serialized with the retriever index."""

    def __init__(
        self, *, chunker: Chunker, retriever: Retriever, chunk_factory: type[RetrievedChunk]
    ) -> None:
        self._lock = threading.Lock()
        self._chunker = chunker
        self._retriever = retriever
        self._chunk_factory = chunk_factory
        self._chunks: list[RetrievedChunk] = []
        self._sources: set[str] = set()
        self._rebuild_needed = True

    def ingest(
        self,
        text: str,
        source: str,
        strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        tenant_id: str | None = None,
    ) -> int:
        with self._lock:
            if strategy == "semantic":
                chunks = self._chunker.split_by_semantic(text)
            else:
                chunks = self._chunker.split_by_fixed(
                    text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
                )
            base = len(self._chunks)
            for i, c in enumerate(chunks):
                self._chunks.append(
                    self._chunk_factory(
                        text=c.text,
                        score=0.0,
                        source=source,
                        chunk_index=base + i,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        metadata={"source": source, "strategy": c.strategy, "tenant_id": tenant_id},
                    )
                )
            self._sources.add(source)
            self._rebuild_needed = True
            return len(chunks)

    def query(self, q: str, top_k: int, tenant_id: str | None = None) -> list[RetrievedChunk]:

        def tenant_of(chunk) -> str:
            return str((getattr(chunk, "metadata", None) or {}).get("tenant_id") or "")

        with self._lock:
            visible = self._chunks
            if tenant_id is not None:
                visible = [chunk for chunk in self._chunks if tenant_of(chunk) == str(tenant_id)]
            self._retriever.index(visible)
            self._rebuild_needed = False
            found = self._retriever.retrieve(q)
            if tenant_id is None:
                return found[:top_k]
            return [chunk for chunk in found if tenant_of(chunk) == str(tenant_id)][:top_k]

    def status(self) -> dict[str, int]:
        with self._lock:
            return {"sources": len(self._sources), "chunks": len(self._chunks)}
