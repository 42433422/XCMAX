"""Shared helpers and permission dependencies for reviewed Excel routes."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from openpyxl.utils.exceptions import InvalidFileException

from app.fastapi_routes.reviewed_excel import app_gateway

logger = logging.getLogger(__name__)
_SLICE_METADATA_LOCK = threading.Lock()
_SLICE_METADATA: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()

def _remember_slice_metadata(key, slices):
    metadata = [
        {"fragments": item["fragments"], "type_label": item.get("type_label", "")}
        for item in slices
    ]
    with _SLICE_METADATA_LOCK:
        _SLICE_METADATA[key] = (time.monotonic(), metadata)
        _SLICE_METADATA.move_to_end(key)
        while len(_SLICE_METADATA) > 8:
            _SLICE_METADATA.popitem(last=False)


def _cached_slice_metadata(key):
    with _SLICE_METADATA_LOCK:
        saved = _SLICE_METADATA.get(key)
        if not saved:
            return None
        if time.monotonic() - saved[0] > 600:
            del _SLICE_METADATA[key]
            return None
        _SLICE_METADATA.move_to_end(key)
        return saved[1]


def _draft_with_structural_index(draft: dict, body: bytes) -> dict:
    """Persist a compact workbook structural index on classification draft_json."""
    try:
        from app.application.reviewed_excel_structural_index import (
            attach_structural_index_to_draft,
            build_workbook_structural_index,
        )

        return attach_structural_index_to_draft(draft, build_workbook_structural_index(body))
    except (
        app_gateway.EltError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        BadZipFile,
        InvalidFileException,
        ParseError,
    ):
        return draft

_manage = app_gateway.require_permission("etl.template.manage")
_execute = app_gateway.require_permission("etl.execute")
_read = app_gateway.require_permission("etl.read")
_archive_admin = app_gateway.require_permission("admin.manage_users")

def _docking_channel():
    from app.application.ai_feature_isolation import BUSINESS_DOCKING, ai_feature_channel

    return ai_feature_channel(BUSINESS_DOCKING)


def _identity(user):

    if getattr(user, "tenant_id", None) is None or getattr(user, "id", None) is None:
        raise HTTPException(status_code=403, detail="需要登录并具有租户上下文")
    return int(user.tenant_id), int(user.id)

def _expected_actor(expected: str, user):
    tenant, owner = _identity(user)
    if expected != f"{tenant}:{owner}":
        raise HTTPException(status_code=409, detail="登录用户或租户已改变，请重新选择文件")


def _recheck(request, expected):
    if _identity(_manage(request)) != expected:
        raise HTTPException(status_code=403, detail="权限或用户身份已改变")


def _build_candidate_previews(body, review, proposal):
    """Keep established route patch points while delegating the pure projection."""
    app_gateway.build_candidate_previews(
        body,
        review,
        proposal,
        clean_workbook=app_gateway.clean_workbook,
        inspect_workbook=app_gateway.inspect_workbook,
    )


async def _body(file, *, allow_legacy=False):
    # archive-classify uses allow_legacy=True so docking can take XLS and statement Word.
    extensions = (".xlsx", ".xls", ".docx") if allow_legacy else (".xlsx",)
    if not (file.filename or "").lower().endswith(extensions):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx；其他格式暂不能保证保真")
    body = await file.read(app_gateway.MAX_BYTES + 1)
    if len(body) > app_gateway.MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20 MB")
    return body

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
    if phase == "paused" and checkpoint.get("repair"):
        message = (
            "模型上次返回的格式不符合要求，尚未完成当前批次；继续处理将请求模型修正，可能产生费用。"
        )
    return {
        "phase": phase,
        "version": checkpoint["version"],
        "completed": len(checkpoint["results"]),
        "total": checkpoint["total"],
        "remaining": checkpoint["total"] - len(checkpoint["results"]),
        "max_calls": checkpoint["max_calls"],
        "calls_in_round": checkpoint.get("calls_in_round", 0),
        "repair_rounds": (checkpoint.get("repair") or {}).get("rounds", 0),
        "remaining_in_round": max(0, checkpoint["max_calls"] - checkpoint.get("calls_in_round", 0)),
        "message": message,
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


def _auto_slices(
    db,
    classification_id,
    version,
    tenant,
    owner,
    with_rows=False,
    only_index=None,
    metadata_only=False,
):
    from app.application.reviewed_excel_auto_slice import derive_classified_documents

    run = app_gateway._classification_run(db, classification_id, tenant, owner)
    versions = app_gateway.load_json(run.draft_json, {}).get("versions", [])
    latest = versions[-1] if versions else {}
    if latest.get("version") != version:
        raise HTTPException(status_code=409, detail="分类版本已改变或模型尚未完成")
    body = app_gateway._source(db, run, tenant, owner)
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
    sheets = latest.get("sheets", [])
    hidden_sheets = {
        sheet.get("sheet")
        for sheet in sheets
        if isinstance(sheet, dict) and sheet.get("sheet_state") in {"hidden", "veryHidden"}
    }

    def has_visible_source(item):
        index = item.get("reference_index")
        if not isinstance(index, dict) or not index:
            return True
        source_sheets = {
            ref.get("ref", {}).get("sheet")
            for ref in index.values()
            if isinstance(ref, dict) and isinstance(ref.get("ref"), dict)
        }
        return not source_sheets or bool(source_sheets - hidden_sheets)

    if any(
        isinstance(item, dict)
        and (item.get("source_coverage") or {}).get("can_slice") is False
        and has_visible_source(item)
        for item in (latest.get("input_summaries") or [])
    ):
        raise app_gateway.ReviewedExcelError("模型明确表示不能自动切片，请人工核对")
    sheets = [
        sheet
        for sheet in sheets
        if not isinstance(sheet, dict) or sheet.get("sheet") not in hidden_sheets
    ]
    coverage = latest.get("coverage")
    coverage = (
        [
            item
            for item in coverage
            if not isinstance(item, dict) or item.get("sheet") not in hidden_sheets
        ]
        if isinstance(coverage, list)
        else []
    )
    source_names = [sheet.get("sheet") for sheet in sheets if isinstance(sheet, dict)]
    coverage_names = [item.get("sheet") for item in coverage if isinstance(item, dict)]
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
        raise app_gateway.ReviewedExcelError("模型尚未完整覆盖原件，不能生成自动切片")
    regions = [
        {**region, "sheet": sheet["sheet"]}
        for sheet in sheets
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
            "coverage": coverage,
        },
        owner_id=owner,
        only_index=only_index,
        metadata_only=metadata_only,
    )
    from app.application.reviewed_excel_sheet_names import annotate_slice_titles

    annotate_slice_titles(slices, latest.get("sheets") or [])
    if with_rows:
        _remember_slice_metadata(
            (tenant, owner, classification_id, version, run.file_sha256), slices
        )
    return slices, latest.get("coverage", []), []

def _call_with_response_audit(function, callback, *args, call_id=None, **kwargs):
    from app.application.reviewed_excel_audit import capture_response

    with capture_response(callback, call_id=call_id) as answer:
        try:
            return function(*args, **kwargs)
        except app_gateway.ReviewedExcelError as exc:
            if not getattr(exc, "answer", ""):
                exc.answer = answer.get("text", "")
            raise


def _response_audit_writer(state, claimed_draft, classification_id, tenant, owner, request_sha):
    """Commit the provider body before parsing; failed CAS keeps the call inflight."""
    from app.application.reviewed_excel_audit import record_response

    holder = [claimed_draft]

    def save(body, status, request_id):
        with app_gateway.tenant_scope(tenant), app_gateway.get_db() as audit_db:
            audit_run = app_gateway._classification_run(audit_db, classification_id, tenant, owner)
            record_response(state, request_sha, body, status, request_id)
            app_gateway._classification_cas(audit_db, audit_run, holder[0], state)
            holder[0] = app_gateway.dump_json(state)

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
        with app_gateway.bind_model_session(model_session):
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
    from app.application.reviewed_excel_audit import REPAIR_ROUNDS, settle_call

    checkpoint = state["analysis_checkpoint"]
    stored_status = state["model_audit"][-1].get("http_status") if stored else None
    outcome = app_gateway.model_call_outcome(exc, stored_status=stored_status)
    reason = app_gateway.public_excel_error(exc)
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
        app_gateway._classification_cas(db, run, draft, state)
        if split:
            logger.info("analyze unit %s truncated; split into two source-closed units", step)
            return {
                "classification_id": classification_id,
                "version": checkpoint["version"],
                "phase": "pending",
                "split": {"step": step, "total": checkpoint["total"]},
                "checkpoint": _checkpoint_view(checkpoint),
            }
        raise app_gateway._model_processing_failure(exc, stored_status=stored_status, retryable=False)
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
        app_gateway._classification_cas(db, run, draft, state)
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
    raise app_gateway._model_processing_failure(
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


def _intake_attempt_status(attempt):
    status = attempt.get("status", "outcome_unknown")
    if status == "running":
        try:
            # New previews allow eight bounded database units plus knowledge.
            # Legacy claims retain the original expiry for compatibility.
            lifetime = min(1800, max(600, int(attempt.get("max_duration_seconds", 600))))
            if (
                app_gateway.utcnow() - datetime.fromisoformat(attempt["started_at"])
            ).total_seconds() > lifetime:
                return "outcome_unknown"
        except (KeyError, TypeError, ValueError):
            return "outcome_unknown"
    return status
