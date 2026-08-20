"""通用 Excel 模板写入员：模板 xlsx + 写入计划 plan.json → 回填结果 xlsx。

哑执行器定位：不含任何领域规则；「写哪个格、写什么值、什么格式」全部由上游
（规则映射员 / 人工）在 plan.json 里声明。模板样式、合并单元格、既有公式原样保留。

plan.json 契约（plan_version=1）：

- ``template.sheet_names``：可选；声明模板必须包含的 sheet，缺失即失败（计划-模板匹配保险）。
- ``protected_ranges``：可选；如 ``["明细!BR1:CC500", "明细!CE:CG"]``。任何写入/清除落入
  保护区默认跳过并记 violation；``payload.strict_protected`` 为真时直接失败。
- ``phases``：按顺序执行的阶段列表，支持：
  - ``clear_ranges``：``{"phase": "clear_ranges", "ranges": ["明细!E4:BM9"]}`` 清值不动样式/合并。
  - ``cell_writes``：``{"phase": "cell_writes", "writes": [{"sheet", "ref"|"row"+"col",
    "value", "value_type"?, "number_format"?}]}``；``value_type`` 支持
    ``date``/``datetime``/``number``/``string``（缺省原样写入）。
  - ``formula_writes``：``{"phase": "formula_writes", "writes": [{"sheet", "ref",
    "formula", "number_format"?}]}``；公式串原样写入，不求值。
  - ``retain_sheets`` / ``remove_sheets``：裁剪输出工作簿的 sheet。
- ``expected``：可选；写入员不消费，原样带回 ``meta.expected`` 与 write_report.json，供质检员对账。

顶层直接给 ``writes`` 时视为单一 ``cell_writes`` 阶段（便于最简调用）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.mod_sdk.errors import RECOVERABLE_ERRORS

PLAN_VERSION = 1

# xlsx 规格上限；无界范围（如 ``BR:CC``）在保护区语义下必须覆盖全部行/列。
XLSX_MAX_ROW = 1_048_576
XLSX_MAX_COL = 16_384

KNOWN_PHASES = {
    "clear_ranges",
    "cell_writes",
    "formula_writes",
    "retain_sheets",
    "remove_sheets",
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M",
)


class PlanError(ValueError):
    """plan.json 结构或与模板不匹配的错误（fail-fast）。"""


def _load_plan(src_path: Optional[Path], payload: Dict[str, Any]) -> Dict[str, Any]:
    inline = (payload or {}).get("plan")
    if isinstance(inline, dict):
        return inline
    if src_path is None or not src_path.is_file():
        raise PlanError("缺少写入计划：请上传 plan.json 或在 payload.plan 传入计划对象。")
    if src_path.suffix.lower() != ".json":
        raise PlanError(f"写入计划必须是 .json：{src_path.name}")
    try:
        data = json.loads(src_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan.json 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise PlanError("plan.json 根节点必须是对象。")
    return data


def _normalize_phases(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = plan.get("phases")
    if phases is None and isinstance(plan.get("writes"), list):
        phases = [{"phase": "cell_writes", "writes": plan["writes"]}]
    if not isinstance(phases, list) or not phases:
        raise PlanError("plan.phases 必须是非空数组（或顶层提供 writes）。")
    out: List[Dict[str, Any]] = []
    for i, ph in enumerate(phases):
        if not isinstance(ph, dict):
            raise PlanError(f"phases[{i}] 必须是对象。")
        kind = str(ph.get("phase") or "").strip()
        if kind not in KNOWN_PHASES:
            raise PlanError(f"phases[{i}] 未知阶段：{kind or '(空)'}；支持 {sorted(KNOWN_PHASES)}")
        out.append(ph)
    return out


def _split_sheet_token(token: str) -> Tuple[Optional[str], str]:
    text = str(token or "").strip()
    if "!" in text:
        sheet, _, rng = text.partition("!")
        return sheet.strip().strip("'"), rng.strip()
    return None, text


def _range_bounds(
    ws, rng: str, *, unbounded_row: Optional[int] = None, unbounded_col: Optional[int] = None
) -> Tuple[int, int, int, int]:
    """``A1:B2`` / ``BR:CC`` / ``A1`` → (min_row, min_col, max_row, max_col)，1-based 闭区间。

    整列/整行写法缺行（列）界时，用 ``unbounded_row/col`` 兜底（缺省取 sheet 已用范围）。
    """
    from openpyxl.utils.cell import range_boundaries

    try:
        min_col, min_row, max_col, max_row = range_boundaries(rng)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        raise PlanError(f"非法范围：{rng!r}（{exc}）") from exc
    return (
        int(min_row or 1),
        int(min_col or 1),
        int(max_row or unbounded_row or ws.max_row or 1),
        int(max_col or unbounded_col or ws.max_column or 1),
    )


class _ProtectedZones:
    """保护区索引：sheet → [(min_row, min_col, max_row, max_col), ...]。"""

    def __init__(self, wb, tokens: List[str]) -> None:
        self.zones: Dict[str, List[Tuple[int, int, int, int]]] = {}
        for token in tokens:
            sheet, rng = _split_sheet_token(token)
            if not sheet:
                raise PlanError(f"protected_ranges 必须带 sheet 名：{token!r}")
            if sheet not in wb.sheetnames:
                raise PlanError(f"protected_ranges 引用不存在的 sheet：{sheet!r}")
            self.zones.setdefault(sheet, []).append(
                _range_bounds(
                    wb[sheet], rng, unbounded_row=XLSX_MAX_ROW, unbounded_col=XLSX_MAX_COL
                )
            )

    def hit(self, sheet: str, row: int, col: int) -> Optional[Tuple[int, int, int, int]]:
        for zone in self.zones.get(sheet, ()):  # 保护区通常个位数，逐一判断足够
            min_row, min_col, max_row, max_col = zone
            if min_row <= row <= max_row and min_col <= col <= max_col:
                return zone
        return None


def _resolve_target(
    ws_names: List[str], item: Dict[str, Any], idx: int, phase: str
) -> Tuple[str, int, int]:
    from openpyxl.utils.cell import coordinate_to_tuple

    sheet = str(item.get("sheet") or "").strip().strip("'")
    if not sheet:
        raise PlanError(f"{phase}[{idx}] 缺少 sheet 字段。")
    if sheet not in ws_names:
        raise PlanError(f"{phase}[{idx}] sheet 不存在：{sheet!r}；模板可用 {ws_names}")
    ref = str(item.get("ref") or "").strip()
    if ref:
        try:
            row, col = coordinate_to_tuple(ref.upper())
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            raise PlanError(f"{phase}[{idx}] 非法单元格引用：{ref!r}") from exc
        return sheet, int(row), int(col)
    try:
        row = int(item.get("row"))
        col = int(item.get("col"))
    except (TypeError, ValueError) as exc:
        raise PlanError(f"{phase}[{idx}] 需要 ref 或 row+col。") from exc
    if row < 1 or col < 1:
        raise PlanError(f"{phase}[{idx}] row/col 必须 ≥ 1：row={row}, col={col}")
    return sheet, row, col


def _coerce_value(item: Dict[str, Any], idx: int, warnings: List[str]) -> Any:
    value = item.get("value")
    vtype = str(item.get("value_type") or "").strip().lower()
    if not vtype or vtype in ("auto", "string", "str"):
        return value
    text = str(value or "").strip()
    if vtype == "number":
        try:
            return float(text) if "." in text or "e" in text.lower() else int(text)
        except ValueError:
            warnings.append(f"cell_writes[{idx}] value_type=number 解析失败，按原样写入：{value!r}")
            return value
    if vtype == "date":
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        warnings.append(f"cell_writes[{idx}] value_type=date 解析失败，按原样写入：{value!r}")
        return value
    if vtype == "datetime":
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        warnings.append(f"cell_writes[{idx}] value_type=datetime 解析失败，按原样写入：{value!r}")
        return value
    warnings.append(f"cell_writes[{idx}] 未知 value_type={vtype!r}，按原样写入。")
    return value


def _apply_number_format(ws, row: int, col: int, number_format: Any) -> None:
    if number_format:
        ws.cell(row, col).number_format = str(number_format)


def _run_clear_ranges(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    ranges = phase.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise PlanError("clear_ranges 阶段缺少 ranges 数组。")
    for token in ranges:
        sheet, rng = _split_sheet_token(str(token))
        if not sheet:
            raise PlanError(f"clear_ranges 范围必须带 sheet 名：{token!r}")
        if sheet not in wb.sheetnames:
            raise PlanError(f"clear_ranges 引用不存在的 sheet：{sheet!r}；模板可用 {wb.sheetnames}")
        ws = wb[sheet]
        min_row, min_col, max_row, max_col = _range_bounds(ws, rng)
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                zone = protected.hit(sheet, r, c)
                if zone is not None:
                    stats["violations"].append(
                        {
                            "phase": "clear_ranges",
                            "sheet": sheet,
                            "row": r,
                            "col": c,
                            "zone": list(zone),
                        }
                    )
                    continue
                cell = ws.cell(r, c)
                if cell.value is not None:
                    cell.value = None
                    stats["cells_cleared"] += 1


def _run_cell_writes(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
    warnings: List[str],
) -> None:
    writes = phase.get("writes")
    if not isinstance(writes, list) or not writes:
        raise PlanError("cell_writes 阶段缺少 writes 数组。")
    for idx, item in enumerate(writes):
        if not isinstance(item, dict):
            raise PlanError(f"cell_writes[{idx}] 必须是对象。")
        sheet, row, col = _resolve_target(wb.sheetnames, item, idx, "cell_writes")
        zone = protected.hit(sheet, row, col)
        if zone is not None:
            stats["violations"].append(
                {"phase": "cell_writes", "sheet": sheet, "row": row, "col": col, "zone": list(zone)}
            )
            continue
        ws = wb[sheet]
        ws.cell(row, col).value = _coerce_value(item, idx, warnings)
        _apply_number_format(ws, row, col, item.get("number_format"))
        stats["cells_written"] += 1


def _run_formula_writes(
    wb,
    phase: Dict[str, Any],
    protected: _ProtectedZones,
    stats: Dict[str, Any],
) -> None:
    writes = phase.get("writes")
    if not isinstance(writes, list) or not writes:
        raise PlanError("formula_writes 阶段缺少 writes 数组。")
    for idx, item in enumerate(writes):
        if not isinstance(item, dict):
            raise PlanError(f"formula_writes[{idx}] 必须是对象。")
        formula = str(item.get("formula") or "").strip()
        if not formula.startswith("="):
            raise PlanError(f"formula_writes[{idx}] 公式必须以 = 开头：{formula!r}")
        sheet, row, col = _resolve_target(wb.sheetnames, item, idx, "formula_writes")
        zone = protected.hit(sheet, row, col)
        if zone is not None:
            stats["violations"].append(
                {
                    "phase": "formula_writes",
                    "sheet": sheet,
                    "row": row,
                    "col": col,
                    "zone": list(zone),
                }
            )
            continue
        ws = wb[sheet]
        ws.cell(row, col).value = formula
        _apply_number_format(ws, row, col, item.get("number_format"))
        stats["formulas_written"] += 1


def _run_sheet_prune(wb, phase: Dict[str, Any], stats: Dict[str, Any]) -> None:
    kind = str(phase.get("phase"))
    names = phase.get("names")
    if not isinstance(names, list) or not names:
        raise PlanError(f"{kind} 阶段缺少 names 数组。")
    wanted = [str(n).strip() for n in names if str(n).strip()]
    if kind == "retain_sheets":
        keep = [n for n in wanted if n in wb.sheetnames]
        if not keep:
            raise PlanError(f"retain_sheets 与模板无交集：{wanted}；模板可用 {wb.sheetnames}")
        for name in list(wb.sheetnames):
            if name not in keep:
                del wb[name]
                stats["sheets_removed"].append(name)
    else:
        for name in wanted:
            if name in wb.sheetnames:
                if len(wb.sheetnames) == 1:
                    raise PlanError(f"remove_sheets 不能删除最后一个 sheet：{name!r}")
                del wb[name]
                stats["sheets_removed"].append(name)


def _resolve_template_path(
    template_path: Optional[Path],
    plan: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Path:
    if template_path is not None and Path(template_path).is_file():
        return Path(template_path)
    hint = plan.get("template")
    raw = str((hint or {}).get("path") or "").strip() if isinstance(hint, dict) else ""
    if raw:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = Path(str((ctx or {}).get("workspace_root") or Path.cwd())) / raw
        if p.is_file():
            return p
    raise PlanError(
        "模板缺失：请在 payload.template_path/template_relpath 指定模板 xlsx，"
        "或在员工包 templates/ 目录内置模板，或在 plan.template.path 声明。"
    )


def _check_template_contract(wb, plan: Dict[str, Any]) -> None:
    hint = plan.get("template")
    if not isinstance(hint, dict):
        return
    wanted = [str(n).strip() for n in (hint.get("sheet_names") or []) if str(n).strip()]
    missing = [n for n in wanted if n not in wb.sheetnames]
    if missing:
        raise PlanError(f"模板缺少计划声明的 sheet：{missing}；模板实际 {wb.sheetnames}")


def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from openpyxl import load_workbook

    payload = payload or {}
    plan = _load_plan(src_path if isinstance(src_path, Path) else None, payload)
    version = plan.get("plan_version", PLAN_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = -1
    if version != PLAN_VERSION:
        raise PlanError(
            f"不支持的 plan_version：{plan.get('plan_version')!r}（当前支持 {PLAN_VERSION}）"
        )
    phases = _normalize_phases(plan)

    template = _resolve_template_path(template_path, plan, ctx or {})
    if template.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise PlanError(f"模板必须是 .xlsx/.xlsm：{template.name}")
    keep_vba = template.suffix.lower() == ".xlsm"

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_path
    if xlsx_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        default_name = Path(
            str(rule_spec.get("default_output_relpath") or "outputs/filled.xlsx")
        ).name
        xlsx_path = output_dir / default_name
    warnings: List[str] = []
    if keep_vba and xlsx_path.suffix.lower() != ".xlsm":
        xlsx_path = xlsx_path.with_suffix(".xlsm")
        warnings.append("模板为 .xlsm，输出扩展名已改为 .xlsm 以保留宏。")

    wb = load_workbook(template, data_only=False, keep_vba=keep_vba)
    try:
        _check_template_contract(wb, plan)
        tokens = [str(t) for t in (plan.get("protected_ranges") or [])]
        protected = _ProtectedZones(wb, tokens)

        stats: Dict[str, Any] = {
            "cells_written": 0,
            "formulas_written": 0,
            "cells_cleared": 0,
            "sheets_removed": [],
            "violations": [],
        }
        for ph in phases:
            kind = str(ph.get("phase"))
            if kind == "clear_ranges":
                _run_clear_ranges(wb, ph, protected, stats)
            elif kind == "cell_writes":
                _run_cell_writes(wb, ph, protected, stats, warnings)
            elif kind == "formula_writes":
                _run_formula_writes(wb, ph, protected, stats)
            else:
                _run_sheet_prune(wb, ph, stats)

        if stats["violations"]:
            msg = f"{len(stats['violations'])} 条写入落在保护区"
            if payload.get("strict_protected"):
                raise PlanError(
                    f"{msg}，strict_protected 模式下拒绝写出。示例：{stats['violations'][:3]}"
                )
            warnings.append(f"{msg}，已跳过（详见 write_report.json violations）。")

        wb.save(xlsx_path)
        output_sheet_names = list(wb.sheetnames)
    finally:
        wb.close()

    report = {
        "plan_version": PLAN_VERSION,
        "template": str(template),
        "output": str(xlsx_path),
        "phases_executed": [str(p.get("phase")) for p in phases],
        "output_sheet_names": output_sheet_names,
        **stats,
        "warnings": warnings,
        "expected": plan.get("expected"),
    }
    report_path = xlsx_path.parent / "write_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "output_path": str(xlsx_path),
        "report_path": str(report_path),
        "cells_written": stats["cells_written"],
        "formulas_written": stats["formulas_written"],
        "cells_cleared": stats["cells_cleared"],
        "violations": stats["violations"],
        "sheets_removed": stats["sheets_removed"],
        "output_sheet_names": output_sheet_names,
        "warnings": warnings,
        "expected": plan.get("expected"),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
