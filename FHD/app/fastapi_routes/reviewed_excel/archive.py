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

from app.application.etl.archive_policy import ArchivePolicyError
from app.application.etl.archive_store import (
    append_original_version,
    create_original,
    read_original,
    recover_complete_pending,
)
from app.application.etl.errors import EtlError, public_excel_error
from app.application.etl.service_support import dump_json, load_json, new_id
from app.application.etl.service_uploads import UploadServiceMixin
from app.application.reviewed_excel_classification import observe_fragment_relationships
from app.application.reviewed_excel_classification_store import (
    _classification_run,
    _classification_version,
)
from app.application.reviewed_excel_template import classify_review_workbook, inspect_workbook
from app.db.models.etl import EtlRun, EtlUpload
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveQuota, EtlArchiveVersion
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
)
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

router = APIRouter()


@router.get("/api/templates/reviewed-excel/archive-quota")
def archive_quota(user=Depends(_archive_admin)):
    tenant, _owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        quota = db.get(EtlArchiveQuota, tenant)
        return {
            "configured": quota is not None,
            "limit_bytes": quota.limit_bytes if quota else None,
            "reserved_bytes": quota.reserved_bytes if quota else 0,
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
        quota = db.get(EtlArchiveQuota, tenant)
        if quota is None:
            quota = EtlArchiveQuota(tenant_id=tenant, limit_bytes=limit_bytes, reserved_bytes=0)
            db.add(quota)
        else:
            result = db.execute(
                update(EtlArchiveQuota)
                .where(
                    EtlArchiveQuota.tenant_id == tenant,
                    EtlArchiveQuota.reserved_bytes <= limit_bytes,
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
            db.query(EtlArchiveAsset)
            .filter_by(tenant_id=tenant, owner_user_id=owner)
            .order_by(EtlArchiveAsset.created_at.desc())
            .limit(200)
            .all()
        )
        versions_by_asset = defaultdict(list)
        if assets:
            versions = (
                db.query(
                    EtlArchiveVersion.asset_id,
                    EtlArchiveVersion.id,
                    EtlArchiveVersion.version,
                    EtlArchiveVersion.status,
                    EtlArchiveVersion.sha256,
                    EtlArchiveVersion.size_bytes,
                    EtlArchiveVersion.classification_id,
                )
                .filter(
                    EtlArchiveVersion.tenant_id == tenant,
                    EtlArchiveVersion.owner_user_id == owner,
                    EtlArchiveVersion.asset_id.in_([asset.id for asset in assets]),
                )
                .order_by(EtlArchiveVersion.version.desc())
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
                root=Path(get_app_data_dir()) / "etl" / "archive",
            )
            return Response(
                content=body,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="original.xlsx"',
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
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    body = await _body(file)
    try:
        await run_in_threadpool(inspect_workbook, body)
        _recheck(request, (tenant, owner))
        with tenant_scope(tenant), get_db() as db:
            item = append_original_version(
                db,
                owner=owner,
                asset_id=asset_id,
                body=body,
                root=Path(get_app_data_dir()) / "etl" / "archive",
                request_key=request_key,
            )
            return {
                "asset_id": item.asset_id,
                "version_id": item.id,
                "version": item.version,
                "sha256": item.sha256,
                "status": item.status,
            }
    except (ArchivePolicyError, ValueError, TypeError, EtlError) as exc:
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
            update(EtlArchiveAsset)
            .where(
                EtlArchiveAsset.id == asset_id,
                EtlArchiveAsset.tenant_id == tenant,
                EtlArchiveAsset.owner_user_id == owner,
            )
            .values(state=EtlArchiveAsset.state)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=404, detail="归档不存在")
        if (
            state == "trashed"
            and db.query(EtlArchiveVersion)
            .filter(
                EtlArchiveVersion.tenant_id == tenant,
                EtlArchiveVersion.owner_user_id == owner,
                EtlArchiveVersion.asset_id == asset_id,
                (EtlArchiveVersion.classification_id.is_not(None))
                | (EtlArchiveVersion.status != "ready"),
            )
            .first()
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="归档存在分类依赖或待核对版本，不能撤回")
        db.execute(
            update(EtlArchiveAsset)
            .where(
                EtlArchiveAsset.id == asset_id,
                EtlArchiveAsset.tenant_id == tenant,
                EtlArchiveAsset.owner_user_id == owner,
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
                root=Path(get_app_data_dir()) / "etl" / "archive",
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
    user=Depends(_manage),
):
    """Archive one explicitly requested original before creating its classification."""
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    body = await _body(file)
    try:
        review = await run_in_threadpool(inspect_workbook, body)
        sheets = classify_review_workbook(review)
        _recheck(request, (tenant, owner))
        with tenant_scope(tenant), get_db() as db:
            archived = create_original(
                db,
                owner=owner,
                name=file.filename or "review.xlsx",
                body=body,
                root=Path(get_app_data_dir()) / "etl" / "archive",
                request_key=request_key,
            )
            return _create_archive_classification(
                db,
                archived,
                body,
                review,
                sheets,
                file.filename or "review.xlsx",
                file.content_type,
                request,
                tenant,
                owner,
            )
    except (ArchivePolicyError, ValueError, TypeError, EtlError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


def _archive_classification_receipt(archived, classification_id, latest, name):
    """Use the same persisted classification state for first replies and idempotent recovery."""
    return {
        "asset_id": archived.asset_id,
        "archive_version_id": archived.id,
        "sha256": archived.sha256,
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
    }


def _create_archive_classification(
    db, archived, body, review, sheets, name, content_type, request, tenant, owner
):
    if archived.classification_id:
        existing = _classification_run(db, archived.classification_id, tenant, owner)
        latest = load_json(existing.draft_json, {}).get("versions", [])[-1]
        return _archive_classification_receipt(archived, existing.id, latest, name)
    fragment_links = observe_fragment_relationships(review, sheets)
    _recheck(request, (tenant, owner))
    classification_id = new_id()
    locked = db.execute(
        update(EtlArchiveAsset)
        .where(
            EtlArchiveAsset.id == archived.asset_id,
            EtlArchiveAsset.tenant_id == tenant,
            EtlArchiveAsset.owner_user_id == owner,
            EtlArchiveAsset.state == "active",
        )
        .values(state=EtlArchiveAsset.state)
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="归档已撤回或不可用")
    claimed = db.execute(
        update(EtlArchiveVersion)
        .where(
            EtlArchiveVersion.id == archived.id,
            EtlArchiveVersion.tenant_id == tenant,
            EtlArchiveVersion.owner_user_id == owner,
            EtlArchiveVersion.status == "ready",
            EtlArchiveVersion.classification_id.is_(None),
        )
        .values(classification_id=classification_id)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="分类正在创建，请按原请求标识核对")
    created_paths: list[Path] = []
    commit_attempted = False
    try:
        upload = UploadServiceMixin().save_upload(
            db, owner_user_id=owner, file_name=name, content_type=content_type, stream=BytesIO(body)
        )
        upload_record = db.get(EtlUpload, upload["upload_id"])
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
        }
        db.add(
            EtlRun(
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
                    {"kind": "classification", "archive_version_id": archived.id}
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
    return _archive_classification_receipt(archived, classification_id, latest, name)


@router.post("/api/templates/reviewed-excel/archive-versions/{version_id}/classify")
def classify_archive_version(
    version_id: str,
    request: Request,
    expected_actor: str = Form(..., max_length=80),
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
                root=Path(get_app_data_dir()) / "etl" / "archive",
            )
            archived = (
                db.query(EtlArchiveVersion)
                .filter_by(id=version_id, tenant_id=tenant, owner_user_id=owner)
                .one()
            )
            asset = (
                db.query(EtlArchiveAsset)
                .filter_by(id=archived.asset_id, tenant_id=tenant, owner_user_id=owner)
                .one()
            )
            review = inspect_workbook(body)
            return _create_archive_classification(
                db,
                archived,
                body,
                review,
                classify_review_workbook(review),
                asset.name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                request,
                tenant,
                owner,
            )
    except (ArchivePolicyError, ValueError, TypeError, EtlError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None
