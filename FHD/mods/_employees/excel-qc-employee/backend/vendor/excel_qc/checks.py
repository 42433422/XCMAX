"""独立 Excel 质检：核对计划、保护区、统计、公式、追溯及结构。

只读取 plan/rules/write_report 和 XLSX，不导入映射员或写入员代码。
缺少核验输入时明确跳过或警告；失败优先于警告，问责路由见 _BLAME。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .plan_coordinates import (
    affected_reserved_names as _affected_reserved_names,
)
from .plan_coordinates import (
    declared_ranges as _declared_ranges,
)
from .plan_coordinates import (
    declared_validation_name as _declared_validation_name,
)
from .plan_coordinates import (
    defined_names as _defined_names,
)
from .plan_coordinates import (
    final_writes as _final_writes,
)
from .plan_coordinates import (
    in_ranges as _in_ranges,
)
from .plan_coordinates import (
    insertions as _insertions,
)
from .plan_coordinates import (
    iter_writes as _iter_writes,
)
from .plan_coordinates import (
    moved_row as _moved_row,
)
from .plan_coordinates import (
    original_row as _original_row,
)
from .plan_coordinates import (
    plan_phases as _plan_phases,
)
from .plan_coordinates import (
    range_bounds as _range_bounds,
)
from .plan_coordinates import (
    reference_sheet as _reference_sheet,
)
from .plan_coordinates import (
    shift_formula_rows as _shift_formula_rows,
)
from .plan_coordinates import (
    shifted_name_definition as _shifted_name_definition,
)
from .plan_coordinates import (
    target as _target,
)
from .plan_coordinates import (
    unsafe_named_control_order as _unsafe_named_control_order,
)
from .styles import check_cell_styles as _check_cell_styles
from .styles import style_signature as _style_signature
from .table_integrity import check_inserted_tables

_MAX_SAMPLES = 8
_NUM_TOL = 1e-6

_REF_ERR_RE = re.compile(r"#REF!")


def canonical_rules_sha256(rules: Dict[str, Any]) -> str:
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _Finding:
    """一节检查的累积器。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "pass"
        self.issues: List[Dict[str, Any]] = []
        self.stats: Dict[str, Any] = {}
        self.skipped_reason = ""

    def fail(self, detail: str, **extra: Any) -> None:
        self.status = "fail"
        if len(self.issues) < _MAX_SAMPLES * 4:
            self.issues.append({"severity": "fail", "detail": detail, **extra})

    def warn(self, detail: str, **extra: Any) -> None:
        if self.status == "pass":
            self.status = "warn"
        if len(self.issues) < _MAX_SAMPLES * 4:
            self.issues.append({"severity": "warn", "detail": detail, **extra})

    def skip(self, reason: str) -> None:
        self.status = "skipped"
        self.skipped_reason = reason

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "issues": self.issues, "stats": self.stats}
        if self.skipped_reason:
            out["skipped_reason"] = self.skipped_reason
        return out


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M",
)


def _coerce_planned(value: Any, value_type: str) -> Any:
    """还原写入员的 value_type 语义（独立实现，不 import 写入员）。"""
    vtype = (value_type or "").strip().lower()
    if not vtype or vtype in ("auto", "string", "str"):
        return value
    text = str(value or "").strip()
    if vtype == "number":
        try:
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            return value
    if vtype == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return value
    if vtype == "datetime":
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return value
    return value


def _values_match(planned: Any, actual: Any) -> bool:
    if planned is None and actual is None:
        return True
    if isinstance(planned, (int, float)) and not isinstance(planned, bool):
        if isinstance(actual, (int, float)) and not isinstance(actual, bool):
            return abs(float(planned) - float(actual)) <= _NUM_TOL
        return False
    if isinstance(planned, date) and not isinstance(planned, datetime):
        if isinstance(actual, datetime):
            return actual.date() == planned and actual.time() == datetime.min.time()
        return actual == planned
    return str(planned) == str(actual) if planned is not None else actual is None


# 六节检查


_STRUCTURAL_PHASES = {"insert_rows", "merge_cells", "set_row_height", "freeze_panes"}


def _check_named_validations(wb, template_wb, plan, finding):
    from collections import Counter

    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.xml.functions import tostring

    changes = tuple(_insertions(plan))
    for ws in wb.worksheets:
        original = template_wb[ws.title] if ws.title in template_wb.sheetnames else None
        validations = (
            [item for item in original.data_validations.dataValidation if item.type == "list"]
            if original is not None
            else []
        )
        for item in validations:
            if any(
                target.casefold() == ws.title.casefold() and row <= area.max_row
                for target, row, _ in changes
                for area in item.sqref.ranges
            ):
                finding.fail(
                    "既有定义名称下拉的应用范围受插行影响，暂不支持迁移",
                    sheet=ws.title,
                    range=str(item.sqref),
                )
        expected = Counter(tostring(item.to_tree()) for item in validations)
        for phase in _plan_phases(plan):
            if (
                phase.get("phase") == "data_validation"
                and phase.get("rule") == "list"
                and phase.get("sheet") == ws.title
            ):
                try:
                    item = DataValidation(
                        type="list",
                        formula1=phase["name"],
                        showErrorMessage=True,
                        errorStyle="stop",
                        error=phase["error"],
                    )
                    item.add(str(phase["range"]).upper().replace("$", ""))
                    expected[tostring(item.to_tree())] += 1
                except (KeyError, TypeError, ValueError) as exc:
                    finding.fail("声明的下拉验证元数据无法核验", sheet=ws.title, reason=str(exc))
        actual = Counter(
            tostring(item.to_tree())
            for item in ws.data_validations.dataValidation
            if item.type == "list"
        )
        if actual != expected:
            finding.fail("既有下拉验证元数据改变、缺失或出现未声明追加", sheet=ws.title)


def _check_defined_names(wb, template_wb, plan, finding):
    from openpyxl.formula.tokenizer import TokenizerError

    _check_named_validations(wb, template_wb, plan, finding)
    for sheet, name in _unsafe_named_control_order(plan):
        finding.fail("定义名称下拉创建后的受影响插行暂不支持", sheet=sheet, name=name)
    for sheet, name in _affected_reserved_names(template_wb, plan):
        finding.fail("受影响的保留定义名称暂不支持插行迁移", sheet=sheet, name=name)
    layouts = {
        phase.get("sheet") for phase in _plan_phases(plan) if phase.get("phase") == "print_layout"
    }
    for sheet in wb.worksheets:
        original = template_wb[sheet.title] if sheet.title in template_wb.sheetnames else None
        for attribute in ("print_area", "print_title_rows", "print_title_cols"):
            if sheet.title in layouts and attribute != "print_title_cols":
                continue  # The declared fields are checked by control_matches.
            before, after = (
                str(getattr(original, attribute, None) or ""),
                str(getattr(sheet, attribute) or ""),
            )
            if before != after:
                finding.fail(
                    "未经授权的保留定义名称改变",
                    sheet=sheet.title,
                    name=attribute,
                    planned=before,
                    actual=after,
                )
    expected = _defined_names(template_wb, wb.sheetnames)
    for phase in _plan_phases(plan):
        changes = tuple(_insertions({"phases": [phase]}))
        if changes:
            for (scope, name), text in list(expected.items()):
                try:
                    expected[scope, name] = _shifted_name_definition(
                        text, scope, template_wb, changes
                    )
                except (ValueError, KeyError, TokenizerError) as exc:
                    finding.fail(
                        "定义名称无法独立核验插行迁移", sheet=scope, name=name, reason=str(exc)
                    )
        elif phase.get("phase") == "data_validation" and phase.get("rule") == "list":
            try:
                key, text = _declared_validation_name(phase, wb)
                if key in expected and expected[key] != text:
                    raise ValueError("计划定义名称覆盖既有绑定")
                expected[key] = text
            except (ValueError, KeyError, TypeError) as exc:
                finding.fail("计划创建的定义名称无效", reason=str(exc))
    actual = _defined_names(wb)
    for scope, name in expected.keys() ^ actual.keys():
        finding.fail("定义名称新增、缺失或作用域改变", sheet=scope, name=name)
    for (scope, name), text in expected.items():
        if actual.get((scope, name)) != text:
            finding.fail(
                "定义名称目的地未按插行迁移",
                sheet=scope,
                name=name,
                planned=text,
                actual=actual.get((scope, name)),
            )


def _check_insert_rows(wb, plan, template_wb, planned_targets, f) -> None:
    if template_wb is None:
        f.warn("未提供原模板，插入行后的数据与公式迁移无法独立核验")
        return
    insertions = tuple(_insertions(plan))
    _check_defined_names(wb, template_wb, plan, f)
    check_inserted_tables(wb, template_wb, plan, f)
    style_ranges = _declared_ranges(plan, "cell_styles", wb)
    for target, _, _ in insertions:
        if target not in template_wb.sheetnames:
            f.fail("插入行的 sheet 不在原模板中", sheet=target)
    clear_ranges = _declared_ranges(plan, "clear_ranges", wb)
    formats = {
        _target(w)
        for kind in ("cell_writes", "formula_writes")
        for w in _final_writes(plan, kind)
        if w.get("number_format")
    }
    issues = 0
    for tpl in template_wb.worksheets:
        sheet = tpl.title
        if sheet not in wb.sheetnames:
            continue
        out = wb[sheet]
        for original in tuple(tpl._cells.values()):
            r, c = _moved_row(sheet, original.row, insertions), original.column
            target, actual = (sheet, r, c), out.cell(r, c)
            expected = original.value
            if isinstance(expected, str) and expected.startswith("="):
                expected = _shift_formula_rows(expected, sheet, insertions)
            overridden = target in planned_targets or _in_ranges(clear_ranges, sheet, r, c)
            if not overridden and not _values_match(expected, actual.value):
                issues += 1
                f.fail(
                    "插入行后原数据或公式引用未按行迁移",
                    sheet=sheet,
                    template_ref=original.coordinate,
                    actual_ref=actual.coordinate,
                    planned=str(expected)[:80],
                    actual=str(actual.value)[:80],
                )
            changed = {"number_format"} if target in formats else set()
            for *bounds, style in style_ranges:
                if _in_ranges([bounds], sheet, r, c):
                    changed.update(
                        key for key in ("bold", "font_size") if style.get(key) is not None
                    )
                    changed.update(
                        key
                        for key in ("horizontal", "vertical", "fill_color", "border")
                        if str(style.get(key) or "").strip()
                    )
            if _style_signature(original, changed) != _style_signature(actual, changed):
                issues += 1
                f.fail(
                    "插入行后原样式未保留",
                    sheet=sheet,
                    template_ref=original.coordinate,
                    actual_ref=actual.coordinate,
                )
            if issues >= _MAX_SAMPLES * 4:
                return
        for cell in tuple(out._cells.values()):
            if (
                cell.value is not None
                and _original_row(sheet, cell.row, insertions) is None
                and (sheet, cell.row, cell.column) not in planned_targets
            ):
                f.fail("插入空行出现计划外数据", sheet=sheet, ref=cell.coordinate)
        merged = {(r.min_row, r.min_col, r.max_row, r.max_col) for r in out.merged_cells.ranges}
        for region in tpl.merged_cells.ranges:
            bounds = (
                _moved_row(sheet, region.min_row, insertions),
                region.min_col,
                _moved_row(sheet, region.max_row, insertions),
                region.max_col,
            )
            if bounds not in merged:
                f.fail("插入行后原合并区域未保留", sheet=sheet, range=str(region))
        heights = {
            _moved_row(sheet, int(ph["row"]), _insertions(plan, index + 1))
            for index, ph in enumerate(_plan_phases(plan))
            if ph.get("phase") == "set_row_height" and ph.get("sheet") == sheet
        }
        for row, dimension in tpl.row_dimensions.items():
            target_row = _moved_row(sheet, row, insertions)
            if (
                target_row not in heights
                and dimension.height != out.row_dimensions[target_row].height
            ):
                f.fail("插入行后原行高未保留", sheet=sheet, row=target_row)


def _check_structural(wb, plan, template_wb, planned_targets, f) -> int:
    from openpyxl.utils.cell import range_boundaries

    checked = 0
    checked_insertions = False
    for index, ph in enumerate(_plan_phases(plan)):
        kind = str(ph.get("phase"))
        if kind not in _STRUCTURAL_PHASES:
            continue
        checked += 1
        sheet = str(ph.get("sheet") or "").strip().strip("'")
        if sheet not in wb.sheetnames:
            f.fail(f"{kind} 的 sheet 不在输出中：{sheet!r}")
            continue
        ws = wb[sheet]
        try:
            if kind == "insert_rows":
                row, count = int(ph.get("row")), int(ph.get("count"))
                if row < 1 or count < 1:
                    raise ValueError("插行位置与数量必须为正数")
                if not checked_insertions:
                    _check_insert_rows(wb, plan, template_wb, planned_targets, f)
                    checked_insertions = True
            elif kind == "merge_cells":
                left, top, right, bottom = range_boundaries(str(ph.get("range")).upper())
                later = tuple(_insertions(plan, index + 1))
                top, bottom = _moved_row(sheet, top, later), _moved_row(sheet, bottom, later)
                merged = {
                    (r.min_row, r.min_col, r.max_row, r.max_col) for r in ws.merged_cells.ranges
                }
                if (top, left, bottom, right) not in merged:
                    f.fail("计划合并区域在输出中不存在", sheet=sheet, range=str(ph.get("range")))
            elif kind == "set_row_height":
                row = _moved_row(sheet, int(ph.get("row")), _insertions(plan, index + 1))
                height = ws.row_dimensions[row].height
                if height is None or abs(float(height) - float(ph.get("height"))) > _NUM_TOL:
                    f.fail(
                        "行高与计划不符",
                        sheet=sheet,
                        row=row,
                        planned=str(ph.get("height")),
                        actual=str(height),
                    )
            else:
                ref = str(ph.get("ref") or "").strip().upper()
                if str(ws.freeze_panes or "").upper() != ref:
                    f.fail(
                        "冻结窗格与计划不符", sheet=sheet, planned=ref, actual=str(ws.freeze_panes)
                    )
        except (TypeError, ValueError, KeyError) as exc:
            f.fail(f"{kind} 计划无法核验：{exc}", sheet=sheet)
    return checked


def _check_conformance(
    wb, plan: Dict[str, Any], write_report: Optional[Dict[str, Any]], template_wb=None
) -> _Finding:
    f = _Finding("conformance")
    cell_writes = _final_writes(plan, "cell_writes")
    formula_writes = _final_writes(plan, "formula_writes")
    planned_targets: set[Tuple[str, int, int]] = set()

    checked = 0
    for kind, writes in (("cell_writes", cell_writes), ("formula_writes", formula_writes)):
        formula = kind == "formula_writes"
        for w in writes:
            try:
                sheet, row, col = _target(w)
            except (TypeError, ValueError, KeyError) as exc:
                f.fail(f"计划 {kind} 条目非法：{exc}", write=w)
                continue
            planned_targets.add((sheet, row, col))
            location = {"sheet": sheet, "row": row, "col": col}
            if sheet not in wb.sheetnames:
                noun = "公式" if formula else "写入"
                f.fail(f"计划{noun}的 sheet 不在输出中：{sheet!r}", row=row, col=col)
                continue
            cell = wb[sheet].cell(row, col)
            actual, raw = cell.value, w.get("formula" if formula else "value")
            planned = raw if formula else _coerce_planned(raw, str(w.get("value_type") or ""))
            matches = str(actual) == str(planned) if formula else _values_match(planned, actual)
            checked += 1
            if not matches:
                detail, limit = ("公式与计划不符", 80) if formula else ("格值与计划不符", None)
                f.fail(detail, **location, planned=str(raw)[:limit], actual=str(actual)[:limit])
            nf = w.get("number_format")
            if not formula and nf and cell.number_format != str(nf):
                f.warn(
                    "number_format 与计划不符",
                    **location,
                    planned=str(nf),
                    actual=str(cell.number_format),
                )

    from app.mod_sdk.workbook_controls import (
        WORKBOOK_CONTROL_PHASES,
        WORKBOOK_NATIVE_PHASES,
        control_matches,
    )
    from app.mod_sdk.workbook_qc_objects import check_native_chart, check_native_table

    native_checked = 0
    for ph in _plan_phases(plan):
        kind = ph.get("phase")
        if kind not in WORKBOOK_NATIVE_PHASES:
            continue
        native_checked += 1
        try:
            ws = wb[ph["sheet"]]
            if ws not in wb.worksheets:
                raise ValueError("目标不是工作表")
            if kind in WORKBOOK_CONTROL_PHASES:
                if not control_matches(wb, ph):
                    f.fail("工作表控制规则与计划不符", phase=kind, sheet=ws.title)
            elif kind == "create_table":
                check_native_table(ws, ph, f, planned_targets)
            elif template_wb is not None and ws.title.casefold() in {
                name.casefold() for name in template_wb.sheetnames
            }:
                f.fail("图表未放在新工作表", sheet=ws.title)
            else:
                check_native_chart(wb, ws, ph, f)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            f.fail("工作簿原生对象缺失或无法核验", phase=kind, sheet=ph.get("sheet"))

    residues = 0
    for sheet, min_row, min_col, max_row, max_col, _ in _declared_ranges(
        plan, "clear_ranges", wb, f
    ):
        ws = wb[sheet]
        for r in range(min_row, min(max_row, ws.max_row or max_row) + 1):
            for c in range(min_col, max_col + 1):
                if (sheet, r, c) in planned_targets:
                    continue
                if ws.cell(r, c).value is not None:
                    residues += 1
                    if residues <= _MAX_SAMPLES:
                        f.fail(
                            "clear 范围内存在计划外残值",
                            sheet=sheet,
                            row=r,
                            col=c,
                            actual=str(ws.cell(r, c).value)[:40],
                        )

    for ph in _plan_phases(plan):
        if str(ph.get("phase")) == "retain_sheets":
            wanted = [str(n) for n in (ph.get("names") or [])]
            extra = [n for n in wb.sheetnames if n not in wanted]
            if extra:
                f.fail(f"retain_sheets 后仍存在多余 sheet：{extra}")

    styled_checked = _check_cell_styles(wb, plan, f)
    structural_checked = _check_structural(wb, plan, template_wb, planned_targets, f)

    f.stats = {
        "cell_writes_planned": len(cell_writes),
        "formula_writes_planned": len(formula_writes),
        "cells_checked": checked,
        "style_cells_checked": styled_checked,
        "clear_residues": residues,
    }
    if native_checked:
        f.stats["native_phases_checked"] = native_checked
    if structural_checked:
        f.stats["structural_phases_checked"] = structural_checked
    if write_report:
        rep_cells = write_report.get("cells_written")
        if rep_cells is not None and int(rep_cells) != len(cell_writes):
            f.warn(
                f"write_report 自述 cells_written={rep_cells} 与计划条数 {len(cell_writes)} 不符"
            )
        if write_report.get("violations"):
            f.warn(
                f"写入员报告 {len(write_report['violations'])} 条保护区 violation（计划与保护区冲突）",
                samples=write_report["violations"][:3],
            )
    return f


def _check_protection(wb, plan: Dict[str, Any], template_wb) -> _Finding:
    f = _Finding("protection")
    tokens = [str(t) for t in (plan.get("protected_ranges") or [])]
    if not tokens:
        f.skip("计划未声明 protected_ranges")
        return f
    if template_wb is None:
        f.skip("未提供原模板，无法对照保护区（建议 payload.template_path 传入）")
        return f
    diffs = 0
    insertions = tuple(_insertions(plan))
    for token in tokens:
        sheet = str(token).split("!")[0].strip("'") if "!" in str(token) else ""
        if not sheet or sheet not in wb.sheetnames or sheet not in template_wb.sheetnames:
            f.warn(f"保护区 sheet 无法对照：{token!r}")
            continue
        ws_out, ws_tpl = wb[sheet], template_wb[sheet]
        try:
            _, min_row, min_col, max_row, max_col = _range_bounds(ws_tpl, token)
        except ValueError:
            f.warn(f"保护区范围无法解析：{token!r}")
            continue
        max_row = min(max_row, max(ws_tpl.max_row or 1, ws_out.max_row or 1))
        first, last = _moved_row(sheet, min_row, insertions), _moved_row(sheet, max_row, insertions)
        for target_row in range(first, last + 1):
            r = _original_row(sheet, target_row, insertions)
            for c in range(min_col, max_col + 1):
                original = ws_tpl.cell(r, c) if r is not None else None
                actual = ws_out.cell(target_row, c)
                tpl_v, out_v = original.value if original is not None else None, actual.value
                if isinstance(tpl_v, str) and tpl_v.startswith("="):
                    tpl_v = _shift_formula_rows(tpl_v, sheet, insertions)
                if str(tpl_v) != str(out_v) or (
                    original is not None and _style_signature(original) != _style_signature(actual)
                ):
                    diffs += 1
                    if diffs <= _MAX_SAMPLES:
                        f.fail(
                            "保护区格与原模板不一致",
                            sheet=sheet,
                            row=target_row,
                            col=c,
                            template=str(tpl_v)[:40],
                            actual=str(out_v)[:40],
                        )
    f.stats = {"protected_ranges": len(tokens), "diffs": diffs}
    return f


def _block_of_row(row: int, blocks: List[Dict[str, Any]], rows: int) -> Optional[str]:
    for b in blocks:
        top = int(b.get("top") or 0)
        if top <= row < top + rows:
            return str(b.get("key") or "").strip()
    return None


def _check_expected(wb, plan: Dict[str, Any], rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("expected")
    expected = plan.get("expected")
    if not isinstance(expected, dict):
        f.skip("计划无 expected 块（映射员未产出对账基准）")
        return f

    cell_writes = _iter_writes(plan, "cell_writes")
    formula_writes = _iter_writes(plan, "formula_writes")

    exp_cells = expected.get("cells_planned")
    if exp_cells is not None and int(exp_cells) != len(cell_writes):
        f.fail(
            f"expected.cells_planned={exp_cells} 与计划实际 {len(cell_writes)} 不符（映射员自述失真）"
        )
    exp_formulas = expected.get("formulas_planned")
    if exp_formulas is not None and int(exp_formulas) != len(formula_writes):
        f.fail(f"expected.formulas_planned={exp_formulas} 与计划实际 {len(formula_writes)} 不符")

    exp_sum = expected.get("per_key_numeric_sum")
    tm = (rules or {}).get("template_map") if isinstance(rules, dict) else None
    if isinstance(exp_sum, dict) and isinstance(tm, dict):
        blocks = [b for b in (tm.get("blocks") or []) if isinstance(b, dict)]
        rows = int((tm.get("block") or {}).get("rows") or 1)
        sheet_name = str(tm.get("sheet") or "")
        plan_sum: Dict[str, float] = {}
        file_sum: Dict[str, float] = {}
        for w in cell_writes:
            try:
                sheet, row, col = _target(w)
            except (TypeError, ValueError, KeyError):
                continue
            if sheet != sheet_name:
                continue
            key = _block_of_row(row, blocks, rows)
            if not key:
                continue
            planned = _coerce_planned(w.get("value"), str(w.get("value_type") or ""))
            if isinstance(planned, (int, float)) and not isinstance(planned, bool):
                plan_sum[key] = round(plan_sum.get(key, 0.0) + float(planned), 4)
            if sheet in wb.sheetnames:
                actual = wb[sheet].cell(row, col).value
                if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                    file_sum[key] = round(file_sum.get(key, 0.0) + float(actual), 4)
        for key, exp_v in exp_sum.items():
            pv = plan_sum.get(str(key), 0.0)
            fv = file_sum.get(str(key), 0.0)
            if abs(float(exp_v) - pv) > _NUM_TOL:
                f.fail(f"键 {key!r} expected 数值合计 {exp_v} ≠ 计划重算 {pv}（映射员统计失真）")
            if abs(pv - fv) > _NUM_TOL:
                f.fail(f"键 {key!r} 计划数值合计 {pv} ≠ 输出文件重算 {fv}（写入丢失/篡改）")
        f.stats = {"keys_checked": len(exp_sum), "plan_sum": plan_sum, "file_sum": file_sum}
    elif isinstance(exp_sum, dict):
        f.warn("expected 含 per_key_numeric_sum 但未提供 rules.json，无法按块重算（建议传入）")

    dropped = expected.get("records_dropped")
    if isinstance(dropped, list) and dropped:
        f.warn(
            f"映射员丢弃了 {len(dropped)} 条记录（携带原因，需人工确认是否合理）",
            samples=dropped[:_MAX_SAMPLES],
        )
    return f


def _check_formulas(wb) -> _Finding:
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError

    f = _Finding("formulas")
    total = 0
    ref_errors = 0
    dangling: set[str] = set()
    names = {name.casefold() for name in wb.sheetnames}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                total += 1
                if _REF_ERR_RE.search(v):
                    ref_errors += 1
                    if ref_errors <= _MAX_SAMPLES:
                        f.fail("公式含 #REF!", sheet=ws.title, ref=cell.coordinate, formula=v[:80])
                try:
                    tokens = Tokenizer(v).items
                except TokenizerError:
                    continue
                for token in tokens:
                    if token.type == "OPERAND" and token.subtype == "RANGE" and "!" in token.value:
                        target, _, _ = _reference_sheet(token.value, ws.title)
                        if target and target.casefold() not in names and not target.isdigit():
                            dangling.add(target)
    for target in sorted(dangling):
        f.fail(f"公式引用了不存在的 sheet：{target!r}")
    f.stats = {"formulas_total": total, "ref_errors": ref_errors}
    return f


def _check_traceability(plan: Dict[str, Any], rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("traceability")
    ref = (
        ((plan.get("meta") or {}).get("rules_ref") or {})
        if isinstance(plan.get("meta"), dict)
        else {}
    )
    declared = str(ref.get("sha256") or "")
    if not declared:
        f.skip("计划未携带 meta.rules_ref（无法追溯规则版本）")
        return f
    if rules is None:
        f.warn("计划声明了 rules_ref 但未提供 rules.json，无法验证哈希")
        f.stats = {"declared": declared[:16]}
        return f
    actual = canonical_rules_sha256(rules)
    if actual != declared:
        f.fail(
            f"rules.json 哈希 {actual[:16]}… ≠ 计划声明 {declared[:16]}…（规则版本不一致，产物不可追溯）"
        )
    f.stats = {"declared": declared[:16], "actual": actual[:16]}
    return f


def _check_structure(wb, rules: Optional[Dict[str, Any]]) -> _Finding:
    f = _Finding("structure")
    tm = (rules or {}).get("template_map") if isinstance(rules, dict) else None
    if not isinstance(tm, dict):
        f.skip("未提供 rules.json，跳过结构漂移检查")
        return f
    sheet_name = str(tm.get("sheet") or "")
    key_col = tm.get("key_col")
    blocks = [b for b in (tm.get("blocks") or []) if isinstance(b, dict)]
    if not sheet_name or not key_col or not blocks:
        f.skip("rules.template_map 缺 sheet/key_col/blocks，无法比对结构")
        return f
    if sheet_name not in wb.sheetnames:
        f.fail(f"规则声明的 sheet 不在输出中：{sheet_name!r}")
        return f
    ws = wb[sheet_name]
    drift = 0
    for b in blocks:
        expected_key = str(b.get("key") or "").strip()
        if not expected_key:
            continue
        top = int(b.get("top") or 0)
        actual = str(ws.cell(top, int(key_col)).value or "").strip()
        if actual != expected_key:
            drift += 1
            if drift <= _MAX_SAMPLES:
                f.fail(
                    "块键与规则不符（模板重排/规则过期）",
                    row=top,
                    expected=expected_key,
                    actual=actual,
                )
    f.stats = {
        "keyed_blocks": sum(1 for b in blocks if str(b.get("key") or "").strip()),
        "drift": drift,
    }
    return f


# 汇总

_BLAME = {
    "conformance": "writer_or_plan",
    "protection": "writer",
    "expected": "mapper",
    "formulas": "template_or_plan",
    "traceability": "pipeline",
    "structure": "rules_stale",
    "semantic": "semantic_llm",
}


def _summarize(report):
    statuses = {name: s.get("status") for name, s in report["sections"].items()}
    if any(s == "fail" for s in statuses.values()):
        report["verdict"] = "FAIL"
    elif any(s == "warn" for s in statuses.values()):
        report["verdict"] = "WARN"
    else:
        report["verdict"] = "PASS"
    report["blame"] = sorted(
        {_BLAME[name] for name, s in statuses.items() if s == "fail" and name in _BLAME}
    )
    summary_bits = [f"{name}:{status}" for name, status in statuses.items()]
    report["summary"] = f"QC {report['verdict']}（" + "，".join(summary_bits) + "）"
    return report


def merge_semantic_section(report: Dict[str, Any], semantic: Dict[str, Any]) -> Dict[str, Any]:
    """并入语义审查，保留各确定性节的原结论。"""
    report["sections"]["semantic"] = semantic
    if semantic.get("human_summary"):
        report["human_summary"] = semantic["human_summary"]
    return _summarize(report)


def run_qc(
    filled_path: Path,
    plan: Dict[str, Any],
    *,
    template_path: Optional[Path] = None,
    rules: Optional[Dict[str, Any]] = None,
    write_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from openpyxl import load_workbook

    keep_vba = filled_path.suffix.lower() == ".xlsm"
    wb = load_workbook(filled_path, data_only=False, keep_vba=keep_vba)
    template_wb = None
    try:
        if template_path is not None and Path(template_path).is_file():
            template_wb = load_workbook(template_path, data_only=False)
        sections = {
            "conformance": _check_conformance(wb, plan, write_report, template_wb),
            "protection": _check_protection(wb, plan, template_wb),
            "expected": _check_expected(wb, plan, rules),
            "formulas": _check_formulas(wb),
            "traceability": _check_traceability(plan, rules),
            "structure": _check_structure(wb, rules),
        }
    finally:
        wb.close()
        if template_wb is not None:
            template_wb.close()

    return _summarize(
        {
            "sections": {name: s.as_dict() for name, s in sections.items()},
            "inputs": {
                "filled": str(filled_path),
                "template": str(template_path or ""),
                "rules_provided": rules is not None,
                "write_report_provided": write_report is not None,
            },
        }
    )
