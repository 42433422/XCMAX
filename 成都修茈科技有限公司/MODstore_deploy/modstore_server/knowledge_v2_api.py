"""知识库 v2 API：集合(Collection) + 文档 + 共享 + 检索。

与 v1（``knowledge_vector_api.py``）共存：
- v1 仍是"按 user_id 直接读写默认集合"，对老前端 100% 兼容。
- v2 引入 owner_kind ∈ {user, employee, workflow, org}、共享授权、可见性等概念。

所有写操作都通过 :mod:`modstore_server.rag_service.can_access_collection` 做权限校验。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from modstore_server import rag_service, vector_engine
from modstore_server.api.deps import _get_current_user
from modstore_server.embedding_service import (
    embedding_config_snapshot,
)
from modstore_server.knowledge_ingest import (
    SUPPORTED_EXTENSIONS,
)
from modstore_server.knowledge_vector_store import KnowledgeVectorError
from modstore_server.knowledge_v2_documents import upload_document
from modstore_server.knowledge_v2_models import (
    CollectionCreateBody,
    CollectionUpdateBody,
    RetrieveBody,
    ShareBody,
)
from modstore_server.models import (
    KnowledgeCollection,
    KnowledgeDocument,
    KnowledgeMembership,
    User,
    get_session_factory,
)
from modstore_server.vector_engine import VectorEngineError

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/knowledge/v2", tags=["knowledge-v2"])


_VALID_OWNER_KINDS = {"user", "employee", "workflow", "org"}
_VALID_VISIBILITIES = {"private", "shared", "public"}
_VALID_PERMISSIONS = {"read", "write", "admin"}


def _now_ts(dt: Optional[datetime]) -> int:
    if not dt:
        return 0
    return int(dt.timestamp())


def _collection_to_dict(coll: KnowledgeCollection) -> Dict[str, Any]:
    return {
        "id": int(coll.id),
        "owner_kind": coll.owner_kind,
        "owner_id": coll.owner_id,
        "name": coll.name,
        "description": coll.description or "",
        "visibility": coll.visibility or "private",
        "embedding_model": coll.embedding_model or "",
        "embedding_dim": int(coll.embedding_dim or 0),
        "chunk_count": int(coll.chunk_count or 0),
        "created_at": _now_ts(coll.created_at),
        "updated_at": _now_ts(coll.updated_at),
    }


def _can_admin(coll: KnowledgeCollection, user: User) -> bool:
    """admin 权限：owner（user_kind 时是自己）、平台管理员 或 grantee.permission='admin'。"""
    if user.is_admin:
        return True
    if coll.owner_kind == "user" and str(coll.owner_id) == str(int(user.id)):
        return True
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(KnowledgeMembership)
            .filter(
                KnowledgeMembership.collection_id == coll.id,
                KnowledgeMembership.grantee_kind == "user",
                KnowledgeMembership.grantee_id == str(int(user.id)),
                KnowledgeMembership.permission == "admin",
            )
            .first()
        )
        return rows is not None


def _ensure_collection(session, coll_id: int) -> KnowledgeCollection:
    coll = session.query(KnowledgeCollection).filter(KnowledgeCollection.id == int(coll_id)).first()
    if coll is None:
        raise HTTPException(404, "集合不存在")
    return coll


def _service_unavailable(e: Exception) -> HTTPException:
    return HTTPException(503, str(e))


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


@router.get("/status")
def api_status(user: User = Depends(_get_current_user)) -> Dict[str, Any]:
    eng = vector_engine.status()
    sf = get_session_factory()
    with sf() as session:
        emb = embedding_config_snapshot(session=session, user_id=int(user.id))
        own_count = (
            session.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.owner_kind == "user",
                KnowledgeCollection.owner_id == str(int(user.id)),
            )
            .count()
        )
    return {
        "ok": bool(emb.get("configured") and eng.get("ready")),
        "embedding": emb,
        "engine": eng,
        "owned_collections": int(own_count),
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@router.get("/collections")
def api_list_collections(
    owner_kind: Optional[str] = None,
    owner_id: Optional[str] = None,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        rows = rag_service.visible_collection_ids(
            session,
            user_id=user.id,
            permission="read",
        )
        if owner_kind:
            rows = [r for r in rows if (r.owner_kind or "") == owner_kind]
        if owner_id is not None:
            rows = [r for r in rows if str(r.owner_id or "") == str(owner_id)]
        return {"collections": [_collection_to_dict(r) for r in rows]}


@router.post("/collections")
def api_create_collection(
    body: CollectionCreateBody,
    user: User = Depends(_get_current_user),
):
    owner_kind = (body.owner_kind or "user").strip().lower()
    if owner_kind not in _VALID_OWNER_KINDS:
        raise HTTPException(400, f"owner_kind 必须为 {sorted(_VALID_OWNER_KINDS)}")
    owner_id = (body.owner_id or "").strip()
    if owner_kind == "user":
        owner_id = str(int(user.id))
    elif not owner_id:
        raise HTTPException(400, "非 user 类型必须提供 owner_id")
    visibility = (body.visibility or "private").lower()
    if visibility not in _VALID_VISIBILITIES:
        raise HTTPException(400, f"visibility 必须为 {sorted(_VALID_VISIBILITIES)}")

    if owner_kind != "user" and not user.is_admin:
        raise HTTPException(403, "仅平台管理员可为非用户实体创建集合")

    sf = get_session_factory()
    with sf() as session:
        existing = (
            session.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.owner_kind == owner_kind,
                KnowledgeCollection.owner_id == owner_id,
                KnowledgeCollection.name == body.name.strip(),
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(409, "同名集合已存在")
        emb_cfg = embedding_config_snapshot(session=session, user_id=int(user.id))
        coll = KnowledgeCollection(
            owner_kind=owner_kind,
            owner_id=owner_id,
            name=body.name.strip(),
            description=(body.description or "").strip(),
            visibility=visibility,
            embedding_model=(body.embedding_model or emb_cfg.get("model") or "").strip(),
            embedding_dim=int(body.embedding_dim or emb_cfg.get("dim") or 1536),
            chunk_count=0,
        )
        session.add(coll)
        session.commit()
        session.refresh(coll)
        return {"ok": True, "collection": _collection_to_dict(coll)}


@router.patch("/collections/{coll_id}")
def api_update_collection(
    coll_id: int,
    body: CollectionUpdateBody,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not _can_admin(coll, user):
            raise HTTPException(403, "无权修改该集合")
        if body.name is not None:
            coll.name = body.name.strip()
        if body.description is not None:
            coll.description = body.description.strip()
        if body.visibility is not None:
            v = body.visibility.lower()
            if v not in _VALID_VISIBILITIES:
                raise HTTPException(400, f"visibility 必须为 {sorted(_VALID_VISIBILITIES)}")
            coll.visibility = v
        session.commit()
        session.refresh(coll)
        return {"ok": True, "collection": _collection_to_dict(coll)}


@router.delete("/collections/{coll_id}")
def api_delete_collection(
    coll_id: int,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not _can_admin(coll, user):
            raise HTTPException(403, "无权删除该集合")
        try:
            vector_engine.drop_collection(
                vector_engine.kb_collection_name(int(coll.id)),
                missing_ok=True,
            )
        except VectorEngineError:
            pass
        session.query(KnowledgeDocument).filter(KnowledgeDocument.collection_id == coll.id).delete()
        session.query(KnowledgeMembership).filter(
            KnowledgeMembership.collection_id == coll.id
        ).delete()
        session.delete(coll)
        session.commit()
    return {"ok": True, "id": int(coll_id)}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@router.get("/collections/{coll_id}/documents")
def api_list_documents(
    coll_id: int,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not rag_service.can_access_collection(
            session, collection_id=coll.id, user_id=user.id, permission="read"
        ):
            raise HTTPException(403, "无权查看该集合")
        rows = (
            session.query(KnowledgeDocument)
            .filter(KnowledgeDocument.collection_id == coll.id)
            .order_by(KnowledgeDocument.created_at.desc())
            .all()
        )
        return {
            "collection": _collection_to_dict(coll),
            "documents": [
                {
                    "doc_id": r.doc_id,
                    "filename": r.filename or "",
                    "size_bytes": int(r.size_bytes or 0),
                    "chunk_count": int(r.chunk_count or 0),
                    "created_at": _now_ts(r.created_at),
                }
                for r in rows
            ],
        }


@router.post("/collections/{coll_id}/documents")
async def api_upload_document(
    coll_id: int,
    file: UploadFile = File(...),
    embedding_provider: str | None = Form(None),
    embedding_model: str | None = Form(None),
    chunk_strategy: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    user: User = Depends(_get_current_user),
):
    del embedding_model, chunk_size, chunk_overlap
    return await upload_document(
        coll_id=coll_id,
        file=file,
        embedding_provider=embedding_provider,
        chunk_strategy=chunk_strategy,
        user=user,
        ensure_collection=_ensure_collection,
        can_admin=_can_admin,
        service_unavailable=_service_unavailable,
    )


@router.delete("/collections/{coll_id}/documents/{doc_id}")
def api_delete_document(
    coll_id: int,
    doc_id: str,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not rag_service.can_access_collection(
            session, collection_id=coll.id, user_id=user.id, permission="write"
        ) and not _can_admin(coll, user):
            raise HTTPException(403, "无权写入该集合")
        doc_row = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.collection_id == coll.id,
                KnowledgeDocument.doc_id == str(doc_id),
            )
            .first()
        )
        if doc_row is None:
            raise HTTPException(404, "文档不存在")
        try:
            vector_engine.delete(
                vector_engine.kb_collection_name(int(coll.id)),
                where={"doc_id": str(doc_id)},
            )
        except VectorEngineError:
            pass
        session.delete(doc_row)
        coll.chunk_count = max(0, int(coll.chunk_count or 0) - int(doc_row.chunk_count or 0))
        session.commit()
        return {"ok": True, "doc_id": doc_id}


# ---------------------------------------------------------------------------
# 共享授权
# ---------------------------------------------------------------------------


@router.post("/collections/{coll_id}/share")
def api_share_collection(
    coll_id: int,
    body: ShareBody,
    user: User = Depends(_get_current_user),
):
    grantee_kind = body.grantee_kind.strip().lower()
    if grantee_kind not in _VALID_OWNER_KINDS:
        raise HTTPException(400, f"grantee_kind 必须为 {sorted(_VALID_OWNER_KINDS)}")
    permission = body.permission.strip().lower()
    if permission not in _VALID_PERMISSIONS:
        raise HTTPException(400, f"permission 必须为 {sorted(_VALID_PERMISSIONS)}")
    grantee_id = body.grantee_id.strip()
    if not grantee_id:
        raise HTTPException(400, "grantee_id 不能为空")

    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not _can_admin(coll, user):
            raise HTTPException(403, "无权共享该集合")
        existing = (
            session.query(KnowledgeMembership)
            .filter(
                KnowledgeMembership.collection_id == coll.id,
                KnowledgeMembership.grantee_kind == grantee_kind,
                KnowledgeMembership.grantee_id == grantee_id,
            )
            .first()
        )
        if existing is None:
            existing = KnowledgeMembership(
                collection_id=coll.id,
                grantee_kind=grantee_kind,
                grantee_id=grantee_id,
                permission=permission,
            )
            session.add(existing)
        else:
            existing.permission = permission
        session.commit()
        return {
            "ok": True,
            "membership": {
                "id": int(existing.id),
                "collection_id": int(coll.id),
                "grantee_kind": grantee_kind,
                "grantee_id": grantee_id,
                "permission": permission,
            },
        }


@router.delete("/collections/{coll_id}/share/{membership_id}")
def api_unshare_collection(
    coll_id: int,
    membership_id: int,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        coll = _ensure_collection(session, coll_id)
        if not _can_admin(coll, user):
            raise HTTPException(403, "无权取消共享")
        row = (
            session.query(KnowledgeMembership)
            .filter(
                KnowledgeMembership.id == int(membership_id),
                KnowledgeMembership.collection_id == coll.id,
            )
            .first()
        )
        if row is None:
            raise HTTPException(404, "授权记录不存在")
        session.delete(row)
        session.commit()
        return {"ok": True, "id": int(membership_id)}


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


@router.post("/retrieve")
async def api_retrieve(
    body: RetrieveBody,
    user: User = Depends(_get_current_user),
):
    try:
        chunks = await rag_service.retrieve(
            user_id=int(user.id),
            query=body.query,
            employee_id=body.employee_id,
            workflow_id=body.workflow_id,
            org_id=body.org_id,
            extra_collection_ids=body.collection_ids,
            top_k=body.top_k,
            min_score=body.min_score,
            embedding_provider=body.embedding_provider,
        )
    except KnowledgeVectorError as e:
        raise _service_unavailable(e)
    return {
        "items": [c.to_dict() for c in chunks],
        "count": len(chunks),
    }


__all__ = ["router"]
