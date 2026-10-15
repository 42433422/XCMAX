# mypy: disable-error-code="assignment"
"""Shared catalog-public authentication, caching, and indexing helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import threading
from concurrent.futures import Future
from typing import Any, Dict, Optional

from fastapi import HTTPException

from modstore_server.catalog_publication_policy import stable_version
from modstore_server.catalog_store import catalog_write_lock, load_store, packages_path
from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
from modstore_server.models import get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_semantic_index_lock = threading.Lock()
_semantic_index_future: Future[bool] | None = None


def is_customer_delivery_seed(row: Dict[str, Any] | None) -> bool:
    return str((row or {}).get("artifact") or "").strip().lower() == "customer_delivery_seed"


def catalog_cache_scope() -> str:
    """Separate cache entries for each configured catalog store root."""
    path = str(packages_path().resolve())
    return hashlib.sha1(path.encode()).hexdigest()[:12]


def invalidate_catalog_list_caches(pkg_id: Any = None, version: Any = None) -> None:
    """Invalidate the exact detail key; list keys expire through their short TTL."""
    from modstore_server import cache

    if pkg_id and version:
        cache.delete(f"catalog:v1:{catalog_cache_scope()}:pkg:{pkg_id}:{version}")


def _semantic_index_timeout_seconds() -> float:
    raw = (os.environ.get("MODSTORE_CATALOG_INDEX_TIMEOUT_SECONDS") or "5").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 5.0
    return min(max(value, 0.05), 30.0)


def _index_catalog_item(record: Dict[str, Any]) -> bool:
    # Resolve through the historical public module so existing integrations that
    # patch ``catalog_public_routes.insert_embedding`` keep working.
    from modstore_server.api import catalog_public_routes

    embedding_text = f"{record.get('name', '')} {record.get('description', '')}"
    if not embedding_text.strip():
        return False
    try:
        catalog_public_routes.insert_embedding(
            item_id=f"{record.get('id')}:{record.get('version')}",
            text=embedding_text,
            metadata={
                "pkg_id": record.get("id"),
                "version": record.get("version"),
                "artifact": record.get("artifact", "mod"),
                "industry": record.get("industry", "通用"),
            },
        )
    except RECOVERABLE_ERRORS:
        logger.exception(
            "catalog semantic indexing degraded pkg_id=%s version=%s",
            record.get("id"),
            record.get("version"),
        )
        return False
    return True


def _start_semantic_index(record: Dict[str, Any]) -> Future[bool] | None:
    global _semantic_index_future
    with _semantic_index_lock:
        if _semantic_index_future is not None and not _semantic_index_future.done():
            return None
        future: Future[bool] = Future()
        _semantic_index_future = future

        def run() -> None:
            future.set_result(_index_catalog_item(dict(record)))

        threading.Thread(target=run, name="catalog-semantic-index", daemon=True).start()
        return future


async def try_index_catalog_item(record: Dict[str, Any]) -> bool:
    """Bound optional indexing without delaying durable publication."""
    future = _start_semantic_index(record)
    if future is None:
        logger.warning(
            "catalog semantic indexing already in flight; publication continues pkg_id=%s version=%s",
            record.get("id"),
            record.get("version"),
        )
        return False
    timeout = _semantic_index_timeout_seconds()
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "catalog semantic indexing exceeded %.2fs; publication continues pkg_id=%s version=%s",
            timeout,
            record.get("id"),
            record.get("version"),
        )
        return False


def authorize_upload(authorization: Optional[str]) -> str:
    supplied = (authorization or "").strip()
    upload = (os.environ.get("MODSTORE_CATALOG_UPLOAD_TOKEN") or "").strip()
    auto = (os.environ.get("MODSTORE_AUTO_PUBLISH_TOKEN") or "").strip()
    if auto and secrets.compare_digest(supplied, f"Bearer {auto}"):
        return "auto_publish"
    if upload and secrets.compare_digest(supplied, f"Bearer {upload}"):
        return "upload"
    if not upload and not auto:
        raise HTTPException(503, "未配置 Catalog 上传凭证，拒绝写入")
    raise HTTPException(401, "无效的上传凭证")


def require_upload(authorization: Optional[str]) -> None:
    authorize_upload(authorization)


def validated_automation_provenance(value: Any, *, package_sha256: str) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise HTTPException(400, "自动上架必须提供 automation_provenance")
    repository = str(value.get("source_repository") or "").strip()
    expected_repository = (
        os.environ.get("MODSTORE_AUTO_PUBLISH_REPOSITORY") or "42433422/XCMAX"
    ).strip()
    source_sha = str(value.get("source_sha") or "").strip()
    workflow_run_id = str(value.get("workflow_run_id") or "").strip()
    claimed_sha = str(value.get("package_sha256") or "").strip()
    if repository != expected_repository:
        raise HTTPException(403, "自动上架来源仓库不在允许范围")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise HTTPException(400, "automation_provenance.source_sha 无效")
    if not re.fullmatch(r"[1-9][0-9]*", workflow_run_id):
        raise HTTPException(400, "automation_provenance.workflow_run_id 无效")
    if not secrets.compare_digest(claimed_sha, package_sha256):
        raise HTTPException(400, "automation_provenance.package_sha256 与上传包不一致")
    return {
        "source_repository": repository,
        "source_sha": source_sha,
        "workflow_run_id": workflow_run_id,
        "package_sha256": package_sha256,
    }


def upsert_market_listing(saved: Dict[str, Any], *, public_listing: bool) -> None:
    from modstore_server.models import CatalogItem

    # Keep the JSON release ordering check and market pointer update serialized:
    # replaying an old version must never downgrade the one-row market listing.
    with catalog_write_lock():
        if saved.get("automation_provenance"):
            candidate = stable_version(saved.get("version"))
            rows = load_store().get("packages") or []
            for package in rows:
                if (
                    package.get("id") == saved.get("id")
                    and package.get("automation_provenance")
                    and stable_version(package.get("version")) > candidate
                ):
                    return
        sf = get_session_factory()
        with sf() as db:
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=None)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == str(saved.get("id"))).first()
            if row and public_listing:
                row.is_public = True
                row.compliance_status = "approved"
                row.delist_reason = ""
            db.commit()
    if public_listing:
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()


def params_hash(*args: Any) -> str:
    return hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]
