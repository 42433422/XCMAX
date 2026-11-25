"""本机文件索引任务：增量扫描授权目录并写入 local-files 知识库。

单后台线程串行处理，避免整机扫描时并发打爆磁盘与向量库；撤销授权后由
``request_purge`` 清理已入库文档。
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
from pathlib import Path
from typing import Any, cast

from app.application.local_file_access.extract import extract_text
from app.application.local_file_access.paths import iter_candidate_files
from app.application.local_file_access.service import DATASET_ID, LocalFileAccessError
from app.db.models.local_file import LocalFileDocument, LocalFileGrant
from app.db.session import get_db
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.logging.audit_logger import audit_log
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

_QUEUE: queue.Queue[tuple[str, int, int, int]] = queue.Queue()
_PENDING: set[tuple[str, int]] = set()
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None


def _ensure_worker() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_loop, name="local-file-indexer", daemon=True)
        _WORKER.start()


def _enqueue(action: str, grant_id: int, owner_id: int, tenant: int) -> bool:
    key = (action, int(grant_id))
    with _LOCK:
        if key in _PENDING:
            return False
        _PENDING.add(key)
    _QUEUE.put((action, int(grant_id), int(owner_id), int(tenant)))
    _ensure_worker()
    return True


def request_sync(grant_id: int, owner_id: int, tenant: int) -> bool:
    """请求增量同步；同一授权已在队列中时返回 False。"""
    return _enqueue("sync", grant_id, owner_id, tenant)


def request_purge(grant_id: int, owner_id: int, tenant: int) -> bool:
    """请求清理某个授权已入库的内容。"""
    return _enqueue("purge", grant_id, owner_id, tenant)


def _loop() -> None:
    while True:
        action, grant_id, owner_id, tenant = _QUEUE.get()
        try:
            if action == "sync":
                _sync_grant(grant_id, owner_id, tenant)
            else:
                _purge_grant(grant_id, owner_id, tenant)
        except RECOVERABLE_ERRORS:
            logger.warning("local file %s failed: grant=%s", action, grant_id, exc_info=True)
            _mark_error(grant_id, owner_id, tenant)
        finally:
            with _LOCK:
                _PENDING.discard((action, grant_id))
            _QUEUE.task_done()


def _load_grant(grant_id: int, owner_id: int, tenant: int) -> LocalFileGrant | None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileGrant)
            .filter(
                LocalFileGrant.id == int(grant_id),
                LocalFileGrant.owner_user_id == int(owner_id),
            )
            .first()
        )
        if row is None:
            return None
        db.expunge(row)
        return cast(LocalFileGrant, row)


def _mark_status(
    grant_id: int,
    owner_id: int,
    tenant: int,
    status: str,
    *,
    error: str = "",
    indexed: int | None = None,
    skipped: int | None = None,
    failed: int | None = None,
    scanned_at: bool = False,
) -> None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileGrant)
            .filter(
                LocalFileGrant.id == int(grant_id),
                LocalFileGrant.owner_user_id == int(owner_id),
            )
            .first()
        )
        if row is None:
            return
        row.scan_status = status
        row.scan_error = str(error or "")[:2000]
        if indexed is not None:
            row.indexed_count = int(indexed)
        if skipped is not None:
            row.skipped_count = int(skipped)
        if failed is not None:
            row.error_count = int(failed)
        if scanned_at:
            row.last_scan_at = utc_now_naive()
        db.commit()


def _mark_error(grant_id: int, owner_id: int, tenant: int) -> None:
    try:
        _mark_status(grant_id, owner_id, tenant, "error", error="扫描失败，请重试")
    except RECOVERABLE_ERRORS:
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document_id(grant_id: int, relative_path: str) -> str:
    stable = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:32]
    return f"lf-{int(grant_id)}-{stable}"


def _access_context(owner_id: int, tenant: int):
    from app.application.dataset_rag_app_service import (
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
    )

    return DatasetAccessContext(
        actor_id=str(owner_id),
        tenant_id=str(tenant),
        permissions=frozenset({DATASET_WRITE_PERMISSION}),
    )


def _sync_grant(grant_id: int, owner_id: int, tenant: int) -> None:
    grant = _load_grant(grant_id, owner_id, tenant)
    if grant is None:
        return
    if not grant.is_active:
        _purge_grant(grant_id, owner_id, tenant)
        return
    _mark_status(grant_id, owner_id, tenant, "scanning")
    roots = [Path(grant.root_path)]
    if grant.mode == "full_disk":
        volumes = Path("/Volumes")
        if volumes.is_dir():
            roots.append(volumes)

    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    service = get_dataset_rag_app_service()
    access = _access_context(owner_id, tenant)
    indexed = skipped = failed = 0
    seen: set[str] = set()

    for root in roots:
        for candidate in iter_candidate_files(root):
            if not _still_active(grant_id, owner_id, tenant):
                return
            path = str(candidate.path)
            seen.add(path)
            try:
                state = _existing_document(grant_id, owner_id, tenant, path)
                if (
                    state is not None
                    and state.status == "indexed"
                    and int(state.size_bytes) == candidate.size_bytes
                    and int(state.mtime_ns) == candidate.mtime_ns
                ):
                    skipped += 1
                    continue
                digest = _sha256(candidate.path)
                if state is not None and state.status == "indexed" and state.sha256 == digest:
                    _touch_document(
                        state.id, owner_id, tenant, candidate.size_bytes, candidate.mtime_ns
                    )
                    skipped += 1
                    continue
                document_id = (
                    state.document_id
                    if state is not None and state.document_id
                    else _document_id(grant_id, candidate.relative_path)
                )
                text, parser, parser_meta = extract_text(candidate.path)
                with tenant_scope(tenant):
                    result = service.ingest_document(
                        dataset_id=DATASET_ID,
                        source=str(candidate.path),
                        text=text,
                        document_id=document_id,
                        tenant_id=str(tenant),
                        metadata={
                            "local_file": True,
                            "grant_id": int(grant_id),
                            "relative_path": candidate.relative_path,
                            "sha256": digest,
                            "size_bytes": candidate.size_bytes,
                            "mtime_ns": candidate.mtime_ns,
                            "parser": parser,
                            "extension": candidate.path.suffix.lower(),
                            **(parser_meta or {}),
                        },
                        access_context=access,
                    )
                if not isinstance(result, dict) or result.get("success") is not True:
                    message = result.get("message") if isinstance(result, dict) else None
                    raise LocalFileAccessError(
                        "local_file_ingest_failed", str(message or "知识库写入失败")
                    )
                # 以知识库回执里的 document_id 为准，删除时才能命中同一条文档。
                stored_id = str(((result.get("document") or {}).get("document_id")) or document_id)
                _upsert_document(
                    grant_id,
                    owner_id,
                    tenant,
                    path,
                    candidate,
                    digest,
                    stored_id,
                )
                indexed += 1
            except (LocalFileAccessError,) + RECOVERABLE_ERRORS as exc:
                failed += 1
                _record_failure(grant_id, owner_id, tenant, path, str(exc))
                audit_log(
                    "local_file_access.index_error",
                    actor_id=owner_id,
                    success=False,
                    details={"grant_id": int(grant_id), "path": path, "error": str(exc)[:300]},
                )

    _purge_missing(grant_id, owner_id, tenant, seen, service, access)
    _mark_status(
        grant_id,
        owner_id,
        tenant,
        "ready",
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        scanned_at=True,
    )


def _still_active(grant_id: int, owner_id: int, tenant: int) -> bool:
    grant = _load_grant(grant_id, owner_id, tenant)
    return bool(grant and grant.is_active)


def _existing_document(
    grant_id: int, owner_id: int, tenant: int, path: str
) -> LocalFileDocument | None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.path == path,
            )
            .first()
        )
        if row is None:
            return None
        db.expunge(row)
        return cast(LocalFileDocument, row)


def _touch_document(document_pk: int, owner_id: int, tenant: int, size: int, mtime_ns: int) -> None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.id == int(document_pk),
                LocalFileDocument.owner_user_id == int(owner_id),
            )
            .first()
        )
        if row is not None:
            row.size_bytes = int(size)
            row.mtime_ns = int(mtime_ns)
            db.commit()


def _upsert_document(
    grant_id: int,
    owner_id: int,
    tenant: int,
    path: str,
    candidate,
    digest: str,
    document_id: str,
) -> None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.path == path,
            )
            .first()
        )
        if row is None:
            row = LocalFileDocument(
                grant_id=int(grant_id),
                owner_user_id=int(owner_id),
                path=path,
                dataset_id=DATASET_ID,
            )
            db.add(row)
        row.relative_path = candidate.relative_path
        row.size_bytes = int(candidate.size_bytes)
        row.mtime_ns = int(candidate.mtime_ns)
        row.sha256 = digest
        row.document_id = document_id
        row.status = "indexed"
        row.last_indexed_at = utc_now_naive()
        row.last_error = ""
        row.attempt_count = 0
        db.commit()


def _record_failure(grant_id: int, owner_id: int, tenant: int, path: str, error: str) -> None:
    with tenant_scope(tenant), get_db() as db:
        row = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.path == path,
            )
            .first()
        )
        if row is None:
            row = LocalFileDocument(
                grant_id=int(grant_id),
                owner_user_id=int(owner_id),
                path=path,
                dataset_id=DATASET_ID,
            )
            db.add(row)
        row.status = "error"
        row.last_error = str(error or "")[:2000]
        row.attempt_count = int(row.attempt_count or 0) + 1
        db.commit()


def _purge_missing(
    grant_id: int, owner_id: int, tenant: int, seen: set[str], service, access
) -> None:
    with tenant_scope(tenant), get_db() as db:
        rows = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.status != "deleted",
            )
            .all()
        )
        stale = [(row.id, row.path, row.document_id) for row in rows if row.path not in seen]
    for pk, path, document_id in stale:
        deleted = False
        try:
            with tenant_scope(tenant):
                result = service.delete_document(DATASET_ID, document_id, access_context=access)
            deleted = isinstance(result, dict) and result.get("success") is True
        except RECOVERABLE_ERRORS:
            logger.warning("local file document delete failed: %s", document_id, exc_info=True)
        if not deleted:
            _record_failure(grant_id, owner_id, tenant, path, "知识库文档清理失败")
            continue
        with tenant_scope(tenant), get_db() as db:
            row = (
                db.query(LocalFileDocument)
                .filter(
                    LocalFileDocument.id == int(pk),
                    LocalFileDocument.owner_user_id == int(owner_id),
                )
                .first()
            )
            if row is not None:
                row.status = "deleted"
                row.last_error = ""
                db.commit()


def _purge_grant(grant_id: int, owner_id: int, tenant: int) -> None:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    service = get_dataset_rag_app_service()
    access = _access_context(owner_id, tenant)
    with tenant_scope(tenant), get_db() as db:
        rows = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
            )
            .all()
        )
        targets = [(row.id, row.document_id) for row in rows]
    for pk, document_id in targets:
        deleted = not document_id
        if document_id:
            try:
                with tenant_scope(tenant):
                    result = service.delete_document(DATASET_ID, document_id, access_context=access)
                deleted = isinstance(result, dict) and result.get("success") is True
            except RECOVERABLE_ERRORS:
                logger.warning("local file purge delete failed: %s", document_id, exc_info=True)
        if not deleted:
            continue
        with tenant_scope(tenant), get_db() as db:
            row = db.query(LocalFileDocument).filter(LocalFileDocument.id == int(pk)).first()
            if row is not None:
                db.delete(row)
                db.commit()
    _mark_status(
        grant_id,
        owner_id,
        tenant,
        "revoked",
        indexed=0,
        skipped=0,
        failed=0,
    )


def status_snapshot(grant_id: int, owner_id: int, tenant: int) -> dict[str, Any]:
    grant = _load_grant(grant_id, owner_id, tenant)
    if grant is None:
        return {}
    with tenant_scope(tenant), get_db() as db:
        total = (
            db.query(LocalFileDocument)
            .filter(
                LocalFileDocument.grant_id == int(grant_id),
                LocalFileDocument.owner_user_id == int(owner_id),
                LocalFileDocument.status != "deleted",
            )
            .count()
        )
    return {
        "grant_id": int(grant_id),
        "scan_status": grant.scan_status,
        "total_documents": int(total),
        "indexed_count": grant.indexed_count,
        "skipped_count": grant.skipped_count,
        "error_count": grant.error_count,
    }
