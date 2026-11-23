"""ELT 导入工具：让智能对话通过数据对接中心（ELT）完成预演与入库。

与 `import_excel_to_database` 直接写库不同，这里复用 ELT 的
"预演 → 确认 → 执行 → 回执" 流程，具备源快照、映射核对与回滚能力。
"""

from __future__ import annotations

import csv
import io
import os
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import or_

from app.application.elt.auxiliary_assets import _knowledge_receipt, _template_receipt
from app.application.tools.workflow_spreadsheet_scope import (
    TenantScopeError,
    _bound_actor,
    publish_stream_note,
    publish_stream_tool_record,
    resolve_owned_upload_path,
    tenant_id_for_write,
    tenant_scope,
)
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.application.elt.service import EltService

PREVIEW_PENDING = {"queued", "previewing"}
EXECUTION_PENDING = {"queued", "executing", "persisting"}
EXECUTION_UNCERTAIN = EXECUTION_PENDING | {"outcome_unknown"}
PREVIEW_TIMEOUT_SECONDS = 120
EXECUTION_TIMEOUT_SECONDS = 240
POLL_INTERVAL_SECONDS = 0.5


def _failure(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"success": False, "error_code": code, "message": message, **details}


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
            "sha256": str(row.sha256 or ""),
        }


def _publish_note(text: str) -> None:
    """把逐文件进度推给对话流；没有流式上下文时静默忽略。"""
    publish_stream_note(text)


def _publish_file_stage(
    *,
    node_id: str,
    action: str,
    phase: str,
    success: bool | None = None,
    output: str = "",
    error: str = "",
    deferred: bool = False,
    committed: bool = False,
    requires_reconciliation: bool = False,
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
        if deferred:
            record["deferred"] = True
        if committed:
            record["committed"] = True
        if requires_reconciliation:
            record["requires_reconciliation"] = True
        if error:
            record["error"] = str(error)[:200]
    try:
        publish_stream_tool_record(record)
    except BOUNDARY_ERRORS:
        pass


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


def _has_stage_budget(runtime_context: dict[str, Any]) -> bool:
    remaining = _remaining_budget(runtime_context)
    return remaining is None or remaining > _MIN_WAIT_SECONDS


def _can_start_file_stage(runtime_context: dict[str, Any]) -> bool:
    return callable(runtime_context.get("_renew_elt_file_deadline")) or _has_stage_budget(
        runtime_context
    )


def _renew_file_stage(runtime_context: dict[str, Any], stage: str) -> None:
    renew = runtime_context.get("_renew_elt_file_deadline")
    if callable(renew):
        runtime_context["deadline_monotonic"] = renew(stage)
        runtime_context["_elt_file_phase"] = stage


def _linked_preview_cap(runtime_context: dict[str, Any]) -> float:
    from app.application.agent_orchestrator.tool_timeouts import ELT_LINKED_PREVIEW_TIMEOUT_SECONDS

    if runtime_context.get("_elt_linked_preview_used") is not True:
        _renew_file_stage(runtime_context, "linked_preview")
        runtime_context["_elt_linked_preview_used"] = True
    return ELT_LINKED_PREVIEW_TIMEOUT_SECONDS


def _wait_timeout(params: dict[str, Any], runtime_context: dict[str, Any], cap: float) -> float:
    declared = params.get("_wait_timeout")
    limit = float(declared) if isinstance(declared, (int, float)) and declared > 0 else cap
    remaining = _remaining_budget(runtime_context)
    if remaining is None:
        return min(limit, cap)
    return max(0.0, min(limit, cap, remaining))


def _batch_result_text(action: str, label: str, out: dict[str, Any]) -> str:
    """单个文件的收口说明；预演/执行共用，供进度提示与执行链复用。"""
    raw_data = out.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    if out.get("outcome") == "unknown":
        return f"「{label}」{action}待核对：{out.get('message') or '结果待确认'}"
    if out.get("deferred") or out.get("error_code") == "elt_companion_incomplete":
        return f"「{label}」{out['message']}"
    if not out.get("success"):
        return f"「{label}」{action}失败：{out.get('message') or '未知原因'}"
    if action == "预演":
        return (
            f"「{label}」预演完成：共 {data.get('total_rows', 0)} 行，"
            f"新增 {data.get('new_rows', 0)}、更新 {data.get('update_rows', 0)}、"
            f"跳过 {data.get('skip_rows', 0)}、错误 {data.get('error_rows', 0)}"
        )
    if out.get("message"):
        return f"「{label}」{out['message']}"
    text = f"「{label}」导入完成：写入 {data.get('executed_rows', 0)} 行"
    if data.get("skip_rows"):
        text += f"，重复跳过 {data.get('skip_rows')} 行"
    return text


def _batch_result_note(action: str, label: str, out: dict[str, Any]) -> None:
    _publish_note(_batch_result_text(action, label, out))


def _run_file_stage(
    action: str,
    index: int,
    total: int,
    label: str,
    operation: Callable[[], dict],
    runtime_context: dict[str, Any],
) -> dict:
    stage = "preview" if action == "预演" else "execute"
    runtime_context.pop("_elt_linked_preview_used", None)
    _renew_file_stage(runtime_context, stage)
    node_id = f"elt-{stage}-{index}"
    stage_action = f"{action} {index}/{total}：{label}"
    _publish_file_stage(node_id=node_id, action=stage_action, phase="started")
    _batch_progress_note(action, index, total, label)
    try:
        out = operation()
    except PermissionError as err:
        out = _failure("spreadsheet_access_denied", str(err))
    _batch_result_note(action, label, out)
    _publish_file_stage(
        node_id=node_id,
        action=stage_action,
        phase="finished",
        success=bool(out.get("success")),
        output=_batch_result_text(action, label, out),
        error="" if out.get("success") else str(out.get("message") or ""),
        deferred=out.get("deferred") is True,
        committed=_confirmed_written_rows(out) > 0,
        requires_reconciliation=out.get("outcome") == "unknown",
    )
    return out


def _progress_record(data: dict, runtime_context: dict[str, Any]) -> dict[str, Any]:
    """Project persisted ELT progress into the existing tool event contract."""
    status = str(data.get("status") or "")
    stage = (
        status
        if status not in PREVIEW_PENDING | EXECUTION_PENDING
        else str(data.get("stage") or status)
    )
    label = {
        "queued": "等待处理",
        "previewing": "正在生成预演",
        "parsing": "正在解析文件",
        "loading": "正在保存源数据",
        "source_loaded": "源数据已保存",
        "transforming": "正在校验数据",
        "validating": "正在校验数据",
        "preview_ready": "预演结果已生成",
        "executing": "正在执行导入",
        "persisting": "正在写入业务数据",
        "completed": "业务数据已写入",
        "partial": "部分数据已写入",
        "failed": "数据处理失败",
        "cancelled": "数据处理已取消",
        "interrupted": "数据处理已中断",
        "outcome_unknown": "数据处理结果待核对",
    }.get(stage, "正在读取数据处理状态")
    name = Path(str(data.get("file_name") or "").replace("\\", "/")).name
    if name:
        label = f"「{' '.join(name.split())[:120]}」{label}"
    record: dict[str, Any] = {
        "phase": "progress",
        "node_id": str(runtime_context.get("node_id") or ""),
        "tool_id": "elt_import",
        "label": label,
    }
    progress = data.get("progress")
    if (
        isinstance(progress, (int, float))
        and not isinstance(progress, bool)
        and 0 <= progress <= 100
    ):
        record["progress"] = progress
        record["label"] += f" · {progress:g}%"
    for field in ("processed_rows", "total_rows"):
        # ELT retains preview's processed_rows during execution; it is not a write count.
        if field == "processed_rows" and status not in PREVIEW_PENDING | {"preview_ready"}:
            continue
        value = data.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            record[field] = value
    if record.get("total_rows") and "processed_rows" in record:
        record["label"] += f" · 已处理 {record['processed_rows']}/{record['total_rows']} 行"
    return record


def _wait(
    service,
    run_id: str,
    owner_id: int,
    *,
    pending: set[str],
    timeout: float,
    runtime_context: dict[str, Any] | None = None,
) -> dict:
    deadline = time.monotonic() + timeout
    previous_record = None
    previous_stage = None
    while True:
        with get_db() as db:
            db.expire_all()
            data = service.get_run(db, run_id=run_id, owner_user_id=owner_id)
        if not isinstance(data, dict):
            return {}
        record = _progress_record(data, runtime_context or {})
        stage = (data.get("status"), data.get("stage"), data.get("file_name"))
        if stage != previous_stage:
            _publish_note(record["label"])
        if record != previous_record and record["node_id"]:
            try:
                publish_stream_tool_record(record)
            except BOUNDARY_ERRORS:
                pass  # Observability must not change the persisted import result.
        previous_record, previous_stage = record, stage
        if str(data.get("status") or "") not in pending:
            return data
        if time.monotonic() >= deadline:
            return data
        time.sleep(POLL_INTERVAL_SECONDS)


def _execution_message(summary: dict, notes: str) -> str:
    """导入回执必须说清「写了多少 / 跳过多少」，否则全量重复时会误报导入成功。"""
    executed = int(summary.get("executed_rows") or 0)
    skipped = int(summary.get("skip_rows") or 0)
    label = (
        "出货记录写入完成" if summary.get("target_type") == "shipment_records" else "ELT 导入完成"
    )
    message = f"{label}：写入 {executed} 行，失败 {summary['error_rows']} 行"
    if skipped:
        message += f"，重复跳过 {skipped} 行"
        if executed == 0:
            message += "（本次全部判定为重复，业务库没有新增数据）"
    return f"{message}{notes}。"


def _summary(data: dict) -> dict[str, Any]:
    return {
        "run_id": data.get("id"),
        **{
            key: data.get(key)
            for key in ("target_type", "status", "preview_revision", "stage", "total_rows")
        },
        **{
            f"{key}_rows": data.get("summary", {}).get(key)
            for key in ("new", "update", "skip", "error", "executed")
        },
        "error": data.get("error"),
        "reversible": data.get("reversible"),
        "customer_products": _linked_companion_preview(data),
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
                io.TextIOWrapper(
                    stream, encoding="utf-8-sig", errors="replace", newline=""
                ) as handle,
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
                best_sheet = ""
                best_rows: list[list[str]] = []
                try:
                    for worksheet in workbook.worksheets[:8]:
                        rows = []
                        for index, values in enumerate(worksheet.iter_rows(values_only=True)):
                            rows.append(
                                ["" if value is None else str(value).strip() for value in values][
                                    :60
                                ]
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


def _preview_decision(
    params: dict, *, ready: bool, error_rows: int, pending_mappings: list
) -> dict[str, Any]:
    """Keep newly created and existing previews on the same confirmation contract."""
    blocked_by_errors = bool(error_rows) and params.get("valid_rows_only") is not True
    executable = (
        ready
        and not blocked_by_errors
        and (not pending_mappings or params.get("accept_suggested") is True)
    )
    requires_decision = ready and not executable
    resume_params: dict[str, Any] = {}
    if requires_decision and blocked_by_errors:
        resume_params["valid_rows_only"] = True
    elif requires_decision and pending_mappings:
        resume_params["accept_suggested"] = True
    return {
        "executable": executable,
        "executable_with_suggestions": ready and not blocked_by_errors,
        "requires_user_decision": requires_decision,
        "resume_params": resume_params,
    }


def _preview(
    params: dict,
    runtime_context: dict,
    *,
    upload: dict[str, str] | None = None,
    checkpoint_id: str = "",
    checkpoint: dict | None = None,
) -> dict:
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service

    if upload is None:
        upload = _owned_upload(str(params.get("file_path") or ""), runtime_context)
    if not upload:
        return _failure(
            "upload_not_found", "找不到当前账号可用上传文件，请重新上传 Excel 后再导入。"
        )
    service = get_elt_service()
    actor = _bound_actor(runtime_context)
    try:
        if checkpoint:
            created = checkpoint
            target_type = str(created.get("target_type") or "auto")
            template = {"id": created.get("template_id")}
            _resume_checkpoint_previews(service, actor.id, created)
        else:
            target_type, template = _resolve_template(upload, actor.id)
            resolved_target = "auto"
            if template and target_type not in {"auto", "abnormal", "shipment_records"}:
                resolved_target = target_type
            with get_db() as db:
                created = service.create_preview(
                    db,
                    owner_user_id=actor.id,
                    upload_id=upload["id"],
                    target_type=resolved_target,
                    template_id=str(template.get("id") or "") or None,
                    checkpoint_run_id=checkpoint_id or None,
                )
    except EltError as exc:
        return _failure(exc.code, exc.message)
    run_id = str(created.get("id") or "")
    data = _wait(
        service,
        run_id,
        actor.id,
        pending=PREVIEW_PENDING,
        timeout=_wait_timeout(params, runtime_context, PREVIEW_TIMEOUT_SECONDS),
        runtime_context=runtime_context,
    )
    summary = _summary(data)
    summary["customer_products"] = _read_linked_companion(service, actor, data)
    if not summary.get("target_type"):
        summary["target_type"] = target_type
    summary["template_id"] = str(template.get("id") or "")
    summary["template_name"] = str(template.get("name") or "")
    summary["template_source"] = str(template.get("matched_by") or "")
    summary["template_confidence"] = template.get("match_confidence")
    primary_ready = data.get("status") == "preview_ready"
    companion = (
        _companion_summary(_wait_linked_preview(service, actor.id, data, runtime_context))
        if primary_ready
        else {}
    )
    if companion:
        summary["customer_products"] = companion
    companion_ready = _companion_preview_ready(companion)
    pending_mappings = [
        str(item.get("target") or item.get("source") or "字段") for item in _pending_mappings(data)
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
    ok = primary_ready and companion_ready
    decision = _preview_decision(
        params, ready=ok, error_rows=error_rows, pending_mappings=pending_mappings
    )
    summary["executable"] = decision["executable"]
    # 只剩映射置信度不足时，用户可以一次性接受 AI 建议直接执行。
    summary["executable_with_suggestions"] = decision["executable_with_suggestions"]
    template_note = ""
    if summary["template_name"]:
        ai_note = (
            "（AI 识别）" if summary["template_source"] in {"ai", "ai_created", "ai_rank"} else ""
        )
        template_note = f"，已套用导入模板{ai_note}「{summary['template_name']}」"
    if not primary_ready:
        message = f"预演未完成：{data.get('error') or data.get('stage')}"
    elif not companion_ready:
        message = f"运单预演已完成{_companion_note(companion)}。业务写入未提交。"
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
        message += _companion_note(summary["customer_products"])
    # 预演发现阻断项时，契约要求编排在此暂停询问用户，而不是继续执行后失败。
    requires_decision = decision["requires_user_decision"]
    return {
        "success": ok,
        "preview": True,
        "deferred": data.get("status") in PREVIEW_PENDING
        or (not companion_ready and _companion_is_deferred(companion)),
        "error_code": None if ok else "elt_preview_not_ready",
        "message": message,
        "requires_user_decision": requires_decision,
        "question": message if requires_decision else "",
        # 用户确认后重新执行预演/执行时带上解除阻断的参数，避免再次停在同一个问题。
        "resume_params": decision["resume_params"],
        "data": summary,
    }


def _receipt_tenant(data: dict[str, Any], owner_id: int) -> int:
    """Resolve the owned run before handing its fixed tenant to worker threads."""
    try:
        return tenant_id_for_write()
    except TenantScopeError:
        pass
    from app.db.models.elt import EltRun

    with get_db() as db:
        row = (
            db.query(EltRun.tenant_id)
            .filter(
                EltRun.id == str(data.get("id") or data.get("run_id") or ""),
                EltRun.owner_user_id == owner_id,
            )
            .first()
        )
    if row is None:
        raise TenantScopeError("写入业务数据缺少 tenant_id")
    return int(row[0])


def _parallel_receipts(
    data: dict[str, Any], owner_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep each worker's original approval context and the fixed tenant scope."""
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    tenant = _receipt_tenant(data, owner_id)

    def run_receipt(writer: Callable[[dict[str, Any], int], dict[str, Any]]) -> dict[str, Any]:
        with tenant_scope(tenant):
            return writer(data, owner_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(copy_context().run, run_receipt, writer)
            for writer in (_knowledge_receipt, _template_receipt)
        ]
        receipts: list[dict[str, Any]] = []
        for future in futures:
            try:
                receipt = future.result()
                receipts.append(
                    receipt
                    if isinstance(receipt, dict) and receipt
                    else {"action": "unknown", "reason": "auxiliary_receipt_unavailable"}
                )
            except BOUNDARY_ERRORS as exc:
                # The business transaction is already committed. Preserve its
                # identity even when an auxiliary worker dies without a receipt.
                receipts.append({"action": "unknown", "reason": type(exc).__name__})
    return receipts[0], receipts[1]


def _unknown_auxiliary(reason: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    knowledge = {"action": "unknown", "reason": reason}
    template = dict(knowledge)
    return knowledge, template, _receipt_notes(knowledge, template)


def _auxiliary_projection(auxiliary: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not isinstance(auxiliary, dict) or auxiliary.get("state") != "returned":
        return _unknown_auxiliary("auxiliary_started")
    knowledge, template = auxiliary.get("knowledge"), auxiliary.get("template")
    if (
        not isinstance(knowledge, dict)
        or not knowledge
        or not isinstance(template, dict)
        or not template
    ):
        return _unknown_auxiliary("auxiliary_receipt_unavailable")
    return knowledge, template, _receipt_notes(knowledge, template)


def _finalize_import(
    data: dict[str, Any], owner_id: int, *, allow_start: bool = True
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Claim once in the original run; restarts only read its persisted auxiliary result.

    Auxiliary stores commit independently. The existing non-reclaimable batch
    owner excludes rollback until their receipts are durably attached, and a
    started stage is never retried after a lost return or process restart.
    """
    from typing import cast

    from sqlalchemy import Table, update

    from app.application.elt.errors import EltConflict
    from app.application.elt.operation_owner import claim_operation, finish_operation
    from app.application.elt.preview_confirmation import CONFIRMATION_KEY
    from app.application.elt.service_support import dump_json, load_json
    from app.db.models.elt import EltRun

    try:
        tenant = _receipt_tenant(data, owner_id)
        run_id = str(data.get("id") or data.get("run_id") or "")
        table = cast("Table", EltRun.__table__)
        columns = table.c
        scope = [
            columns.id == run_id,
            columns.tenant_id == tenant,
            columns.owner_user_id == owner_id,
        ]
        with tenant_scope(tenant), get_db() as db:
            run = db.query(EltRun).filter(*scope).first()
            if run is None:
                return _unknown_auxiliary("auxiliary_run_unavailable")
            original = run.receipt_json
            receipt = load_json(original, None)
            if not isinstance(receipt, dict):
                return _unknown_auxiliary("auxiliary_receipt_unavailable")
            details = load_json(run.summary_json, {})
            confirmation = details.get(CONFIRMATION_KEY, {})
            binding = {
                "run_id": run.id,
                "tenant_id": tenant,
                "owner_user_id": owner_id,
                "upload_id": run.upload_id,
                "file_sha256": run.file_sha256,
                "preview_revision": confirmation.get("preview_revision"),
            }
            if "auxiliary" in receipt:
                auxiliary = receipt["auxiliary"]
                if (
                    not isinstance(auxiliary, dict)
                    or auxiliary.get("schema") != "xcmax.elt-auxiliary.v1"
                    or auxiliary.get("binding") != binding
                ):
                    return _unknown_auxiliary("auxiliary_binding_mismatch")
                return _auxiliary_projection(auxiliary)
            if run.operation_token or run.rollback_status or run.status != "completed":
                return _unknown_auxiliary("auxiliary_run_busy")
            if not allow_start:
                return {}, {}, ""
            if not all(binding.values()):
                return _unknown_auxiliary("auxiliary_binding_unavailable")
            unknown = {"action": "unknown", "reason": "auxiliary_started"}
            auxiliary = {
                "schema": "xcmax.elt-auxiliary.v1",
                "binding": binding,
                "state": "started",
                "knowledge": dict(unknown),
                "template": dict(unknown),
            }
            started = dump_json({**receipt, "auxiliary": auxiliary})
            operation = claim_operation(
                db,
                run,
                "batch_execute",
                allowed_statuses={"completed"},
                require_unrolled_back=True,
            )
            changed = db.execute(
                update(table)
                .where(
                    *scope,
                    columns.receipt_json == original,
                    columns.status == "completed",
                    columns.rollback_status.is_(None),
                    columns.operation_token == operation.token,
                )
                .values(receipt_json=started)
            )
            if changed.rowcount != 1:
                db.rollback()
                return _unknown_auxiliary("auxiliary_claim_conflict")
            source_data = {
                **data,
                "id": run.id,
                "upload_id": run.upload_id,
                "file_sha256": run.file_sha256,
                "target_type": run.target_type,
                "source_features": load_json(run.source_features_json, {}),
            }
            db.commit()
        with tenant_scope(tenant):
            knowledge, template = _parallel_receipts(source_data, owner_id)
        returned = dump_json(
            {
                **receipt,
                "auxiliary": {
                    **auxiliary,
                    "state": "returned",
                    "knowledge": knowledge,
                    "template": template,
                },
            }
        )
        with tenant_scope(tenant), get_db() as db:
            changed = db.execute(
                update(table)
                .where(
                    *scope,
                    columns.receipt_json == started,
                    columns.status == "completed",
                    columns.rollback_status.is_(None),
                    columns.operation_token == operation.token,
                    columns.operation_kind == operation.kind,
                )
                .values(receipt_json=returned)
            )
            if changed.rowcount != 1:
                db.rollback()
                return _unknown_auxiliary("auxiliary_receipt_conflict")
            finish_operation(db, operation)
            db.commit()
        return knowledge, template, _receipt_notes(knowledge, template)
    except EltConflict as exc:
        return _unknown_auxiliary(str(exc)[:200])
    except RECOVERABLE_ERRORS as exc:
        return _unknown_auxiliary(str(exc)[:200])


def _receipt_notes(knowledge: dict[str, Any], template: dict[str, Any]) -> str:
    """把知识库与模板库的登记结果转成一句说明；跳过与失败都必须写清原因。"""
    note = ""
    action = str(knowledge.get("action") or "")
    if action == "unknown":
        note += "；知识库原回执待核对，请勿重复提交"
    elif action == "error":
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
    if template_action == "unknown":
        note += "；模板库原回执待核对，请勿重复提交"
    elif template_action == "error":
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
    from app.application.agent_orchestrator.business_write_guard import worker_write_guard
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service

    run_id = str(params.get("run_id") or "").strip()
    if not run_id:
        return _failure("missing_run_id", "缺少 ELT 预演编号，请先执行 elt_import.preview。")
    service = get_elt_service()
    actor = _bound_actor(runtime_context)
    resumed = False
    write_requested = False
    try:
        with get_db() as db:
            current = service.get_run(db, run_id=run_id, owner_user_id=actor.id)
            if _resumable_linked_preview(current) and _has_stage_budget(runtime_context):
                current = _resume_linked_preview(service, db, actor.id, current)
                resumed = True
        status = str(current.get("status") or "")
        if status in PREVIEW_PENDING:
            wait_cap = (
                _linked_preview_cap(runtime_context)
                if _linked_shipment_id(current)
                else PREVIEW_TIMEOUT_SECONDS
            )
            current = _wait(
                service,
                run_id,
                actor.id,
                pending=PREVIEW_PENDING,
                timeout=_wait_timeout(params, runtime_context, wait_cap),
                runtime_context=runtime_context,
            )
            if (
                not resumed
                and _interrupted_linked_preview(current)
                and _has_stage_budget(runtime_context)
            ):
                with get_db() as db:
                    _resume_linked_preview(service, db, actor.id, current)
                current = _wait(
                    service,
                    run_id,
                    actor.id,
                    pending=PREVIEW_PENDING,
                    timeout=_wait_timeout(params, runtime_context, wait_cap),
                    runtime_context=runtime_context,
                )
            status = str(current.get("status") or "")
        if status in PREVIEW_PENDING or _interrupted_linked_preview(current):
            return _failure(
                "elt_preview_not_ready",
                f"预演 {run_id} 尚未就绪，业务写入未提交。",
                preview=True,
                deferred=True,
                data={**_summary(current), "run_id": run_id},
            )
        if status == "preview_ready":
            companion = _companion_summary(
                _wait_linked_preview(service, actor.id, current, runtime_context)
            )
            if not _companion_preview_ready(companion):
                summary = {**_summary(current), "customer_products": companion}
                if companion["status"] in EXECUTION_UNCERTAIN - PREVIEW_PENDING:
                    return _unknown_execution(companion["run_id"], summary)
                return _failure(
                    "elt_companion_incomplete",
                    f"运单预演已完成{_companion_note(companion)}。运单写入未提交。",
                    deferred=_companion_is_deferred(companion),
                    data=summary,
                )
            if runtime_context.get("_elt_file_phase") == "linked_preview":
                _renew_file_stage(runtime_context, "execute")
        if status not in EXECUTION_UNCERTAIN | {"completed", "partial"}:
            with get_db() as db, worker_write_guard(db):
                revision = str(current.get("preview_revision") or "")
                confirmed_revision = params.get("preview_revision")
                if params.get("run_ids"):
                    revisions = params.get("preview_revisions")
                    confirmed_revision = (
                        revisions.get(run_id) if isinstance(revisions, dict) else None
                    )
                confirmed_revision = str(confirmed_revision or "")
                linked = (current.get("draft") or {}).get("linked_preview") or _linked_shipment_id(
                    current
                )
                if ((linked or params.get("run_ids")) and not confirmed_revision) or (
                    confirmed_revision and confirmed_revision != revision
                ):
                    raise EltError(
                        "ELT_PREVIEW_CHANGED",
                        "请单独核对当前预演的目标、行数及映射，并确认对应 preview_revision 后执行。"
                        f"可发送新消息：查看导入预演，run_id={run_id}",
                    )
                if status == "preview_ready" and _linked_shipment_id(current):
                    _verified_companion_source(service, db, actor.id, current)
                    if current.get("total_rows") == 0:
                        return {
                            "success": True,
                            "message": "关联附表预演已完成，未识别到可入库的客户及产品。",
                            "data": _summary(current),
                        }
                if not _has_stage_budget(runtime_context):
                    return _failure(
                        "elt_preview_not_ready",
                        f"预演 {run_id} 已就绪，本轮尚未提交写入。",
                        deferred=True,
                        data=_summary(current),
                    )
                write_requested = True
                service.execute(
                    db,
                    run_id=run_id,
                    owner_user_id=actor.id,
                    confirmed=True,
                    valid_rows_only=bool(params.get("valid_rows_only") is True),
                    preview_revision=revision or None,
                    accept_suggested=bool(params.get("accept_suggested") is True),
                    chat_context=runtime_context,
                )
    except EltError as exc:
        if write_requested and exc.code == "ELT_RUN_BUSY":
            return _unknown_execution(run_id, {"run_id": run_id})
        if exc.code == "ELT_RUN_BUSY":
            return _failure(
                "elt_preview_not_ready",
                f"预演 {run_id} 正在处理，业务写入未提交。",
                deferred=True,
                data={"run_id": run_id},
            )
        return _failure(exc.code, exc.message)
    try:
        data = _wait(
            service,
            run_id,
            actor.id,
            pending=EXECUTION_PENDING,
            timeout=_wait_timeout(params, runtime_context, EXECUTION_TIMEOUT_SECONDS),
            runtime_context=runtime_context,
        )
    except RECOVERABLE_ERRORS:
        data = current if status in {"completed", "partial"} else {}
    summary = _summary(data)
    summary["run_id"] = summary.get("run_id") or run_id
    status = str(summary.get("status") or "")
    ok = status == "completed"
    companion = _read_linked_companion(service, actor, data)
    if companion:
        summary["customer_products"] = companion
    if not status or status in EXECUTION_UNCERTAIN:
        return _unknown_execution(run_id, summary)
    knowledge, template, notes = (
        _finalize_import(
            data, actor.id, allow_start=write_requested and _has_stage_budget(runtime_context)
        )
        if ok and not _linked_shipment_id(data)
        else ({}, {}, "")
    )
    summary["knowledge"] = knowledge
    summary["template"] = template
    companion_note = _companion_note(companion)
    if ok and not write_requested and summary.get("target_type") == "shipment_records":
        message = (
            f"原出货回执记录写入 {int(summary.get('executed_rows') or 0)} 行{companion_note}。"
        )
    elif ok:
        message = _execution_message(summary, companion_note + notes)
    else:
        message = f"ELT 导入未完成：{summary.get('error') or data.get('stage')}"
    return {
        "success": ok,
        "committed": _confirmed_written_rows({"data": summary}) > 0,
        "error_code": None if ok else f"elt_execute_{status}",
        "message": message,
        "data": summary,
    }


def _unknown_execution(run_id: str, summary: dict) -> dict:
    return _failure(
        "tool_timeout_unknown",
        f"请在数据对接中心核对原回执 {run_id}，勿重复提交。",
        outcome="unknown",
        committed=_confirmed_written_rows({"data": summary, "outcome": "unknown"}) > 0,
        reconciliation_required=True,
        retryable=False,
        data=summary,
    )


def _confirmed_written_rows(result: dict) -> int:
    data = result.get("data") or {}
    rows = 0
    if data.get("receipt_verified") is not False and (
        result.get("outcome") != "unknown" or data.get("status") == "completed"
    ):
        rows = int(data.get("executed_rows") or 0)
    companion = data.get("customer_products") or {}
    if companion.get("receipt_verified") is not False and companion.get("status") in {
        "completed",
        "partial",
    }:
        rows += int(companion.get("executed_rows") or 0)
    return rows


def _interrupted_linked_preview(run: dict) -> bool:
    return run.get("status") != "queued" and _resumable_linked_preview(run)


def _linked_shipment_id(run: dict) -> str:
    if run.get("target_type") != "customer_products":
        return ""
    details = run.get("details") or {}
    return str(details.get("linked_from_shipment_preview") or "")


def _resumable_linked_preview(run: dict) -> bool:
    status = run.get("status")
    return (
        bool(_linked_shipment_id(run))
        and (
            status == "queued"
            or status in {"failed", "interrupted"}
            and (run.get("error") or {}).get("code")
            in {"ELT_EXECUTION_INTERRUPTED", "ELT_OPERATION_LEASE_LOST"}
        )
        and "confirmed_at" in run
        and run["confirmed_at"] is None
        and "executed_at" in run
        and run["executed_at"] is None
        and (run.get("summary") or {}).get("executed") == 0
    )


def _verified_companion_source(
    service, db, owner_id: int, current: dict, *, context: dict | None = None
):
    from app.application.elt.batch_continuation import (
        shipment_parent_writes_present,
        unchanged_source_upload,
    )
    from app.application.elt.errors import EltConflict
    from app.application.elt.service_support import load_json

    child = service._owned_run(db, current["id"], owner_id)
    parent_id = _linked_shipment_id(current)
    parent = service._owned_run(db, parent_id, owner_id)
    link = load_json(parent.summary_json, {}).get("linked_customer_products_preview") or {}
    # A same-task checkpoint may prove that the parent completed entirely as duplicates.
    same_zero_write = bool(
        context
        and context.get("durable_elt_batch") is True
        and parent.executed_rows == 0
        and _batch_checkpoint_ids([parent.upload_id], context).get(parent.upload_id) == parent.id
        and _checkpoint_receipt_present(db, parent, service.run_dict(parent))
    )
    if (
        parent.status != "completed"
        or parent.target_type != "shipment_records"
        or parent.executed_at is None
        or parent.rollback_status is not None
        or parent.tenant_id != child.tenant_id
        or parent.upload_id != child.upload_id
        or parent.file_sha256 != child.file_sha256
        or link.get("run_id") != child.id
        or child.confirmed_at is not None
        or child.executed_at is not None
        or child.executed_rows != 0
        or not (same_zero_write or shipment_parent_writes_present(db, parent))
        or not unchanged_source_upload(db, child)
    ):
        raise EltConflict(
            "elt_companion_incomplete", "原出货回执或附件无法核对，客户及产品恢复未提交。"
        )
    return child


def _resume_linked_preview(service: EltService, db: Session, owner_id: int, current: dict) -> dict:
    child = _verified_companion_source(service, db, owner_id, current)
    if child.status == "queued":
        # The previous tool may have exited before its preview worker claimed the row.
        service._submit_preview(child.id, child.tenant_id, owner_id)
        return current
    return service.retry(db, run_id=child.id, owner_user_id=owner_id)


def _wait_linked_preview(service, owner_id: int, data: dict, context: dict) -> dict:
    from app.application.elt.errors import EltError

    link = (data.get("details") or {}).get("linked_customer_products_preview")
    run_id = str(link.get("run_id") or "") if isinstance(link, dict) else ""
    if not run_id:
        return {}
    try:
        can_renew = callable(context.get("_renew_elt_file_deadline"))
        current = _wait(
            service,
            run_id,
            owner_id,
            pending=PREVIEW_PENDING,
            timeout=0.0 if can_renew else _wait_timeout({}, context, PREVIEW_TIMEOUT_SECONDS),
            runtime_context=context,
        )
        if can_renew and current.get("status") in PREVIEW_PENDING:
            cap = _linked_preview_cap(context)
            current = _wait(
                service,
                run_id,
                owner_id,
                pending=PREVIEW_PENDING,
                timeout=_wait_timeout({}, context, cap),
                runtime_context=context,
            )
    except EltError as exc:
        current = {"status": "failed", "error": {"code": exc.code}}
    return {**(current or {"status": "outcome_unknown"}), "id": run_id}


def _companion_summary(run: dict) -> dict:
    if not run:
        return {}
    summary = _review_summary(run)
    if summary["status"] == "preview_ready" and summary["total_rows"] == 0:
        summary["empty_preview"] = True
    if _interrupted_linked_preview(run):
        summary["preview_interrupted"] = True
    return summary


def _companion_is_empty(companion: dict) -> bool:
    return (
        companion.get("empty_preview") is True
        or (companion.get("error") or {}).get("code") == "ELT_PREVIEW_EMPTY"
    )


def _companion_preview_ready(companion: dict) -> bool:
    return (
        not companion
        or companion.get("status") in {"completed", "preview_ready"}
        or _companion_is_empty(companion)
    )


def _companion_is_deferred(companion: dict) -> bool:
    return not _companion_is_empty(companion) and (
        companion.get("status") in PREVIEW_PENDING | {"preview_ready"}
        or companion.get("preview_interrupted") is True
    )


def _linked_companion_preview(data: dict) -> dict[str, Any]:
    """Disclose the separate target without inheriting shipment execution consent."""
    raw_details = data.get("details")
    details = raw_details if isinstance(raw_details, dict) else {}
    link = details.get("linked_customer_products_preview") or {}
    if not isinstance(link, dict):
        return {}
    run_id = str(link.get("run_id") or "")
    if not run_id:
        return {}
    return {
        "run_id": run_id,
        "target_type": "customer_products",
        "status": str(link.get("status") or "queued"),
        "preview_revision": link.get("preview_revision"),
        "total_rows": link.get("total_rows"),
        "summary": link.get("summary") or {},
        "preview_only": link.get("status") in PREVIEW_PENDING | {"preview_ready"},
        "requires_user_confirmation": link.get("status") == "preview_ready",
    }


def _read_linked_companion(service, actor, data: dict) -> dict[str, Any]:
    link = _linked_companion_preview(data)
    if not link:
        return {}
    from app.application.elt.errors import EltError

    try:
        with get_db() as db:
            child = service.get_run(db, run_id=link["run_id"], owner_user_id=actor.id)
        if child.get("target_type") != "customer_products" or (
            child.get("draft", {}).get("linked_preview") or {}
        ).get("parent_run_id") != data.get("id"):
            return {"run_id": link["run_id"], "status": "unavailable"}
        return _companion_summary(child)
    except EltError:
        return {"run_id": link["run_id"], "status": "unavailable"}


def _review_summary(data: dict) -> dict[str, Any]:
    return {
        **_summary(data),
        "mapping_pending": [
            f"{item.get('source') or '未指定来源'} → {item.get('target') or '未指定字段'}"
            for item in _pending_mappings(data)
        ],
        "preview_only": data.get("status") in PREVIEW_PENDING | {"preview_ready"},
        "requires_user_confirmation": data.get("status") == "preview_ready",
    }


def _review_existing(run_id: str, params: dict, runtime_context: dict) -> dict:
    """Read an owned existing preview even in auto mode; never create or execute it."""
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service

    actor = _bound_actor(runtime_context)
    service = get_elt_service()
    try:
        with get_db() as db:
            data = service.get_run(db, run_id=run_id, owner_user_id=actor.id)
        summary = _review_summary(data)
        companion = _read_linked_companion(service, actor, data)
        summary["customer_products"] = companion
        decision = _preview_decision(
            params,
            ready=data.get("status") == "preview_ready" and _companion_preview_ready(companion),
            error_rows=int(summary.get("error_rows") or 0),
            pending_mappings=_pending_mappings(data),
        )
        summary["executable"] = decision["executable"]
        summary["executable_with_suggestions"] = decision["executable_with_suggestions"]
        message = (
            _companion_note(summary)
            if (data.get("draft") or {}).get("linked_preview")
            else f"导入目标「{summary['target_type']}」，状态 {summary['status']}"
            + _companion_note(companion)
        )
        return {
            "success": True,
            "preview": True,
            "message": message,
            "requires_user_decision": decision["requires_user_decision"],
            "question": message if decision["requires_user_decision"] else "",
            "resume_params": decision["resume_params"],
            "data": summary,
        }
    except EltError as exc:
        return _failure(exc.code, exc.message)


def _companion_note(companion: dict) -> str:
    if not companion:
        return ""
    if _companion_is_empty(companion):
        return "；未识别到可入库的客户及产品"
    status = companion.get("status")
    if status in EXECUTION_UNCERTAIN - PREVIEW_PENDING:
        return f"；客户及产品结果待核对（回执 {companion['run_id']}）"
    if status not in {"completed", "partial"}:
        if status != "preview_ready":
            return (
                f"；附表客户及产品的独立处理状态：{status}。可发送新消息只读核对："
                f"查看导入预演，run_id={companion['run_id']}"
            )
        note = (
            f"；附表客户及产品仅预演，共 {int(companion.get('total_rows') or 0)} 行，"
            f"拟写入 {int(companion.get('new_rows') or 0) + int(companion.get('update_rows') or 0)} 行，"
            f"重复跳过 {int(companion.get('skip_rows') or 0)} 行，错误 {int(companion.get('error_rows') or 0)} 行，"
            "未随本次出货写入，需单独确认"
        )
        revision = companion.get("preview_revision")
        if revision:
            mappings = companion.get("mapping_pending") or []
            mapping_note = f"，接受建议映射（{'、'.join(mappings)}）" if mappings else ""
            note += (
                "。核对后可发送新消息：确认导入附表客户及产品，"
                f"run_id={companion['run_id']}，preview_revision={revision}，"
                f"仅写入校验通过的行{mapping_note}"
            )
        return note
    executed = int(companion.get("executed_rows") or 0)
    skipped = int(companion.get("skip_rows") or 0)
    errors = int(companion.get("error_rows") or 0)
    note = f"；客户及产品已写入 {executed} 行"
    if status == "partial":
        note += "，部分行写入失败"
    if skipped:
        note += f"，重复跳过 {skipped} 行"
    if errors:
        note += f"，{errors} 行校验未通过，未写入"
    return note


def _run_execution_stage(
    run_id: str, params: dict, context: dict, index=1, total=1, label: str | None = None
) -> dict:
    return _run_file_stage(
        "导入",
        index,
        total,
        _run_label(run_id, context) if label is None else label,
        partial(_execute, {**params, "run_id": run_id}, context),
        context,
    )


def _registered_router_elt_import(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    """注册路由：elt_import.preview / elt_import.execute。"""
    if not _elt_enabled():
        return _failure(
            "elt_center_disabled", "数据对接中心未启用（需要企业版），暂时无法通过 ELT 导入。"
        )
    payload = dict(params or {})
    if action == "preview":
        if run_id := str(payload.get("run_id") or "").strip():
            return _review_existing(run_id, payload, runtime_context)
        paths = _split_paths(payload.get("file_paths"))
        if paths:
            return _preview_batch(paths, payload, runtime_context)
        if not str(payload.get("file_path") or "").strip():
            return _failure(
                "elt_file_path_required",
                "请提供 file_path（单个文件）或 file_paths（整批文件）后再预演。",
            )
        try:
            path = str(payload["file_path"])
            upload = _owned_upload(path, runtime_context)
            label = upload.get("file_name") or Path(path).name or path
            return _run_file_stage(
                "预演",
                1,
                1,
                label,
                partial(_preview, payload, runtime_context, upload=upload),
                runtime_context,
            )
        except PermissionError as err:
            return _failure("spreadsheet_access_denied", str(err))
    if action == "execute":
        ids = _split_run_ids(payload.get("run_ids")) or _split_run_ids(payload.get("run_id"))
        paths = _split_paths(payload.get("file_paths"))
        if paths:
            if ids:
                return {"success": False, "message": "请选择文件列表或预演编号作为导入范围。"}
            return _preview_batch(paths, payload, runtime_context, write=True)
        if len(ids) > 1:
            return _execute_batch(ids, payload, runtime_context)
        if ids:
            return _run_execution_stage(ids[0], payload, runtime_context)
        return _execute(payload, runtime_context)
    return {"success": False, "message": f"未知的 ELT 导入操作：{action}"}


def _split_paths(value: object) -> list[str]:
    # An array element is a single path. Separators are valid in filenames.
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


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
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


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
        matched = [name for name in sorted(names) if _owned_upload(name, runtime_context)]
        if matched:
            expanded.extend(matched)
            continue
        unresolved.append(
            _failure(
                "directory_needs_upload",
                f"「{candidate.name}」是本地目录，ELT 只导入已上传到本账号的文件；"
                f"目录内 {len(names)} 个可导入文件尚无上传记录，"
                "请先用「上传附件」或数据对接中心上传后再导入。",
                file_path=str(path),
                file_name=candidate.name,
            )
        )
    return expanded, unresolved


def _single_params(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in {"file_paths", "run_ids"}}


def _batch_checkpoint_ids(paths: list[str], context: dict) -> dict[str, str]:
    from app.application.agent_orchestrator.business_write_guard import capture_worker_claim

    if context.get("durable_elt_batch") is not True:
        return {}
    claim = capture_worker_claim()
    step_id = str(context.get("step_id") or "")
    if claim is None or claim[0] != context.get("run_id") or not step_id:
        raise PermissionError("导入批次缺少原任务与步骤的执行绑定。")
    return durable_elt_checkpoint_ids(claim[0], step_id, paths)


def durable_elt_checkpoint_ids(run_id: str, step_id: str, upload_ids: list[str]) -> dict[str, str]:
    """Locate native ELT receipts for a previously authorized task and step."""
    try:
        if not all(
            isinstance(upload_id, str) and str(UUID(upload_id)) == upload_id
            for upload_id in upload_ids
        ):
            raise ValueError
    except ValueError as exc:
        raise PermissionError("导入批次需要原审批绑定的上传编号。") from exc
    return {
        upload_id: str(uuid5(NAMESPACE_URL, f"xcagi:elt:{run_id}:{step_id}:{upload_id}"))
        for upload_id in upload_ids
    }


def _checkpoint_submitted(run: dict) -> bool:
    return bool(
        run.get("confirmed_at")
        or run.get("executed_at")
        or run.get("receipt")
        or run.get("status") in (EXECUTION_UNCERTAIN - PREVIEW_PENDING) | {"completed", "partial"}
        or (run.get("summary") or {}).get("executed")
    )


def _checkpoint_companion(service: EltService, db: Session, owner_id: int, run: dict) -> dict:
    details = run.get("details") or {}
    link = details.get("linked_customer_products_preview") or {}
    if not link.get("run_id"):
        return {}
    child: dict[str, Any] = service.get_run(db, run_id=link["run_id"], owner_user_id=owner_id)
    if (
        _linked_shipment_id(child) != run.get("id")
        or child.get("upload_id") != run.get("upload_id")
        or child.get("file_sha256") != run.get("file_sha256")
    ):
        raise PermissionError("原出货与客户产品预演的来源无法核对。")
    return child


def _resume_checkpoint_previews(service, owner_id: int, parent: dict) -> None:
    with get_db() as db:
        child = _checkpoint_companion(service, db, owner_id, parent)
        for run in (parent, child):
            if not run or _checkpoint_submitted(run):
                continue
            if run.get("status") == "queued":
                service._submit_preview(run["id"], tenant_id_for_write(), owner_id)
            elif run.get("status") in {"failed", "interrupted"} and (run.get("error") or {}).get(
                "code"
            ) in {
                "ELT_EXECUTION_INTERRUPTED",
                "ELT_OPERATION_LEASE_LOST",
            }:
                service.retry(db, run_id=run["id"], owner_user_id=owner_id)


def _checkpoint_receipt_present(db, row, run: dict) -> bool:
    from app.application.elt.batch_continuation import shipment_parent_writes_present

    receipt = run.get("receipt") or {}
    rows = (run.get("summary") or {}).get("executed")
    return (
        row is not None
        and run.get("status") == "completed"
        and bool(run.get("confirmed_at") and run.get("executed_at"))
        and not (row.rolled_back_at or row.rollback_status)
        and receipt.get("run_id") == run.get("id")
        and receipt.get("target_type") == run.get("target_type")
        and type(rows) is int
        and rows >= 0
        and receipt.get("executed_rows") == rows
        and (
            run.get("target_type") != "shipment_records"
            or rows == 0
            or shipment_parent_writes_present(db, row)
        )
    )


def _load_checkpoint_batch(checkpoint_ids: dict[str, str], context: dict) -> tuple[dict, dict]:
    from app.application.elt.errors import EltError
    from app.application.elt.service import get_elt_service
    from app.db.models.elt import EltRun

    stored: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    if not checkpoint_ids:
        return stored, receipts
    service = get_elt_service()
    owner_id = _bound_actor(context).id
    tenant_id = tenant_id_for_write()
    with get_db() as db:
        for upload_id, checkpoint_id in checkpoint_ids.items():
            row = db.get(EltRun, checkpoint_id)
            if row is None:
                continue
            if (row.tenant_id, row.owner_user_id, row.upload_id) != (
                tenant_id,
                owner_id,
                upload_id,
            ):
                raise PermissionError("原任务的导入回执与已批准的文件范围不一致。")
            parent: dict[str, Any] = {}
            summary: dict[str, Any]
            try:
                parent = service.get_run(db, run_id=checkpoint_id, owner_user_id=owner_id)
                child = _checkpoint_companion(service, db, owner_id, parent)
            except (EltError, PermissionError):
                summary = (
                    _summary(parent)
                    if _checkpoint_receipt_present(db, row, parent)
                    else {"run_id": checkpoint_id}
                )
                receipts[upload_id] = _unknown_execution(checkpoint_id, summary)
                continue
            stored[upload_id] = parent
            if not (_checkpoint_submitted(parent) or _checkpoint_submitted(child)):
                continue
            summary = _summary(parent)
            if child:
                summary["customer_products"] = _companion_summary(child)
            if not _checkpoint_receipt_present(db, row, parent):
                summary["receipt_verified"] = False
                if child:
                    summary["customer_products"]["receipt_verified"] = False
                receipts[upload_id] = _unknown_execution(checkpoint_id, summary)
            elif _checkpoint_submitted(child) and not _checkpoint_receipt_present(
                db, db.get(EltRun, child["id"]), child
            ):
                summary["customer_products"]["receipt_verified"] = False
                receipts[upload_id] = _unknown_execution(child["id"], summary)
            elif (
                not _checkpoint_submitted(child)
                or child.get("status") == "completed"
                or _companion_is_empty(summary["customer_products"])
            ):
                receipts[upload_id] = {
                    "success": True,
                    "message": "已核对原导入回执。",
                    "data": summary,
                }
    return stored, receipts


class _PreviewCheckpoint(TypedDict, total=False):
    checkpoint_id: str
    checkpoint: dict[str, Any]


def _preview_batch(
    paths: list[str], payload: dict, runtime_context: dict, *, write: bool = False
) -> dict:
    """逐份预演。只有正式执行动作可以继续提交通过校验的文件。"""
    base = _single_params(payload)
    paths = list(dict.fromkeys(paths))
    try:
        checkpoint_ids = _batch_checkpoint_ids(paths, runtime_context) if write else {}
        checkpoints, receipts = _load_checkpoint_batch(checkpoint_ids, runtime_context)
    except PermissionError as exc:
        return _failure("spreadsheet_access_denied", str(exc))
    expanded, unresolved = (
        (paths, [])
        if checkpoint_ids
        else _expand_directory_paths(paths[:_MAX_BATCH_IMPORTS], runtime_context)
    )
    targets = list(dict.fromkeys(expanded))[:_MAX_BATCH_IMPORTS]
    truncated = len(paths) > _MAX_BATCH_IMPORTS or len(set(expanded)) > _MAX_BATCH_IMPORTS
    items: list[dict] = list(unresolved)
    seen: set[tuple[str, ...]] = set()
    total = len(targets)
    deferred_count = 0
    if any(receipt.get("outcome") == "unknown" for receipt in receipts.values()):
        # An earlier unresolved write must fence the whole recovered task before
        # a missing slot is treated as work the dispatcher can submit.
        items = [
            {
                "file_path": path,
                "file_name": checkpoints.get(path, {}).get("file_name") or path,
                **receipt,
            }
            for path, receipt in receipts.items()
        ]
        return _execution_batch_result(
            items, deferred_count=max(0, total - len(items)), truncated=truncated
        )
    for index, path in enumerate(targets, start=1):
        if not _can_start_file_stage(runtime_context):
            deferred_count = total - index + 1
            _publish_note(f"本轮预演时间不足，剩余 {deferred_count} 个文件未开始预演")
            break
        checkpoint = checkpoints.get(path) or {}
        label = checkpoint.get("file_name") or Path(path).name or path
        if path in receipts:
            out = _run_file_stage(
                "导入", index, total, label, lambda: receipts[path], runtime_context
            )
            items.append({"file_path": path, "file_name": label, **out})
            if checkpoint.get("file_sha256"):
                seen.add((label, Path(label).suffix.lower(), checkpoint["file_sha256"]))
            continue
        try:
            upload = _owned_upload(path, runtime_context)
            if checkpoint_ids and upload and upload.get("id") != path:
                raise PermissionError("原任务仅允许读取已批准的上传记录。")
            if checkpoint and upload and upload.get("sha256") != checkpoint.get("file_sha256"):
                raise PermissionError("原任务上传的文件内容已改变。")
        except PermissionError as err:
            items.append(
                _failure("spreadsheet_access_denied", str(err), file_path=path, file_name=label)
            )
            continue
        if upload:
            label = upload.get("file_name") or label
            # Filename can influence recognition and the resulting import, even for identical bytes.
            fingerprint = upload.get("sha256")
            identity = (
                (label, upload.get("suffix", ""), fingerprint) if fingerprint else (upload["id"],)
            )
            # Frozen plans need a native receipt for every approved upload ID.
            # Row-level deduplication records skips without losing that checkpoint.
            if identity in seen and not checkpoint_ids:
                continue
            seen.add(identity)
        already_submitted = bool(checkpoint and _checkpoint_submitted(checkpoint))
        if already_submitted:
            from app.application.elt.service import get_elt_service

            _resume_checkpoint_previews(
                get_elt_service(), _bound_actor(runtime_context).id, checkpoint
            )
            out = _run_execution_stage(checkpoint["id"], base, runtime_context, index, total, label)
        else:
            checkpoint_args: _PreviewCheckpoint = {}
            if checkpoint_ids:
                checkpoint_args = {"checkpoint_id": checkpoint_ids[path], "checkpoint": checkpoint}
            out = _run_file_stage(
                "预演",
                index,
                total,
                label,
                partial(
                    _preview,
                    {**base, "file_path": path},
                    runtime_context,
                    upload=upload,
                    **checkpoint_args,
                ),
                runtime_context,
            )
        if write and out.get("success") and not already_submitted:
            preview = out["data"]
            run_id = preview.get("run_id")
            if (
                run_id
                and preview.get("executable") is True
                and _can_start_file_stage(runtime_context)
            ):
                out = _run_execution_stage(run_id, base, runtime_context, index, total, label)
            else:
                out = {
                    **out,
                    "success": False,
                    "deferred": preview.get("executable") is True,
                    "message": f"{out['message']} 请在数据对接中心继续处理该预演。",
                }
        items.append({"file_path": path, "file_name": label, **out})
        if write and out.get("outcome") == "unknown":
            deferred_count = total - index
            break
    if write:
        return _execution_batch_result(items, deferred_count=deferred_count, truncated=truncated)
    ready = [item for item in items if item.get("success")]
    needs_decision = [item for item in items if item.get("requires_user_decision")]
    run_ids = [str((item.get("data") or {}).get("run_id") or "") for item in ready]
    complete = (
        bool(run_ids)
        and all(run_ids)
        and len(ready) == len(items)
        and not (deferred_count or truncated)
    )
    executable = complete and not needs_decision
    run_ids = run_ids if executable else []
    message = (
        f"批量预演：{len(items)} 个文件，预演完成 {len(ready)}，"
        f"需人工确认 {len(needs_decision)}，未完成 {len(items) - len(ready)}"
    )
    if truncated:
        message += f"（一次最多 {_MAX_BATCH_IMPORTS} 个，其余请分批）"
    if deferred_count:
        message += f"；剩余 {deferred_count} 个文件未开始预演"
    if not complete:
        message += "；本批未进入业务写入"
    requires_decision = complete and bool(needs_decision)
    message += "".join(
        _companion_note((item.get("data") or {}).get("customer_products") or {}) for item in ready
    )
    return {
        "success": complete,
        "error_code": None if complete else "elt_preview_not_ready",
        "batch": True,
        "file_count": len(items),
        "ready_count": len(ready),
        "needs_decision_count": len(needs_decision),
        "deferred_count": deferred_count,
        "truncated": truncated,
        "message": message,
        "run_ids": run_ids,
        "requires_user_decision": requires_decision,
        "question": message if requires_decision else "",
        "resume_params": {
            key: value
            for item in needs_decision
            for key, value in item.get("resume_params", {}).items()
        },
        # 与单文件预演保持同一形状：编排引用 {{preview.data.run_id}} 也能取到值。
        "data": {
            "run_id": ",".join(run_ids),
            "run_ids": run_ids,
            "file_count": len(items),
            "ready_count": len(ready),
            "needs_decision_count": len(needs_decision),
            "executable": executable,
        },
        "results": items,
    }


def _execute_batch(run_ids: list[str], payload: dict, runtime_context: dict) -> dict:
    """整批执行：按预演 run 逐个写入，单个失败不影响其余。"""
    targets = run_ids[:_MAX_BATCH_IMPORTS]
    base = {**_single_params(payload), "run_ids": run_ids}
    items: list[dict] = []
    total = len(targets)
    for index, run_id in enumerate(targets, start=1):
        if not _can_start_file_stage(runtime_context):
            break
        label = _run_label(run_id, runtime_context)
        out = _run_execution_stage(run_id, base, runtime_context, index, total, label)
        items.append({"run_id": run_id, "file_name": label, **out})
        if out.get("outcome") == "unknown":
            break
    deferred = run_ids[len(items) :]
    out = _execution_batch_result(
        items, deferred_count=len(deferred), truncated=len(run_ids) > total
    )
    return {**out, "deferred_run_ids": deferred}


def _execution_batch_result(items: list[dict], *, deferred_count: int, truncated: bool) -> dict:
    done = [item for item in items if item.get("success")]
    uncertain = [item for item in items if item.get("outcome") == "unknown"]
    written = sum(_confirmed_written_rows(item) for item in items)
    skipped = sum(int((item.get("data") or {}).get("skip_rows") or 0) for item in done)
    pending_count = sum(item.get("deferred") is True for item in items)
    needs_review = sum(bool(item.get("requires_user_decision")) for item in items)
    failed_count = len(items) - len(done) - pending_count - needs_review - len(uncertain)
    complete = bool(done) and len(done) == len(items) and not (deferred_count or truncated)
    message = (
        f"批量导入：已处理 {len(items)} 份，完成 {len(done)} 份，"
        f"失败 {failed_count} 份，已确认写入 {written} 行"
    )
    if skipped:
        message += f"（重复跳过 {skipped} 行）"
        if complete and written == 0:
            message += "；本次没有新增业务记录"
    if truncated:
        message += f"（一次最多 {_MAX_BATCH_IMPORTS} 个，其余请分批）"
    if uncertain:
        message += "；" + "；".join(item["message"] for item in uncertain)
    if needs_review:
        message += f"；{needs_review} 份待确认，请在数据对接中心核对对应预演"
    if pending_count:
        message += f"；{pending_count} 份已有回执，剩余步骤待继续"
    if deferred_count:
        message += f"；剩余 {deferred_count} 份未提交执行"
    message += "".join(
        _companion_note((item.get("data") or {}).get("customer_products") or {}) for item in done
    )
    error_code = None if complete else "elt_execute_batch_incomplete"
    if uncertain:
        error_code = "tool_timeout_unknown"
    return {
        "success": complete,
        "error_code": error_code,
        **(
            {"outcome": "unknown", "reconciliation_required": True, "retryable": False}
            if uncertain
            else {}
        ),
        "batch": True,
        "run_count": len(items),
        "done_count": len(done),
        "pending_count": pending_count,
        "deferred_count": deferred_count,
        "deferred": not (uncertain or failed_count or needs_review)
        and bool(pending_count or deferred_count),
        "committed": written > 0,
        "data": {"executed_rows": written},
        "message": message,
        "results": items,
    }
