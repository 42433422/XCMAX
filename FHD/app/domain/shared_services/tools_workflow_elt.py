"""ELT 导入工具：让智能对话通过数据对接中心（ELT）完成预演与入库。

与 `import_excel_to_database` 直接写库不同，这里复用 ELT 的
"预演 → 确认 → 执行 → 回执" 流程，具备源快照、映射核对与回滚能力。
"""

from __future__ import annotations

import os
import time
from typing import Any

from sqlalchemy import or_

from app.application.tools.workflow_spreadsheet_scope import resolve_owned_upload_path
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.auth.agent_mod_scope import _bound_actor
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

PREVIEW_PENDING = {"queued", "previewing"}
EXECUTION_PENDING = {"queued", "executing", "persisting"}
PREVIEW_TIMEOUT_SECONDS = 120
EXECUTION_TIMEOUT_SECONDS = 240
POLL_INTERVAL_SECONDS = 0.5


def _elt_enabled() -> bool:
    flag = str(os.environ.get("FHD_ELT_CENTER_ENABLED") or "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    from app.mod_sdk.product_skus import resolve_product_sku

    return resolve_product_sku() == "enterprise"


def _owned_upload(file_path: str, context: dict[str, Any]) -> dict[str, str]:
    """把展示名/存储路径解析为当前账号自己的 ELT 上传记录（仅返回会话内取出的标量）。"""
    value = resolve_owned_upload_path(str(file_path or ""), context)
    if not value:
        return {}
    actor = _bound_actor(context)
    with get_db() as db:
        row = (
            db.query(EltUpload)
            .filter(
                EltUpload.owner_user_id == actor.id,
                EltUpload.tenant_id == tenant_id_for_write(),
                or_(EltUpload.id == value, EltUpload.storage_path == value),
                EltUpload.expires_at > utc_now_naive(),
            )
            .order_by(EltUpload.id.desc())
            .first()
        )
        if row is None:
            return {}
        # 会话关闭后实例会过期，必须在会话内取出需要的字段。
        return {
            "id": str(row.id),
            "storage_path": str(row.storage_path or ""),
            "suffix": str(row.suffix or ""),
        }


def _wait(service, run_id: str, owner_id: int, *, pending: set[str], timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        with get_db() as db:
            db.expire_all()
            data = service.get_run(db, run_id=run_id, owner_user_id=owner_id)
        if str(data.get("status") or "") not in pending:
            return data
        if time.monotonic() >= deadline:
            return data
        time.sleep(POLL_INTERVAL_SECONDS)


def _summary(data: dict) -> dict[str, Any]:
    return {
        "run_id": data.get("id"),
        "target_type": data.get("target_type"),
        "status": data.get("status"),
        "stage": data.get("stage"),
        "total_rows": data.get("total_rows"),
        "new_rows": data.get("summary", {}).get("new"),
        "update_rows": data.get("summary", {}).get("update"),
        "skip_rows": data.get("summary", {}).get("skip"),
        "error_rows": data.get("summary", {}).get("error"),
        "executed_rows": data.get("summary", {}).get("executed"),
        "error": data.get("error"),
        "reversible": data.get("reversible"),
    }


def _pending_mappings(data: dict) -> list[dict]:
    """与执行阶段共用同一判定，避免把已自动确认的映射误报成待确认。"""
    from app.application.elt.service_execution import _unconfirmed_mappings

    return _unconfirmed_mappings((data.get("draft") or {}).get("field_mappings"))


def _error_row_details(run_id: str, owner_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """列出预演中校验失败的行，供对话直接指出需要修正的位置。"""
    if not run_id:
        return []
    from app.application.elt.service_support import load_json
    from app.db.models.elt import EltRunRow

    try:
        with get_db() as db:
            rows = (
                db.query(EltRunRow)
                .filter(
                    EltRunRow.run_id == run_id,
                    EltRunRow.owner_user_id == owner_id,
                    EltRunRow.tenant_id == tenant_id_for_write(),
                    EltRunRow.final_action == "error",
                )
                .order_by(EltRunRow.id)
                .limit(limit)
                .all()
            )
            details: list[dict[str, Any]] = []
            for row in rows:
                issues = load_json(row.validation_json, [])
                details.append(
                    {
                        "sheet": row.source_sheet,
                        "row": row.source_row,
                        "message": "；".join(
                            str(item.get("message") or item.get("code") or "")
                            for item in issues
                            if isinstance(item, dict)
                        ),
                    }
                )
            return details
    except RECOVERABLE_ERRORS:
        return []


def _resolve_template(upload: dict[str, str], owner_id: int) -> tuple[str, dict]:
    """识别目标类型，并在模板唯一匹配时自动套用。

    多个候选模板时不自动选，避免用错映射把数据写进错误字段；
    此时回退到 ELT 的默认草稿 + 自动映射建议。
    """
    from app.application.elt.target_detection import detect_elt_target

    target_type = "auto"
    try:
        detection = detect_elt_target(
            upload.get("storage_path") or "",
            suffix=upload.get("suffix") or "",
            owner_user_id=owner_id,
        )
        detected = str(detection.get("target_type") or "").strip()
        if detected:
            target_type = detected
    except RECOVERABLE_ERRORS:
        return "auto", {}
    if target_type in {"auto", "abnormal"}:
        return target_type, {}
    from app.application.elt.service import get_elt_service

    try:
        with get_db() as db:
            candidates = [
                item
                for item in get_elt_service().list_templates(db, owner_user_id=owner_id)
                if str(item.get("target_type") or "") == target_type
            ]
    except RECOVERABLE_ERRORS:
        return target_type, {}
    if len(candidates) == 1:
        return target_type, candidates[0]
    return target_type, {}


def _preview(params: dict, runtime_context: dict) -> dict:
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service

    upload = _owned_upload(str(params.get("file_path") or ""), runtime_context)
    if not upload:
        return {
            "success": False,
            "error_code": "upload_not_found",
            "message": "找不到当前账号可用上传文件，请重新上传 Excel 后再导入。",
        }
    service = get_elt_service()
    actor = _bound_actor(runtime_context)
    target_type, template = _resolve_template(upload, actor.id)
    try:
        with get_db() as db:
            created = service.create_preview(
                db,
                owner_user_id=actor.id,
                upload_id=upload["id"],
                # 仍让 ELT 内部完成自动识别：多工作表送货单会同时生成关联预演，
                # 显式传目标类型会跳过该逻辑；模板按同一识别结果匹配。
                target_type="auto",
                template_id=str(template.get("id") or "") or None,
            )
    except EltError as exc:
        return {"success": False, "error_code": exc.code, "message": exc.message}
    run_id = str(created.get("id") or "")
    data = _wait(
        service,
        run_id,
        actor.id,
        pending=PREVIEW_PENDING,
        timeout=PREVIEW_TIMEOUT_SECONDS,
    )
    summary = _summary(data)
    if not summary.get("target_type"):
        summary["target_type"] = target_type
    summary["template_id"] = str(template.get("id") or "")
    summary["template_name"] = str(template.get("name") or "")
    pending_mappings = [
        str(item.get("target") or item.get("source") or "字段")
        for item in _pending_mappings(data)
    ]
    summary["mapping_pending"] = pending_mappings[:8]
    error_rows = int(summary.get("error_rows") or 0)
    error_details = _error_row_details(run_id, actor.id) if error_rows else []
    summary["error_row_details"] = error_details
    # 有错误行或映射待确认时，ELT 会阻断整批执行；提前告知调用方，避免执行阶段才失败。
    summary["executable"] = error_rows == 0 and not pending_mappings
    ok = data.get("status") == "preview_ready"
    template_note = f"，已套用导入模板「{summary['template_name']}」" if summary["template_name"] else ""
    if not ok:
        message = f"预演未完成：{data.get('error') or data.get('stage')}"
    else:
        message = (
            f"预演完成：目标「{summary['target_type']}」，共 {summary['total_rows']} 行，"
            f"新增 {summary['new_rows']}、更新 {summary['update_rows']}、"
            f"跳过 {summary['skip_rows']}、错误 {summary['error_rows']}{template_note}。"
        )
        blockers: list[str] = []
        if error_rows:
            detail = "；".join(
                f"第{item['row']}行（{item['sheet']}）：{item['message']}"
                for item in error_details
                if item.get("row") is not None
            )
            blockers.append(
                f"{error_rows} 行源数据未通过校验{f'（{detail}）' if detail else ''}，"
                "默认不能整批入库；只写入正确的 "
                f"{int(summary.get('new_rows') or 0) + int(summary.get('update_rows') or 0)} 行需明确确认 valid_rows_only=true，"
                "否则请先修正源文件。"
            )
        if pending_mappings:
            blockers.append(
                f"{len(pending_mappings)} 个字段映射待确认（{'、'.join(pending_mappings[:8])}），确认后才能入库。"
            )
        if blockers:
            message += "".join(blockers)
    return {
        "success": ok,
        "preview": True,
        "error_code": None if ok else "elt_preview_not_ready",
        "message": message,
        "data": summary,
    }


def _execute(params: dict, runtime_context: dict) -> dict:
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service

    run_id = str(params.get("run_id") or "").strip()
    if not run_id:
        return {
            "success": False,
            "error_code": "missing_run_id",
            "message": "缺少 ELT 预演编号，请先执行 elt_import.preview。",
        }
    service = get_elt_service()
    actor = _bound_actor(runtime_context)
    try:
        with get_db() as db:
            service.execute(
                db,
                run_id=run_id,
                owner_user_id=actor.id,
                confirmed=True,
                valid_rows_only=bool(params.get("valid_rows_only") is True),
            )
    except EltError as exc:
        return {"success": False, "error_code": exc.code, "message": exc.message}
    data = _wait(
        service,
        run_id,
        actor.id,
        pending=EXECUTION_PENDING,
        timeout=EXECUTION_TIMEOUT_SECONDS,
    )
    summary = _summary(data)
    ok = data.get("status") == "completed"
    return {
        "success": ok,
        "error_code": None if ok else f"elt_execute_{data.get('status')}",
        "message": (
            f"ELT 导入完成：写入 {summary['executed_rows']} 行，"
            f"失败 {summary['error_rows']} 行。"
            if ok
            else f"ELT 导入未完成：{summary.get('error') or data.get('stage')}"
        ),
        "data": summary,
    }


def _registered_router_elt_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    """注册路由：elt_import.preview / elt_import.execute。"""
    if not _elt_enabled():
        return {
            "success": False,
            "error_code": "elt_center_disabled",
            "message": "数据对接中心未启用（需要企业版），暂时无法通过 ELT 导入。",
        }
    payload = dict(params or {})
    if action == "preview":
        try:
            return _preview(payload, runtime_context)
        except PermissionError as err:
            return {
                "success": False,
                "error_code": "spreadsheet_access_denied",
                "message": str(err),
            }
    if action == "execute":
        return _execute(payload, runtime_context)
    return {"success": False, "message": f"未知的 ELT 导入操作：{action}"}
