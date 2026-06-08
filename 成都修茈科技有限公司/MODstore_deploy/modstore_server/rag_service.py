"""RAG 服务层：跨多个集合(Collection)做向量检索 + 权限过滤 + 可选 rerank。

调用方（员工 cognition / 工作流 knowledge_search 节点 / 前端聊天）只需要传：

- ``user_id``（必填，作为身份基线，用于解析"我自己拥有 + 别人 grant 给我"的集合）
- 可选 ``employee_id`` / ``workflow_id`` / ``org_id``：把对应实体拥有的集合一起加入候选
- 可选 ``extra_collection_ids``：明确指定要查的集合（节点编辑器场景）
- ``query``：检索文本

引擎仅 Chroma；嵌入向量始终通过 :mod:`modstore_server.embedding_service` 外部生成。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

from modstore_server import vector_engine
from modstore_server.embedding_service import EmbeddingConfigError, embed_texts
from modstore_server.models import (
    KnowledgeCollection,
    KnowledgeMembership,
    get_session_factory,
)
from modstore_server.vector_engine import VectorEngineError

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """单个 RAG 检索结果。"""

    collection_id: int
    collection_name: str
    owner_kind: str
    owner_id: str
    doc_id: str
    chunk_id: str
    filename: str
    page_no: Optional[int]
    content: str
    distance: float
    score: float
    source_url: str = ""
    char_range: Optional[List[int]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "collection_id": self.collection_id,
            "collection_name": self.collection_name,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "filename": self.filename,
            "page_no": self.page_no,
            "content": self.content,
            "distance": self.distance,
            "score": self.score,
        }
        if self.source_url:
            d["source_url"] = self.source_url
        if self.char_range:
            d["char_range"] = self.char_range
        return d


# ---------------------------------------------------------------------------
# 集合访问解析（owner + grantee + visibility）
# ---------------------------------------------------------------------------


def visible_collection_ids(
    session: Session,
    *,
    user_id: int,
    employee_id: Optional[str] = None,
    workflow_id: Optional[int] = None,
    org_id: Optional[str] = None,
    permission: str = "read",
) -> List[KnowledgeCollection]:
    """解析当前调用上下文可见 / 可写 的全部集合。

    ``permission='read'`` 时返回：
        - 我自己 owned（owner_kind=user, owner_id=user_id）
        - employee_id/workflow_id/org_id 自身 owned 的集合
        - 任意 grant 给上述身份的集合（KnowledgeMembership）
        - visibility='public' 的集合
    ``permission='write'`` 时仅返回 owned 或 grantee.permission in (write, admin)。
    """
    perm_norm = (permission or "read").lower()
    write_only = perm_norm in ("write", "admin")

    identities: List[tuple[str, str]] = [("user", str(int(user_id)))]
    if employee_id:
        identities.append(("employee", str(employee_id)))
    if workflow_id is not None:
        identities.append(("workflow", str(int(workflow_id))))
    if org_id:
        identities.append(("org", str(org_id)))

    candidates: Dict[int, KnowledgeCollection] = {}

    owned_q = session.query(KnowledgeCollection).filter(_or_owner_filter(identities))
    for row in owned_q.all():
        candidates[int(row.id)] = row

    grant_rows = session.query(KnowledgeMembership).filter(_or_grantee_filter(identities)).all()
    if grant_rows:
        granted_ids = []
        allowed_grants: Dict[int, str] = {}
        for g in grant_rows:
            cid = int(g.collection_id)
            granted_ids.append(cid)
            allowed_grants[cid] = (g.permission or "read").lower()
        for row in (
            session.query(KnowledgeCollection).filter(KnowledgeCollection.id.in_(granted_ids)).all()
        ):
            cid = int(row.id)
            if write_only:
                grant_perm = allowed_grants.get(cid, "read")
                if grant_perm not in ("write", "admin"):
                    continue
            candidates[cid] = row

    if not write_only:
        for row in (
            session.query(KnowledgeCollection)
            .filter(KnowledgeCollection.visibility == "public")
            .all()
        ):
            candidates.setdefault(int(row.id), row)

    return list(candidates.values())


def _or_owner_filter(identities: Sequence[tuple[str, str]]):
    from sqlalchemy import and_, or_

    clauses = [
        and_(
            KnowledgeCollection.owner_kind == kind,
            KnowledgeCollection.owner_id == oid,
        )
        for kind, oid in identities
    ]
    if not clauses:
        return KnowledgeCollection.id == -1
    return or_(*clauses)


def _or_grantee_filter(identities: Sequence[tuple[str, str]]):
    from sqlalchemy import and_, or_

    clauses = [
        and_(
            KnowledgeMembership.grantee_kind == kind,
            KnowledgeMembership.grantee_id == oid,
        )
        for kind, oid in identities
    ]
    if not clauses:
        return KnowledgeMembership.id == -1
    return or_(*clauses)


def can_access_collection(
    session: Session,
    *,
    collection_id: int,
    user_id: int,
    employee_id: Optional[str] = None,
    workflow_id: Optional[int] = None,
    org_id: Optional[str] = None,
    permission: str = "read",
) -> bool:
    """检查指定集合在当前身份下是否有 ``permission`` 权限。"""
    rows = visible_collection_ids(
        session,
        user_id=user_id,
        employee_id=employee_id,
        workflow_id=workflow_id,
        org_id=org_id,
        permission=permission,
    )
    return any(int(r.id) == int(collection_id) for r in rows)


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


async def retrieve(
    *,
    user_id: int,
    query: str,
    employee_id: Optional[str] = None,
    workflow_id: Optional[int] = None,
    org_id: Optional[str] = None,
    extra_collection_ids: Optional[Sequence[int]] = None,
    top_k: int = 6,
    min_score: float = 0.0,
    query_embedding: Optional[Sequence[float]] = None,
    embedding_provider: Optional[str] = None,
) -> List[RetrievedChunk]:
    """跨可见集合做 KNN 检索并归并。

    参数 ``query_embedding`` 给已自带向量的调用方（避免重复计算），不传则自动调用
    embedding 服务。失败时（缺 API Key、向量库不可用等）记录 warning 并返回空列表，
    保证调用链不中断。
    """
    q = (query or "").strip()
    if not q and not query_embedding:
        return []
    n = max(1, min(int(top_k or 6), 50))

    sf = get_session_factory()
    with sf() as session:
        all_visible = visible_collection_ids(
            session,
            user_id=user_id,
            employee_id=employee_id,
            workflow_id=workflow_id,
            org_id=org_id,
            permission="read",
        )
        wanted: Optional[Set[int]] = None
        if extra_collection_ids:
            wanted = {int(x) for x in extra_collection_ids if x is not None}
        scoped: List[KnowledgeCollection] = []
        for r in all_visible:
            if wanted is None or int(r.id) in wanted:
                scoped.append(r)
        if not scoped:
            return []

    if query_embedding is None:
        try:
            sf_embed = get_session_factory()
            with sf_embed() as session:
                try:
                    vecs = await embed_texts(
                        [q],
                        session=session,
                        user_id=int(user_id),
                        provider=embedding_provider,
                    )
                except TypeError:
                    vecs = await embed_texts([q])
        except EmbeddingConfigError as e:
            logger.warning("rag_service.retrieve: embedding 配置缺失: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.warning("rag_service.retrieve: embedding 调用失败: %s", e)
            return []
        if not vecs:
            return []
        query_vec = list(vecs[0])
    else:
        query_vec = list(query_embedding)

    chunks: List[RetrievedChunk] = []
    for coll in scoped:
        try:
            rows = vector_engine.query(
                vector_engine.kb_collection_name(int(coll.id)),
                query_embedding=query_vec,
                top_k=n,
            )
        except VectorEngineError as e:
            logger.warning("rag_service.retrieve: 集合 %s 查询失败: %s", coll.id, e)
            continue
        for r in rows:
            meta = r.get("metadata") or {}
            page_no = None
            page_raw = meta.get("page_no")
            if page_raw not in (None, "", 0):
                try:
                    page_no = int(page_raw)
                except Exception:  # noqa: BLE001
                    page_no = None
            distance = float(r.get("distance") or 1.0)
            score = max(0.0, 1.0 - distance)
            if score < float(min_score or 0.0):
                continue
            chunks.append(
                RetrievedChunk(
                    collection_id=int(coll.id),
                    collection_name=str(coll.name or ""),
                    owner_kind=str(coll.owner_kind or ""),
                    owner_id=str(coll.owner_id or ""),
                    doc_id=str(meta.get("doc_id") or ""),
                    chunk_id=str(meta.get("chunk_id") or r.get("id") or ""),
                    filename=str(meta.get("filename") or ""),
                    page_no=page_no,
                    content=str(r.get("document") or ""),
                    distance=distance,
                    score=score,
                    source_url=str(meta.get("source_url") or ""),
                    char_range=meta.get("char_range"),
                )
            )

    chunks.sort(key=lambda c: c.distance)
    chunks = chunks[:n]

    retrieval_mode = (os.environ.get("MODSTORE_RAG_RETRIEVAL_MODE") or "vector").strip().lower()
    if retrieval_mode == "hybrid":
        try:
            from modstore_server.hybrid_retriever import get_hybrid_retriever

            corpus = [c.content for c in chunks]
            retriever = get_hybrid_retriever()
            chunks = retriever.fuse(chunks, q, corpus=corpus, final_top_k=n)
        except Exception as exc:
            logger.warning("rag_service.retrieve: hybrid fusion failed, using vector: %s", exc)

    chunks = _maybe_rerank(q, chunks)
    return chunks


def _maybe_rerank(query: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """可选 cross-encoder 重排：环境变量 ``MODSTORE_RAG_RERANK=cross-encoder``，
    并已安装 ``sentence-transformers`` 时启用；否则原样返回。"""
    if not chunks:
        return chunks
    mode = (os.environ.get("MODSTORE_RAG_RERANK") or "").strip().lower()
    if mode != "cross-encoder":
        return chunks
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception:  # noqa: BLE001
        return chunks
    model_name = (
        os.environ.get("MODSTORE_RAG_RERANK_MODEL") or "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ).strip()
    try:
        ce = CrossEncoder(model_name)
        pairs = [(query, c.content) for c in chunks]
        scores = ce.predict(pairs)
        for c, s in zip(chunks, list(scores)):
            c.score = float(s)
        chunks.sort(key=lambda c: -c.score)
    except Exception as e:  # noqa: BLE001
        logger.warning("rag_service: cross-encoder rerank 失败，沿用 distance: %s", e)
    return chunks


# ---------------------------------------------------------------------------
# Prompt 注入
# ---------------------------------------------------------------------------


def format_retrieved_block(chunks: Iterable[RetrievedChunk]) -> str:
    """把检索结果格式化为可拼到 system prompt 的 Markdown 片段（带引用编号和来源标注）。"""
    parts: List[str] = []
    for i, c in enumerate(chunks, start=1):
        page = f" · 第 {c.page_no} 页" if c.page_no else ""
        char_info = ""
        if c.char_range and len(c.char_range) == 2:
            char_info = f" · 字符 {c.char_range[0]}-{c.char_range[1]}"
        source_parts = f"{c.filename or '资料'}{page}{char_info}"
        head = f"[{i}] {source_parts} (集合: {c.collection_name})"
        body = (c.content or "").strip()
        if len(body) > 1200:
            body = body[:1200] + "…"
        parts.append(f"{head}\n{body}")
    return "\n\n".join(parts)


def inject_rag_into_messages(
    messages: List[Dict[str, str]],
    chunks: Iterable[RetrievedChunk],
    *,
    intro: str = (
        "以下是知识库检索到的相关资料（带编号 [1][2]…）。"
        "请在回答时：\n"
        "1. 优先使用这些资料中的信息；\n"
        "2. 在使用某条资料时，在对应内容后标注引用编号，如「…[1]」；\n"
        "3. 如果资料不足以回答问题，请明确指出并给出你的判断；\n"
        "4. 不要编造资料中不存在的信息。\n\n"
    ),
) -> List[Dict[str, str]]:
    """在 messages 头部追加/合并一段 system 上下文。

    若已有 system 消息则把片段拼到末尾；否则在最前插入新 system。
    返回新列表，不修改入参。
    """
    chunks_list = list(chunks)
    if not chunks_list:
        return list(messages)
    block = format_retrieved_block(chunks_list)
    if not block:
        return list(messages)
    suffix = f"{intro}\n\n{block}"

    out = [dict(m) for m in messages]
    sys_idx = next(
        (i for i, m in enumerate(out) if (m.get("role") or "") == "system"),
        -1,
    )
    if sys_idx >= 0:
        existing = out[sys_idx].get("content") or ""
        out[sys_idx]["content"] = f"{existing}\n\n{suffix}" if existing.strip() else suffix
    else:
        out.insert(0, {"role": "system", "content": suffix})
    return out


def extract_citations(
    llm_output: str,
    chunks: List[RetrievedChunk],
) -> List[Dict[str, Any]]:
    """从 LLM 输出中提取引用标记 [1][2]… 并映射回 RetrievedChunk。

    Returns a list of citation dicts:
        [{"ref": 1, "chunk": RetrievedChunk}, ...]
    """
    import re as _re

    seen: set[int] = set()
    citations: List[Dict[str, Any]] = []
    for m in _re.finditer(r"\[(\d+)\]", llm_output):
        ref = int(m.group(1))
        if ref in seen or ref < 1 or ref > len(chunks):
            continue
        seen.add(ref)
        citations.append({"ref": ref, "chunk": chunks[ref - 1].to_dict()})
    return citations


__all__ = [
    "RetrievedChunk",
    "visible_collection_ids",
    "can_access_collection",
    "retrieve",
    "format_retrieved_block",
    "inject_rag_into_messages",
    "extract_citations",
]
