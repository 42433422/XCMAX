"""ELT 导入工具：让智能对话通过数据对接中心（ELT）完成预演与入库。

与 `import_excel_to_database` 直接写库不同，这里复用 ELT 的
"预演 → 确认 → 执行 → 回执" 流程，具备源快照、映射核对与回滚能力。
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
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

# ELT 目标类型 → 模板库业务范围（与前端 templateScopeRules 的 scope key 一致）。
_TEMPLATE_SCOPE_BY_TARGET = {
    "shipment_records": "shipmentRecords",
    "customer_products": "products",
    "products": "products",
    "customers": "customers",
    "materials": "materials",
}


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


def _knowledge_receipt(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """业务入库完成后，把原件正文同步写入知识库（与数据对接中心同一通道）。

    知识库写入失败不能回滚已完成的业务入库，但必须如实告诉用户。
    """
    upload_id = str(data.get("upload_id") or "")
    file_name = str(data.get("file_name") or "")
    if not upload_id:
        return {"action": "skip", "reason": "missing_upload"}
    from app.application.elt.auto_ingest_service import (
        _extract_text,
        get_auto_ingest_service,
    )
    from app.db.models.elt import EltUpload
    from app.infrastructure.tenant_scope import tenant_scope

    tenant = tenant_id_for_write()
    try:
        with tenant_scope(tenant), get_db() as db:
            upload = (
                db.query(EltUpload)
                .filter(
                    EltUpload.id == upload_id,
                    EltUpload.owner_user_id == owner_id,
                    EltUpload.tenant_id == tenant,
                )
                .first()
            )
            if upload is None:
                return {"action": "skip", "reason": "upload_not_found"}
            storage_path = str(upload.storage_path or "")
            sha = str(upload.sha256 or "")
            label = file_name or str(upload.file_name or "elt-import")
        if not storage_path:
            return {"action": "skip", "reason": "upload_missing"}
        text = _extract_text(Path(storage_path), owned_upload_user_id=owner_id)
        if not text.strip():
            return {"action": "skip", "reason": "empty_document"}
        receipt = get_auto_ingest_service()._ingest_knowledge(
            text=text,
            source_key=label,
            run_id=str(data.get("id") or ""),
            owner_user_id=owner_id,
            content_hash=sha,
            note="",
            tenant_id=tenant,
        )
        return receipt if isinstance(receipt, dict) else {"action": "new"}
    except RECOVERABLE_ERRORS as exc:
        return {"action": "error", "reason": str(exc)[:200]}


def _grid_preview(file_path: str, max_rows: int = 12) -> dict[str, Any]:
    """读取切分后的模板文件前若干行，作为模板库卡片的真实网格预览。"""
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except RECOVERABLE_ERRORS:
        return {"rows": []}
    try:
        worksheet = workbook.active
        if worksheet is None:
            return {"rows": []}
        rows: list[list[dict[str, Any]]] = []
        for row_number, values in enumerate(
            worksheet.iter_rows(max_row=min(worksheet.max_row or 1, max_rows), values_only=True),
            start=1,
        ):
            cells = [
                {
                    "row": row_number,
                    "col": column,
                    "text": "" if value in (None, "") else str(value).strip(),
                    "rowspan": 1,
                    "colspan": 1,
                }
                for column, value in enumerate(values, start=1)
            ]
            rows.append(cells)
        return {"rows": rows, "sheet_name": str(worksheet.title or "")}
    finally:
        workbook.close()


def _template_name(meta: dict[str, Any], stem: str, target_type: str, *, primary: bool) -> str:
    """按预演切出的区段生成模板名，而不是用整份文件名。"""
    sheet = str(meta.get("sheet") or "").strip() or "送货单"
    customer = str(meta.get("customer_name") or "").strip()
    if target_type == "shipment_records" and primary and customer:
        return f"{customer}-发货单版式"
    title = str(meta.get("title") or "").strip()
    return f"{stem}-{title or sheet}"


def _template_scope(region: dict[str, Any], meta: dict[str, Any], target_type: str) -> str:
    """按区段内容判断业务范围，而不是整次预演的目标类型。"""
    if region.get("status") == "selected" or region.get("headerless"):
        return _TEMPLATE_SCOPE_BY_TARGET.get(target_type, "")
    headers = " ".join(str(item) for item in meta.get("headers") or [])
    text = f"{meta.get('title') or ''} {headers}"
    if "报价" in text or ("单价" in text and "型号" in text):
        return "products"
    return ""


def _safe_file_component(value: str) -> str:
    text = "".join(char if char.isalnum() or char in {" ", "-", "_"} else "-" for char in value)
    return text.strip(" .-")[:80] or "elt-template"


def _template_receipt(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """业务入库完成后，把预演切出的区段登记进模板库。

    ELT 的第一步就是把上传文件切成模板区段，模板库应保存这些区段，
    而不是整份原始文件（原始文件可能含多个模板甚至无关工作表）。
    模板库写入失败不影响已完成的导入，但必须在回执里如实说明。
    """
    upload_id = str(data.get("upload_id") or "")
    if not upload_id:
        return {"action": "skip", "reason": "missing_upload"}
    from app.application.template_app_service import get_template_app_service
    from app.db.models.elt import EltUpload
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope

    target_type = str(data.get("target_type") or "").strip()
    all_regions = [
        region
        for region in (data.get("source_features") or {}).get("regions") or []
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    ]
    # 模板库保存预演切出的全部区段；业务数据仍只写入预演选中的区段。
    if not all_regions:
        return {"action": "skip", "reason": "no_region"}
    try:
        from app.application.elt.errors import EltError
        from app.application.elt.shipment_template_extractor import extract_region_template
        from app.utils.path_io.path_utils import get_app_data_dir

        tenant = tenant_id_for_write()
        with tenant_scope(tenant), get_db() as db:
            upload = (
                db.query(EltUpload)
                .filter(
                    EltUpload.id == upload_id,
                    EltUpload.owner_user_id == owner_id,
                    EltUpload.tenant_id == tenant,
                )
                .first()
            )
            if upload is None:
                return {"action": "skip", "reason": "upload_not_found"}
            storage_path = str(upload.storage_path or "")
            file_name = str(data.get("file_name") or upload.file_name or "")
        if not storage_path or not os.path.exists(storage_path):
            return {"action": "skip", "reason": "upload_missing"}
        stem = Path(file_name).stem.strip() or Path(storage_path).stem or "ELT 模板"
        template_type = (
            target_type if target_type and target_type not in {"auto", "abnormal"} else "Excel"
        )
        service = get_template_app_service()
        templates = [item for item in (service.get_templates().get("templates") or []) if str(item.get("source") or "") == "db"]
        existing_names = {
            str(item.get("name") or "").strip(): str(item.get("file_path") or item.get("path") or "")
            for item in templates
        }
        existing_keys = {str(item.get("template_key") or "").strip() for item in templates}
        digest = "".join(
            char for char in str(data.get("file_sha256") or "")[:12].lower() if char in "0123456789abcdef"
        )
        out_dir = (
            Path(get_app_data_dir()).resolve()
            / "tenants"
            / str(tenant)
            / "template_library"
            / str(owner_id)
        )
        names: list[str] = []
        template_ids: list[int] = []
        failures: list[str] = []
        for region in all_regions:
            region_id = str(region.get("id") or "")
            # 用区段 id 派生稳定模板键：同一来源区段重复导入不会重复登记，
            # 且与区段在文件中的先后顺序无关。
            region_key = f"ELT_{hashlib.sha1(region_id.encode()).hexdigest()[:12]}"
            if region_key in existing_keys:
                continue
            destination = out_dir / f"{_safe_file_component(stem)}-{region_key[-12:]}-{digest or 'seg'}.xlsx"
            try:
                meta = extract_region_template(
                    storage_path,
                    source_features={
                        "regions": (data.get("source_features") or {}).get("regions") or []
                    },
                    destination=destination,
                    source_region_id=region_id,
                    clear_example_rows=target_type == "shipment_records",
                )
            except EltError as exc:
                failures.append(str(exc.message)[:120])
                continue
            except RECOVERABLE_ERRORS as exc:
                failures.append(str(exc)[:120])
                continue
            base = _template_name(
                meta,
                stem,
                target_type,
                primary=region.get("status") == "selected",
            )
            if region_key in existing_keys:
                continue
            name = base
            suffix = 2
            while name in existing_names:
                name = f"{base}-{suffix}"
                suffix += 1
            headers = [header for header in meta.get("headers") or [] if header]
            result = service.save_template(
                {
                    "template_name": name,
                    "template_key": region_key,
                    "template_type": template_type,
                    "original_file_path": str(meta.get("file_path") or ""),
                    "analyzed_data": {
                        "category": "excel",
                        "business_scope": _template_scope(region, meta, target_type),
                        "fields": [{"label": header, "value": "", "type": "dynamic"} for header in headers],
                        "preview_data": {
                            "sample_rows": [],
                            "sheet_name": meta.get("sheet") or "",
                            "grid_preview": _grid_preview(str(meta.get("file_path") or "")),
                        },
                    },
                }
            )
            if not result.get("success"):
                return {"action": "error", "reason": str(result.get("message") or "save_failed")}
            existing_names[name] = str(meta.get("file_path") or "")
            existing_keys.add(region_key)
            names.append(name)
            template_ids.append(int(result.get("id") or 0))
        if not names:
            if failures:
                return {"action": "error", "reason": failures[0]}
            return {"action": "skip", "reason": "duplicate_name"}
        return {"action": "new", "names": names, "template_ids": template_ids}
    except TenantScopeError:
        return {"action": "error", "reason": "missing_tenant"}
    except RECOVERABLE_ERRORS as exc:
        return {"action": "error", "reason": str(exc)[:200]}


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
                # 显式传目标类型会跳过该逻辑；模板按同一识别结果自动套用。
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
    # 用户已明确只写入正确行时，错误行不再阻断，执行节点会带 valid_rows_only=true。
    accept_valid_rows = params.get("valid_rows_only") is True
    blocked_by_errors = bool(error_rows) and not accept_valid_rows
    # 有错误行或映射待确认时，ELT 会阻断整批执行；提前告知调用方，避免执行阶段才失败。
    summary["executable"] = not blocked_by_errors and not pending_mappings
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
        if blocked_by_errors:
            detail = "；".join(
                f"第{item['row']}行（{item['sheet']}）：{item['message']}"
                for item in error_details
                if item.get("row") is not None
            )
            blockers.append(
                f"{error_rows} 行源数据未通过校验{f'（{detail}）' if detail else ''}，"
                "默认不能整批入库；只写入正确的 "
                f"{int(summary.get('new_rows') or 0) + int(summary.get('update_rows') or 0)} 行"
                "需用户明确确认（确认后预演与执行都传 valid_rows_only=true），否则请先修正源文件。"
            )
        if pending_mappings:
            blockers.append(
                f"{len(pending_mappings)} 个字段映射待确认（{'、'.join(pending_mappings[:8])}），确认后才能入库。"
            )
        if blockers:
            message += "".join(blockers)
    # 预演发现阻断项时，契约要求编排在此暂停询问用户，而不是继续执行后失败。
    requires_decision = ok and not summary["executable"]
    return {
        "success": ok,
        "preview": True,
        "error_code": None if ok else "elt_preview_not_ready",
        "message": message,
        "requires_user_decision": requires_decision,
        "question": message if requires_decision else "",
        # 用户确认后重新执行预演时，按「仅写入正确行」补充参数，避免再次阻断。
        "resume_params": {"valid_rows_only": True} if requires_decision else {},
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
            # 执行必须绑定本次预演内容的修订号，否则 ELT 会拒绝（防止预演后被改动）。
            current = service.get_run(db, run_id=run_id, owner_user_id=actor.id)
            revision = str(current.get("preview_revision") or "")
            service.execute(
                db,
                run_id=run_id,
                owner_user_id=actor.id,
                confirmed=True,
                valid_rows_only=bool(params.get("valid_rows_only") is True),
                preview_revision=revision or None,
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
    knowledge = _knowledge_receipt(data, actor.id) if ok else {}
    summary["knowledge"] = knowledge
    template = _template_receipt(data, actor.id) if ok else {}
    summary["template"] = template
    knowledge_note = ""
    if ok:
        action = str(knowledge.get("action") or "")
        reason = str(knowledge.get("reason") or "")
        if action == "error":
            knowledge_note = "；知识库同步失败，业务数据已入库，可稍后在数据对接中心重试"
        elif action in {"new", "update"}:
            knowledge_note = "；原件已同步到知识库"
        elif action == "skip" and reason not in {"missing_upload", "upload_not_found"}:
            knowledge_note = "；知识库已有相同内容，已跳过"
    template_note = ""
    if ok:
        action = str(template.get("action") or "")
        if action == "error":
            template_note = "；模板库登记失败，业务数据已入库"
        elif action == "new":
            names = [str(name) for name in template.get("names") or [] if name]
            template_note = (
                f"；已从原件切出 {len(names)} 个模板并登记到模板库（{'、'.join(names)}）"
                if names
                else "；原件区段已登记到模板库"
            )
        elif action == "skip" and str(template.get("reason") or "") == "duplicate_name":
            template_note = "；模板库已有同名模板，已跳过"
    return {
        "success": ok,
        "error_code": None if ok else f"elt_execute_{data.get('status')}",
        "message": (
            f"ELT 导入完成：写入 {summary['executed_rows']} 行，"
            f"失败 {summary['error_rows']} 行{knowledge_note}{template_note}。"
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
