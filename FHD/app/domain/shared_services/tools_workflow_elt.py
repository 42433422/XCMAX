"""ELT 导入工具：让智能对话通过数据对接中心（ELT）完成预演与入库。

与 `import_excel_to_database` 直接写库不同，这里复用 ELT 的
"预演 → 确认 → 执行 → 回执" 流程，具备源快照、映射核对与回滚能力。
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_

from app.application.tools.workflow_spreadsheet_scope import resolve_owned_upload_path
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.auth.agent_mod_scope import _bound_actor
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import BOUNDARY_ERRORS
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
            "file_name": str(row.file_name or ""),
        }


_IMPORT_WINDOW_MINUTES = 30


def _recent_upload_ids(runtime_context: dict[str, Any]) -> list[str]:
    """本轮（最近一段时间）上传的 ELT 文件；用户说「导入」时用它替代模型枚举。"""
    try:
        actor = _bound_actor(runtime_context)
        cutoff = utc_now_naive() - timedelta(minutes=_IMPORT_WINDOW_MINUTES)
        with get_db() as db:
            rows = (
                db.query(EltUpload.id)
                .filter(
                    EltUpload.owner_user_id == actor.id,
                    EltUpload.tenant_id == tenant_id_for_write(),
                    EltUpload.created_at >= cutoff,
                    EltUpload.expires_at > utc_now_naive(),
                )
                .order_by(EltUpload.created_at.asc())
                .limit(_MAX_BATCH_IMPORTS)
                .all()
            )
    except RECOVERABLE_ERRORS:
        return []
    return [str(row[0]) for row in rows]


def _publish_note(text: str) -> None:
    """把逐文件进度推给对话流；没有流式上下文时静默忽略。"""
    from app.infrastructure.chat_stream_lifetime import publish_stream_note

    publish_stream_note(text)


def _publish_file_stage(
    *,
    node_id: str,
    action: str,
    phase: str,
    success: bool | None = None,
    output: str = "",
    error: str = "",
) -> None:
    """把「正在处理哪个文件 / 哪个文件已完成」推进执行链。

    只发结构化 tool_call 事件，前端按 node_id 原地增改；发布失败不影响导入。
    """
    record: dict[str, Any] = {
        "node_id": node_id,
        "tool_id": "elt_import",
        "action": action,
        "phase": phase,
    }
    if phase == "finished":
        record["success"] = bool(success)
        record["output_preview"] = str(output or "")[:200]
        if error:
            record["error"] = str(error)[:200]
    try:
        from app.infrastructure.chat_stream_lifetime import publish_stream_tool_record

        publish_stream_tool_record(record)
    except BOUNDARY_ERRORS:  # noqa: BLE001 - 观测通道不得改变导入结果
        pass


def _upload_label(path: str, runtime_context: dict[str, Any]) -> str:
    """批次进度里用的可读文件名；查不到时退回路径名。"""
    try:
        name = str(_owned_upload(path, runtime_context).get("file_name") or "").strip()
    except RECOVERABLE_ERRORS:
        name = ""
    return name or Path(str(path)).name or str(path)


def _run_label(run_id: str, runtime_context: dict[str, Any]) -> str:
    """执行阶段按预演编号反查文件名，用于逐文件进度提示。"""
    from app.db.models.elt import EltRun, EltUpload

    try:
        actor = _bound_actor(runtime_context)
        with get_db() as db:
            row = (
                db.query(EltUpload.file_name)
                .join(EltRun, EltRun.upload_id == EltUpload.id)
                .filter(EltRun.id == run_id, EltRun.owner_user_id == actor.id)
                .first()
            )
    except RECOVERABLE_ERRORS:
        return run_id
    name = str(row[0]) if row else ""
    return name or run_id


def _batch_progress_note(action: str, index: int, total: int, label: str) -> None:
    _publish_note(f"正在{action} {index}/{total}：{label}")


_RESERVED_SECONDS = 3.0
_MIN_WAIT_SECONDS = 5.0


def _remaining_budget(runtime_context: dict[str, Any]) -> float | None:
    """按本轮工具调用剩余预算收口，避免把「还在跑」判成结果未知。"""
    deadline = (runtime_context or {}).get("deadline_monotonic")
    if isinstance(deadline, (int, float)):
        return float(deadline) - time.monotonic() - _RESERVED_SECONDS
    return None


def _wait_timeout(params: dict[str, Any], runtime_context: dict[str, Any], cap: float) -> float:
    declared = params.get("_wait_timeout")
    limit = float(declared) if isinstance(declared, (int, float)) and declared > 0 else cap
    remaining = _remaining_budget(runtime_context)
    if remaining is None:
        return min(limit, cap)
    return max(0.0, min(limit, cap, remaining))


def _batch_result_text(action: str, label: str, out: dict[str, Any]) -> str:
    """单个文件的收口说明；预演/执行共用，供进度提示与执行链复用。"""
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    if not out.get("success"):
        return f"「{label}」{action}失败：{out.get('message') or '未知原因'}"
    if action == "预演":
        return (
            f"「{label}」预演完成：共 {data.get('total_rows', 0)} 行，"
            f"新增 {data.get('new_rows', 0)}、更新 {data.get('update_rows', 0)}、"
            f"跳过 {data.get('skip_rows', 0)}、错误 {data.get('error_rows', 0)}"
        )
    text = f"「{label}」导入完成：写入 {data.get('executed_rows', 0)} 行"
    if data.get("skip_rows"):
        text += f"，重复跳过 {data.get('skip_rows')} 行"
    return text


def _batch_result_note(action: str, label: str, out: dict[str, Any]) -> None:
    _publish_note(_batch_result_text(action, label, out))


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


def _execution_message(summary: dict, notes: str) -> str:
    """导入回执必须说清「写了多少 / 跳过多少」，否则全量重复时会误报导入成功。"""
    executed = int(summary.get("executed_rows") or 0)
    skipped = int(summary.get("skip_rows") or 0)
    message = f"ELT 导入完成：写入 {executed} 行，失败 {summary['error_rows']} 行"
    if skipped:
        message += f"，重复跳过 {skipped} 行"
        if executed == 0:
            message += "（本次全部判定为重复，业务库没有新增数据）"
    return f"{message}{notes}。"


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


def _template_target_type(data: dict[str, Any]) -> str:
    """模板登记必须用真实注册过的目标类型；auto/abnormal 一律按通用表处理。"""
    target_type = str(data.get("target_type") or "").strip()
    if target_type in {"", "auto", "abnormal"}:
        return "dynamic_table"
    return target_type


def _register_header_template(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """通用表已经是模板库里的表：按每张通用表写一个可见模板。

    模板库页面读的是 ``templates`` 表 + 模板文件；只写 ``elt_templates``
    在页面上是看不见的，所以这里直接落成可见模板，名字与列沿用通用表本身。
    """
    import json

    from app.application.template_app_service import get_template_app_service
    from app.db.models.elt import EltDynamicTable
    from app.utils.path_io.path_utils import get_app_data_dir

    file_name = str(data.get("file_name") or "")
    specs: list[tuple[str, list[str]]] = []
    existing_names: set[str] = set()
    try:
        with get_db() as db:
            tables = (
                db.query(EltDynamicTable)
                .filter(
                    EltDynamicTable.tenant_id == tenant_id_for_write(),
                    EltDynamicTable.owner_user_id == owner_id,
                    EltDynamicTable.source_file == file_name,
                )
                .order_by(EltDynamicTable.created_at.asc())
                .all()
            )
            for table in tables:
                name = str(table.name or "").strip()
                headers = [str(h) for h in json.loads(table.headers_json or "[]") or [] if str(h)]
                if name and headers:
                    specs.append((name, headers))
    except RECOVERABLE_ERRORS:
        return {}
    if not specs:
        return {}
    service = get_template_app_service()
    try:
        existing_names = {
            str(item.get("name") or "").strip()
            for item in (service.get_templates().get("templates") or [])
            if str(item.get("source") or "") == "db"
        }
    except RECOVERABLE_ERRORS:
        existing_names = set()
    out_dir = (
        Path(get_app_data_dir()).resolve()
        / "tenants"
        / str(tenant_id_for_write())
        / "template_library"
        / str(owner_id)
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    template_ids: list[Any] = []
    for name, headers in specs:
        if name in existing_names:
            continue
        try:
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = name[:31] or "Sheet1"
            sheet.append(headers)
            digest = hashlib.sha1("|".join(headers).encode("utf-8")).hexdigest()[:12]
            destination = out_dir / f"{_safe_file_component(name)}-{digest}.xlsx"
            workbook.save(destination)
            workbook.close()
            result = service.save_template(
                {
                    "template_name": name,
                    "template_key": f"ELT_{digest}",
                    "template_type": "Excel",
                    "original_file_path": str(destination),
                    "analyzed_data": {
                        "category": "excel",
                        "fields": [
                            {"label": header, "value": "", "type": "dynamic"} for header in headers
                        ],
                        "preview_data": {
                            "sample_rows": [],
                            "sheet_name": name,
                            "grid_preview": _grid_preview(str(destination)),
                        },
                    },
                }
            )
        except RECOVERABLE_ERRORS:
            continue
        if not result.get("success"):
            continue
        existing_names.add(name)
        names.append(name)
        template_ids.append(result.get("id"))
    if not names:
        return {"action": "skip", "reason": "duplicate_name"}
    return {"action": "new", "names": names, "template_ids": template_ids}


def _template_receipt(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """业务入库完成后，把预演切出的区段登记进模板库。

    ELT 的第一步就是把上传文件切成模板区段，模板库应保存这些区段，
    而不是整份原始文件（原始文件可能含多个模板甚至无关工作表）。
    模板库写入失败不影响已完成的导入，但必须在回执里如实说明。
    """
    upload_id = str(data.get("upload_id") or "")
    if not upload_id:
        return {"action": "skip", "reason": "missing_upload"}
    from app.application import template_ai
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
        # 通用表没有区段信息时按表头登记，避免「导入完成但模板库空白」。
        fallback = _register_header_template(data, owner_id)
        if fallback:
            return fallback
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
        template_type = _template_target_type(data)
        service = get_template_app_service()
        templates = [item for item in (service.get_templates().get("templates") or []) if str(item.get("source") or "") == "db"]
        existing_names = {
            str(item.get("name") or "").strip(): str(item.get("file_path") or item.get("path") or "")
            for item in templates
        }
        existing_keys = {str(item.get("template_key") or "").strip() for item in templates}
        # 已登记过的机器占位名（如“…-Sheet1”）有界地换成业务名，避免模板库越积越乱。
        renamed = template_ai.rename_meaningless_templates(service)
        for entry in renamed:
            existing_names.pop(entry["from"], None)
            existing_names[entry["to"]] = ""
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
            base = ""
            if region.get("status") == "selected":
                base = template_ai.suggest_template_name(
                    file_name=file_name,
                    sheet_title=str(meta.get("sheet") or ""),
                    region_label=str(region.get("range") or ""),
                    target_type=target_type,
                    headers=meta.get("headers") or [],
                )
            if not base:
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
        receipt: dict[str, Any] = {
            "action": "new",
            "names": names,
            "template_ids": template_ids,
        }
        if renamed:
            receipt["renamed"] = renamed
        return receipt
    except TenantScopeError:
        return {"action": "error", "reason": "missing_tenant"}
    except RECOVERABLE_ERRORS as exc:
        return {"action": "error", "reason": str(exc)[:200]}


def _resolve_template(upload: dict[str, str], owner_id: int) -> tuple[str, dict]:
    """识别目标类型，并在模板可确定时自动套用。

    先让模型识别目标、挑模板或直接生成映射；模型不可用或不确定时回退规则。
    只有「缺失必填字段」这类数据事实才会挡住套用，不再因为类型没被规则认出而拒绝。
    """
    from app.application import template_ai

    features = _upload_features(upload, owner_id)
    rules = _rule_target(upload, owner_id)
    # 送货单依赖 ELT 的多工作表关联预演，保持原有规则路径，不让模型改判。
    if str(rules.get("target_type") or "") == "shipment_records":
        return _rule_template(rules, owner_id, upload)
    candidates = _list_import_templates(owner_id)
    proposal = template_ai.propose_import_template(
        file_name=Path(str(upload.get("storage_path") or "")).name,
        sheet_title=features.get("sheet") or "",
        headers=features.get("headers") or [],
        samples=features.get("samples") or {},
        candidates=candidates,
        targets=_target_catalog(),
    )
    if proposal:
        index = int(proposal.get("template_index") or -1)
        if 0 <= index < len(candidates):
            matched = candidates[index]
            return str(matched.get("target_type") or "auto"), {
                **matched,
                "match_confidence": proposal["confidence"],
                "match_reason": proposal["reason"],
                "matched_by": "ai",
            }
        created = _create_ai_import_template(owner_id, features, proposal, candidates)
        if created:
            return str(created.get("target_type") or "auto"), created
    return _rule_template(rules, owner_id, upload)


def _rule_target(upload: dict[str, str], owner_id: int) -> dict[str, Any]:
    from app.application.elt.target_detection import detect_elt_target

    try:
        return detect_elt_target(
            upload.get("storage_path") or "",
            suffix=upload.get("suffix") or "",
            owner_user_id=owner_id,
        )
    except RECOVERABLE_ERRORS:
        return {}


def _rule_template(
    rules: dict[str, Any], owner_id: int, upload: dict[str, str]
) -> tuple[str, dict]:
    """规则兜底：唯一候选直接套用，多候选用模型排序（不可用则人工确认）。"""
    target_type = str(rules.get("target_type") or "auto").strip() or "auto"
    if target_type in {"auto", "abnormal"}:
        return target_type, {}
    candidates = [
        item for item in _list_import_templates(owner_id) if item.get("target_type") == target_type
    ]
    if not candidates:
        return target_type, {}
    if len(candidates) == 1:
        return target_type, candidates[0]
    from app.application.template_ai import rank_templates

    requirement = f"{Path(str(upload.get('storage_path') or '')).stem}（导入目标：{target_type}）"
    picked = rank_templates(requirement=requirement, candidates=candidates)
    if not picked:
        return target_type, {}
    template = dict(picked["template"])
    template["match_confidence"] = picked["confidence"]
    template["match_reason"] = picked["reason"]
    template["matched_by"] = "ai_rank"
    return target_type, template


def _list_import_templates(owner_id: int) -> list[dict[str, Any]]:
    from app.application.elt.service import get_elt_service

    try:
        with get_db() as db:
            return get_elt_service().list_templates(db, owner_user_id=owner_id)
    except RECOVERABLE_ERRORS:
        return []


_IMPORT_TARGET_TYPES = (
    "customers",
    "customer_products",
    "products",
    "purchase_orders",
    "shipment_records",
    "attendance",
)


def _target_catalog() -> list[dict[str, Any]]:
    """给模型的导入目标清单；兼容/导出类目标不参与自动识别。"""
    from app.application.elt.targets import get_adapter

    catalog: list[dict[str, Any]] = []
    for target_type in _IMPORT_TARGET_TYPES:
        try:
            capability = get_adapter(target_type).capability()
        except RECOVERABLE_ERRORS:
            continue
        catalog.append(
            {
                "type": capability["type"],
                "label": capability["label"],
                "fields": capability["fields"],
            }
        )
    return catalog


def _upload_features(upload: dict[str, str], owner_id: int) -> dict[str, Any]:
    """读取上传文件前若干行，取出表头与样例行（不解析整份数据）。"""
    sheet, rows = _read_head_rows(
        str(upload.get("storage_path") or ""),
        str(upload.get("suffix") or ""),
        owner_id,
    )
    found = _header_positions(rows)
    if found is None:
        return {"headers": [], "samples": {}, "sheet": sheet}
    header_index, columns = found
    first = rows[header_index]
    headers: list[str] = []
    picked: list[int] = []
    for column in columns:
        header = str(first[column]).strip()[:80]
        if not header or header in headers:
            continue
        headers.append(header)
        picked.append(column)
        if len(headers) >= 40:
            break
    samples: dict[str, list[str]] = {header: [] for header in headers}
    for row in rows[header_index + 1 : header_index + 8]:
        for header, column in zip(headers, picked):
            if column < len(row) and str(row[column]).strip():
                if len(samples[header]) < 3:
                    samples[header].append(str(row[column]).strip()[:60])
    return {
        "headers": headers,
        "samples": samples,
        "sheet": sheet,
        "file_name": Path(str(upload.get("storage_path") or "")).name,
    }


def _header_positions(rows: list[list[str]]) -> tuple[int, list[int]] | None:
    """找到最像表头的一行：至少两个非空单元格且以文字为主。"""
    for index, row in enumerate(rows[:12]):
        filled = [column for column, cell in enumerate(row) if str(cell).strip()]
        if len(filled) < 2:
            continue
        text_like = sum(
            1
            for column in filled
            if not str(row[column]).strip().replace(".", "", 1).replace(",", "", 1).isdigit()
        )
        if text_like * 2 >= len(filled):
            return index, filled[:40]
    return None


def _read_head_rows(path: str, suffix: str, owner_id: int) -> tuple[str, list[list[str]]]:
    from app.application.shipment_excel_elt_security import open_elt_input_file

    source = Path(path)
    ext = str(suffix or source.suffix).lower()
    try:
        if ext == ".csv":
            rows: list[list[str]] = []
            with (
                open_elt_input_file(source, owner_user_id=owner_id) as stream,
                io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="")
                as handle,
            ):
                for index, row in enumerate(csv.reader(handle)):
                    rows.append([str(cell).strip() for cell in row][:60])
                    if index >= 14:
                        break
            return "CSV", rows
        if ext in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook

            with open_elt_input_file(source, owner_user_id=owner_id) as stream:
                workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
                best_sheet, best_rows = "", []
                try:
                    for worksheet in workbook.worksheets[:8]:
                        rows = []
                        for index, values in enumerate(worksheet.iter_rows(values_only=True)):
                            rows.append(
                                ["" if value is None else str(value).strip() for value in values][:60]
                            )
                            if index >= 14:
                                break
                        if sum(1 for row in rows for cell in row if cell) > sum(
                            1 for row in best_rows for cell in row if cell
                        ):
                            best_sheet, best_rows = worksheet.title, rows
                finally:
                    workbook.close()
                return best_sheet, best_rows
    except RECOVERABLE_ERRORS:
        return "", []
    return "", []


def _create_ai_import_template(
    owner_id: int,
    features: dict[str, Any],
    proposal: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """把模型提议落成导入模板；映射必须覆盖必填字段，否则不建（交给预演自己补映射）。"""
    from app.application import template_ai
    from app.application.elt.service import get_elt_service
    from app.application.elt.targets import get_adapter

    target_type = str(proposal.get("target_type") or "")
    try:
        adapter = get_adapter(target_type)
    except RECOVERABLE_ERRORS:
        return {}
    signature = sorted(str(header) for header in features.get("headers") or [])
    # 同一目标 + 同一表头签名视为同一模板，避免每次预演都新建一份。
    for item in candidates:
        stored = ((item.get("version") or {}).get("source_features") or {}).get("headers") or []
        if item.get("target_type") == target_type and sorted(str(h) for h in stored) == signature:
            return {
                **item,
                "matched_by": "signature",
                "match_confidence": proposal.get("confidence"),
                "match_reason": proposal.get("reason") or "",
            }
    allowed = {field.key for field in adapter.fields}
    headers = set(signature)
    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in proposal.get("field_mappings") or []:
        source = str(item.get("source") or "")
        field = str(item.get("target") or "")
        if source not in headers or field not in allowed or field in seen:
            continue
        seen.add(field)
        mappings.append(
            {
                "source": source,
                "target": field,
                "confidence": item.get("confidence") or proposal.get("confidence") or 0,
                "suggested_by": "llm",
            }
        )
    required = {field.key for field in adapter.fields if field.required}
    if not mappings or not required.issubset(seen):
        return {}
    name = str(proposal.get("name") or "") or template_ai.suggest_template_name(
        file_name=str(features.get("file_name") or "导入模板"),
        sheet_title=str(features.get("sheet") or ""),
        target_type=target_type,
        headers=features.get("headers") or [],
    )
    if not name:
        return {}
    draft = {
        "field_mappings": mappings,
        "validation_rules": [],
        "match_keys": list(adapter.default_match_keys),
        "allowed_update_fields": [],
        "action_rules": {"duplicate": "skip"},
    }
    try:
        with get_db() as db:
            created = get_elt_service().create_template(
                db,
                owner_user_id=owner_id,
                name=name,
                target_type=target_type,
                draft=draft,
                source_features={
                    "headers": features.get("headers") or [],
                    "sheet": features.get("sheet") or "",
                    "ai_generated": True,
                    "ai_confidence": proposal.get("confidence"),
                    "ai_reason": proposal.get("reason") or "",
                },
            )
    except RECOVERABLE_ERRORS:
        return {}
    return {
        **created,
        "ai_generated": True,
        "match_confidence": proposal.get("confidence"),
        "match_reason": proposal.get("reason") or "",
        "matched_by": "ai_created",
    }


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
    # 模型识别出的非送货单目标显式传入，避免 ELT 再按旧规则改判；送货单保留关联预演。
    resolved_target = "auto"
    if template and target_type not in {"auto", "abnormal", "shipment_records"}:
        resolved_target = target_type
    try:
        with get_db() as db:
            created = service.create_preview(
                db,
                owner_user_id=actor.id,
                upload_id=upload["id"],
                # 送货单仍交给 ELT 自动识别，多工作表会同时生成关联预演。
                target_type=resolved_target,
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
        timeout=_wait_timeout(params, runtime_context, PREVIEW_TIMEOUT_SECONDS),
    )
    summary = _summary(data)
    if not summary.get("target_type"):
        summary["target_type"] = target_type
    summary["template_id"] = str(template.get("id") or "")
    summary["template_name"] = str(template.get("name") or "")
    summary["template_source"] = str(template.get("matched_by") or "")
    summary["template_confidence"] = template.get("match_confidence")
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
    # 用户明确接受 AI 建议映射后，置信度不足的映射不再阻断（执行阶段需传同一个参数）。
    accept_suggested = params.get("accept_suggested") is True
    blocked_by_errors = bool(error_rows) and not accept_valid_rows
    # 有错误行或映射待确认时，ELT 会阻断整批执行；提前告知调用方，避免执行阶段才失败。
    summary["executable"] = not blocked_by_errors and (not pending_mappings or accept_suggested)
    # 只剩映射置信度不足时，用户可以一次性接受 AI 建议直接执行。
    summary["executable_with_suggestions"] = not blocked_by_errors
    ok = data.get("status") == "preview_ready"
    template_note = ""
    if summary["template_name"]:
        ai_note = "（AI 识别）" if summary["template_source"] in {"ai", "ai_created", "ai_rank"} else ""
        template_note = f"，已套用导入模板{ai_note}「{summary['template_name']}」"
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
        if pending_mappings and not accept_suggested:
            blockers.append(
                f"{len(pending_mappings)} 个字段映射为 AI 建议（{'、'.join(pending_mappings[:8])}），"
                "用户确认后可一次性接受并入库（执行时传 accept_suggested=true）。"
            )
        if blockers:
            message += "".join(blockers)
    # 预演发现阻断项时，契约要求编排在此暂停询问用户，而不是继续执行后失败。
    requires_decision = ok and not summary["executable"]
    resume_params: dict[str, Any] = {}
    if requires_decision and accept_valid_rows is False and error_rows:
        resume_params["valid_rows_only"] = True
    if requires_decision and pending_mappings and not blocked_by_errors:
        resume_params["accept_suggested"] = True
    # 自动审批档：预演通过后直接入库，避免计划只排了预演就停在 preview_ready，
    # 导致「导入成功但模板库/知识库空白」。
    if ok and summary["executable"] and str(runtime_context.get("chat_approval_mode") or "") == "auto":
        executed = _execute({"run_id": run_id}, runtime_context)
        if executed.get("success"):
            data = executed.get("data") if isinstance(executed.get("data"), dict) else {}
            data["preview"] = summary
            executed["data"] = data
            executed["preview"] = True
            return executed
    return {
        "success": ok,
        "preview": True,
        "error_code": None if ok else "elt_preview_not_ready",
        "message": message,
        "requires_user_decision": requires_decision,
        "question": message if requires_decision else "",
        # 用户确认后重新执行预演/执行时带上解除阻断的参数，避免再次停在同一个问题。
        "resume_params": resume_params,
        "data": summary,
    }


def _receipt_tenant(data: dict[str, Any]) -> int:
    """登记线程拿不到调用线程的租户上下文，先固定本次运行的租户再进线程。"""
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_id_for_write

    try:
        return tenant_id_for_write()
    except TenantScopeError:
        pass
    from app.db.models.elt import EltRun

    with get_db() as db:
        row = (
            db.query(EltRun.tenant_id)
            .filter(EltRun.id == str(data.get("id") or data.get("run_id") or ""))
            .first()
        )
    if row is None:
        raise TenantScopeError("写入业务数据缺少 tenant_id")
    return int(row[0])


def _parallel_receipts(data: dict[str, Any], owner_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """知识库与模板库互不依赖，一次导入内并行写，互不拖累。"""
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.tenant_scope import tenant_scope

    tenant = _receipt_tenant(data)

    def knowledge_receipt() -> dict[str, Any]:
        with tenant_scope(tenant):
            return _knowledge_receipt(data, owner_id)

    def template_receipt() -> dict[str, Any]:
        with tenant_scope(tenant):
            return _template_receipt(data, owner_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        knowledge_future = pool.submit(knowledge_receipt)
        template_future = pool.submit(template_receipt)
        try:
            knowledge = knowledge_future.result()
        except RECOVERABLE_ERRORS as exc:
            knowledge = {"action": "error", "reason": str(exc)[:200]}
        try:
            template = template_future.result()
        except RECOVERABLE_ERRORS as exc:
            template = {"action": "error", "reason": str(exc)[:200]}
    return knowledge, template


def _finalize_import(
    data: dict[str, Any], owner_id: int
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """一次导入的唯一收口：并行写知识库与模板库，并生成如实回执。

    预演自动入库、正常执行、「已完成」补登三条路径都只调用它，不再各写一份。
    """
    knowledge, template = _parallel_receipts(data, owner_id)
    return knowledge, template, _receipt_notes(knowledge, template)


def _receipt_notes(knowledge: dict[str, Any], template: dict[str, Any]) -> str:
    """把知识库与模板库的登记结果转成一句说明；跳过与失败都必须写清原因。"""
    note = ""
    action = str(knowledge.get("action") or "")
    if action == "error":
        note += "；知识库同步失败，业务数据已入库"
    elif action in {"new", "update"}:
        note += "；原件已同步到知识库"
    elif action == "skip":
        note += "；" + {
            "empty_document": "原件没有可提取的正文，未写入知识库",
            "upload_missing": "上传文件已过期，未同步知识库",
            "missing_upload": "缺少上传记录，未同步知识库",
            "upload_not_found": "未找到上传记录，未同步知识库",
        }.get(str(knowledge.get("reason") or ""), "知识库已有相同内容，已跳过")
    template_action = str(template.get("action") or "")
    if template_action == "error":
        note += "；模板库登记失败，业务数据已入库"
    elif template_action == "new":
        names = [str(name) for name in template.get("names") or [] if name]
        note += f"；已登记模板到模板库（{'、'.join(names)}）" if names else "；模板已登记到模板库"
    elif template_action == "skip":
        note += "；" + {
            "no_region": "未切出模板区段，模板库未登记",
            "upload_not_found": "未找到上传记录，模板库未登记",
            "upload_missing": "上传文件已过期，模板库未登记",
            "missing_upload": "缺少上传记录，模板库未登记",
        }.get(str(template.get("reason") or ""), "模板库已有同名模板，已跳过")
    return note


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
            status = str(current.get("status") or "")
            if status in PREVIEW_PENDING:
                # 计划可能把执行排到预演还没跑完的时候：先等预演结束，再按结果执行，
                # 不能直接报「请先完成预演再执行」把整条导入判失败。
                _wait(
                    service,
                    run_id,
                    actor.id,
                    pending=PREVIEW_PENDING,
                    timeout=_wait_timeout(params, runtime_context, PREVIEW_TIMEOUT_SECONDS),
                )
                with get_db() as wait_db:
                    current = service.get_run(wait_db, run_id=run_id, owner_user_id=actor.id)
                status = str(current.get("status") or "")
            revision = str(current.get("preview_revision") or "")
            # 自动审批档下预演可能已经触发入库（executing/completed）：
            # 计划里的执行步骤只需等待或收口，重复调用 execute 会报「请先完成预演再执行」。
            if status not in ("executing", "completed"):
                service.execute(
                    db,
                    run_id=run_id,
                    owner_user_id=actor.id,
                    confirmed=True,
                    valid_rows_only=bool(params.get("valid_rows_only") is True),
                    preview_revision=revision or None,
                    accept_suggested=bool(params.get("accept_suggested") is True),
                )
    except EltError as exc:
        return {"success": False, "error_code": exc.code, "message": exc.message}
    data = _wait(
        service,
        run_id,
        actor.id,
        pending=EXECUTION_PENDING,
        timeout=_wait_timeout(params, runtime_context, EXECUTION_TIMEOUT_SECONDS),
    )
    summary = _summary(data)
    ok = data.get("status") == "completed"
    companion = _execute_linked_companion(service, actor, data) if ok else {}
    if companion:
        summary["customer_products"] = companion
    # 业务数据已入库；知识库与模板库并行写，一个慢或失败不影响另一个。
    knowledge, template, notes = _finalize_import(data, actor.id) if ok else ({}, {}, "")
    summary["knowledge"] = knowledge
    summary["template"] = template
    message = (
        _execution_message(summary, notes + _companion_note(companion))
        if ok
        else f"ELT 导入未完成：{summary.get('error') or data.get('stage')}"
    )
    return {
        "success": ok,
        "error_code": None if ok else f"elt_execute_{data.get('status')}",
        "message": message,
        "data": summary,
    }


def _execute_linked_companion(service, actor, data: dict) -> dict[str, Any]:
    """同一文件附表生成的「客户及产品」预演，在主运单执行时一并落库。

    只预演不执行会让客户库/产品库永远没有数据，而用户看到的是「导入完成」。
    """
    from app.application.elt.errors import EltError

    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    link = details.get("linked_customer_products_preview") or {}
    run_id = str(link.get("run_id") or "")
    if not run_id or str(link.get("status") or "") != "preview_ready":
        return {}
    try:
        with get_db() as db:
            current = service.get_run(db, run_id=run_id, owner_user_id=actor.id)
            if str(current.get("status") or "") != "preview_ready":
                return {}
            revision = str(current.get("preview_revision") or "")
            service.execute(
                db,
                run_id=run_id,
                owner_user_id=actor.id,
                confirmed=True,
                # 附表通常夹杂非客户/产品行，只写校验通过的行，避免整批被阻断。
                valid_rows_only=True,
                preview_revision=revision or None,
                accept_suggested=True,
            )
        waited = _wait(service, run_id, actor.id, pending=EXECUTION_PENDING, timeout=30.0)
    except EltError:
        return {"run_id": run_id, "status": "failed"}
    result = _summary(waited)
    result["run_id"] = run_id
    return result


def _companion_note(companion: dict) -> str:
    if not companion:
        return ""
    if companion.get("status") != "completed":
        return "；客户及产品未能写入，请到数据对接中心重试"
    executed = int(companion.get("executed_rows") or 0)
    skipped = int(companion.get("skip_rows") or 0)
    errors = int(companion.get("error_rows") or 0)
    note = f"；客户及产品写入 {executed} 行"
    if skipped or errors:
        note += f"（重复跳过 {skipped} 行，非客户/产品 {errors} 行已忽略）"
    return note


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
        paths = _split_paths(payload.get("file_paths"))
        if not paths and not str(payload.get("file_path") or "").strip():
            # 用户说「导入」但模型只看到被截断的附件清单时，按本轮上传的全部文件预演，
            # 不让模型枚举决定导入范围。
            recent = _recent_upload_ids(runtime_context)
            if len(recent) > 1:
                return _preview_batch(recent, payload, runtime_context)
        if paths:
            # 模型只看到被截断的附件清单时，会少传文件；用户没有点名具体文件时按本轮全部上传预演。
            if runtime_context.get("chat_approval_mode") == "auto" and not _mentions_file(
                user_message, paths
            ):
                recent = _recent_upload_ids(runtime_context)
                if len(recent) > len(paths):
                    paths = recent
            return _preview_batch(paths, payload, runtime_context)
        if not str(payload.get("file_path") or "").strip():
            return {
                "success": False,
                "error_code": "elt_file_path_required",
                "message": "请提供 file_path（单个文件）或 file_paths（整批文件）后再预演。",
            }
        try:
            label = _upload_label(str(payload.get("file_path") or ""), runtime_context)
            node_id = "elt-preview-1"
            stage_action = f"预演 1/1：{label}"
            _publish_file_stage(node_id=node_id, action=stage_action, phase="started")
            out = _preview(payload, runtime_context)
            _publish_file_stage(
                node_id=node_id,
                action=stage_action,
                phase="finished",
                success=bool(out.get("success")),
                output=_batch_result_text("预演", label, out),
                error="" if out.get("success") else str(out.get("message") or ""),
            )
            return out
        except PermissionError as err:
            return {
                "success": False,
                "error_code": "spreadsheet_access_denied",
                "message": str(err),
            }
    if action == "execute":
        ids = _split_run_ids(payload.get("run_ids")) or _split_run_ids(payload.get("run_id"))
        if len(ids) > 1:
            return _execute_batch(ids, payload, runtime_context)
        if ids:
            label = _run_label(ids[0], runtime_context)
            node_id = "elt-execute-1"
            stage_action = f"导入 1/1：{label}"
            _publish_file_stage(node_id=node_id, action=stage_action, phase="started")
            out = _execute({**payload, "run_id": ids[0]}, runtime_context)
            _publish_file_stage(
                node_id=node_id,
                action=stage_action,
                phase="finished",
                success=bool(out.get("success")),
                output=_batch_result_text("导入", label, out),
                error="" if out.get("success") else str(out.get("message") or ""),
            )
            return out
        return _execute(payload, runtime_context)
    return {"success": False, "message": f"未知的 ELT 导入操作：{action}"}


def _mentions_file(message: str, paths: list[str]) -> bool:
    """用户是否在消息里点名了某个文件；没点名时按本轮全部上传处理。"""
    text = str(message or "")
    return any(
        Path(str(path)).stem.strip() and Path(str(path)).stem.strip() in text
        for path in paths
    )


def _split_paths(value: object) -> list[str]:
    """file_paths 可能是数组，也可能是被包成数组的逗号分隔文件名串。"""
    import re

    raw = [str(item) for item in value] if isinstance(value, (list, tuple)) else []
    parts: list[str] = []
    for item in raw:
        parts.extend(re.split(r"[,;，；\n]+", item))
    return [part.strip() for part in parts if part.strip()]


def _split_run_ids(value: object) -> list[str]:
    """run_id 可能写成单个编号、逗号分隔字符串，或被包成只含一个字符串的数组。"""
    import re

    if isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    else:
        raw = [str(value or "")]
    parts: list[str] = []
    for item in raw:
        parts.extend(re.split(r"[,;，；\s]+", item))
    return [part.strip() for part in parts if part.strip()]


_MAX_BATCH_IMPORTS = 50
_IMPORT_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv", ".docx", ".pdf")
_DIRECTORY_SCAN_LIMIT = 400


def _expand_directory_paths(
    paths: list[str], runtime_context: dict[str, Any]
) -> tuple[list[str], list[dict]]:
    """模型把本地目录当文件传时，展开为目录内已上传的文件；展开不了给出可操作提示。"""
    expanded: list[str] = []
    unresolved: list[dict] = []
    for path in paths:
        candidate = Path(str(path)).expanduser()
        try:
            is_dir = candidate.is_dir()
        except OSError:
            is_dir = False
        if not is_dir:
            expanded.append(path)
            continue
        names: list[str] = []
        try:
            for entry in candidate.rglob("*"):
                if len(names) >= _DIRECTORY_SCAN_LIMIT:
                    break
                if entry.is_file() and entry.suffix.lower() in _IMPORT_SUFFIXES:
                    names.append(entry.name)
        except OSError:
            names = []
        matched = [name for name in names if _owned_upload(name, runtime_context)]
        if matched:
            expanded.extend(matched)
            continue
        unresolved.append(
            {
                "file_path": str(path),
                "file_name": candidate.name,
                "success": False,
                "error_code": "directory_needs_upload",
                "message": (
                    f"「{candidate.name}」是本地目录，ELT 只导入已上传到本账号的文件；"
                    f"目录内 {len(names)} 个可导入文件尚无上传记录，"
                    "请先用「上传附件」或数据对接中心上传后再导入。"
                ),
            }
        )
    return expanded, unresolved


def _single_params(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in {"file_paths", "run_ids"}}


def _preview_batch(paths: list[str], payload: dict, runtime_context: dict) -> dict:
    """整批预演：每个文件独立出结果，单个失败不影响其余。"""
    targets = paths[:_MAX_BATCH_IMPORTS]
    base = _single_params(payload)
    targets, unresolved = _expand_directory_paths(targets, runtime_context)
    items: list[dict] = list(unresolved)
    total = len(targets) + len(unresolved)
    processed = len(unresolved)
    for index, path in enumerate(targets, start=1):
        remaining = _remaining_budget(runtime_context)
        if remaining is not None and remaining <= _MIN_WAIT_SECONDS:
            # 本轮预算不足：保留已完成结果，剩余文件下一轮继续，不能报成未知超时。
            deferred = total - index + 1
            _publish_note(f"本轮时间不足，剩余 {deferred} 个文件将在下一轮继续导入")
            break
        label = _upload_label(path, runtime_context)
        node_id = f"elt-preview-{index}"
        action = f"预演 {index}/{total}：{label}"
        _publish_file_stage(node_id=node_id, action=action, phase="started")
        _batch_progress_note("预演", index, total, label)
        try:
            out = _preview({**base, "file_path": path}, runtime_context)
        except PermissionError as err:
            out = {"success": False, "error_code": "spreadsheet_access_denied", "message": str(err)}
        _batch_result_note("预演", label, out)
        _publish_file_stage(
            node_id=node_id,
            action=action,
            phase="finished",
            success=bool(out.get("success")),
            output=_batch_result_text("预演", label, out),
            error="" if out.get("success") else str(out.get("message") or ""),
        )
        processed += 1
        items.append({"file_path": path, "file_name": label, **out})
    ready = [item for item in items if item.get("success")]
    needs_decision = [item for item in items if item.get("requires_user_decision")]
    run_ids = [
        str((item.get("data") or {}).get("run_id") or "")
        for item in ready
    ]
    run_ids = [run_id for run_id in run_ids if run_id]
    truncated = len(paths) > len(targets)
    message = (
        f"批量预演：{len(items)} 个文件，预演完成 {len(ready)}，"
        f"需人工确认 {len(needs_decision)}，未完成 {len(items) - len(ready)}"
    )
    if truncated:
        message += f"（一次最多 {_MAX_BATCH_IMPORTS} 个，其余请分批）"
    deferred_count = total - processed
    if deferred_count:
        message += f"；剩余 {deferred_count} 个文件超出本轮时间预算，请回复「继续导入」"
    # 对话自动审批模式下，预演已可执行的批次直接入库，避免「只预演却回复导入完成」。
    executable_ids = [
        str((item.get("data") or {}).get("run_id") or "")
        for item in ready
        if (item.get("data") or {}).get("executable") is True
    ]
    executable_ids = [run_id for run_id in executable_ids if run_id]
    execution: dict[str, Any] = {}
    if (
        executable_ids
        and runtime_context.get("chat_approval_mode") == "auto"
        and payload.get("auto_execute") is not False
    ):
        execution = _execute_batch(
            executable_ids,
            {**base, "accept_suggested": True},
            runtime_context,
        )
        message += f"；已自动入库 {execution.get('done_count', 0)} 个"
    return {
        "success": bool(ready),
        "batch": True,
        "file_count": len(items),
        "ready_count": len(ready),
        "needs_decision_count": len(needs_decision),
        "truncated": truncated,
        "message": message,
        "run_ids": run_ids,
        "execution": execution,
        # 与单文件预演保持同一形状：编排引用 {{preview.data.run_id}} 也能取到值。
        "data": {
            "run_id": ",".join(run_ids),
            "run_ids": run_ids,
            "file_count": len(items),
            "ready_count": len(ready),
            "needs_decision_count": len(needs_decision),
            "executable": bool(run_ids) and not needs_decision,
            "executed_count": int(execution.get("done_count") or 0),
        },
        "results": items,
    }


def _execute_batch(run_ids: list[str], payload: dict, runtime_context: dict) -> dict:
    """整批执行：按预演 run 逐个写入，单个失败不影响其余。"""
    targets = run_ids[:_MAX_BATCH_IMPORTS]
    base = _single_params(payload)
    items: list[dict] = []
    total = len(targets)
    processed = 0
    for index, run_id in enumerate(targets, start=1):
        remaining = _remaining_budget(runtime_context)
        if remaining is not None and remaining <= _MIN_WAIT_SECONDS:
            deferred = total - index + 1
            _publish_note(f"本轮时间不足，剩余 {deferred} 个文件将在下一轮继续导入")
            break
        label = _run_label(run_id, runtime_context)
        node_id = f"elt-execute-{index}"
        action = f"导入 {index}/{total}：{label}"
        _publish_file_stage(node_id=node_id, action=action, phase="started")
        _batch_progress_note("导入", index, total, label)
        out = _execute({**base, "run_id": run_id}, runtime_context)
        _batch_result_note("导入", label, out)
        _publish_file_stage(
            node_id=node_id,
            action=action,
            phase="finished",
            success=bool(out.get("success")),
            output=_batch_result_text("导入", label, out),
            error="" if out.get("success") else str(out.get("message") or ""),
        )
        processed += 1
        items.append({"run_id": run_id, "file_name": label, **out})
    done = [item for item in items if item.get("success")]
    written = sum(int((item.get("data") or {}).get("executed_rows") or 0) for item in done)
    skipped = sum(int((item.get("data") or {}).get("skip_rows") or 0) for item in done)
    message = (
        f"批量导入：{len(items)} 个预演，完成 {len(done)}，"
        f"失败 {len(items) - len(done)}，写入 {written} 行"
    )
    if skipped:
        message += f"（重复跳过 {skipped} 行）"
        if written == 0:
            message += "；本次没有新增业务记录"
    if len(run_ids) > len(targets):
        message += f"（一次最多 {_MAX_BATCH_IMPORTS} 个，其余请分批）"
    deferred_count = total - processed
    if deferred_count:
        message += f"；剩余 {deferred_count} 个预演超出本轮时间预算，请回复「继续导入」"
    return {
        "success": bool(done),
        "batch": True,
        "run_count": len(items),
        "done_count": len(done),
        "message": message,
        "results": items,
    }