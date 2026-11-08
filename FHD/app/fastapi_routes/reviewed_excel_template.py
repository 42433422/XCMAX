"""Tenant- and owner-scoped workbook reviews backed by existing ETL records."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import update
from starlette.concurrency import run_in_threadpool

from app.application.elt.errors import (
    EltError,
    ModelAnswerRejected,
    ReviewedExcelError,
    model_call_outcome,
    public_excel_error,
)
from app.application.elt.service_support import dump_json, load_json, new_id, utcnow
from app.application.elt.service_uploads import UploadServiceMixin, discard_stored_upload
from app.application.elt_login_authorization import (
    bind_model_session,
    model_session_identity,
    require_model_session,
    template_model_authorization,
)
from app.application.reviewed_excel_classification import (
    _classify_semantic_batch,
    apply_classification_corrections,
    combine_semantic_batches,
    observe_fragment_relationships,
    plan_semantic_batches,
)
from app.application.reviewed_excel_classification_store import (
    _CLASS_READY,
    _classification_cas,
    _classification_run,
    _classification_version,
)
from app.application.reviewed_excel_evidence import (
    bounded_range,
    unresolved_fragments,
)
from app.application.reviewed_excel_review_projection import build_candidate_previews
from app.application.reviewed_excel_review_store import (
    _CLASS_SAVING,
    _MODEL_PENDING,
    _READY,
    _SAVED,
    _SAVING,
    _archived_original,
    _cas,
    _fork_saved_review,
    _intake_selection_key,
    _lock_review_classification,
    _model_processing_failure,
    _proposals,
    _refinement_response,
    _release_failed_review,
    _require_private_model,
    _review_source_version,
    _run,
    _source,
    _stored_candidate_response,
    _unlock_review_classification,
    _update_candidate_claim,
    _usage_restrictions,
)
from app.application.reviewed_excel_review_store import (
    _rebuild_archived_document as _rebuild_archived_document,
)
from app.application.reviewed_excel_template import (
    MAX_BYTES,
    classify_review_workbook,
    clean_workbook,
    derive_document_workbook,
    inspect_workbook,
    make_proposals,
    refine_proposal,
)
from app.db.models.elt import EltRun, EltUpload
from app.db.session import get_db
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.tenant_scope import tenant_scope
from app.middleware.error_handler import ReviewedExcelRoute, _reviewed_excel_context
from app.utils.operational_errors import BOUNDARY_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)


def _draft_with_structural_index(draft: dict, body: bytes) -> dict:
    """Persist a compact workbook structural index on classification draft_json."""
    try:
        from app.application.reviewed_excel_structural_index import (
            attach_structural_index_to_draft,
            build_workbook_structural_index,
        )

        return attach_structural_index_to_draft(draft, build_workbook_structural_index(body))
    except (
        EltError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        BadZipFile,
        InvalidFileException,
        ParseError,
    ):
        return draft


router = APIRouter(route_class=ReviewedExcelRoute)
_manage = require_permission("etl.template.manage")
_execute = require_permission("etl.execute")
_read = require_permission("etl.read")
_archive_admin = require_permission("admin.manage_users")


def _docking_channel():
    from app.application.ai_feature_isolation import BUSINESS_DOCKING, ai_feature_channel

    return ai_feature_channel(BUSINESS_DOCKING)


def _identity(user):

    if getattr(user, "tenant_id", None) is None or getattr(user, "id", None) is None:
        raise HTTPException(status_code=403, detail="需要登录并具有租户上下文")
    return int(user.tenant_id), int(user.id)


@router.get("/api/templates/reviewed-excel/identity")
def reviewed_excel_identity(request: Request, user=Depends(_manage)):
    tenant, owner = _identity(user)
    return model_session_identity(request, tenant, owner)


def _expected_actor(expected: str, user):
    tenant, owner = _identity(user)
    if expected != f"{tenant}:{owner}":
        raise HTTPException(status_code=409, detail="登录用户或租户已改变，请重新选择文件")


def _recheck(request, expected):
    if _identity(_manage(request)) != expected:
        raise HTTPException(status_code=403, detail="权限或用户身份已改变")


def _build_candidate_previews(body, review, proposal):
    """Keep established route patch points while delegating the pure projection."""
    build_candidate_previews(
        body,
        review,
        proposal,
        clean_workbook=clean_workbook,
        inspect_workbook=inspect_workbook,
    )


async def _body(file, *, allow_legacy=False):
    # archive-classify uses allow_legacy=True so docking can take XLS and statement Word.
    extensions = (".xlsx", ".xls", ".docx") if allow_legacy else (".xlsx",)
    if not (file.filename or "").lower().endswith(extensions):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx；其他格式暂不能保证保真")
    body = await file.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20 MB")
    return body


@router.post("/api/templates/reviewed-excel/classify")
async def reviewed_excel_classify(
    request: Request,
    files: list[UploadFile] = File(...),
    expected_actor: str = Form(..., max_length=80),
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    identity = _identity(user)
    if not files or len(files) > 200:
        raise HTTPException(status_code=400, detail="请选择 1 至 200 个文件；更多文件请分批上传")
    results = []
    prepared = []
    total = 0
    for file in files:
        try:
            body = await _body(file)
            total += len(body)
            if total > 50 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="本批文件超过 50 MB")
            review = await run_in_threadpool(inspect_workbook, body)
            result = {
                "name": file.filename,
                "sha256": review["sha256"],
                "status": "classified",
                "sheets": classify_review_workbook(review),
                "model_status": "not_called",
                "read_only_print_areas": review["read_only_print_areas"],
                "usage_restrictions": list(review.get("usage_restrictions", [])),
            }
            result["fragment_links"] = observe_fragment_relationships(review, result["sheets"])
            results.append(result)
            prepared.append((file, body, result))
        except HTTPException as exc:
            if exc.status_code == 413 and total > 50 * 1024 * 1024:
                raise
            results.append(
                {
                    "name": file.filename,
                    "status": "unsupported",
                    "message": str(exc.detail),
                    "sheets": [],
                }
            )
        except (ValueError, TypeError) as exc:
            results.append(
                {
                    "name": file.filename,
                    "status": "unsupported",
                    "message": public_excel_error(exc),
                    "sheets": [],
                }
            )
    _recheck(request, identity)
    tenant, owner = identity
    from app.utils.operational_errors import BOUNDARY_ERRORS

    created_paths = []
    commit_attempted = False
    try:
        with tenant_scope(tenant), get_db() as db:
            for file, body, result in prepared:
                upload = UploadServiceMixin().save_upload(
                    db,
                    owner_user_id=owner,
                    file_name=file.filename or "review.xlsx",
                    content_type=file.content_type,
                    stream=BytesIO(body),
                )
                record = db.get(EltUpload, upload["upload_id"])
                created_paths.append(Path(record.storage_path))
                version = _classification_version(
                    result["sha256"],
                    "",
                    {
                        "sheets": result["sheets"],
                        "fragment_links": result["fragment_links"],
                    },
                )
                result.update(
                    {"classification_id": new_id(), "version": version, "confirmed": False}
                )
                db.add(
                    EltRun(
                        id=result["classification_id"],
                        tenant_id=tenant,
                        owner_user_id=owner,
                        upload_id=upload["upload_id"],
                        target_type="template_classification",
                        status=_CLASS_READY,
                        stage=_CLASS_READY,
                        file_sha256=result["sha256"],
                        draft_json=dump_json(
                            _draft_with_structural_index(
                                {
                                    "versions": [
                                        {
                                            "version": version,
                                            "sheets": result["sheets"],
                                            "fragment_links": result["fragment_links"],
                                            "model_status": "not_called",
                                            "confirmed": False,
                                            "read_only_print_areas": result[
                                                "read_only_print_areas"
                                            ],
                                            "usage_restrictions": result["usage_restrictions"],
                                        }
                                    ]
                                },
                                body,
                            )
                        ),
                        summary_json=dump_json(
                            {
                                "kind": "classification",
                                "usage_restrictions": result["usage_restrictions"],
                            }
                        ),
                    )
                )
            commit_attempted = True
            db.commit()
    except BOUNDARY_ERRORS:
        if not commit_attempted:
            for path in created_paths:
                discard_stored_upload(path)
        raise
    return {"files": results, "scope": "仅检查工作表非空单元格和公式表达式；不表示语义完整理解"}


def _checkpoint_view(checkpoint):
    if not checkpoint:
        return None
    phase = checkpoint["phase"]
    message = {
        "inflight": "请求处理中或结果未知；市场确认前不会重发",
        "failed": "模型答案多轮未通过校验，已停止；保留已完成批次，需人工核对",
        "paused": "本轮预算已用完；确认后可继续剩余批次",
        "ready": "上一轮答案未通过校验，下一次请求请模型按原因修正"
        if checkpoint.get("repair")
        else "可继续剩余批次",
    }[phase]
    return {
        "phase": phase,
        "version": checkpoint["version"],
        "completed": len(checkpoint["results"]),
        "total": checkpoint["total"],
        "remaining": checkpoint["total"] - len(checkpoint["results"]),
        "max_calls": checkpoint["max_calls"],
        "calls_in_round": checkpoint.get("calls_in_round", 0),
        "remaining_in_round": max(0, checkpoint["max_calls"] - checkpoint.get("calls_in_round", 0)),
        "message": message,
    }


@router.get("/api/templates/reviewed-excel/classifications")
def reviewed_excel_recent_classifications(user=Depends(_read)):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        runs = (
            db.query(EltRun)
            .filter(
                EltRun.tenant_id == tenant,
                EltRun.owner_user_id == owner,
                EltRun.target_type == "template_classification",
            )
            .order_by(EltRun.created_at.desc())
            .limit(200)
            .all()
        )
        result = []
        for run in runs:
            upload = db.get(EltUpload, run.upload_id)
            state = load_json(run.draft_json, {})
            versions = state.get("versions", [])
            result.append(
                {
                    "classification_id": run.id,
                    "name": upload.file_name if upload else "",
                    "sha256": run.file_sha256,
                    "latest": versions[-1] if versions else None,
                    "archive_version_id": load_json(run.summary_json, {}).get("archive_version_id"),
                    "conversion_receipt": load_json(run.summary_json, {}).get("conversion_receipt"),
                    "usage_restrictions": _usage_restrictions(db, run, tenant, owner),
                    "template_write_state": "locked"
                    if run.status == _CLASS_SAVING
                    else "available",
                    "checkpoint": _checkpoint_view(state.get("analysis_checkpoint")),
                }
            )
        return {"files": result}


@router.get("/api/templates/reviewed-excel/classifications/{classification_id}/source")
def archived_classification_source(classification_id: str, user=Depends(_read)):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        run = _classification_run(db, classification_id, tenant, owner)
        if not load_json(run.summary_json, {}).get("archive_version_id"):
            raise HTTPException(status_code=404, detail="旧分类没有归档来源")
        return Response(
            content=_source(db, run, tenant, owner),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Cache-Control": "no-store"},
        )


@router.get("/api/templates/reviewed-excel/classifications/{classification_id}")
def reviewed_excel_classification_history(classification_id: str, user=Depends(_read)):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        run = _classification_run(db, classification_id, tenant, owner)
        state = load_json(run.draft_json, {})
        return {
            "classification_id": run.id,
            "sha256": run.file_sha256,
            "usage_restrictions": _usage_restrictions(db, run, tenant, owner),
            "conversion_receipt": load_json(run.summary_json, {}).get("conversion_receipt"),
            "template_write_state": "locked" if run.status == _CLASS_SAVING else "available",
            "versions": state.get("versions", []),
            "checkpoint": _checkpoint_view(state.get("analysis_checkpoint")),
            "unsettled_candidate_requests": [
                {
                    "candidate_key": key,
                    "state": claim.get("state"),
                    "attempts": claim.get("attempts", 1),
                }
                for key, claim in (state.get("template_candidate_requests") or {}).items()
                if claim.get("state") != "completed"
            ],
        }


def _model_allows_unassigned_slice(latest: dict) -> bool:
    """Only an explicit model decision lets covered documents slice while cells remain outside."""
    summaries = latest.get("input_summaries") or []
    if not isinstance(summaries, list):
        return False
    allowed = False
    for item in summaries:
        if not isinstance(item, dict):
            continue
        decision = (item.get("source_coverage") or {}).get("can_slice")
        if decision is None:
            continue
        if decision is not True:
            return False
        allowed = True
    return allowed


def _auto_slices(db, classification_id, version, tenant, owner, with_rows=False):
    from app.application.reviewed_excel_auto_slice import derive_classified_documents

    run = _classification_run(db, classification_id, tenant, owner)
    versions = load_json(run.draft_json, {}).get("versions", [])
    latest = versions[-1] if versions else {}
    if latest.get("version") != version:
        raise HTTPException(status_code=409, detail="分类版本已改变或模型尚未完成")
    body = _source(db, run, tenant, owner)
    if latest.get("model_status") == "not_called":
        from app.application.reviewed_excel_auto_slice import (
            derive_rule_slices,
            rule_row_dispositions,
        )

        slices = derive_rule_slices(body, latest)
        dispositions = rule_row_dispositions(body, latest, slices) if with_rows else []
        return slices, latest.get("coverage") or [], dispositions
    if latest.get("model_status") != "returned":
        raise HTTPException(status_code=409, detail="分类版本已改变或模型尚未完成")
    coverage = latest.get("coverage")
    sheets = latest.get("sheets", [])
    source_names = (
        [sheet.get("sheet") for sheet in sheets if isinstance(sheet, dict)]
        if isinstance(sheets, list)
        else []
    )
    coverage_names = (
        [item.get("sheet") for item in coverage if isinstance(item, dict)]
        if isinstance(coverage, list)
        else []
    )
    if (
        not source_names
        or len(source_names) != len(sheets)
        or len(set(source_names)) != len(source_names)
        or len(coverage_names) != len(source_names)
        or set(coverage_names) != set(source_names)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("total"), int)
            or not isinstance(item.get("sent"), int)
            or item["total"] < 0
            or item["sent"] != item["total"]
            or item.get("unread")
            or (item.get("unassigned") and not _model_allows_unassigned_slice(latest))
            or item.get("merged_omitted")
            or item.get("value_truncated")
            or item.get("deferred_large_values")
            or item.get("deferred_oversized_rows")
            for item in coverage
        )
    ):
        raise ReviewedExcelError("模型尚未完整覆盖原件，不能生成自动切片")
    regions = [
        {**region, "sheet": sheet["sheet"]}
        for sheet in latest.get("sheets", [])
        for region in sheet.get("regions", [])
        if region.get("range_source") == "model"
    ]
    slices = derive_classified_documents(
        body,
        {
            "source_sha256": run.file_sha256,
            "model_status": latest["model_status"],
            "regions": regions,
            "suggested_documents": latest.get("suggested_documents", []),
            "coverage": latest.get("coverage", []),
        },
        owner_id=owner,
    )
    from app.application.reviewed_excel_sheet_names import annotate_slice_titles

    annotate_slice_titles(slices, latest.get("sheets") or [])
    return slices, latest.get("coverage", []), []


@router.get(
    "/api/templates/reviewed-excel/classifications/{classification_id}/auto-slices/{version}"
)
def reviewed_excel_auto_slices(classification_id: str, version: str, user=Depends(_read)):
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            slices, coverage, rows = _auto_slices(
                db, classification_id, version, tenant, owner, with_rows=True
            )
        return {
            "classification_id": classification_id,
            "version": version,
            "coverage": coverage,
            "row_dispositions": rows,
            "slices": [
                {
                    **{key: value for key, value in item.items() if key != "workbook"},
                    "index": index,
                    "display_name": item.get("display_name") or Path(item["filename"]).stem,
                    "type_label": item.get("type_label") or "",
                    "sha256": hashlib.sha256(item["workbook"]).hexdigest(),
                }
                for index, item in enumerate(slices)
            ],
        }
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


@router.get(
    "/api/templates/reviewed-excel/classifications/{classification_id}/auto-slices/{version}/{index}"
)
def reviewed_excel_auto_slice_download(
    classification_id: str, version: str, index: int, user=Depends(_read)
):
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            slices, _coverage, _rows = _auto_slices(db, classification_id, version, tenant, owner)
        if index < 0 or index >= len(slices):
            raise HTTPException(status_code=404, detail="切片不存在")
        return Response(
            slices[index]["workbook"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(slices[index]['filename'])}"
            },
        )
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/confirm")
def reviewed_excel_classification_confirm(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    labels_json: str = Form(..., max_length=200_000),
    links_json: str = Form("[]", max_length=100_000),
    independent_confirmed: bool = Form(False),
    user=Depends(_manage),
):
    tenant, owner = _identity(user)
    try:
        labels = json.loads(labels_json)
        selected_links = json.loads(links_json)
        if not isinstance(labels, list):
            raise ReviewedExcelError("分类修正无效")
        with tenant_scope(tenant), get_db() as db:
            run = _classification_run(db, classification_id, tenant, owner)
            review = inspect_workbook(_source(db, run, tenant, owner))
            old = run.draft_json
            state = load_json(old, {})
            versions = state.get("versions", [])
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            latest = json.loads(json.dumps(versions[-1], ensure_ascii=False))
            # Keep historical versions intact, but never copy legacy prompt bodies into a new version.
            latest.pop("input_messages", None)
            latest = apply_classification_corrections(review, latest, labels)
            before = [
                [(region["range"], region["labels"]) for region in sheet["regions"]]
                for sheet in versions[-1]["sheets"]
            ]
            after = [
                [(region["range"], region["labels"]) for region in sheet["regions"]]
                for sheet in latest["sheets"]
            ]
            partition_pending = latest["partition_pending"] or (
                versions[-1].get("partition_pending", False) and before != after
            )
            latest["partition_pending"] = partition_pending
            if before != after:
                latest["fragment_links"] = {"items": [], "omitted": 0}
                latest["suggested_documents"] = []
                latest["suggested_document_count"] = None
            if partition_pending:
                # New slices never inherit an approval or relationships from their old geometry.
                latest["fragment_links"] = observe_fragment_relationships(review, latest["sheets"])
            from app.application.reviewed_excel_classification_store import (
                _confirmed_document_count,
                _confirmed_documents,
            )

            latest["logical_documents"] = _confirmed_documents(
                run.file_sha256,
                version,
                latest["sheets"],
                latest.get("fragment_links", {}),
                [] if partition_pending else selected_links,
                review["cells"],
            )
            latest["confirmed_document_count"] = _confirmed_document_count(
                review,
                latest,
                latest["logical_documents"],
                independent_confirmed and not partition_pending,
            )
            latest["document_count_status"] = (
                "confirmed" if latest["confirmed_document_count"] is not None else "partial"
            )
            latest["independent_confirmed"] = independent_confirmed and not partition_pending
            selected_set = {
                (edge["sheet"], edge["first"], edge["second"])
                for edge in ([] if partition_pending else selected_links)
            }
            for link in latest.get("fragment_links", {}).get("items", []):
                link["selected"] = (link["sheet"], link["first"], link["second"]) in selected_set
            latest.update({"parent_version": version, "confirmed": not partition_pending})
            latest["version"] = _classification_version(
                run.file_sha256,
                version,
                {
                    "sheets": latest["sheets"],
                    "logical_documents": latest["logical_documents"],
                    "confirmed_document_count": latest["confirmed_document_count"],
                    "independent_confirmed": latest["independent_confirmed"],
                    "confirmed": latest["confirmed"],
                },
            )
            versions.append(latest)
            if len(versions) > 50:
                raise ReviewedExcelError("分类版本已达上限")
            _recheck(request, (tenant, owner))
            _classification_cas(db, run, old, state)
        return {
            "classification_id": classification_id,
            "version": latest["version"],
            "confirmed": latest["confirmed"],
            "partition_pending": partition_pending,
            "message": "拆分已保存，核对新片段与续表关系后再次确认" if partition_pending else "",
            "sheets": latest["sheets"],
            "coverage": latest.get("coverage", []),
            "fragment_links": latest.get("fragment_links", {"items": [], "omitted": 0}),
            "logical_documents": latest["logical_documents"],
            "confirmed_document_count": latest["confirmed_document_count"],
            "document_count_status": latest["document_count_status"],
        }
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


def _call_with_response_audit(function, callback, *args, call_id=None, **kwargs):
    from app.application.reviewed_excel_audit import capture_response

    with capture_response(callback, call_id=call_id) as answer:
        try:
            return function(*args, **kwargs)
        except ReviewedExcelError as exc:
            if not getattr(exc, "answer", ""):
                exc.answer = answer.get("text", "")
            raise


def _response_audit_writer(state, claimed_draft, classification_id, tenant, owner, request_sha):
    """Commit the provider body before parsing; failed CAS keeps the call inflight."""
    from app.application.reviewed_excel_audit import record_response

    holder = [claimed_draft]

    def save(body, status, request_id):
        with tenant_scope(tenant), get_db() as audit_db:
            audit_run = _classification_run(audit_db, classification_id, tenant, owner)
            record_response(state, request_sha, body, status, request_id)
            _classification_cas(audit_db, audit_run, holder[0], state)
            holder[0] = dump_json(state)

    return holder, save


async def _lookup_market_call(call_id, owner, model_session):
    """The market's record of one idempotency key, or None when it cannot be read."""
    if not call_id:
        return None
    from app.application.elt.llm_session_provider import (
        bind_etl_llm_owner,
        current_owner_market_provider,
        reset_etl_llm_owner,
    )

    token = bind_etl_llm_owner(int(owner))
    try:
        with bind_model_session(model_session):
            provider = current_owner_market_provider(timeout_seconds=15.0)
        if provider is None or not hasattr(provider, "lookup_call"):
            return None
        return await provider.lookup_call(str(call_id))
    finally:
        reset_etl_llm_owner(token)


def _settle_failed_step(
    db,
    run,
    state,
    draft,
    request_sha,
    exc,
    *,
    stored,
    step,
    previous_calls,
    classification_id,
    split_unit=None,
):
    """Record a failed call's real outcome. A rejected answer continues as a bounded repair."""
    from app.application.elt.errors import model_call_outcome
    from app.application.reviewed_excel_audit import REPAIR_ROUNDS, settle_call

    checkpoint = state["analysis_checkpoint"]
    stored_status = state["model_audit"][-1].get("http_status") if stored else None
    outcome = model_call_outcome(exc, stored_status=stored_status)
    reason = public_excel_error(exc)
    settle_call(state, request_sha, outcome, reason)
    checkpoint["results"] = checkpoint["results"][:step]
    rounds, exhausted = 0, False
    if outcome == "truncated":
        # A smaller unit is a different request; the same prompt is never resent.
        checkpoint["calls_in_round"] = previous_calls + 1
        split = split_unit is not None and split_unit(step)
        checkpoint["phase"] = "ready" if split else "failed"
        if not split:
            checkpoint["repair"] = {
                "step": step,
                "rounds": 0,
                "reason": "模型输出达到长度上限且本单元无法再按源结构拆分",
                "exhausted": True,
            }
        _classification_cas(db, run, draft, state)
        if split:
            logger.info("analyze unit %s truncated; split into two source-closed units", step)
            return {
                "classification_id": classification_id,
                "version": checkpoint["version"],
                "phase": "pending",
                "split": {"step": step, "total": checkpoint["total"]},
                "checkpoint": _checkpoint_view(checkpoint),
            }
        raise _model_processing_failure(exc, stored_status=stored_status, retryable=False)
    if outcome == "answered_invalid":
        checkpoint["calls_in_round"] = previous_calls + 1
        earlier = checkpoint.get("repair") or {}
        rounds = earlier.get("rounds", 0) + 1 if earlier.get("step") == step else 1
        exhausted = rounds > REPAIR_ROUNDS
        checkpoint["repair"] = {"step": step, "rounds": rounds, "reason": reason[:300]}
        if exhausted:
            checkpoint["repair"]["exhausted"] = True
        else:
            checkpoint["repair"]["answer"] = str(getattr(exc, "answer", "") or "")[:12_000]
        over_budget = checkpoint["calls_in_round"] >= checkpoint["max_calls"]
        checkpoint["phase"] = "failed" if exhausted else ("paused" if over_budget else "ready")
    elif outcome != "unknown":
        checkpoint["phase"] = "ready"
    try:
        _classification_cas(db, run, draft, state)
    except HTTPException:
        if outcome != "unknown":
            raise
    if outcome == "answered_invalid" and not exhausted:
        logger.info("analyze answer rejected; repair round %s of %s queued", rounds, REPAIR_ROUNDS)
        return {
            "classification_id": classification_id,
            "version": checkpoint["version"],
            "phase": "paused" if checkpoint["phase"] == "paused" else "pending",
            "repair": {"round": rounds, "max_rounds": REPAIR_ROUNDS, "reason": reason[:300]},
            "checkpoint": _checkpoint_view(checkpoint),
        }
    raise _model_processing_failure(
        exc, stored_status=stored_status, retryable=False if exhausted else None
    )


def _analysis_in_flight(classification_id, version, state):
    """202 for a call that is still running here or at the market."""
    return JSONResponse(
        status_code=202,
        content={
            "classification_id": classification_id,
            "version": version,
            "phase": "inflight",
            "retry_after": 30,
            "checkpoint": _checkpoint_view(state["analysis_checkpoint"]),
        },
    )


@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/analyze")
async def reviewed_excel_classification_analyze(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    auto_group: bool = Form(False),
    user=Depends(_manage),
):
    request.state.elt_stage = "analyze"
    tenant, owner = _identity(user)
    model_session = require_model_session(request, tenant, owner)
    from app.application.reviewed_excel_audit import live_claims

    with _docking_channel(), live_claims():
        return await _reviewed_excel_classification_analyze_body(
            classification_id, request, version, auto_group, tenant, owner, model_session
        )


@router.post("/api/templates/reviewed-excel/classifications/{classification_id}/analyze/abandon")
def reviewed_excel_classification_abandon_call(
    classification_id: str,
    request: Request,
    version: str = Form(..., max_length=64),
    request_sha256: str = Form("", max_length=64),
    candidate_key: str = Form("", max_length=64),
    confirm: str = Form(..., max_length=40),
    note: str = Form("", max_length=300),
    user=Depends(_manage),
):
    """The user accepts a possible duplicate charge to unlock one unknown-outcome call."""
    from app.application.reviewed_excel_audit import abandon_call, normalize_audit

    if confirm != "abandon_unknown_call":
        raise HTTPException(status_code=400, detail="须明确确认放弃未知结果请求")
    tenant, owner = _identity(user)
    try:
        with tenant_scope(tenant), get_db() as db:
            run = _classification_run(db, classification_id, tenant, owner)
            old = run.draft_json
            state = load_json(old, {})
            versions = state.get("versions", [])
            checkpoint = state.get("analysis_checkpoint") or {}
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            if candidate_key:
                record = _abandon_candidate_claim(state, candidate_key, owner, note)
            else:
                if checkpoint.get("phase") != "inflight":
                    raise HTTPException(status_code=409, detail="没有待处理的未知结果请求")
                normalize_audit(state)
                record = abandon_call(
                    state, request_sha256, authorized_by=f"user:{owner}", note=note or "user"
                )
            _recheck(request, (tenant, owner))
            _classification_cas(db, run, old, state)
        return {
            "classification_id": classification_id,
            "version": version,
            "abandoned_call_id": record.get("call_id"),
            "possible_duplicate_charge": True,
            "checkpoint": _checkpoint_view(state.get("analysis_checkpoint")),
        }
    except ReviewedExcelError as exc:
        raise HTTPException(status_code=409, detail=public_excel_error(exc)) from None


def _abandon_candidate_claim(state, candidate_key, owner, note):
    from datetime import UTC, datetime

    from app.application.reviewed_excel_audit import is_live, owned_here

    claims = state.get("template_candidate_requests") or {}
    claim = claims.get(candidate_key)
    if not claim or claim.get("state") not in {"inflight", "sent", "unknown"}:
        raise HTTPException(status_code=409, detail="没有可放弃的候选请求")
    if is_live(candidate_key) or (owned_here(claim) and claim.get("state") == "sent"):
        raise HTTPException(status_code=409, detail="该候选请求仍在本进程处理中，不能放弃")
    record = {
        **claims.pop(candidate_key),
        "candidate_key": candidate_key,
        "state": "abandoned",
        "abandoned_by": f"user:{owner}",
        "abandoned_note": str(note or "user")[:300],
        "abandoned_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "possible_duplicate_charge": True,
    }
    history = state.setdefault("abandoned_candidate_requests", [])
    history.append(record)
    del history[:-50]
    return record


async def _reviewed_excel_classification_analyze_body(
    classification_id, request, version, auto_group, tenant, owner, model_session
):
    try:
        with tenant_scope(tenant), get_db() as db:
            run = _classification_run(db, classification_id, tenant, owner)
            old = run.draft_json
            state = load_json(old, {})
            versions = state.get("versions", [])
            if not versions or versions[-1].get("version") != version:
                raise HTTPException(status_code=409, detail="分类版本已改变，请刷新")
            from app.application.reviewed_excel_audit import normalize_audit

            normalize_audit(state)
            body = _source(db, run, tenant, owner)
            review = inspect_workbook(body)
            checkpoint = state.get("analysis_checkpoint")
            from app.application.reviewed_excel_budget import (
                BUDGET_VERSION,
                validate_checkpoint_budget,
                validate_remaining_audit_budget,
            )

            try:
                validate_checkpoint_budget(checkpoint)
            except ReviewedExcelError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if checkpoint and (
                checkpoint.get("version") != version
                or checkpoint.get("source_sha256") != run.file_sha256
            ):
                raise HTTPException(
                    status_code=409, detail="分类或来源版本已改变；未覆盖已确认结果"
                )
            if checkpoint and checkpoint.get("auto_group", False) != auto_group:
                raise HTTPException(status_code=409, detail="分组模式已改变，请核对已有批次")
            if checkpoint and checkpoint.get("phase") == "inflight":
                from app.application.reviewed_excel_audit import is_live, recovery_action

                latest = (state.get("model_audit") or [{}])[-1]
                if is_live(latest.get("request_sha256")):
                    return _analysis_in_flight(classification_id, version, state)
                lookup = await _lookup_market_call(latest.get("call_id"), owner, model_session)
                action = recovery_action(latest, lookup)
                if action == "wait":
                    return _analysis_in_flight(classification_id, version, state)
                if action == "locked":
                    raise HTTPException(
                        status_code=409,
                        detail="上次请求结果未知且市场无法确认；不会自动重发。"
                        "如需放弃并重发，须由用户明确授权（可能重复计费）",
                    )
                checkpoint["recovery"] = {
                    "call_id": latest["call_id"],
                    "request_sha256": latest["request_sha256"],
                }
                checkpoint["phase"] = "ready"
                logger.info("analyze resumes an unsettled call by same-key market recovery")
            repair = (checkpoint or {}).get("repair") or {}
            if checkpoint and checkpoint.get("phase") == "failed":
                if repair.get("exhausted"):
                    raise _model_processing_failure(
                        ModelAnswerRejected(
                            f"模型连续 {repair['rounds']} 轮答案未通过校验：{repair['reason']}；"
                            "未再调用模型，请人工核对或重新归档"
                        ),
                        stored_status=200,
                        retryable=False,
                    )
                if checkpoint.get("calls_in_round", 0) >= checkpoint["max_calls"]:
                    checkpoint["calls_in_round"] = 0
                checkpoint["phase"] = "ready"
            if checkpoint and checkpoint.get("phase") == "paused":
                checkpoint["phase"] = "ready"
                checkpoint["calls_in_round"] = 0
            from app.application.reviewed_excel_plan import (
                restore_coordinate_plan,
                split_plan_step,
                store_coordinate_plan,
            )

            if checkpoint:
                try:
                    batches = restore_coordinate_plan(review, checkpoint)
                except ReviewedExcelError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                max_calls = checkpoint["max_calls"]
            else:
                batches, max_calls = await run_in_threadpool(
                    plan_semantic_batches, review, neutral=True
                )
                from app.application.reviewed_excel_template import (
                    configured_template_llm_provider,
                )

                template_provider = configured_template_llm_provider()
                checkpoint = {
                    "budget_version": BUDGET_VERSION,
                    "version": version,
                    "source_sha256": run.file_sha256,
                    "phase": "ready",
                    "results": [],
                    "total": len(batches),
                    "max_calls": max_calls,
                    "calls_in_round": 0,
                    "auto_group": auto_group,
                    "authorization": {
                        "kind": "account_session",
                        "tenant_id": tenant,
                        "owner_user_id": owner,
                        "source_sha256": run.file_sha256,
                        "provider": template_provider,
                        "provider_basis": "configured_before_call",
                        "scope": "this_file_bounded_cells_and_structure",
                        "requested_at": utcnow().isoformat(),
                    },
                }
                store_coordinate_plan(checkpoint, batches)
            validate_remaining_audit_budget(state, checkpoint, len(batches))
            index = len(checkpoint["results"])
            if index > len(batches):
                raise HTTPException(status_code=409, detail="分析批次状态无效")
            state["analysis_checkpoint"] = checkpoint

            def turn_for(step):
                from app.application.reviewed_excel_audit import repair_turn

                if repair.get("step") != step or repair.get("exhausted"):
                    return None
                return repair_turn(repair.get("answer", ""), repair.get("reason", ""))

            async def audited(draft, prepared, phase, step, function, *args, **kwargs):
                """Send one claimed call: (result, draft), or a repair continuation dict."""
                from app.application.reviewed_excel_audit import claim_request, mark_live
                from app.application.reviewed_excel_template import template_llm_model_label
                from app.build_identity import build_identity

                request_sha = claim_request(
                    state,
                    prepared,
                    source_sha256=run.file_sha256,
                    version=version,
                    classification_id=classification_id,
                    code_version=build_identity()["git_sha"] or "unavailable",
                    model=template_llm_model_label(),
                    phase=phase,
                )
                checkpoint["phase"] = "inflight"
                _recheck(request, (tenant, owner))
                _classification_cas(db, run, draft, state)
                mark_live(request_sha)
                draft = dump_json(state)
                holder, save = _response_audit_writer(
                    state, draft, classification_id, tenant, owner, request_sha
                )
                previous_calls = checkpoint.get("calls_in_round", 0)
                try:
                    with bind_model_session(model_session):
                        value = await run_in_threadpool(
                            _call_with_response_audit,
                            function,
                            save,
                            *args,
                            call_id=state["model_audit"][-1].get("call_id"),
                            expected_request_sha256=request_sha,
                            owner_id=owner,
                            **kwargs,
                        )
                except (ValueError, TypeError, EltError) as exc:
                    return _settle_failed_step(
                        db,
                        run,
                        state,
                        holder[0],
                        request_sha,
                        exc,
                        stored=holder[0] != draft,
                        step=step,
                        previous_calls=previous_calls,
                        classification_id=classification_id,
                        split_unit=(
                            (lambda unit: split_plan_step(checkpoint, unit, review))
                            if phase == "classification"
                            else None
                        ),
                    )
                _recheck(request, (tenant, owner))
                _source(db, run, tenant, owner)
                from app.application.reviewed_excel_audit import mark_answered

                mark_answered(state, request_sha)
                checkpoint["calls_in_round"] = previous_calls + 1
                checkpoint["phase"] = "ready"
                checkpoint.pop("repair", None)
                return value, holder[0]

            claimed_draft = old
            if index < len(batches):
                batch_review = {**review, "cells": batches[index], "full_cells": review["cells"]}
                options = {"reference_ids": auto_group, "repair": turn_for(index)}
                prepared = await run_in_threadpool(
                    _classify_semantic_batch, batch_review, prepare_only=True, **options
                )
                step = await audited(
                    claimed_draft,
                    prepared,
                    "classification",
                    index,
                    _classify_semantic_batch,
                    batch_review,
                    **options,
                )
                if isinstance(step, dict):
                    return step
                batch_result, claimed_draft = step
                checkpoint["results"].append(batch_result)
                result = combine_semantic_batches(
                    review, batches[: index + 1], checkpoint["results"], max_calls
                )
                if index + 1 < len(batches):
                    if checkpoint["calls_in_round"] >= max_calls:
                        checkpoint["phase"] = "paused"
                    _classification_cas(db, run, claimed_draft, state)
                    return {
                        "classification_id": classification_id,
                        "version": version,
                        "phase": "paused" if checkpoint["phase"] == "paused" else "pending",
                        "checkpoint": _checkpoint_view(checkpoint),
                    }
            else:
                if not auto_group or len(batches) <= 1:
                    raise HTTPException(status_code=409, detail="分析批次状态无效")
                result = combine_semantic_batches(review, batches, checkpoint["results"], max_calls)
            from app.application.reviewed_excel_partition import boundary_left_for_confirmation

            # Uncovered cells stay for a person. Do not send another model call to fill them.
            if auto_group and len(batches) > 1 and not boundary_left_for_confirmation(result):
                from app.application.reviewed_excel_grouping import group_semantic_fragments

                # Persist complete fragment results before beginning a separate model request.
                if index < len(batches):
                    if checkpoint["calls_in_round"] >= max_calls:
                        checkpoint["phase"] = "paused"
                    _classification_cas(db, run, claimed_draft, state)
                    claimed_draft = dump_json(state)
                    if checkpoint["phase"] == "paused":
                        return {
                            "classification_id": classification_id,
                            "version": version,
                            "phase": "paused",
                            "checkpoint": _checkpoint_view(checkpoint),
                        }
                options = {"repair": turn_for(len(batches))}
                grouping_request: dict | list[dict] = await run_in_threadpool(
                    group_semantic_fragments, review, result, prepare_only=True, **options
                )
                if not isinstance(grouping_request, dict):
                    raise ReviewedExcelError("分组请求格式无效")
                step = await audited(
                    claimed_draft,
                    grouping_request,
                    "grouping",
                    len(batches),
                    group_semantic_fragments,
                    review,
                    result,
                    **options,
                )
                if isinstance(step, dict):
                    return step
                result["suggested_documents"], claimed_draft = step
                result["budget"]["grouping_calls"] = 1
            old = claimed_draft
            state.pop("analysis_checkpoint", None)
            rule_sheets = classify_review_workbook(review)
            values = {(c["sheet"], c["cell"]): c["value"][:160] for c in review["cells"]}
            from openpyxl.utils.cell import (
                column_index_from_string,
                coordinate_from_string,
            )

            sheets = []
            for rule_sheet in rule_sheets:
                regions = []
                for region in (r for r in result["regions"] if r["sheet"] == rule_sheet["sheet"]):
                    c1, r1, c2, r2 = bounded_range(region["range"])

                    def inside(ref):
                        col, row = coordinate_from_string(ref["cell"])
                        return c1 <= column_index_from_string(col) <= c2 and r1 <= row <= r2

                    rule_regions = rule_sheet["regions"]
                    headers = [
                        h
                        for candidate in rule_regions
                        for h in candidate["header_cells"]
                        if inside(h)
                    ]
                    headings = [
                        e for candidate in rule_regions for e in candidate["evidence"] if inside(e)
                    ]
                    merged = []
                    for candidate in rule_regions:
                        for item in candidate["merged_ranges"]:
                            mc1, mr1, mc2, mr2 = bounded_range(item)
                            if (
                                c1 <= mc1 <= mc2 <= c2
                                and r1 <= mr1 <= mr2 <= r2
                                and item not in merged
                            ):
                                merged.append(item)
                    regions.append(
                        {
                            "range": region["range"],
                            "labels": region["labels"],
                            "label_source": "not_classified" if auto_group else "model",
                            "range_source": "model",
                            "evidence": [
                                {
                                    "label": "model",
                                    "cell": ref["cell"],
                                    "matched": values[(ref["sheet"], ref["cell"])],
                                }
                                for ref in region["evidence"]
                                if (ref.get("sheet"), ref.get("cell")) in values
                            ],
                            "parent_heading": headings[0]["matched"] if headings else "",
                            "header_cells": headers,
                            "merged_ranges": merged,
                            "dependencies": region["dependencies"],
                            **(
                                {"drawing_evidence": region["drawing_evidence"]}
                                if "drawing_evidence" in region
                                else {}
                            ),
                            "possible_shared_context": [
                                {
                                    "cell": ref["cell"],
                                    "kind": f"{ref['sheet']}：模型建议依赖，待确认",
                                }
                                for ref in region["dependencies"]
                            ],
                            "dependency_status": "模型建议，边界和跨区依赖待确认",
                            "needs_confirmation": True,
                            "checked_cells": 0,
                            "reason": region["reason"],
                            "open_fragment": region.get("open_fragment", False),
                            "model_original_range": region.get("model_original_range"),
                            "suggested_labels": region.get("suggested_labels", []),
                            "context_warning": region.get("context_warning", ""),
                            "continuation_context": region.get("continuation_context"),
                            "value_extent": region.get("value_extent"),
                        }
                    )
                dimensions = next(
                    item
                    for item in review["sheet_overview"]
                    if item["sheet"] == rule_sheet["sheet"]
                )
                for candidate in rule_sheet["regions"]:
                    regions.extend(
                        unresolved_fragments(candidate, regions, dimensions["merged_regions"])
                    )
                sheets.append({**rule_sheet, "regions": regions})
            from app.application.reviewed_excel_sheet_names import apply_unknown_sheet_names

            apply_unknown_sheet_names(sheets, review["cells"], owner_id=owner)
            actual_providers = sorted(
                {item.get("provider", "unreported") for item in result["input_summaries"]}
            )
            latest = {
                "parent_version": version,
                "sheets": sheets,
                "model_status": "returned",
                "model_authorization": checkpoint.get("authorization"),
                "actual_model_providers": actual_providers,
                "read_only_print_areas": review["read_only_print_areas"],
                "suggested_documents": result["suggested_documents"],
                "suggested_document_count": result["suggested_document_count"],
                "document_count_status": result["document_count_status"],
                "layout_references": result["layout_references"],
                "coverage": result["coverage"],
                "input_summaries": result["input_summaries"],
                "structure_map": result["structure_map"],
                "structure_map_source": result["structure_map_source"],
                "budget": result["budget"],
                "fragment_links": result["fragment_links"],
                "confirmed": False,
            }
            latest["version"] = _classification_version(run.file_sha256, version, latest)
            versions.append(latest)
            if len(versions) > 50:
                raise ReviewedExcelError("分类版本已达上限")
            _recheck(request, (tenant, owner))
            _classification_cas(db, run, old, state)
        return {"classification_id": classification_id, **latest}
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


@router.post("/api/templates/reviewed-excel/preview")
async def reviewed_excel_preview(
    request: Request,
    file: UploadFile = File(...),
    expected_actor: str = Form(..., max_length=80),
    classification_id: str = Form("", max_length=36),
    classification_version: str = Form("", max_length=64),
    region_sheet: str = Form("", max_length=200),
    region_range: str = Form("", max_length=60),
    auto_slice_index: int = Form(-1),
    print_area_mode: str = Form("source", max_length=16),
    user=Depends(_manage),
):
    _expected_actor(expected_actor, user)
    tenant, owner = _identity(user)
    model_session = require_model_session(request, tenant, owner)
    if not classification_id or not classification_version:
        raise HTTPException(status_code=409, detail="请先建立文件分类记录，再生成候选")
    from app.application.reviewed_excel_audit import (
        call_key,
        is_live,
        live_claims,
        mark_live,
        owner_stamp,
        recovery_action,
    )

    _dock_cm = _docking_channel()
    _dock_cm.__enter__()
    _live_cm = live_claims()
    _live_cm.__enter__()
    try:
        request.state.elt_stage = "read_workbook"
        body = await _body(file)
        review = inspect_workbook(body)
        source_restrictions = list(review.get("usage_restrictions", []))
        selected_region: dict[str, Any] | None = None
        if auto_slice_index >= 0:
            if not classification_id or not classification_version or region_sheet or region_range:
                raise ReviewedExcelError("自动切片选择无效")
            with tenant_scope(tenant), get_db() as db:
                classification = _classification_run(db, classification_id, tenant, owner)
                if classification.file_sha256 != review["sha256"]:
                    raise HTTPException(status_code=409, detail="分类来源已改变，请重新选择")
                archive_version_id = load_json(classification.summary_json, {}).get(
                    "archive_version_id"
                )
                if not archive_version_id:
                    raise ReviewedExcelError("自动切片须先归档原件")
                slices, _coverage, _rows = _auto_slices(
                    db, classification_id, classification_version, tenant, owner
                )
                if auto_slice_index >= len(slices):
                    raise HTTPException(status_code=404, detail="切片不存在")
                selected_slice = slices[auto_slice_index]
                if selected_slice["basis"] != "model_group":
                    raise ReviewedExcelError("模型尚未确定此单据的完整关系")
                body = selected_slice["workbook"]
                review = inspect_workbook(body)
                fragments = selected_slice["fragments"]
                selected_region = {
                    "classification_id": classification_id,
                    "version": classification_version,
                    "selection_basis": "model_group",
                    "auto_slice_index": auto_slice_index,
                    "range_objects_receipt": selected_slice["range_objects_receipt"],
                    "archive_version_id": archive_version_id,
                    "source_sha256": classification.file_sha256,
                    "fragments": fragments,
                    "print_area_mode": "source",
                    "derived_sha256": review["sha256"],
                }
        elif classification_id:
            with tenant_scope(tenant), get_db() as db:
                classification = _classification_run(db, classification_id, tenant, owner)
                _source(db, classification, tenant, owner)
                state = load_json(classification.draft_json, {})
                versions = state.get("versions", [])
                latest = versions[-1] if versions else {}
                if (
                    classification.file_sha256 != review["sha256"]
                    or latest.get("version") != classification_version
                    or not latest.get("confirmed")
                    or not any(
                        sheet.get("sheet") == region_sheet
                        and any(
                            region.get("range") == region_range
                            for region in sheet.get("regions", [])
                        )
                        for sheet in latest.get("sheets", [])
                    )
                ):
                    raise HTTPException(status_code=409, detail="分类来源或区域已变化，请重新确认")
                selected_region = {
                    "classification_id": classification_id,
                    "version": classification_version,
                    "sheet": region_sheet,
                    "range": region_range,
                }
                selected_region["archive_version_id"] = load_json(
                    classification.summary_json, {}
                ).get("archive_version_id")
                selected_region["logical_documents"] = [
                    group
                    for group in latest.get("logical_documents", [])
                    if {"sheet": region_sheet, "range": region_range} in group["fragments"]
                ]
                fragments = (
                    selected_region["logical_documents"][0]["fragments"]
                    if selected_region["logical_documents"]
                    else [{"sheet": region_sheet, "range": region_range}]
                )
                from openpyxl.utils.cell import (
                    column_index_from_string,
                    coordinate_from_string,
                )

                def inside_fragment(ref):
                    col, row = coordinate_from_string(ref["cell"])
                    col = column_index_from_string(col)
                    return any(
                        ref["sheet"] == part["sheet"] and c1 <= col <= c2 and r1 <= row <= r2
                        for part in fragments
                        for c1, r1, c2, r2 in [bounded_range(part["range"])]
                    )

                for sheet in latest["sheets"]:
                    for region in sheet["regions"]:
                        if {"sheet": sheet["sheet"], "range": region["range"]} in fragments:
                            if any(
                                not inside_fragment(ref) for ref in region.get("dependencies", [])
                            ):
                                raise ReviewedExcelError(
                                    "所选文档依赖外部说明或标题，暂不能保证保真提取"
                                )
                selected_region["source_sha256"] = review["sha256"]
                selected_region["fragments"] = fragments
                selected_region["source_print_areas"] = [
                    area
                    for area in review["read_only_print_areas"]
                    if area["sheet"] == region_sheet
                ]
                if not selected_region["source_print_areas"]:
                    original_print = next(
                        sheet["print_area"]
                        for sheet in review["sheet_overview"]
                        if sheet["sheet"] == region_sheet
                    )
                    if original_print:
                        selected_region["source_print_areas"] = [
                            {"sheet": region_sheet, "value": original_print}
                        ]
                selected_region["print_area_mode"] = print_area_mode
                object_receipt: dict = {}
                request.state.elt_stage = "extract_document"
                body = derive_document_workbook(
                    body, fragments, print_area_mode=print_area_mode, object_receipt=object_receipt
                )
                selected_region["range_objects_receipt"] = object_receipt
                review = inspect_workbook(body)
                selected_region["derived_print_area"] = next(
                    sheet["print_area"]
                    for sheet in review["sheet_overview"]
                    if sheet["sheet"] == region_sheet
                )
                selected_region["derived_sha256"] = review["sha256"]
        request.state.elt_stage = "generate_candidates"
        proposal = make_proposals(review)
        versions = [proposal]
        candidate_key = ""
        if classification_id:
            candidate_key = hashlib.sha256(
                dump_json(
                    {
                        "version": classification_version,
                        "source": review["sha256"],
                        "slice": auto_slice_index,
                        "sheet": region_sheet,
                        "range": region_range,
                    }
                ).encode()
            ).hexdigest()
            with tenant_scope(tenant), get_db() as db:
                classification = _classification_run(db, classification_id, tenant, owner)
                old = classification.draft_json
                state = load_json(old, {})
                if (
                    not state.get("versions")
                    or state["versions"][-1].get("version") != classification_version
                ):
                    raise HTTPException(status_code=409, detail="分类版本已变化，请重新处理")
                claims = state.setdefault("template_candidate_requests", {})
                existing = claims.get(candidate_key)
                claim = None
                if existing:
                    if existing.get("state") == "completed" and existing.get("review_id"):
                        return _stored_candidate_response(db, existing["review_id"], tenant, owner)
                    if is_live(candidate_key):
                        return JSONResponse(
                            status_code=202, content={"phase": "inflight", "retry_after": 30}
                        )
                    lookup = await _lookup_market_call(
                        existing.get("call_id"), owner, model_session
                    )
                    action = recovery_action(existing, lookup)
                    if action == "wait":
                        return JSONResponse(
                            status_code=202, content={"phase": "inflight", "retry_after": 30}
                        )
                    if action == "locked":
                        error = _model_processing_failure(
                            ReviewedExcelError(
                                "上次候选请求结果未知且市场无法确认；不会重复发送。"
                                "如需放弃并重发，须由用户明确授权（可能重复计费）"
                            )
                        )
                        error.status_code = 409
                        raise error
                    claim = {**existing, "state": "sent", "owner": owner_stamp()}
                    claim["attempts"] = int(existing.get("attempts") or 1) + 1
                if len(claims) >= 200:
                    raise HTTPException(
                        status_code=409, detail="本文件候选请求已达上限，请先核对已有结果"
                    )
                claims[candidate_key] = claim or {
                    "state": "sent",
                    "call_id": uuid4().hex,
                    "owner": owner_stamp(),
                    "attempts": 1,
                }
                candidate_call_id = claims[candidate_key]["call_id"]
                _recheck(request, (tenant, owner))
                _classification_cas(db, classification, old, state)
                mark_live(candidate_key)
        try:
            request.state.elt_stage = "model_candidates"
            with (
                tenant_scope(tenant),
                bind_model_session(model_session),
                call_key(candidate_call_id),
            ):
                proposal = await run_in_threadpool(
                    refine_proposal,
                    review,
                    proposal["version"],
                    "生成三个清理候选，保留固定说明和公式",
                    owner_id=owner,
                    initial=True,
                )
            versions.append(proposal)
        except ValueError as exc:
            # Only a call that may have been answered without our seeing it keeps the claim.
            unknown = model_call_outcome(exc) == "unknown"
            with tenant_scope(tenant), get_db() as db:
                try:
                    _update_candidate_claim(
                        db, classification_id, candidate_key, tenant, owner, unknown=unknown
                    )
                except HTTPException:
                    # Claim already moved; still surface the model failure.
                    pass
            raise _model_processing_failure(exc) from None
        proposal["model"]["authorization"] = template_model_authorization(
            model_session,
            tenant,
            owner,
            review["sha256"],
            selected_region or {},
        )
        request.state.elt_stage = "render_candidates"
        for version in versions:
            _build_candidate_previews(body, review, version)
        _recheck(request, (tenant, owner))
        request.state.elt_stage = "save_preview"
        with tenant_scope(tenant), get_db() as db:
            if selected_region and selected_region.get("derived_sha256"):
                current = _classification_run(
                    db, selected_region["classification_id"], tenant, owner
                )
                _source(db, current, tenant, owner)
                source_restrictions.extend(_usage_restrictions(db, current, tenant, owner))
                current_versions = load_json(current.draft_json, {}).get("versions", [])
                if (
                    not current_versions
                    or current_versions[-1].get("version") != selected_region["version"]
                    or (
                        current_versions[-1].get("model_status") != "returned"
                        if selected_region.get("selection_basis") == "model_group"
                        else not current_versions[-1].get("confirmed")
                    )
                ):
                    raise HTTPException(status_code=409, detail="文档分类已变化，请重新生成候选")
            review["usage_restrictions"] = list(dict.fromkeys(source_restrictions))
            upload = UploadServiceMixin().save_upload(
                db,
                owner_user_id=owner,
                file_name=file.filename or "review.xlsx",
                content_type=file.content_type,
                stream=BytesIO(body),
            )
            run = EltRun(
                id=new_id(),
                tenant_id=tenant,
                owner_user_id=owner,
                upload_id=upload["upload_id"],
                target_type="template_review",
                status=_READY,
                stage=_READY,
                file_sha256=review["sha256"],
                draft_json=dump_json({"versions": versions}),
                summary_json=dump_json(
                    {
                        "kind": "reviewed_excel",
                        "selected_region": selected_region,
                        "usage_restrictions": review["usage_restrictions"],
                    }
                ),
            )
            db.add(run)
            if candidate_key:
                _update_candidate_claim(db, classification_id, candidate_key, tenant, owner, run.id)
            else:
                db.commit()
            review_id = run.id
        return {
            "success": True,
            **review,
            "review_id": review_id,
            "proposal": proposal,
            "versions": versions,
            "selected_region": selected_region,
        }
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None
    finally:
        _live_cm.__exit__(None, None, None)
        _dock_cm.__exit__(None, None, None)


@router.get("/api/templates/reviewed-excel/reviews/{review_id}")
def reviewed_excel_history(review_id: str, user=Depends(_read)):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        run = _run(db, review_id, tenant, owner)
        state, versions = _proposals(run)
        return {
            "success": True,
            "review_id": run.id,
            "source_sha256": run.file_sha256,
            "selected_region": load_json(run.summary_json, {}).get("selected_region"),
            "usage_restrictions": _usage_restrictions(db, run, tenant, owner),
            "status": run.status,
            "versions": versions,
            "confirmation": state.get("confirmation"),
            "receipt": load_json(run.receipt_json, {}),
            "revision_parent": load_json(run.summary_json, {}).get("revision_parent"),
        }


@router.get(
    "/api/templates/reviewed-excel/reviews/{review_id}/versions/{version}/candidates/{candidate_id}/download"
)
def reviewed_excel_candidate_download(
    review_id: str, version: str, candidate_id: str, user=Depends(_read)
):
    tenant, owner = _identity(user)
    with tenant_scope(tenant), get_db() as db:
        run = _run(db, review_id, tenant, owner)
        _review_source_version(db, run, tenant, owner)
        _state, versions = _proposals(run)
        proposal = next((item for item in versions if item.get("version") == version), None)
        candidate = next(
            (
                item
                for item in (proposal or {}).get("candidates", [])
                if item.get("id") == candidate_id
            ),
            None,
        )
        if proposal is None or not candidate or not proposal.get("result_previews"):
            raise HTTPException(status_code=404, detail="候选模板不存在")
        body = _source(db, run, tenant, owner)
        try:
            cleaned = clean_workbook(body, run.file_sha256, candidate["clear"])
        except ReviewedExcelError as exc:
            raise HTTPException(status_code=409, detail=public_excel_error(exc)) from None
    return Response(
        cleaned,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="candidate.xlsx"'},
    )


@router.post("/api/templates/reviewed-excel/refine")
async def reviewed_excel_refine(
    request: Request,
    review_id: str = Form(..., max_length=36),
    parent_version: str = Form(..., max_length=64),
    feedback: str = Form(..., max_length=1000),
    current: str = Form("[]", max_length=100_000),
    user=Depends(_manage),
):
    tenant, owner = _identity(user)
    model_session = require_model_session(request, tenant, owner)
    with _docking_channel():
        return await _reviewed_excel_refine_body(
            request, review_id, parent_version, feedback, current, tenant, owner, model_session
        )


async def _reviewed_excel_refine_body(
    request, review_id, parent_version, feedback, current, tenant, owner, model_session
):
    try:
        current_cells = json.loads(current)
        if not isinstance(current_cells, list):
            raise ReviewedExcelError("当前候选无效")
        with tenant_scope(tenant), get_db() as db:
            run = _run(db, review_id, tenant, owner)
            _review_source_version(db, run, tenant, owner)
            state, versions = _proposals(run)
            if run.status == _SAVED and versions[-1]["version"] == parent_version:
                body = _source(db, run, tenant, owner)
                clean_workbook(body, run.file_sha256, current_cells)
                _recheck(request, (tenant, owner))
                run = _fork_saved_review(
                    db, run, versions[-1], feedback, current_cells, tenant, owner
                )
                state, versions = _proposals(run)
                if run.status in {_READY, _SAVED} and versions[-1]["version"] != parent_version:
                    return _refinement_response(run, versions[-1], replayed=True)
            if run.status == _MODEL_PENDING:
                error = _model_processing_failure(
                    ReviewedExcelError("上次模型处理仍在进行或结果未知，请先核对状态；不会重复发送")
                )
                error.status_code = 409
                raise error
            if run.status != _READY or versions[-1]["version"] != parent_version:
                raise HTTPException(status_code=409, detail="审阅版本已过期，请刷新")
            if len(versions) >= 50:
                raise ReviewedExcelError("提案版本已达上限")
            old_draft = run.draft_json
            body = _source(db, run, tenant, owner)
            review = inspect_workbook(body)
            clean_workbook(body, run.file_sha256, current_cells)
            _recheck(request, (tenant, owner))
            _cas(db, run, old_draft, status=_MODEL_PENDING, stage="model_candidates")
            try:
                with bind_model_session(model_session):
                    proposal = await run_in_threadpool(
                        refine_proposal,
                        review,
                        parent_version,
                        feedback,
                        owner_id=owner,
                        current=current_cells,
                        initial=True,
                    )
            except ValueError as exc:
                if model_call_outcome(exc) != "unknown":
                    _cas(
                        db,
                        run,
                        old_draft,
                        expected_status=_MODEL_PENDING,
                        status=_READY,
                        stage=_READY,
                    )
                raise _model_processing_failure(exc) from None
            source_scope = load_json(run.summary_json, {}).get("selected_region") or {}
            proposal["model"]["authorization"] = template_model_authorization(
                model_session,
                tenant,
                owner,
                run.file_sha256,
                source_scope,
                feedback=True,
            )
            _build_candidate_previews(body, review, proposal)
            _recheck(request, (tenant, owner))
            versions.append(proposal)
            state["versions"] = versions
            _cas(
                db,
                run,
                old_draft,
                expected_status=_MODEL_PENDING,
                status=_READY,
                stage=_READY,
                draft_json=dump_json(state),
            )
            response = _refinement_response(run, proposal)
        return response
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(status_code=400, detail=public_excel_error(exc)) from None


def _authorize_intake(request, expected, target_type=""):
    from app.domain.app_pure.auth_permission_resolver import require_allowed
    from app.request_active_mod_ctx import get_request_active_mod_id

    user = _execute(request)
    if _identity(user) != expected:
        raise HTTPException(status_code=403, detail="入库账号已变化，请重新预演")
    mod_id = get_request_active_mod_id()
    require_allowed(user=user, mod_id=mod_id)
    if target_type == "attendance":
        raise HTTPException(
            status_code=409, detail="当前考勤写入目标无法核实业务空间，请使用考勤工作区授权导入"
        )
    return mod_id


@router.post("/api/templates/reviewed-excel/intake-preview")
def reviewed_excel_intake_preview(
    request: Request,
    review_id: str = Form(..., max_length=36),
    proposal_version: str = Form(..., max_length=64),
    candidate_id: str = Form(..., max_length=64),
    selections: str = Form(..., max_length=500_000),
    name: str = Form(..., max_length=160),
    composer_note: str = Form("", max_length=4000),
    user=Depends(_manage),
):
    """Stage the selected bytes and a reviewable business run; never write business/KB data."""
    from app.application.elt.auto_ingest_service import get_auto_ingest_service
    from app.application.elt.service import get_elt_service

    tenant, owner = _identity(user)
    mod_id = _authorize_intake(request, (tenant, owner))
    staged_path = None
    preview_started = False
    try:
        selected = json.loads(selections)
        if not isinstance(selected, list) or not name.strip():
            raise ReviewedExcelError("请选择模板并填写名称")
        with tenant_scope(tenant), get_db() as db:
            review = _run(db, review_id, tenant, owner)
            _review_source_version(db, review, tenant, owner)
            state, versions = _proposals(review)
            if review.status != _READY or versions[-1]["version"] != proposal_version:
                raise HTTPException(status_code=409, detail="审阅版本已变化，请重新选择候选")
            _require_private_model(request, versions[-1], tenant, owner)
            candidate = next(
                (item for item in versions[-1]["candidates"] if item["id"] == candidate_id), None
            )
            if candidate is None:
                raise HTTPException(status_code=409, detail="候选不属于该审阅版本")
            old_draft = review.draft_json
            key = _intake_selection_key(
                review, proposal_version, candidate_id, selected, name, composer_note
            )
            # The review upload is the template fragment. Database and knowledge
            # read the classification's archived original, which still has item rows.
            template_source = _source(db, review, tenant, owner)
            archived = _archived_original(db, review, tenant, owner)
            chosen = clean_workbook(template_source, review.file_sha256, selected)
            service = get_elt_service()
            upload = service.save_upload(
                db,
                owner_user_id=owner,
                file_name=f"{name.strip()}.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                stream=BytesIO(chosen),
            )
            source = service._owned_upload(db, upload["upload_id"], owner)
            if source.tenant_id != tenant:
                raise HTTPException(status_code=403, detail="无权使用该入库预演")
            path = staged_path = Path(source.storage_path)
            from app.application.elt.auto_ingest_service import workbook_text
            from app.application.elt.candidate_table import (
                confirmed_business_table,
                dataset_from_business_rows,
                dataset_from_document_text,
                read_delivery_note_business,
            )
            from app.application.elt.llm_assist import advise_business_import, etl_llm_enabled

            original_text = workbook_text(archived)
            from app.application.elt.llm_session_provider import (
                bind_etl_llm_owner,
                reset_etl_llm_owner,
            )

            # Identity can already see the account model. Bind that same session
            # so these two lanes resolve it; each lane still has its own circuit.
            model_session = require_model_session(request, tenant, owner)
            owner_token = bind_etl_llm_owner(owner)
            try:
                with bind_model_session(model_session):
                    business_llm = (
                        advise_business_import(original_text) if etl_llm_enabled() else None
                    )
                    ai_table = None
                    if (
                        business_llm is not None
                        and business_llm.used_llm
                        and not business_llm.degraded
                    ):
                        ai_table = dataset_from_business_rows(
                            list(business_llm.data.get("rows") or [])
                        )
                    delivery = read_delivery_note_business(archived)
                    if ai_table is not None:
                        chosen_table = ai_table
                        target_type = "shipment_records"
                        detection_reason = "database_llm"
                    elif delivery is not None:
                        chosen_table = delivery
                        target_type = "shipment_records"
                        detection_reason = "delivery_note_business_rows"
                    else:
                        confirmed = confirmed_business_table(path) or confirmed_business_table(
                            archived
                        )
                        if confirmed is None:
                            chosen_table = dataset_from_document_text(original_text, name.strip())
                            target_type = "knowledge"
                            detection_reason = "archived_document"
                        else:
                            chosen_table, target_type = confirmed
                            detection_reason = "candidate_headers"
                    detection = {
                        "target_type": target_type,
                        "reason": detection_reason,
                        "confirmed": True,
                        "llm_lane": "database",
                        "used_llm": bool(business_llm and business_llm.used_llm),
                        "degraded": bool(business_llm and business_llm.degraded),
                    }
                    _authorize_intake(request, (tenant, owner), target_type)
                    intake = get_auto_ingest_service()
                    knowledge = intake.knowledge_plan(
                        path=path,
                        file_name=name.strip(),
                        note=composer_note.strip(),
                        owner_user_id=owner,
                        owned_upload_user_id=source.owner_user_id,
                        source_text=original_text,
                    )
            finally:
                reset_etl_llm_owner(owner_token)
            preview_started = True
            business = service.create_preview(
                db,
                owner_user_id=owner,
                upload_id=upload["upload_id"],
                target_type=target_type,
                source_dataset=chosen_table,
            )
            plan = {
                "run_id": business["id"],
                "upload_id": upload["upload_id"],
                "selection_key": key,
                "source_sha256": review.file_sha256,
                "candidate_sha256": upload["sha256"],
                "target_type": target_type,
                "mod_id": mod_id,
                "name": name.strip(),
                "note": composer_note.strip(),
                "detection": detection,
                "knowledge": knowledge,
            }
            _recheck(request, (tenant, owner))
            _review_source_version(db, review, tenant, owner)
            state["intake_preview"] = plan
            _cas(db, review, old_draft, draft_json=dump_json(state))
            return {"success": True, "intake": {**plan, "business": business}}
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 400), detail=public_excel_error(exc)
        ) from None
    finally:
        if staged_path is not None and not preview_started:
            discard_stored_upload(staged_path)


@router.post("/api/templates/reviewed-excel/save")
async def reviewed_excel_save(
    request: Request,
    review_id: str = Form(..., max_length=36),
    proposal_version: str = Form(..., max_length=64),
    candidate_id: str = Form(..., max_length=64),
    selections: str = Form(..., max_length=500_000),
    name: str = Form(..., max_length=160),
    publish_to_tenant: bool = Form(False),
    private_intake: bool = Form(False),
    intake_run_id: str = Form("", max_length=36),
    preview_revision: str = Form("", max_length=64),
    valid_rows_only: bool = Form(False),
    composer_note: str = Form("", max_length=4000),
    user=Depends(_manage),
):
    tenant, owner = _identity(user)
    # Enterprise shared-library path still requires explicit publish consent.
    # User intake (archiveOnSelect) uses private_intake: save + auto-ingest without
    # enterprise-library publish checkbox; approval withdraw remains available.
    if publish_to_tenant and private_intake:
        raise HTTPException(status_code=400, detail="不能同时选择企业发布与私有入库")
    if not publish_to_tenant and not private_intake:
        raise HTTPException(status_code=400, detail="请确认将清理后的模板发布到企业模板库")
    if not name.strip() or len(name.strip()) > 160:
        raise HTTPException(status_code=400, detail="模板名称不能为空或超过 160 字")
    try:
        selected = json.loads(selections)
        if not isinstance(selected, list):
            raise ReviewedExcelError("清理范围无效")
        summary_for_ingest: dict = {}
        confirmed_plan: dict | None = None
        with tenant_scope(tenant), get_db() as db:
            run = _run(db, review_id, tenant, owner)
            _review_source_version(db, run, tenant, owner)
            # Print/layout restrictions block enterprise publish only; private intake may proceed.
            if publish_to_tenant and _usage_restrictions(db, run, tenant, owner):
                raise HTTPException(
                    status_code=409,
                    detail="此来源仅供数据/模板测试，打印版式未验证；可预览和下载测试候选，不得发布到企业模板库",
                )
            state, versions = _proposals(run)
            if private_intake:
                _require_private_model(request, versions[-1], tenant, owner)
            request_key = hashlib.sha256(
                dump_json(
                    {
                        "version": proposal_version,
                        "candidate": candidate_id,
                        "selections": selected,
                        "name": name.strip(),
                        **(
                            {
                                "intake_run_id": intake_run_id,
                                "preview_revision": preview_revision,
                                "valid_rows_only": valid_rows_only,
                                "note": composer_note.strip(),
                            }
                            if intake_run_id
                            else {}
                        ),
                    }
                ).encode()
            ).hexdigest()
            if run.status == _SAVED:
                receipt = load_json(run.receipt_json, {})
                if receipt.get("request_key") == request_key:
                    return {
                        "success": True,
                        "template_id": receipt["template_id"],
                        "replayed": True,
                        "auto_ingest": receipt.get("auto_ingest")
                        or {
                            "success": False,
                            "error": "outcome_unknown"
                            if intake_run_id
                            else "confirmation_required",
                        },
                    }
                raise HTTPException(status_code=409, detail="此审阅已保存；新的清理范围请新建审阅")
            if run.status != _READY or versions[-1]["version"] != proposal_version:
                raise HTTPException(status_code=409, detail="审阅版本已过期或保存结果待核对")
            candidate = next(
                (item for item in versions[-1]["candidates"] if item["id"] == candidate_id), None
            )
            if candidate is None:
                raise HTTPException(status_code=409, detail="候选不属于该审阅版本")
            body = _source(db, run, tenant, owner)
            if private_intake and not intake_run_id:
                raise HTTPException(
                    status_code=409, detail="请先核对入库目标和记录数量，再确认入库"
                )
            if intake_run_id:
                from app.application.elt.auto_ingest_service import get_auto_ingest_service
                from app.application.elt.service import get_elt_service

                plan = state.get("intake_preview") or {}
                expected_key = _intake_selection_key(
                    run, proposal_version, candidate_id, selected, name, composer_note
                )
                mod_id = _authorize_intake(
                    request, (tenant, owner), str(plan.get("target_type") or "")
                )
                if (
                    plan.get("run_id") != intake_run_id
                    or plan.get("selection_key") != expected_key
                    or plan.get("source_sha256") != run.file_sha256
                    or plan.get("mod_id") != mod_id
                ):
                    raise HTTPException(
                        status_code=409, detail="候选、整理要求或业务空间已变化，请重新预演"
                    )
                upload = get_elt_service()._owned_upload(db, plan["upload_id"], owner)
                if upload.tenant_id != tenant:
                    raise HTTPException(status_code=403, detail="无权使用该入库预演")
                prepared_path = Path(upload.storage_path)
                business = get_auto_ingest_service().validate_prepared(
                    db,
                    plan=plan,
                    path=prepared_path,
                    owner_user_id=owner,
                    tenant_id=tenant,
                    preview_revision=preview_revision,
                    owned_upload_user_id=upload.owner_user_id,
                )
                error_rows = int((business.get("summary") or {}).get("error") or 0)
                if error_rows:
                    valid_rows_only = True
                confirmed_plan = {
                    **plan,
                    "preview_revision": preview_revision,
                    "valid_rows_only": valid_rows_only,
                }
                if error_rows:
                    from app.application.elt.auto_ingest_service import (
                        knowledge_document_keeps_unwritten_rows,
                    )

                    held = confirmed_plan.get("knowledge")
                    held = held if isinstance(held, dict) else {}
                    kept = knowledge_document_keeps_unwritten_rows(
                        str(held.get("content") or ""),
                        str(held.get("source_text") or ""),
                    )
                    if kept:
                        # The archived source hash stays so the preview is still the same file.
                        # The stored document is the summary plus that source, including unwritten rows.
                        refreshed = get_auto_ingest_service().knowledge_plan(
                            path=prepared_path,
                            file_name=str(confirmed_plan.get("name") or ""),
                            note=str(confirmed_plan.get("note") or ""),
                            owner_user_id=owner,
                            owned_upload_user_id=upload.owner_user_id,
                            source_text=kept,
                            allow_model=False,
                        )
                        refreshed["used_llm"] = True
                        refreshed["source_hash"] = held.get("source_hash")
                        refreshed["source_text"] = held.get("source_text")
                        confirmed_plan["knowledge"] = refreshed
                # The staged upload is the candidate chosen at preview. The template
                # file is that same cleanup of the review workbook, not the full original.
                cleaned = clean_workbook(body, run.file_sha256, selected)
            else:
                # Old template-library clients authorize one template only, never implicit business writes.
                cleaned = clean_workbook(body, run.file_sha256, selected)
            before = {(i["sheet"], i["cell"]) for i in candidate["clear"]}
            after = {(i["sheet"], i["cell"]) for i in selected}
            state["confirmation"] = {
                "version": proposal_version,
                "candidate": candidate_id,
                "selected": selected,
                "added": [{"sheet": s, "cell": c} for s, c in sorted(after - before)],
                "removed": [{"sheet": s, "cell": c} for s, c in sorted(before - after)],
            }
            old_draft = run.draft_json
            saving_draft = dump_json(state)
            classification_lock = _lock_review_classification(db, run, tenant, owner)
            _cas(db, run, old_draft, status=_SAVING, stage=_SAVING, draft_json=saving_draft)
            try:
                _recheck(request, (tenant, owner))
                db.expire_all()
                _review_source_version(db, run, tenant, owner)
                if confirmed_plan:
                    if (
                        _authorize_intake(request, (tenant, owner), confirmed_plan["target_type"])
                        != confirmed_plan["mod_id"]
                    ):
                        raise HTTPException(status_code=409, detail="业务空间已变化，请重新预演")
                    from app.application.elt.auto_ingest_service import workbook_text

                    get_auto_ingest_service().validate_prepared(
                        db,
                        plan=confirmed_plan,
                        path=prepared_path,
                        owner_user_id=owner,
                        tenant_id=tenant,
                        preview_revision=preview_revision,
                        owned_upload_user_id=upload.owner_user_id,
                        source_text=workbook_text(_archived_original(db, run, tenant, owner)),
                    )
            except (HTTPException, EltError):
                _release_failed_review(
                    db, run.id, tenant, owner, saving_draft, old_draft, classification_lock
                )
                raise
            root = Path(get_app_data_dir()) / "templates" / "reviewed_excel" / str(tenant)
            path = root / f"{uuid4().hex}.xlsx"
            created = False
            fd = None
            try:
                root.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                stream = os.fdopen(fd, "wb")
                fd = None
                with stream:
                    stream.write(cleaned)
            except OSError:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                cleanup_failed = False
                if created:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        cleanup_failed = True
                _release_failed_review(
                    db, run.id, tenant, owner, saving_draft, old_draft, classification_lock
                )
                detail = "临时文件写入失败，模板未提交，可以重试"
                if cleanup_failed:
                    detail = "临时文件写入失败，模板未提交；临时副本需管理员清理"
                raise HTTPException(status_code=503, detail=detail) from None
            try:
                from app.legacy.routes.document_templates_compat import run_archive_template_create

                result, code = run_archive_template_create(
                    {
                        "name": name.strip(),
                        "template_type": "Excel",
                        "category": "excel",
                        "business_scope": "custom",
                        "source": "reviewed_excel_cleanup",
                        "file_path": str(path),
                        "fields": [],
                        "preview_data": {
                            "reviewed_excel": True,
                            "source_sha256": (
                                load_json(run.summary_json, {}).get("selected_region") or {}
                            ).get("source_sha256", run.file_sha256),
                            "derived_sha256": run.file_sha256,
                            "selected_region": load_json(run.summary_json, {}).get(
                                "selected_region"
                            ),
                            "review_id": review_id,
                            **(
                                {
                                    "revision_parent": load_json(run.summary_json, {})[
                                        "revision_parent"
                                    ]
                                }
                                if load_json(run.summary_json, {}).get("revision_parent")
                                else {}
                            ),
                        },
                    }
                )
                if code >= 400 or not result.get("success"):
                    raise HTTPException(
                        status_code=code if code >= 400 else 500,
                        detail=result.get("message", "保存失败"),
                    )
                template_id = result["template"]["id"]
                persisted = db.execute(
                    update(EltRun)
                    .where(
                        EltRun.id == run.id,
                        EltRun.tenant_id == tenant,
                        EltRun.owner_user_id == owner,
                        EltRun.status == _SAVING,
                    )
                    .values(
                        status=_SAVED,
                        stage=_SAVED,
                        receipt_json=dump_json(
                            {
                                "request_key": request_key,
                                "template_id": template_id,
                                **(
                                    {
                                        "revision_parent": load_json(run.summary_json, {})[
                                            "revision_parent"
                                        ]
                                    }
                                    if load_json(run.summary_json, {}).get("revision_parent")
                                    else {}
                                ),
                            }
                        ),
                    )
                )
                if persisted.rowcount != 1:
                    db.rollback()
                    raise HTTPException(
                        status_code=409, detail="模板已写入但审阅回执未确认，请人工核对"
                    )
                _unlock_review_classification(db, classification_lock, tenant, owner)
                # Snapshot before session closes: EltRun detaches when get_db() exits,
                # and post-save auto-ingest must not touch ORM attributes afterward.
                summary_for_ingest = load_json(run.summary_json, {})
                db.commit()
            except BOUNDARY_ERRORS:
                # The legacy library commits in a separate transaction; do not retry or remove
                # files when its outcome may have succeeded but its receipt was lost.
                raise
        auto_ingest = {"success": False, "error": "confirmation_required"}
        if confirmed_plan:
            try:
                from app.application.elt.auto_ingest_service import get_auto_ingest_service

                auto_ingest = get_auto_ingest_service().start_background(
                    owner_user_id=owner,
                    tenant_id=tenant,
                    # Staged candidate workbook chosen at preview.
                    source_path=str(prepared_path),
                    file_name=name.strip(),
                    template_id=str(template_id),
                    review_id=review_id,
                    classification_id=str(summary_for_ingest.get("classification_id") or ""),
                    composer_note=composer_note.strip(),
                    prepared_plan=confirmed_plan,
                    # Pin etl/uploads/<tenant>/<owner> jail (ownership already checked).
                    owned_upload_user_id=owner,
                )
            except BOUNDARY_ERRORS as exc:
                context = _reviewed_excel_context(request)
                logger.error(
                    "ELT auto-ingest failed stage=save request_id=%s error_type=%s",
                    context["request_id"],
                    type(exc).__name__,
                )
                auto_ingest = {"success": False, "error": "auto_ingest_failed", **context}
            with tenant_scope(tenant), get_db() as db:
                persisted_run = _run(db, review_id, tenant, owner)
                receipt = load_json(persisted_run.receipt_json, {})
                receipt["auto_ingest"] = auto_ingest
                persisted_run.receipt_json = dump_json(receipt)
                db.commit()
        return {
            "success": True,
            "template_id": template_id,
            "replayed": False,
            "auto_ingest": auto_ingest,
        }
    except (ValueError, TypeError, EltError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 400), detail=public_excel_error(exc)
        ) from None


@router.get("/api/templates/reviewed-excel/{template_id}/download")
def reviewed_excel_download(template_id: int, user=Depends(_read)):
    tenant, _owner = _identity(user)
    from sqlalchemy import text

    with tenant_scope(tenant), get_db() as db:
        row = db.execute(
            text(
                "SELECT original_file_path, analyzed_data FROM templates WHERE id = :id AND tenant_id = :tenant AND (is_active IS NULL OR is_active = 1)"
            ),
            {"id": template_id, "tenant": tenant},
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        metadata = json.loads(row.analyzed_data or "{}")
        review_id = (metadata.get("preview_data") or {}).get("review_id")
        with tenant_scope(tenant), get_db() as db:
            run = (
                db.query(EltRun)
                .filter(
                    EltRun.id == review_id,
                    EltRun.tenant_id == tenant,
                    EltRun.target_type == "template_review",
                )
                .first()
            )
            if run is None:
                raise ReviewedExcelError("unavailable")
            receipt = load_json(run.receipt_json, {})
            if run.status != _SAVED or str(receipt.get("template_id")) != f"db:{template_id}":
                raise ReviewedExcelError("unavailable")
        root = (Path(get_app_data_dir()) / "templates" / "reviewed_excel" / str(tenant)).resolve()
        raw = Path(row.original_file_path or "")
        path = raw.resolve()
        if (
            metadata.get("source") != "reviewed_excel_cleanup"
            or raw.is_symlink()
            or root not in path.parents
            or not path.is_file()
        ):
            raise ReviewedExcelError("unavailable")
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="模板文件不可用") from None
    return FileResponse(
        path,
        filename="cleaned-template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
