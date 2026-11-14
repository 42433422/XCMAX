"""用租户模板库中的真实模板填充数据行（禁止模型编造数据）。

调用方要么直接给 ``rows``（通常来自前序读取步骤的记录），要么给 ``file_path``
让本模块从源 Excel 中定位表头并抽取数据行。所有写出的单元格都来自源数据，
模板中找不到对应来源的列保持空白。
"""

from __future__ import annotations

import os
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl.cell.cell import MergedCell

from app.utils.operational_errors import RECOVERABLE_ERRORS

# 规范字段 -> 可接受的表头别名（顺序即优先级）。
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "原材料编号": (
        "原材料编号",
        "原料编号",
        "产品型号",
        "产品编号",
        "物料编号",
        "物料编码",
        "产品编码",
        "型号",
    ),
    "原料数量": (
        "原料数量（KG)",
        "原料数量(KG)",
        "原料数量",
        "数量/KG",
        "数量(KG)",
        "数量/千克",
        "用量",
        "重量",
        "数量",
    ),
    "工艺流程": ("工艺流程", "工艺", "工序"),
    "备注": ("备注", "说明"),
    "产品名称": ("产品名称", "品名", "名称"),
    "规格": ("规格", "规格型号", "规格/KG"),
    "单价": ("单价", "单价/元"),
    "金额": ("金额", "金额/元"),
    "客户名称": ("客户名称", "客户", "购货单位", "单位名称"),
}

_FOOTER_ROW_RE = re.compile(
    r"^(合计|总计|小计|共计|总金额|总价|大写|销售|购货|收货|签收|备注[:：]|制单|送货|负责人|经手人|电话|地址|开户|账号)"
)
_MAX_SCAN_ROWS = 30
_MAX_SCAN_COLS = 40


def _normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u3000", "").replace(" ", "").replace("\n", "").replace("\r", "")
    return text.replace("（", "(").replace("）", ")").replace("：", ":")


def _canonical_field(header: Any) -> str | None:
    normalized = _normalize(header)
    if not normalized:
        return None
    for field, aliases in _FIELD_ALIASES.items():
        if normalized in {_normalize(alias) for alias in aliases}:
            return field
    return None


def _match_source_header(field: str, headers: list[str]) -> str | None:
    """在源表头里为规范字段挑一个最合适的列（精确优先，其次包含关系）。"""
    normalized_headers = [(_normalize(h), h) for h in headers if _normalize(h)]
    for alias in _FIELD_ALIASES.get(field, ()):
        target = _normalize(alias)
        for norm, original in normalized_headers:
            if norm == target:
                return original
    for alias in _FIELD_ALIASES.get(field, ()):
        target = _normalize(alias)
        if len(target) < 2:
            continue
        for norm, original in normalized_headers:
            if target in norm or norm in target:
                return original
    return None


def _template_header(ws: Any) -> tuple[int, list[str]]:
    """定位模板表头行：首个包含至少 2 个已知字段的行。"""
    max_row = min(int(ws.max_row or 1), _MAX_SCAN_ROWS)
    max_col = min(int(ws.max_column or 1), _MAX_SCAN_COLS)
    for row_idx in range(1, max_row + 1):
        labels = [
            str(ws.cell(row_idx, col_idx).value).strip()
            for col_idx in range(1, max_col + 1)
            if ws.cell(row_idx, col_idx).value not in (None, "")
        ]
        known = [label for label in labels if _canonical_field(label)]
        if len(known) >= 2:
            return row_idx, labels
    if max_row >= 1:
        return 1, [
            str(ws.cell(1, col_idx).value).strip()
            for col_idx in range(1, max_col + 1)
            if ws.cell(1, col_idx).value not in (None, "")
        ]
    return 1, []


def _read_source_records(
    file_path: str, sheet_name: str | None
) -> tuple[list[dict[str, Any]], list[str], str]:
    """从源 Excel 定位表头并返回记录、表头与 sheet 名。"""
    from openpyxl import load_workbook

    wb = load_workbook(file_path, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]
        max_row = min(int(ws.max_row or 1), _MAX_SCAN_ROWS)
        max_col = min(int(ws.max_column or 1), _MAX_SCAN_COLS)
        best_row = 0
        best_headers: list[str] = []
        best_score = 0
        for row_idx in range(1, max_row + 1):
            headers = [
                str(ws.cell(row_idx, col_idx).value).strip()
                for col_idx in range(1, max_col + 1)
            ]
            score = sum(1 for h in headers if _canonical_field(h))
            if score > best_score:
                best_row, best_headers, best_score = row_idx, headers, score
        if best_score < 2:
            raise ValueError("源文件未识别到可用表头，请确认数据行包含产品型号/数量等列")
        records: list[dict[str, Any]] = []
        for row_idx in range(best_row + 1, int(ws.max_row or best_row) + 1):
            values = [ws.cell(row_idx, col_idx).value for col_idx in range(1, len(best_headers) + 1)]
            if all(v in (None, "") for v in values):
                continue
            first_text = str(next((v for v in values if v not in (None, "")), "") or "").strip()
            # 表尾合计/协议/签章等说明行不是明细行，写入模板会污染数据区。
            if _FOOTER_ROW_RE.match(first_text.replace(" ", "").replace("\u3000", "")):
                break
            records.append(
                {
                    header: values[index]
                    for index, header in enumerate(best_headers)
                    if header and values[index] not in (None, "")
                }
            )
        if not records:
            raise ValueError("源文件表头下没有可用数据行")
        return records, [h for h in best_headers if h], ws.title
    finally:
        wb.close()


def _resolve_template(template_id: str, template_name: str, tenant_id: int | None) -> dict[str, Any]:
    from app.application import get_template_app_service
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(tenant_id):
        result = get_template_app_service().get_templates()
    templates = result.get("templates") if isinstance(result, dict) else result
    candidates = [t for t in (templates or []) if isinstance(t, dict) and t.get("path")]
    if template_id:
        wanted = str(template_id).strip()
        wanted = wanted if wanted.startswith("db:") else wanted
        matched = [
            t
            for t in candidates
            if str(t.get("id")) == wanted
            or str(t.get("db_id")) == wanted
            or f"db:{t.get('db_id')}" == wanted
        ]
    else:
        wanted_name = _normalize(template_name)
        matched = [
            t
            for t in candidates
            if wanted_name and wanted_name in _normalize(t.get("name"))
        ]
    if not matched:
        raise ValueError(
            f"模板库中找不到模板：{template_id or template_name}"
            "（请先确认模板已入库，且当前账号有该模板所属租户的权限）"
        )
    matched.sort(key=lambda t: int(t.get("db_id") or 0), reverse=True)
    return matched[0]


def fill_document_from_template(
    *,
    template_id: str | None = None,
    template_name: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    file_path: str | None = None,
    sheet_name: str | None = None,
    field_mapping: dict[str, str] | None = None,
    output_name: str | None = None,
    tenant_id: int | None = None,
    workspace_root: str | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按模板写入真实数据行，返回 ``{"content": bytes, "file_name": str, ...}``。"""
    if not template_id and not template_name:
        raise ValueError("缺少 template_id 或 template_name")

    template = _resolve_template(str(template_id or ""), str(template_name or ""), tenant_id)
    template_path = str(template.get("path") or "")
    if not os.path.exists(template_path):
        raise ValueError(f"模板文件不存在：{template_path}")

    from openpyxl import load_workbook

    wb = load_workbook(template_path)
    try:
        ws = wb[wb.sheetnames[0]] if wb.sheetnames else wb.active
        if ws is None:
            raise ValueError("模板工作簿没有工作表")
        template_sheet = ws.title
        header_row, template_labels = _template_header(ws)
    finally:
        wb.close()
    if not template_labels:
        raise ValueError("模板未识别到表头行，无法确定要填充的列")

    source_headers: list[str] = []
    source_records = rows or []
    resolved_sheet = ""
    if not source_records:
        if not file_path:
            raise ValueError("缺少数据来源：请提供 rows 或源文件 file_path")
        from app.infrastructure.tenant_scope import tenant_scope

        # 审批后执行发生后台线程，没有请求上下文，必须显式带上租户做归属校验。
        with tenant_scope(tenant_id):
            resolved_path = _resolve_source_path(file_path, workspace_root, runtime_context)
        source_records, source_headers, resolved_sheet = _read_source_records(
            resolved_path, sheet_name
        )
    if not source_records:
        raise ValueError("没有可写入的数据行")

    if not source_headers:
        for record in source_records:
            if isinstance(record, dict):
                for key in record:
                    text = str(key)
                    if text not in source_headers:
                        source_headers.append(text)

    mapping: dict[str, str] = {}
    for label in template_labels:
        canonical = _canonical_field(label)
        explicit = (field_mapping or {}).get(label)
        if not explicit and canonical:
            explicit = (field_mapping or {}).get(canonical)
        if explicit:
            mapping[label] = str(explicit)
            continue
        if canonical and canonical in source_headers:
            mapping[label] = canonical
            continue
        found = _match_source_header(canonical, source_headers) if canonical else None
        if found is None and _normalize(label) in {_normalize(h) for h in source_headers}:
            found = next(h for h in source_headers if _normalize(h) == _normalize(label))
        if found:
            mapping[label] = found

    normalized_records: list[dict[str, Any]] = []
    for record in source_records:
        if not isinstance(record, dict):
            continue
        normalized = {
            label: record.get(source_key)
            for label, source_key in mapping.items()
            if source_key in record
        }
        if any(value not in (None, "") for value in normalized.values()):
            normalized_records.append(normalized)
    if not normalized_records:
        raise ValueError(
            "源数据与模板表头没有可对应的列（模板："
            + "/".join(template_labels)
            + "；源表头："
            + "/".join(source_headers[:10])
            + "）"
        )

    try:
        truncated = _write_rows_into_template(
            template_path,
            template_sheet,
            header_row,
            template_labels,
            normalized_records,
        )
    except RECOVERABLE_ERRORS as error:
        raise ValueError(f"写入模板失败：{error}") from error
    base_name = str(template_name or template.get("name") or "模板").strip() or "模板"
    file_name = (output_name or "").strip() or f"{base_name}-{date.today().isoformat()}.xlsx"
    if not file_name.lower().endswith(".xlsx"):
        file_name += ".xlsx"
    return {
        "content": truncated["content"],
        "file_name": file_name,
        "template_id": str(template.get("id") or ""),
        "template_name": str(template.get("name") or base_name),
        "template_path": template_path,
        "sheet_name": resolved_sheet,
        "row_count": truncated["written_rows"],
        "skipped_rows": truncated["skipped_rows"],
        "field_mapping": mapping,
        "unmapped_labels": [label for label in template_labels if label not in mapping],
    }


def _write_rows_into_template(
    template_path: str,
    sheet_name: str,
    header_row: int,
    template_labels: list[str],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """把记录写进模板的数据区，跳过合并单元格的非锚点格与页脚区域。"""
    from openpyxl import load_workbook

    wb = load_workbook(template_path)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else (wb.active or wb.worksheets[0])
    columns: dict[str, int] = {}
    for col_idx in range(1, (ws.max_column or 1) + 1):
        text = _normalize(ws.cell(header_row, col_idx).value)
        for label in template_labels:
            if label not in columns and _normalize(label) == text:
                columns[label] = col_idx
    if not columns:
        raise ValueError("模板表头列定位失败")
    first_col = min(columns.values())

    data_start = header_row + 1
    data_end = data_start - 1
    row_idx = data_start
    while row_idx <= (ws.max_row or data_start):
        if ws.cell(row_idx, first_col).value not in (None, ""):
            break
        data_end = row_idx
        row_idx += 1
    capacity = max(data_end - data_start + 1, 0)
    if capacity <= 0:
        raise ValueError("模板表头下方没有可写的数据行")

    # 纵向合并的整块列（如工艺/备注共用一块）只写锚点，取记录里第一个非空值。
    block_columns = {
        col_idx: label
        for label, col_idx in columns.items()
        if data_start + 1 <= (ws.max_row or 0)
        and isinstance(ws.cell(data_start + 1, col_idx), MergedCell)
        and not isinstance(ws.cell(data_start, col_idx), MergedCell)
    }
    block_values: dict[int, Any] = {}

    writable = records[:capacity]
    for offset, record in enumerate(writable):
        row_idx = data_start + offset
        for label, col_idx in columns.items():
            cell = ws.cell(row_idx, col_idx)
            if isinstance(cell, MergedCell):
                value = record.get(label)
                if col_idx in block_columns and value not in (None, "") and col_idx not in block_values:
                    block_values[col_idx] = value
                continue
            value = record.get(label)
            cell.value = value if value not in (None, "") else ""
    for col_idx, value in block_values.items():
        anchor = ws.cell(data_start, col_idx)
        if not isinstance(anchor, MergedCell) and anchor.value in (None, ""):
            anchor.value = value

    buffer = BytesIO()
    wb.save(buffer)
    return {
        "content": buffer.getvalue(),
        "written_rows": len(writable),
        "skipped_rows": max(len(records) - len(writable), 0),
    }


def _resolve_source_path(
    file_path: str,
    workspace_root: str | None,
    runtime_context: dict[str, Any] | None = None,
) -> str:
    raw = str(file_path or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("缺少源文件路径")
    if runtime_context:
        # 有登录上下文时必须走归属校验：只允许读当前账号在当前租户的上传文件。
        from app.application.tools.workflow_spreadsheet_scope import (
            resolve_owned_upload_path,
        )

        owned = resolve_owned_upload_path(raw, runtime_context)
        if owned and owned != raw and os.path.exists(owned):
            return owned
        if os.path.isabs(owned) and os.path.exists(owned):
            return owned
        raise ValueError(
            f"找不到源文件或文件不属于当前账号：{raw}（请重新上传，或改用 rows 直接传入数据）"
        )
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw
    from app.infrastructure.workspace import (
        resolve_existing_file_under_root,
        resolve_existing_workspace_file,
    )

    rel = raw.lstrip("@").lstrip("/")
    errors: list[Exception] = []
    if workspace_root:
        try:
            return str(resolve_existing_file_under_root(Path(workspace_root), rel))
        except (FileNotFoundError, ValueError, OSError) as error:
            errors.append(error)
    try:
        return str(resolve_existing_workspace_file(rel))
    except (FileNotFoundError, ValueError, OSError) as error:
        errors.append(error)
    raise ValueError(
        f"找不到源文件：{raw}（请确认上传文件仍在工作区，或改用 rows 直接传入数据）"
    ) from errors[-1]


__all__ = ["fill_document_from_template"]
