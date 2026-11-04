"""Archive + classify-from-archive HTTP adapters for reviewed Excel templates."""

from __future__ import annotations

import os
from collections import defaultdict
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import update
from starlette.concurrency import run_in_threadpool

from app.application.elt.archive_policy import ArchivePolicyError
from app.application.elt.archive_store import (
    DEFAULT_ARCHIVE_QUOTA_BYTES,
    append_original_version,
    create_original,
    default_archive_root,
    read_original,
    recover_complete_pending,
)
from app.application.elt.errors import EltError, public_excel_error
from app.application.elt.service_support import dump_json, load_json, new_id
from app.application.elt.service_uploads import UploadServiceMixin
from app.application.reviewed_excel_classification import observe_fragment_relationships
from app.application.reviewed_excel_classification_store import (
    _classification_run,
    _classification_version,
)
from app.application.reviewed_excel_legacy import OLE_MAGIC, prepare_archive_workbook
from app.application.reviewed_excel_template import classify_review_workbook
from app.db.models.elt import EltRun, EltUpload
from app.db.models.elt_archive import EltArchiveAsset, EltArchiveQuota, EltArchiveVersion
from app.db.session import get_db
from app.fastapi_routes.reviewed_excel_template import (
    _CLASS_READY,
    _archive_admin,
    _body,
    _expected_actor,
    _identity,
    _manage,
    _read,
    _recheck,
    _source,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.middleware.error_handler import ReviewedExcelRoute
from app.utils.operational_errors import BOUNDARY_ERRORS

router = APIRouter(route_class=ReviewedExcelRoute)


@router.get("/api/templates/reviewed-excel/archive-quota")
def archive_quota(user=Depends(_archive_admin)):
    tenant, _owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        quota = db.get(EltArchiveQuota, tenant)
        if quota is None:
            return {
                "configured": False,
                "using_default": True,
                "limit_bytes": DEFAULT_ARCHIVE_QUOTA_BYTES,
                "reserved_bytes": 0,
            }
        return {
            "configured": True,
            "using_default": False,
            "limit_bytes": quota.limit_bytes,
            "reserved_bytes": quota.reserved_bytes,
        }


@router.post("/api/templates/reviewed-excel/archive-quota")
def set_archive_quota(
    request: Request,
    limit_bytes: int = Form(..., gt=0, le=1099511627776),
    expected_actor: str = Form(..., max_length=80),
    user=Depends(_archive_admin),
):
    _expected_actor(expected_actor, user)
    tenant, _owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        quota = db.get(EltArchiveQuota, tenant)
        if quota is None:
            quota = EltArchiveQuota(tenant_id=tenant, limit_bytes=limit_bytes, reserved_bytes=0)
            db.add(quota)
        else:
            result = db.execute(
                update(EltArchiveQuota)
                .where(
                    EltArchiveQuota.tenant_id == tenant,
                    EltArchiveQuota.reserved_bytes <= limit_bytes,
                )
                .values(limit_bytes=limit_bytes)
            )
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(status_code=409, detail="配额不能低于已预留空间")
        db.commit()
        return {"configured": True, "limit_bytes": limit_bytes}


@router.get("/api/templates/reviewed-excel/archive-assets")
def archive_assets(user=Depends(_read)):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        assets = (
            db.query(EltArchiveAsset)
            .filter_by(tenant_id=tenant, owner_user_id=owner)
            .order_by(EltArchiveAsset.created_at.desc())
            .limit(200)
            .all()
        )
        versions_by_asset = defaultdict(list)
        if assets:
            versions = (
                db.query(
                    EltArchiveVersion.asset_id,
                    EltArchiveVersion.id,
                    EltArchiveVersion.version,
                    EltArchiveVersion.status,
                    EltArchiveVersion.sha256,
                    EltArchiveVersion.size_bytes,
                    EltArchiveVersion.classification_id,
                )
                .filter(
                    EltArchiveVersion.tenant_id == tenant,
                    EltArchiveVersion.owner_user_id == owner,
                    EltArchiveVersion.asset_id.in_([asset.id for asset in assets]),
                )
                .order_by(EltArchiveVersion.version.desc())
            )
            for version in versions:
                versions_by_asset[version.asset_id].append(version)
        return {
            "assets": [
                {
                    "id": asset.id,
                    "name": asset.name,
                    "state": asset.state,
                    "retention_mode": asset.retention_mode,
                    "versions": [
                        {
                            "id": version.id,
                            "version": version.version,
                            "status": version.status,
                            "sha256": version.sha256,
                            "size_bytes": version.size_bytes,
                            "classification_id": version.classification_id,
                        }
                        for version in versions_by_asset[asset.id]
                    ],
                }
                for asset in assets
            ]
        }


@router.get("/api/templates/reviewed-excel/archive-versions/{version_id}/download")
def archive_version_download(version_id: str, user=Depends(_read)):
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            body = read_original(
                db,
                owner=owner,
                version_id=version_id,
                root=default_archive_root(),
            )
            legacy = body.startswith(OLE_MAGIC)
            return Response(
                content=body,
                media_type="application/vnd.ms-excel"
                if legacy
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="original.xls"'
                    if legacy
                    else 'attachment; filename="original.xlsx"',
                },
            )
    except ArchivePolicyError as exc:
        raise HTTPException(status_code=404, detail=public_excel_error(exc)) from None


@router.post("/api/templates/reviewed-excel/archive-assets/{asset_id}/versions")
async def archive_new_version(
    asset_id: str,
    request: Request,
    file: UploadFile = File(...),
    request_key: str = Form(..., max_length=80),
    expected_actor: str = Form(..., max_length=80),
    legacy_test_only: bool = Form(False),
    legacy_source_sha256: str = Form("", max_length=64),
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    body = await _body(file, allow_legacy=True)
    try:
        await run_in_threadpool(
            prepare_archive_workbook,
            body,
            legacy_test_only=legacy_test_only,
            legacy_source_sha256=legacy_source_sha256,
        )
        _recheck(request, (tenant, owner))
        with tenant_scope(tenant), get_db() as db:
            item = append_original_version(
                db,
                owner=owner,
                asset_id=asset_id,
                body=body,
                root=default_archive_root(),
                request_key=request_key,
            )
            return {
                "asset_id": item.asset_id,
                "version_id": item.id,
                "version": item.version,
                "sha256": item.sha256,
                "status": item.status,
            }
    except (ArchivePolicyError, ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


@router.post("/api/templates/reviewed-excel/archive-assets/{asset_id}/state")
def archive_asset_state(
    asset_id: str,
    request: Request,
    state: str = Form(..., max_length=16),
    expected_actor: str = Form(..., max_length=80),
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    if state not in {"active", "trashed"}:
        raise HTTPException(status_code=400, detail="归档状态无效")
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        # The row update serializes classification creation and trash/restore.
        changed = db.execute(
            update(EltArchiveAsset)
            .where(
                EltArchiveAsset.id == asset_id,
                EltArchiveAsset.tenant_id == tenant,
                EltArchiveAsset.owner_user_id == owner,
            )
            .values(state=EltArchiveAsset.state)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=404, detail="归档不存在")
        if (
            state == "trashed"
            and db.query(EltArchiveVersion)
            .filter(
                EltArchiveVersion.tenant_id == tenant,
                EltArchiveVersion.owner_user_id == owner,
                EltArchiveVersion.asset_id == asset_id,
                (EltArchiveVersion.classification_id.is_not(None))
                | (EltArchiveVersion.status != "ready"),
            )
            .first()
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="归档存在分类依赖或待核对版本，不能撤回")
        db.execute(
            update(EltArchiveAsset)
            .where(
                EltArchiveAsset.id == asset_id,
                EltArchiveAsset.tenant_id == tenant,
                EltArchiveAsset.owner_user_id == owner,
            )
            .values(state=state)
        )
        db.commit()
        return {"asset_id": asset_id, "state": state}


@router.post("/api/templates/reviewed-excel/archive-versions/{version_id}/recover")
def recover_archive_version(
    version_id: str, expected_actor: str = Form(..., max_length=80), user=Depends(_manage)
):
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            recover_complete_pending(
                db,
                owner=owner,
                version_id=version_id,
                root=default_archive_root(),
            )
            return {"version_id": version_id, "status": "ready"}
    except ArchivePolicyError as exc:
        raise HTTPException(status_code=409, detail=public_excel_error(exc)) from None


@router.post("/api/templates/reviewed-excel/archive-classify")
async def archive_classify(
    request: Request,
    file: UploadFile = File(...),
    request_key: str = Form(..., max_length=80),
    expected_actor: str = Form(..., max_length=80),
    legacy_test_only: bool = Form(False),
    legacy_source_sha256: str = Form("", max_length=64),
    user=Depends(_manage),
):
    """Archive one explicitly requested original before creating its classification."""
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    body = await _body(file, allow_legacy=True)
    try:
        with tenant_scope(tenant), get_db() as db:
            existing_asset = (
                db.query(EltArchiveAsset)
                .filter_by(tenant_id=tenant, owner_user_id=owner, request_key=request_key)
                .first()
            )
            if existing_asset:
                existing_version = create_original(
                    db,
                    owner=owner,
                    name=file.filename or "review.xlsx",
                    body=body,
                    root=default_archive_root(),
                    request_key=request_key,
                )
                if existing_version.classification_id:
                    _recheck(request, (tenant, owner))
                    return _existing_archive_receipt(
                        db,
                        existing_version,
                        tenant,
                        owner,
                        str(Path(existing_asset.name).with_suffix(".xlsx")),
                    )
        derived_body, review = await run_in_threadpool(
            prepare_archive_workbook,
            body,
            legacy_test_only=legacy_test_only,
            legacy_source_sha256=legacy_source_sha256,
        )
        sheets = classify_review_workbook(review)
        _recheck(request, (tenant, owner))
        with tenant_scope(tenant), get_db() as db:
            archived = create_original(
                db,
                owner=owner,
                name=file.filename or "review.xlsx",
                body=body,
                root=default_archive_root(),
                request_key=request_key,
            )
            return _create_archive_classification(
                db,
                archived,
                derived_body,
                review,
                sheets,
                str(Path(file.filename or "review.xlsx").with_suffix(".xlsx")),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                request,
                tenant,
                owner,
            )
    except (ArchivePolicyError, ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


def _archive_classification_receipt(
    archived, classification_id, latest, name, conversion=None, restrictions=None
):
    """Use the same persisted classification state for first replies and idempotent recovery."""
    return {
        "asset_id": archived.asset_id,
        "archive_version_id": archived.id,
        "sha256": (conversion or {}).get("derived_sha256", archived.sha256),
        "original_sha256": archived.sha256,
        "classification_id": classification_id,
        "version": latest["version"],
        "sheets": latest["sheets"],
        "read_only_print_areas": latest.get("read_only_print_areas", []),
        "model_status": latest["model_status"],
        "confirmed": latest["confirmed"],
        "fragment_links": latest.get("fragment_links", {"items": [], "omitted": 0}),
        "logical_documents": latest.get("logical_documents", []),
        "independent_confirmed": latest.get("independent_confirmed", False),
        "partition_pending": latest.get("partition_pending", False),
        "confirmed_document_count": latest.get("confirmed_document_count"),
        "document_count_status": latest.get("document_count_status"),
        "name": name,
        "status": "classified",
        "conversion_receipt": conversion,
        "usage_restrictions": restrictions or [],
    }


def _existing_archive_receipt(db, archived, tenant, owner, name):
    existing = _classification_run(db, archived.classification_id, tenant, owner)
    _source(db, existing, tenant, owner)
    latest = load_json(existing.draft_json, {}).get("versions", [])[-1]
    return _archive_classification_receipt(
        archived,
        existing.id,
        latest,
        name,
        load_json(existing.summary_json, {}).get("conversion_receipt"),
        load_json(existing.summary_json, {}).get("usage_restrictions", []),
    )


def _create_archive_classification(
    db,
    archived,
    body,
    review,
    sheets,
    name,
    content_type,
    request,
    tenant,
    owner,
    *,
    reclassify=False,
    expected_classification_id=None,
):
    if reclassify and (
        not expected_classification_id or archived.classification_id != expected_classification_id
    ):
        raise HTTPException(status_code=409, detail="归档分类已变更，请刷新档案后重新确认")
    if archived.classification_id and not reclassify:
        return _existing_archive_receipt(db, archived, tenant, owner, name)
    fragment_links = observe_fragment_relationships(review, sheets)
    _recheck(request, (tenant, owner))
    classification_id = new_id()
    locked = db.execute(
        update(EltArchiveAsset)
        .where(
            EltArchiveAsset.id == archived.asset_id,
            EltArchiveAsset.tenant_id == tenant,
            EltArchiveAsset.owner_user_id == owner,
            EltArchiveAsset.state == "active",
        )
        .values(state=EltArchiveAsset.state)
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="归档已撤回或不可用")
    claimed = db.execute(
        update(EltArchiveVersion)
        .where(
            EltArchiveVersion.id == archived.id,
            EltArchiveVersion.tenant_id == tenant,
            EltArchiveVersion.owner_user_id == owner,
            EltArchiveVersion.status == "ready",
            (EltArchiveVersion.classification_id == expected_classification_id)
            if reclassify
            else EltArchiveVersion.classification_id.is_(None),
        )
        .values(classification_id=classification_id)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="分类正在创建，请按原请求标识核对")
    created_paths: list[Path] = []
    commit_attempted = False
    try:
        if review.get("conversion_receipt"):
            charged = db.execute(
                update(EltArchiveQuota)
                .where(
                    EltArchiveQuota.tenant_id == tenant,
                    EltArchiveQuota.reserved_bytes + len(body) <= EltArchiveQuota.limit_bytes,
                )
                .values(reserved_bytes=EltArchiveQuota.reserved_bytes + len(body))
            )
            if charged.rowcount != 1:
                db.rollback()
                raise ArchivePolicyError("归档配额不足以保留验证后的转换副本")
        upload = UploadServiceMixin().save_upload(
            db, owner_user_id=owner, file_name=name, content_type=content_type, stream=BytesIO(body)
        )
        upload_record = db.get(EltUpload, upload["upload_id"])
        if review.get("conversion_receipt"):
            upload_record.expires_at = None
        created_paths.append(Path(upload_record.storage_path))
        os.chmod(upload_record.storage_path, 0o600)
        version = _classification_version(
            review["sha256"],
            "",
            {
                "sheets": sheets,
                "fragment_links": fragment_links,
            },
        )
        latest = {
            "version": version,
            "sheets": sheets,
            "fragment_links": fragment_links,
            "logical_documents": [],
            "independent_confirmed": False,
            "partition_pending": False,
            "confirmed_document_count": None,
            "document_count_status": "partial",
            "model_status": "not_called",
            "confirmed": False,
            "read_only_print_areas": review["read_only_print_areas"],
            "conversion_receipt": review.get("conversion_receipt"),
            "usage_restrictions": review.get("usage_restrictions", []),
        }
        db.add(
            EltRun(
                id=classification_id,
                tenant_id=tenant,
                owner_user_id=owner,
                upload_id=upload["upload_id"],
                target_type="template_classification",
                status=_CLASS_READY,
                stage=_CLASS_READY,
                file_sha256=review["sha256"],
                draft_json=dump_json({"versions": [latest]}),
                summary_json=dump_json(
                    {
                        "kind": "classification",
                        "archive_version_id": archived.id,
                        "conversion_receipt": review.get("conversion_receipt"),
                        "usage_restrictions": review.get("usage_restrictions", []),
                    }
                ),
            )
        )
        commit_attempted = True
        db.commit()
    except BOUNDARY_ERRORS:
        if not commit_attempted:
            for path in created_paths:
                path.unlink(missing_ok=True)
        raise
    return _archive_classification_receipt(
        archived,
        classification_id,
        latest,
        name,
        review.get("conversion_receipt"),
        review.get("usage_restrictions", []),
    )


@router.post("/api/templates/reviewed-excel/archive-versions/{version_id}/classify")
def classify_archive_version(
    version_id: str,
    request: Request,
    expected_actor: str = Form(..., max_length=80),
    reclassify: bool = Form(False),
    expected_classification_id: str | None = Form(None, max_length=80),
    legacy_test_only: bool = Form(False),
    legacy_source_sha256: str = Form("", max_length=64),
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            body = read_original(
                db,
                owner=owner,
                version_id=version_id,
                root=default_archive_root(),
            )
            archived = (
                db.query(EltArchiveVersion)
                .filter_by(id=version_id, tenant_id=tenant, owner_user_id=owner)
                .one()
            )
            asset = (
                db.query(EltArchiveAsset)
                .filter_by(id=archived.asset_id, tenant_id=tenant, owner_user_id=owner)
                .one()
            )
            if archived.classification_id and not reclassify:
                _recheck(request, (tenant, owner))
                return _existing_archive_receipt(
                    db, archived, tenant, owner, str(Path(asset.name).with_suffix(".xlsx"))
                )
            derived_body, review = prepare_archive_workbook(
                body, legacy_test_only=legacy_test_only, legacy_source_sha256=legacy_source_sha256
            )
            return _create_archive_classification(
                db,
                archived,
                derived_body,
                review,
                classify_review_workbook(review),
                str(Path(asset.name).with_suffix(".xlsx")),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                request,
                tenant,
                owner,
                reclassify=reclassify,
                expected_classification_id=expected_classification_id,
            )
    except (ArchivePolicyError, ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None
