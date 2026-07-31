"""Dataset RAG knowledge-graph payload helpers (extracted for source-governance)."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.infrastructure.rag import RetrievedChunk


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


_GRAPH_TOPIC_METADATA_KEYS = frozenset(
    {"topic", "topics", "tag", "tags", "entity", "entities", "keywords", "category", "doc_type"}
)
_GRAPH_TOPIC_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "before",
        "default",
        "document",
        "from",
        "into",
        "persy",
        "that",
        "their",
        "this",
        "with",
        "以及",
        "他们",
        "内容",
        "可以",
        "如何",
        "我们",
        "文件",
        "是否",
        "知识",
        "系统",
        "资料",
        "这个",
        "这些",
        "进行",
        "需要",
    }
)


def _build_knowledge_graph_payload(
    *,
    dataset_id: str,
    tenant_id: str,
    documents: list[Any],
    chunks: list[RetrievedChunk],
    limit: int,
) -> dict[str, Any]:
    ordered_documents = sorted(
        documents,
        key=lambda item: (item.source.casefold(), -int(item.version), item.document_id),
    )[:40]
    allowed_document_ids = {doc.document_id for doc in ordered_documents}
    graph_chunks = [
        chunk
        for chunk in chunks
        if str((chunk.metadata or {}).get("document_id") or "") in allowed_document_ids
    ]
    selected_chunks = _select_graph_chunks(
        graph_chunks,
        limit=max(1, limit - len(ordered_documents) - 20),
    )
    root_id = f"persy:{dataset_id}"
    nodes: list[dict[str, Any]] = [
        {
            "id": root_id,
            "label": "Persy",
            "type": "core",
            "summary": (
                f"{len(ordered_documents)} 个来源，{len(graph_chunks)} 条知识切片"
                if ordered_documents
                else "等待资料进入后形成企业知识网络"
            ),
            "size": 72,
            "strength": 1.0,
            "metadata": {
                "dataset_id": dataset_id,
                "tenant_id": tenant_id,
                "document_count": len(ordered_documents),
                "chunk_count": len(graph_chunks),
            },
        }
    ]
    edges: list[dict[str, Any]] = []

    for doc in ordered_documents:
        node_id = f"document:{doc.document_id}"
        nodes.append(
            {
                "id": node_id,
                "label": _graph_source_label(doc.source),
                "type": "source",
                "summary": f"{doc.chunk_count} 个知识切片 · {doc.version_label}",
                "source": doc.source,
                "document_id": doc.document_id,
                "size": 36 + min(doc.chunk_count, 8),
                "strength": min(1.0, 0.45 + doc.chunk_count / 20),
                "metadata": {
                    "parser": doc.parser,
                    "text_length": doc.text_length,
                    "chunk_count": doc.chunk_count,
                    "tenant_id": doc.tenant_id,
                    "version": doc.version,
                    "version_label": doc.version_label,
                    **_public_graph_metadata(doc.metadata),
                },
            }
        )
        edges.append(
            {
                "id": f"edge:{root_id}:{node_id}",
                "source": root_id,
                "target": node_id,
                "type": "source",
                "label": "来源",
                "weight": 0.72,
            }
        )

    chunk_node_rows: list[tuple[str, RetrievedChunk]] = []
    for chunk in selected_chunks:
        metadata = dict(chunk.metadata or {})
        document_id = str(metadata.get("document_id") or "")
        node_id = _graph_chunk_node_id(chunk)
        chunk_node_rows.append((node_id, chunk))
        nodes.append(
            {
                "id": node_id,
                "label": _graph_knowledge_label(chunk.text),
                "type": "knowledge",
                "summary": _graph_excerpt(chunk.text, 420),
                "source": chunk.source,
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "size": 24,
                "strength": 0.5,
                "metadata": {
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "page": chunk.page,
                    "tenant_id": str(metadata.get("tenant_id") or ""),
                    "version_label": str(metadata.get("version_label") or ""),
                },
            }
        )
        parent_id = f"document:{document_id}"
        if document_id in allowed_document_ids:
            edges.append(
                {
                    "id": f"edge:{parent_id}:{node_id}",
                    "source": parent_id,
                    "target": node_id,
                    "type": "contains",
                    "label": "包含",
                    "weight": 0.58,
                }
            )

    topic_rows = _extract_graph_topics(chunk_node_rows, limit=18)
    for topic in topic_rows:
        topic_id = f"topic:{hashlib.sha1(topic['key'].encode('utf-8')).hexdigest()[:12]}"
        nodes.append(
            {
                "id": topic_id,
                "label": topic["label"],
                "type": "topic",
                "summary": f"连接 {topic['count']} 条知识",
                "size": 28 + min(int(topic["count"]) * 3, 18),
                "strength": min(1.0, 0.48 + int(topic["count"]) / 12),
                "metadata": {"mention_count": topic["count"]},
            }
        )
        edges.append(
            {
                "id": f"edge:{root_id}:{topic_id}",
                "source": root_id,
                "target": topic_id,
                "type": "topic",
                "label": "主题",
                "weight": 0.64,
            }
        )
        for chunk_node_id in topic["chunk_ids"][:6]:
            edges.append(
                {
                    "id": f"edge:{topic_id}:{chunk_node_id}",
                    "source": topic_id,
                    "target": chunk_node_id,
                    "type": "mentions",
                    "label": "关联",
                    "weight": 0.42,
                }
            )

    category_counts = Counter(str(node.get("type") or "unknown") for node in nodes)
    return {
        "success": True,
        "dataset_id": dataset_id,
        "tenant_id": tenant_id,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "document_count": len(ordered_documents),
            "knowledge_count": len(selected_chunks),
            "topic_count": len(topic_rows),
            "total_chunk_count": len(graph_chunks),
            "truncated": len(selected_chunks) < len(graph_chunks),
            "categories": dict(sorted(category_counts.items())),
        },
        "generated_at": _utc_now_iso(),
    }


def _select_graph_chunks(chunks: list[RetrievedChunk], *, limit: int) -> list[RetrievedChunk]:
    """Round-robin documents so one large source cannot dominate the graph."""

    grouped: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in chunks:
        document_id = str((chunk.metadata or {}).get("document_id") or chunk.source or "inline")
        grouped[document_id].append(chunk)
    for rows in grouped.values():
        rows.sort(key=lambda item: (item.chunk_index, item.char_start))

    selected: list[RetrievedChunk] = []
    document_ids = sorted(grouped)
    cursor = 0
    while document_ids and len(selected) < max(0, limit):
        remaining: list[str] = []
        for document_id in document_ids:
            rows = grouped[document_id]
            if cursor < len(rows):
                selected.append(rows[cursor])
                if len(selected) >= limit:
                    break
            if cursor + 1 < len(rows):
                remaining.append(document_id)
        document_ids = remaining
        cursor += 1
    return selected


def _extract_graph_topics(
    chunk_rows: list[tuple[str, RetrievedChunk]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    topics: dict[str, dict[str, Any]] = {}
    for node_id, chunk in chunk_rows:
        for label in _graph_topic_candidates(chunk):
            key = label.casefold()
            row = topics.setdefault(key, {"key": key, "label": label, "count": 0, "chunk_ids": []})
            row["count"] += 1
            if node_id not in row["chunk_ids"]:
                row["chunk_ids"].append(node_id)
    return sorted(
        topics.values(),
        key=lambda item: (-int(item["count"]), str(item["label"]).casefold()),
    )[:limit]


def _graph_topic_candidates(chunk: RetrievedChunk) -> list[str]:
    values: list[str] = []
    metadata = dict(chunk.metadata or {})
    for key in _GRAPH_TOPIC_METADATA_KEYS:
        raw = metadata.get(key)
        if isinstance(raw, (list, tuple, set, frozenset)):
            values.extend(str(item) for item in raw)
        elif raw is not None:
            values.extend(re.split(r"[,，;；|/#]+", str(raw)))

    source_stem = Path(str(chunk.source or "")).stem
    if source_stem and source_stem.casefold() not in {"inline", "default"}:
        values.append(source_stem)

    for raw_line in str(chunk.text or "").splitlines()[:40]:
        line = re.sub(r"^[#>*\-\d.、\s]+", "", raw_line).strip()
        is_heading = raw_line.lstrip().startswith("#") or line.endswith(("：", ":"))
        if is_heading and 2 <= len(line.rstrip("：:")) <= 32:
            values.append(line.rstrip("：:"))

    for match in re.finditer(
        r"(?:^|[，。；：、\s])([A-Za-z][A-Za-z0-9_.-]{2,30}|[\u4e00-\u9fff]{2,16})(?=是|为|包括|支持|需要|必须|负责|属于|采用|禁止|应当|不得)",
        str(chunk.text or ""),
    ):
        values.append(match.group(1))

    english_counts = Counter(
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,30}", str(chunk.text or ""))
    )
    values.extend(token for token, count in english_counts.most_common(4) if count >= 2)

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _clean_graph_label(value, max_length=30)
        key = label.casefold()
        if len(label) < 2 or key in _GRAPH_TOPIC_STOPWORDS or key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return cleaned[:8]


def _graph_chunk_node_id(chunk: RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    document_id = str(metadata.get("document_id") or chunk.source or "inline")
    raw = f"{document_id}:{chunk.chunk_index}:{chunk.char_start}:{chunk.text}"
    return f"knowledge:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _graph_source_label(source: str) -> str:
    label = Path(str(source or "资料来源")).name or "资料来源"
    return _clean_graph_label(label, max_length=32)


def _graph_knowledge_label(text: str) -> str:
    for raw_line in str(text or "").splitlines():
        line = re.sub(r"^[#>*\-\d.、\s]+", "", raw_line).strip()
        if not line:
            continue
        sentence = re.split(r"[。！？!?；;]", line, maxsplit=1)[0]
        return _clean_graph_label(sentence or line, max_length=34)
    return "知识片段"


def _graph_excerpt(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"


def _clean_graph_label(value: Any, *, max_length: int) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n#*_-—:：")
    if len(label) <= max_length:
        return label
    return label[: max(1, max_length - 1)].rstrip() + "…"


def _public_graph_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(metadata or {}).items()
        if not str(key).startswith("_") and str(key) not in {"file_path"}
    }
