"""Excel import source, customer, sheet, and reload resolution."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any, Callable

from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _EXCEL_IMPORT_QTY_MEASURE_RE,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExcelImportContextResolver:
    @staticmethod
    def _resolve_excel_path_for_import(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> str:
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not fp and isinstance(preview_data, dict):
            fp = str(preview_data.get("file_path") or "").strip()
        return fp

    @staticmethod
    def _customer_hint_from_preview_grid(preview_data: dict[str, Any]) -> str:
        """与前端网格预览一致：从 grid_preview.rows[].text 解析抬头里的客户名（合并单元格常见）。"""
        if not isinstance(preview_data, dict):
            return ""
        gp = preview_data.get("grid_preview")
        if not isinstance(gp, dict):
            return ""
        grid_rows = gp.get("rows")
        if not isinstance(grid_rows, list):
            return ""
        try:
            from app.application.template_grid_core import _extract_inline_customer_hits_from_cell
        except RECOVERABLE_ERRORS:
            return ""
        for row in grid_rows[:22]:
            if not isinstance(row, list):
                continue
            parts: list[str] = []
            for cell in row:
                if not isinstance(cell, dict):
                    continue
                t = str(cell.get("text") or "").strip()
                if not t:
                    continue
                hits = _extract_inline_customer_hits_from_cell(t)
                if hits:
                    return hits[0]
                parts.append(t)
            joined = " ".join(parts).strip()
            if joined:
                hits = _extract_inline_customer_hits_from_cell(joined)
                if hits:
                    return hits[0]
        return ""

    @staticmethod
    def _excel_cell_looks_like_product_measure_unit(value: Any) -> bool:
        """单元格是否为 SKU 计量单位（非客户全称），用于入库时避免把「件」当成客户。"""
        t = str(value or "").strip()
        if not t:
            return False
        if t.lower() in _EXCEL_IMPORT_MEASURE_UNIT_TOKENS:
            return True
        return bool(_EXCEL_IMPORT_QTY_MEASURE_RE.match(t))

    @staticmethod
    def _default_purchase_unit_for_import(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
        *,
        customer_hint_from_grid: Callable[[dict[str, Any]], str] | None = None,
        resolve_excel_path: Callable[[dict[str, Any], dict[str, Any]], str] | None = None,
        resolve_sheet_name: Callable[..., str | None] | None = None,
        guess_default_unit: Callable[[dict[str, Any]], str] | None = None,
    ) -> str:
        """
        默认客户：优先读表内「客户」类标签与标题区公司名；文档没有时再退回文件名推断。
        """
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 开始, request_context type: %s",
            type(request_context).__name__,
        )
        if isinstance(request_context, dict):
            hint = str(request_context.get("excel_customer_hint") or "").strip()
            logger.debug("[导入调试] request_context.excel_customer_hint = %s", repr(hint))
            if hint:
                return hint
        if isinstance(preview_data, dict):
            hint = str(
                preview_data.get("customer_hint")
                or preview_data.get("document_customer")
                or excel_analysis.get("customer_hint")
                or ""
            ).strip()
            logger.debug("[导入调试] preview_data/excel_analysis customer_hint = %s", repr(hint))
            if hint:
                return hint
        customer_hint_from_grid = (
            customer_hint_from_grid or ExcelImportContextResolver._customer_hint_from_preview_grid
        )
        grid_hint = customer_hint_from_grid(preview_data)
        if grid_hint:
            return grid_hint
        resolve_excel_path = (
            resolve_excel_path or ExcelImportContextResolver._resolve_excel_path_for_import
        )
        resolve_sheet_name = (
            resolve_sheet_name or ExcelImportContextResolver._resolve_sheet_name_for_reimport
        )
        fp = resolve_excel_path(excel_analysis, preview_data)
        sheet = resolve_sheet_name(excel_analysis, preview_data, request_context)
        if fp:
            path = Path(fp)
            if path.is_file():
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel

                    doc_unit = str(
                        _extract_customer_hint_from_excel(str(path), sheet) or ""
                    ).strip()
                    if doc_unit:
                        return doc_unit
                except RECOVERABLE_ERRORS as err:
                    logger.debug("从工作簿读取客户提示失败: %s", err)
        guess_default_unit = (
            guess_default_unit or ExcelImportContextResolver._guess_default_purchase_unit
        )
        return guess_default_unit(excel_analysis)

    @staticmethod
    def _guess_default_purchase_unit(excel_analysis: dict[str, Any]) -> str:
        """
        仅作兜底：报价类文件无表内客户信息时，用文件名猜测公司名。
        """
        name = str(
            excel_analysis.get("file_name") or excel_analysis.get("template_name") or ""
        ).strip()
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not name and fp:
            name = Path(fp).name
        stem = Path(name).stem if name else ""
        stem = str(stem).strip()
        if not stem:
            return ""
        stem = re.sub(r"\d{2,4}年?$", "", stem).strip()
        for token in ("产品报价表", "报价表", "报价单", "价格表", "产品报价", "报价"):
            if stem.endswith(token):
                stem = stem[: -len(token)].strip()
        m = re.search(
            r"(.+?(?:有限公司|股份有限公司|集团有限公司|实业有限公司|科技公司|集团公司|公司|厂|店))",
            stem,
        )
        if m:
            return m.group(1).strip()
        return stem if len(stem) >= 2 else ""

    @staticmethod
    def _sanitize_import_scalar(val: Any) -> Any:
        """pandas/openpyxl 空值与 nan，避免参与字段推断时出现字面量 'nan'。"""
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        if isinstance(val, str):
            s = val.strip()
            if s.lower() in ("nan", "none", "nat", "<na>", "null"):
                return None
            return s
        try:
            fv = float(val)
            if fv != fv:
                return None
        except (TypeError, ValueError):
            pass
        return val

    @staticmethod
    def _resolve_force_header_row_1based(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> int | None:
        """与前端 slim 上下文中的 grid_preview.header_row_index / tables[].header_row 对齐。"""
        pd = preview_data if isinstance(preview_data, dict) else {}
        gp = pd.get("grid_preview") if isinstance(pd.get("grid_preview"), dict) else {}
        for key in ("header_row_index",):
            raw = gp.get(key)
            if raw is not None:
                try:
                    n = int(raw)
                    if n >= 1:
                        return n
                except (TypeError, ValueError):
                    pass
        tables = pd.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                raw = t.get("header_row")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets:
            for s in sheets:
                if not isinstance(s, dict):
                    continue
                st = s.get("tables")
                if isinstance(st, list):
                    for t in st:
                        if not isinstance(t, dict):
                            continue
                        raw = t.get("header_row")
                        if raw is not None:
                            try:
                                n = int(raw)
                                if n >= 1:
                                    return n
                            except (TypeError, ValueError):
                                pass
                sg = s.get("grid_preview") if isinstance(s.get("grid_preview"), dict) else {}
                raw = sg.get("header_row_index")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        return None

    @staticmethod
    def _resolve_sheet_name_for_reimport(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str | None:
        if isinstance(request_context, dict):
            sel = request_context.get("excel_analysis_selected_sheet")
            if isinstance(sel, dict):
                sn = str(sel.get("sheet_name") or "").strip()
                if sn:
                    return sn
            ps = str(request_context.get("preferred_sheet_name") or "").strip()
            if ps:
                return ps
        if isinstance(preview_data, dict):
            for key in ("selected_sheet_name", "sheet_name"):
                v = preview_data.get(key)
                if v and str(v).strip():
                    return str(v).strip()
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets and isinstance(sheets[0], dict):
            sn = sheets[0].get("sheet_name")
            if sn and str(sn).strip():
                return str(sn).strip()
        return None

    @staticmethod
    def _try_structured_reload_records(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """
        聊天上下文里的 sample_rows 常来自 pandas（Unnamed 列）或已被截断；若服务器上仍有原文件，
        默认用 openpyxl 表头识别重读；若 preview_data.parse_mode 为 rectangular，则按矩形区域全读（列键 A/B/…），
        不再依赖推断的数据表头行。
        """
        fp = str(excel_analysis.get("file_path") or "").strip() or (
            str(preview_data.get("file_path") or "").strip()
            if isinstance(preview_data, dict)
            else ""
        )
        if not fp:
            return None
        path = Path(fp)
        if not path.is_file():
            return None
        sheet = ExcelImportContextResolver._resolve_sheet_name_for_reimport(
            excel_analysis, preview_data, request_context
        )
        force_hdr = ExcelImportContextResolver._resolve_force_header_row_1based(
            excel_analysis, preview_data
        )
        try:
            pd0 = preview_data if isinstance(preview_data, dict) else {}
            if str(pd0.get("parse_mode") or "").strip().lower() == "rectangular":
                from app.application.template_grid_core import _extract_rectangular_excel_preview

                structured = _extract_rectangular_excel_preview(str(path), sheet_name=sheet)
            else:
                from app.application.template_grid_core import _extract_structured_excel_preview

                structured = _extract_structured_excel_preview(
                    str(path),
                    sheet_name=sheet,
                    sample_limit=800,
                    force_header_row_1based=force_hdr,
                )
            rows = structured.get("sample_rows") or []
            if not isinstance(rows, list) or not rows:
                return None
            out: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    out.append(
                        {
                            k: ExcelImportContextResolver._sanitize_import_scalar(v)
                            for k, v in row.items()
                        }
                    )
            return out or None
        except RECOVERABLE_ERRORS as err:
            logger.debug("结构化重读 Excel 跳过: %s", err)
            return None


__all__ = ["ExcelImportContextResolver"]
