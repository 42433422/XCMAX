"""Owner-scoped workbook review persistence, immutable sources and revision claims."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.application.elt.archive_policy import ArchivePolicyError
from app.application.elt.archive_store import default_archive_root, read_original
from app.application.elt.errors import ReviewedExcelError, public_excel_error
from app.application.elt.service_support import dump_json, load_json, utcnow
from app.application.elt_login_authorization import require_login_notice_grant
from app.application.reviewed_excel_audit import ModelRequestNotSent
from app.application.reviewed_excel_classification_store import (
    _CLASS_READY,
    _classification_cas,
    _classification_run,
)
from app.application.reviewed_excel_template import (
    MAX_BYTES,
    derive_document_workbook,
    inspect_workbook,
)
from app.db.models.elt import EltRun, EltUpload
from app.utils.path_io.path_utils import get_app_data_dir

_READY = "template_review_ready"
_SAVING = "template_review_saving"
_SAVED = "template_review_saved"
_CLASS_SAVING = "classification_template_saving"
_MODEL_PENDING = "template_review_model_pending"


def _model_processing_failure(exc: Exception) -> HTTPException:
    not_sent = isinstance(exc, ModelRequestNotSent)
    return HTTPException(
        status_code=503,
        detail={
            "code": "model_configuration_error" if not_sent else "model_processing_failed",
            "message": ("模型连接异常，未调用模型。" if not_sent else "模型处理未完成。")
            + public_excel_error(exc),
            "retryable": not_sent,
            "outcome_unknown": not not_sent,
        },
    )


def _run(db, review_id, tenant, owner):
    run = (
        db.query(EltRun)
        .filter(
            EltRun.id == review_id,
            EltRun.tenant_id == tenant,
            EltRun.owner_user_id == owner,
            EltRun.target_type == "template_review",
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="审阅记录不存在")
    return run


def _source(db, run, tenant, owner):
    summary = load_json(run.summary_json, {})
    archive_version_id = summary.get("archive_version_id")
    conversion = summary.get("conversion_receipt")
    if archive_version_id:
        try:
            content = read_original(
                db,
                owner=owner,
                version_id=archive_version_id,
                root=default_archive_root(),
            )
        except ArchivePolicyError as exc:
            raise HTTPException(status_code=409, detail=public_excel_error(exc)) from None
        source_sha = conversion.get("source_sha256") if conversion else run.file_sha256
        if hashlib.sha256(content).hexdigest() != source_sha:
            raise HTTPException(status_code=409, detail="归档来源版本已改变")
        if not conversion:
            return content
        if conversion.get("derived_sha256") != run.file_sha256:
            raise HTTPException(status_code=409, detail="转换副本与归档收据不一致")
    upload = (
        db.query(EltUpload)
        .filter(
            EltUpload.id == run.upload_id,
            EltUpload.tenant_id == tenant,
            EltUpload.owner_user_id == owner,
        )
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="来源不存在")
    from datetime import UTC

    expires = upload.expires_at
    if expires and (expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires) < utcnow():
        rebuilt = _rebuild_archived_document(db, run, tenant, owner)
        if rebuilt is not None:
            return rebuilt
        raise HTTPException(status_code=410, detail="来源已过期，请重新上传")
    root = (
        Path(get_app_data_dir()).resolve() / "etl" / "uploads" / str(tenant) / str(owner)
    ).resolve()
    raw = Path(upload.storage_path or "")
    path = raw.resolve()
    if raw.is_symlink() or root not in path.parents or not path.is_file():
        rebuilt = _rebuild_archived_document(db, run, tenant, owner)
        if rebuilt is not None:
            return rebuilt
        raise HTTPException(status_code=410, detail="来源已删除或不可用")
    if path.stat().st_size > MAX_BYTES:
        raise HTTPException(status_code=413, detail="来源超过大小限制")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != run.file_sha256 or upload.sha256 != run.file_sha256:
        raise HTTPException(status_code=409, detail="来源已改变，请重新上传")
    return content


def _rebuild_archived_document(db, run, tenant, owner):
    scope = load_json(run.summary_json, {}).get("selected_region") or {}
    if not scope.get("archive_version_id") or not scope.get("derived_sha256"):
        return None
    _review_source_version(db, run, tenant, owner)
    try:
        original = read_original(
            db,
            owner=owner,
            version_id=scope["archive_version_id"],
            root=default_archive_root(),
        )
        classification = _classification_run(db, scope["classification_id"], tenant, owner)
        if load_json(classification.summary_json, {}).get("conversion_receipt"):
            original = _source(db, classification, tenant, owner)
        derived = derive_document_workbook(
            original, scope["fragments"], print_area_mode=scope["print_area_mode"]
        )
    except (ArchivePolicyError, ValueError, KeyError):
        raise HTTPException(
            status_code=409, detail="归档派生副本无法保真重建，请重新预览"
        ) from None
    if hashlib.sha256(derived).hexdigest() != run.file_sha256:
        raise HTTPException(status_code=409, detail="重建结果与原预览不一致，请重新预览")
    return derived


def _usage_restrictions(db, run, tenant, owner):
    """Server-side immutable source lineage, not just removable workbook metadata."""
    summary = load_json(run.summary_json, {})
    restrictions = list(summary.get("usage_restrictions", []))
    conversion = summary.get("conversion_receipt") or {}
    if conversion.get("purpose") == "data_template_test_only":
        restrictions.append("仅供数据/模板测试；打印版式未验证，不得发布到企业模板库")
    scope = summary.get("selected_region") or {}
    if scope.get("classification_id"):
        classification = _classification_run(db, scope["classification_id"], tenant, owner)
        restrictions.extend(_usage_restrictions(db, classification, tenant, owner))
    return list(dict.fromkeys(restrictions))


def _review_source_version(db, run, tenant, owner):
    """Fail closed when a derived document's original classification has changed."""
    scope = load_json(run.summary_json, {}).get("selected_region") or {}
    if not scope.get("derived_sha256"):
        return
    classification = _classification_run(db, scope["classification_id"], tenant, owner)
    _source(db, classification, tenant, owner)
    versions = load_json(classification.draft_json, {}).get("versions", [])
    latest = versions[-1] if versions else {}
    if (
        classification.file_sha256 != scope["source_sha256"]
        or latest.get("version") != scope["version"]
        or (
            latest.get("model_status") != "returned"
            if scope.get("selection_basis") == "model_group"
            else not latest.get("confirmed")
        )
        or run.file_sha256 != scope["derived_sha256"]
    ):
        raise HTTPException(status_code=409, detail="文档分类或原件已变化，请重新生成候选")


def _lock_review_classification(db, run, tenant, owner):
    """Serialize classification changes with a derived-template library write."""
    scope = load_json(run.summary_json, {}).get("selected_region") or {}
    if not scope.get("derived_sha256"):
        return None
    classification = _classification_run(db, scope["classification_id"], tenant, owner)
    versions = load_json(classification.draft_json, {}).get("versions", [])
    if not versions or versions[-1].get("version") != scope["version"]:
        raise HTTPException(status_code=409, detail="文档分类已变化，请重新生成候选")
    locked = db.execute(
        update(EltRun)
        .where(
            EltRun.id == classification.id,
            EltRun.tenant_id == tenant,
            EltRun.owner_user_id == owner,
            EltRun.status == _CLASS_READY,
            EltRun.draft_json == classification.draft_json,
        )
        .values(status=_CLASS_SAVING)
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="文档分类正在保存或已改变，请核对")
    return classification.id


def _unlock_review_classification(db, classification_id, tenant, owner):
    if classification_id is None:
        return
    released = db.execute(
        update(EltRun)
        .where(
            EltRun.id == classification_id,
            EltRun.tenant_id == tenant,
            EltRun.owner_user_id == owner,
            EltRun.status == _CLASS_SAVING,
        )
        .values(status=_CLASS_READY)
    )
    if released.rowcount != 1:
        raise HTTPException(status_code=409, detail="分类写入锁状态异常，请人工核对")


def _release_failed_review(
    db, review_id, tenant, owner, saving_draft, old_draft, classification_lock
):
    """Release only this review's lock when the library was not called."""
    released = db.execute(
        update(EltRun)
        .where(
            EltRun.id == review_id,
            EltRun.tenant_id == tenant,
            EltRun.owner_user_id == owner,
            EltRun.status == _SAVING,
            EltRun.draft_json == saving_draft,
        )
        .values(status=_READY, stage=_READY, draft_json=old_draft)
    )
    if released.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="审阅锁状态已改变，请人工核对")
    _unlock_review_classification(db, classification_lock, tenant, owner)
    db.commit()


def _proposals(run):
    state = load_json(run.draft_json, {})
    versions = state.get("versions")
    if not isinstance(versions, list) or not versions:
        raise HTTPException(status_code=409, detail="审阅状态无效")
    return state, versions


def _cas(db, run, old_draft, *, expected_status=_READY, **values):
    result = db.execute(
        update(EltRun)
        .where(
            EltRun.id == run.id,
            EltRun.tenant_id == run.tenant_id,
            EltRun.owner_user_id == run.owner_user_id,
            EltRun.status == expected_status,
            EltRun.draft_json == old_draft,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="审阅版本已改变，请刷新")
    db.commit()


def _update_candidate_claim(db, classification_id, key, tenant, owner, review_id=""):
    run = _classification_run(db, classification_id, tenant, owner)
    old = run.draft_json
    state = load_json(old, {})
    claims = state.get("template_candidate_requests", {})
    if claims.get(key, {}).get("state") != "inflight":
        raise HTTPException(status_code=409, detail="模型候选请求状态已改变，请核对")
    if review_id:
        claims[key] = {"state": "completed", "review_id": review_id}
    else:
        claims.pop(key)
    _classification_cas(db, run, old, state)


def _stored_candidate_response(db, review_id, tenant, owner):
    run = _run(db, review_id, tenant, owner)
    _review_source_version(db, run, tenant, owner)
    _, versions = _proposals(run)
    if run.status == _MODEL_PENDING or versions[-1]["model"].get("status") != "returned":
        error = _model_processing_failure(
            ReviewedExcelError("候选存在未完成的模型请求，请先核对状态")
        )
        error.status_code = 409
        raise error
    return {
        "success": True,
        **inspect_workbook(_source(db, run, tenant, owner)),
        "review_id": run.id,
        "proposal": versions[-1],
        "versions": versions,
        "selected_region": load_json(run.summary_json, {}).get("selected_region"),
    }


def _refinement_response(run, proposal, *, replayed=False):
    parent = load_json(run.summary_json, {}).get("revision_parent", {})
    return {
        "success": True,
        "review_id": run.id,
        "proposal": proposal,
        **(
            {"parent_review_id": parent["review_id"], "parent_version": parent["proposal_version"]}
            if parent
            else {}
        ),
        **({"replayed": True} if replayed else {}),
    }


def _fork_saved_review(db, parent, proposal, feedback, current_cells, grant, tenant, owner):
    summary = load_json(parent.summary_json, {})
    request_digest = hashlib.sha256(
        dump_json(
            {
                "tenant": tenant,
                "owner": owner,
                "parent": parent.id,
                "version": proposal["version"],
                "source": parent.file_sha256,
                "scope": summary.get("selected_region"),
                "feedback": feedback,
                "current": sorted(current_cells, key=lambda item: (item["sheet"], item["cell"])),
                "publication": grant["publication"],
                "route": grant["route"],
            }
        ).encode()
    ).hexdigest()
    child_id = str(uuid5(NAMESPACE_URL, f"xcmax-review-refinement:{request_digest}"))
    child = db.get(EltRun, child_id)
    if child is None:
        summary["revision_parent"] = {
            "review_id": parent.id,
            "proposal_version": proposal["version"],
            "template_id": load_json(parent.receipt_json, {}).get("template_id"),
        }
        child = EltRun(
            id=child_id,
            tenant_id=tenant,
            owner_user_id=owner,
            upload_id=parent.upload_id,
            target_type="template_review",
            status=_READY,
            stage=_READY,
            file_sha256=parent.file_sha256,
            draft_json=dump_json({"versions": [proposal]}),
            summary_json=dump_json(summary),
        )
        db.add(child)
        try:
            db.commit()
        except IntegrityError:
            # The deterministic primary key elects one canonical draft across concurrent retries.
            db.rollback()
            child = _run(db, child_id, tenant, owner)
    if (
        child.tenant_id != tenant
        or child.owner_user_id != owner
        or child.target_type != "template_review"
    ):
        raise HTTPException(status_code=409, detail="模板修订身份不一致，未调用模型")
    return child


def _intake_selection_key(run, proposal_version, candidate_id, selected, name, note):
    return hashlib.sha256(
        dump_json(
            {
                "review_id": run.id,
                "source_sha256": run.file_sha256,
                "version": proposal_version,
                "candidate": candidate_id,
                "selections": selected,
                "name": name.strip(),
                "note": note.strip(),
            }
        ).encode()
    ).hexdigest()


def _require_private_model(request, proposal, tenant, owner):
    grant = require_login_notice_grant(request, tenant, owner)
    model = proposal.get("model", {})
    authorization = model.get("authorization", {})
    if (
        model.get("status") != "returned"
        or authorization.get("notice_publication") != grant["publication"]
        or authorization.get("model_route")
        != {key: value for key, value in grant["route"].items() if key != "base"}
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_required",
                "message": "数据对接须先完成当前已授权平台模型处理，未写入任何数据；请重新开始处理。",
                "retryable": False,
            },
        )
