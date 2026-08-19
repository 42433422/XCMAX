"""Shared serialization, filtering, ranking, and path helpers for dataset vector indexes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.utils.path_io.path_utils import get_app_data_dir


def default_dataset_vector_index_path(storage_path: str | Path | None = None) -> Path:
    configured = (
        os.environ.get("DATASET_RAG_VECTOR_INDEX_PATH")
        or os.environ.get("XCAGI_DATASET_RAG_VECTOR_INDEX_PATH")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if storage_path:
        path = Path(storage_path).expanduser().resolve()
        return path.with_suffix(path.suffix + ".vectors.sqlite")
    return Path(get_app_data_dir()).resolve() / "dataset_rag" / "dataset_vectors.sqlite"


def _index_id(dataset_id: str) -> str:
    return f"dataset:{dataset_id}"


def _is_rebuildable_index_error(exc: sqlite3.DatabaseError) -> bool:
    message = str(exc).strip().lower()
    return "file is not a database" in message or "database disk image is malformed" in message


def _chunk_row_id(dataset_id: str, chunk: RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    raw = "\0".join(
        [
            dataset_id,
            str(metadata.get("document_id") or ""),
            str(metadata.get("tenant_id") or ""),
            str(metadata.get("document_version") or ""),
            str(chunk.chunk_index),
            str(chunk.char_start),
            str(chunk.char_end),
        ]
    )
    digest = _sha256(raw)
    return f"dvc_{digest[:24]}"


def _sha256(value: str) -> str:

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row_to_chunk(row: sqlite3.Row) -> RetrievedChunk:
    metadata = _load_json_object(row["metadata"])
    return RetrievedChunk(
        text=str(row["content"] or ""),
        score=0.0,
        source=str(row["source"] or ""),
        chunk_index=int(row["chunk_index"] or 0),
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        metadata=metadata,
        source_url=str(row["source_url"] or ""),
        page=row["page"] if isinstance(row["page"], int) else None,
    )


def _pg_row_to_chunk(row: Any) -> RetrievedChunk:
    metadata = _load_json_object(row.get("metadata", {}))
    return RetrievedChunk(
        text=str(row["content"] or ""),
        score=float(row["score"] or 0.0),
        source=str(row["source"] or "pgvector"),
        chunk_index=int(row["chunk_index"] or 0),
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        metadata=metadata,
        source_url=str(row["source_url"] or ""),
        page=row["page"] if isinstance(row["page"], int) else None,
    )


def _load_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _embedding_from_metadata(metadata: dict[str, Any]) -> list[float]:
    embedding = metadata.get("_embedding")
    if not isinstance(embedding, list):
        return []
    try:
        return [float(item) for item in embedding]
    except (TypeError, ValueError):
        return []


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _filter_chunks(
    chunks: list[RetrievedChunk],
    *,
    tenant_id: str,
    version: str | int,
    metadata_filter: dict[str, Any],
) -> list[RetrievedChunk]:
    selected = list(chunks)
    if tenant_id:
        selected = [
            chunk
            for chunk in selected
            if str((chunk.metadata or {}).get("tenant_id") or "") == tenant_id
        ]
    if metadata_filter:
        selected = [
            chunk for chunk in selected if _metadata_matches(chunk.metadata or {}, metadata_filter)
        ]
    version_text = str(version or "").strip()
    if not version_text:
        return selected
    if version_text.lower() == "latest":
        latest_by_scope: dict[tuple[str, str], int] = {}
        for chunk in selected:
            metadata = chunk.metadata or {}
            scope = (
                str(metadata.get("tenant_id") or ""),
                str(metadata.get("source") or chunk.source or ""),
            )
            latest_by_scope[scope] = max(
                latest_by_scope.get(scope, 0),
                int(metadata.get("document_version") or 1),
            )
        return [
            chunk
            for chunk in selected
            if int((chunk.metadata or {}).get("document_version") or 1)
            == latest_by_scope.get(
                (
                    str((chunk.metadata or {}).get("tenant_id") or ""),
                    str((chunk.metadata or {}).get("source") or chunk.source or ""),
                ),
                1,
            )
        ]
    normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
    return [
        chunk
        for chunk in selected
        if str((chunk.metadata or {}).get("document_version") or "") == normalized
        or str((chunk.metadata or {}).get("version_label") or "") == version_text
    ]


def _metadata_matches(metadata: dict[str, Any], metadata_filter: dict[str, Any]) -> bool:
    for key, expected in metadata_filter.items():
        actual = metadata.get(str(key))
        if isinstance(expected, list):
            if str(actual) not in {str(item) for item in expected}:
                return False
        elif isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for nested_key, nested_expected in expected.items():
                if str(actual.get(str(nested_key))) != str(nested_expected):
                    return False
        elif str(actual) != str(expected):
            return False
    return True


def _lexical_score(text: str, query_terms: Iterable[str]) -> float:
    terms = set(query_terms)
    if not terms:
        return 0.0
    text_terms = set(_tokenize_for_lexical(text))
    return len(terms & text_terms) / max(1, len(terms))


def _tokenize_for_lexical(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [part for part in cleaned.split() if part]
