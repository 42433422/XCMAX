from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from app.application.ports.vector_store import VectorStorePort
from app.domain.ports.embedder import EmbedderPort, HashEmbedder
from app.infrastructure.persistence.pg_vector_store import PgVectorStore
from app.infrastructure.persistence.sqlite_vector_store import SQLiteVectorStore
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

# HashEmbedder 实现已下沉至 app.domain.ports.embedder（本模块仍 re-export，
# 保持 app.application.excel_vector_app_service.HashEmbedder 历史 import 路径可用）。


@dataclass
class ExcelVectorChunk:
    chunk_id: str
    content: str
    metadata: dict[str, Any]


def _get_default_embedder() -> EmbedderPort:
    """优先用真实 EmbeddingService（local/remote），不可用时回退到 HashEmbedder。

    保持向后兼容：FHD_EMBEDDING_MODE=disabled（默认）时返回 HashEmbedder，
    行为与改造前完全一致。
    """
    try:
        from app.infrastructure.llm import get_default_embedding_service

        svc = get_default_embedding_service()
        if svc is not None and svc.is_available():
            return cast("EmbedderPort", svc)
    except RECOVERABLE_ERRORS:
        pass
    return HashEmbedder()


class ExcelVectorIngestApplicationService:
    def __init__(
        self,
        vector_store: VectorStorePort | None = None,
        embedder: EmbedderPort | None = None,
        chunk_window_size: int = 20,
    ) -> None:
        self._vector_store = vector_store or get_vector_store()
        self._embedder = embedder or _get_default_embedder()
        self._chunk_window_size = max(5, int(chunk_window_size))

    def ingest_excel(
        self,
        file_path: str,
        index_name: str | None = None,
        index_id: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "message": f"文件不存在: {file_path}"}

        target_index_id = index_id or uuid.uuid4().hex
        name = (index_name or path.stem or target_index_id).strip()

        sheets = pd.read_excel(file_path, sheet_name=None)
        chunks = self._build_chunks(sheets, source_file=path.name)
        if not chunks:
            return {"success": False, "message": "Excel 中没有可索引的有效数据"}

        texts = [chunk.content for chunk in chunks]
        embeddings = self._embedder.embed_texts(texts)
        store_payload: list[dict[str, Any]] = []
        for chunk, embedding in zip(chunks, embeddings):
            store_payload.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "embedding": embedding,
                    "metadata": chunk.metadata,
                }
            )

        if hasattr(self._vector_store, "create_or_update_index"):
            self._vector_store.create_or_update_index(
                index_id=target_index_id,
                name=name,
                source_file=path.name,
            )

        written = self._vector_store.upsert_chunks(target_index_id, store_payload)
        return {
            "success": True,
            "index_id": target_index_id,
            "index_name": name,
            "source_file": path.name,
            "chunk_count": written,
        }

    def _build_chunks(
        self, sheets: dict[str, pd.DataFrame], source_file: str
    ) -> list[ExcelVectorChunk]:
        chunks: list[ExcelVectorChunk] = []

        for sheet_name, df in sheets.items():
            if df is None or df.empty:
                continue

            normalized = df.fillna("")
            columns = [str(col).strip() for col in normalized.columns]

            # 行级分块：对精准定位最有效
            for row_idx, (_, row) in enumerate(normalized.iterrows(), start=1):
                row_pairs = []
                for col in columns:
                    value = str(row.get(col, "")).strip()
                    if value:
                        row_pairs.append(f"{col}: {value}")
                if not row_pairs:
                    continue

                row_text = f"sheet={sheet_name}; row={row_idx}; " + " | ".join(row_pairs)
                chunks.append(
                    ExcelVectorChunk(
                        chunk_id=uuid.uuid4().hex,
                        content=row_text,
                        metadata={
                            "source_file": source_file,
                            "sheet": sheet_name,
                            "chunk_type": "row",
                            "row_index": row_idx,
                            "columns": columns[:50],
                        },
                    )
                )

            # 窗口分块：提升跨行问题召回能力
            row_records = normalized.to_dict(orient="records")
            for start in range(0, len(row_records), self._chunk_window_size):
                part = row_records[start : start + self._chunk_window_size]
                if not part:
                    continue

                rendered_rows: list[str] = []
                for rel_idx, record in enumerate(part, start=1):
                    items = []
                    for col in columns:
                        value = str(record.get(col, "")).strip()
                        if value:
                            items.append(f"{col}: {value}")
                    if items:
                        rendered_rows.append(f"row={start + rel_idx}; " + " | ".join(items))

                if not rendered_rows:
                    continue

                window_text = (
                    f"sheet={sheet_name}; rows={start + 1}-{start + len(part)}\n"
                    + "\n".join(rendered_rows)
                )
                chunks.append(
                    ExcelVectorChunk(
                        chunk_id=uuid.uuid4().hex,
                        content=window_text,
                        metadata={
                            "source_file": source_file,
                            "sheet": sheet_name,
                            "chunk_type": "window",
                            "row_start": start + 1,
                            "row_end": start + len(part),
                            "columns": columns[:50],
                        },
                    )
                )
        return chunks


class ExcelVectorSearchApplicationService:
    def __init__(
        self,
        vector_store: VectorStorePort | None = None,
        embedder: EmbedderPort | None = None,
    ) -> None:
        self._vector_store = vector_store or get_vector_store()
        self._embedder = embedder or _get_default_embedder()

    def query(self, index_id: str, query_text: str, top_k: int = 5) -> dict[str, Any]:
        if not index_id:
            return {"success": False, "message": "缺少 index_id"}
        if not query_text:
            return {"success": False, "message": "缺少 query"}

        query_vector = self._embedder.embed_query(query_text)
        hits = self._vector_store.query(index_id=index_id, query_vector=query_vector, top_k=top_k)
        return {
            "success": True,
            "index_id": index_id,
            "query": query_text,
            "top_k": top_k,
            "hits": hits,
        }

    def list_indexes(self) -> dict[str, Any]:
        return {"success": True, "indexes": self._vector_store.list_indexes()}

    def delete_index(self, index_id: str) -> dict[str, Any]:
        deleted = self._vector_store.delete_index(index_id)
        return {"success": deleted, "index_id": index_id}


def _default_vector_db_path() -> str:
    env_path = os.environ.get("EXCEL_VECTOR_DB_PATH", "").strip()
    if env_path:
        folder = os.path.dirname(env_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        return env_path
    folder = os.path.join(get_app_data_dir(), "vectors")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "excel_vectors.db")


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(ExcelVectorIngestApplicationService)
instrument_application_service_class(ExcelVectorSearchApplicationService)

_sqlite_vector_store_instance: SQLiteVectorStore | None = None
_pg_vector_store_instance: PgVectorStore | None = None
_vector_store_instance: VectorStorePort | None = None
_excel_vector_ingest_service_instance: ExcelVectorIngestApplicationService | None = None
_excel_vector_search_service_instance: ExcelVectorSearchApplicationService | None = None


def get_sqlite_vector_store() -> SQLiteVectorStore:
    global _sqlite_vector_store_instance
    if _sqlite_vector_store_instance is None:
        _sqlite_vector_store_instance = SQLiteVectorStore(db_path=_default_vector_db_path())
    return _sqlite_vector_store_instance


def get_pg_vector_store() -> PgVectorStore:
    global _pg_vector_store_instance
    if _pg_vector_store_instance is None:
        db_url = os.environ.get("VECTOR_DB_URL") or os.environ.get("DATABASE_URL")
        if not db_url:
            raise ValueError("缺少 VECTOR_DB_URL / DATABASE_URL 配置")
        _pg_vector_store_instance = PgVectorStore(database_url=db_url)
    return _pg_vector_store_instance


def get_vector_store() -> VectorStorePort:
    global _vector_store_instance
    if _vector_store_instance is not None:
        return _vector_store_instance
    use_sqlite_fallback = (
        os.environ.get("ENABLE_SQLITE_VECTOR_FALLBACK", "0") or "0"
    ).strip() == "1"
    if use_sqlite_fallback:
        _vector_store_instance = get_sqlite_vector_store()
    else:
        _vector_store_instance = get_pg_vector_store()
    return _vector_store_instance


def get_excel_vector_ingest_app_service() -> ExcelVectorIngestApplicationService:
    global _excel_vector_ingest_service_instance
    if _excel_vector_ingest_service_instance is None:
        _excel_vector_ingest_service_instance = ExcelVectorIngestApplicationService()
    return _excel_vector_ingest_service_instance


def get_excel_vector_search_app_service() -> ExcelVectorSearchApplicationService:
    global _excel_vector_search_service_instance
    if _excel_vector_search_service_instance is None:
        _excel_vector_search_service_instance = ExcelVectorSearchApplicationService()
    return _excel_vector_search_service_instance
