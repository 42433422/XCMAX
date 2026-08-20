"""通用 Excel 质检：对回填结果做独立结构对账，产出 verdict + 问责路由。

独立性原则（复式记账）：本模块**不 import** 规则映射员/模板写入员的任何代码，
只依赖三方契约文件（plan.json / rules.json / write_report.json）与输出 xlsx 本身，
从独立路径重算不变量——写入员或映射员的 bug 无法「自证清白」。

六节检查（缺输入的节自动跳过并记 warning，绝不假装通过）：

1. conformance   计划符合性：plan 每条 cell/formula 写入逐格比对输出文件；
                 clear 范围内非计划格必须无残值；retain_sheets 生效。
2. protection    保护区完整性：提供原模板时，protected_ranges 逐格与模板 diff。
3. expected      映射员自洽性：从 plan 独立重算 per_key 数值合计 / 计划格数，
                 与 plan.expected 自述比对；再与输出文件实际值二次对账。
4. formulas      公式健康：全簿扫描 #REF! 与悬空 sheet 引用。
5. traceability  追溯：重算 rules.json 哈希与 plan.meta.rules_ref 比对。
6. structure     结构漂移：rules.blocks 的键 → 输出文件键列实际值逐块比对。

verdict：任一 fail → FAIL；无 fail 有 warn → WARN；否则 PASS。
blame 路由：conformance/protection → writer；expected → mapper；
traceability → pipeline；structure → rules_stale；formulas → template_or_plan。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_MAX_SAMPLES = 8
_NUM_TOL = 1e-6

_REF_ERR_RE = re.compile(r"#REF!")
_SHEET_REF_RE = re.compile(r"(?:'([^']+)'|([A-Za-z0-9\u4e00-\u9fff_]+))!")
_RANGE_RE = re.compile(r"^(?:'?([^'!]+)'?!)?([A-Z]{1,3})?(\d+)?(?::([A-Z]{1,3})?(\d+)?)?$")


def _col_to_index(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _ref_to_tuple(ref: str) -> Tuple[int, int]:
    m = re.match(r"^([A-Z]{1,3})(\d+)$", ref.strip().upper())
    if not m:
        raise ValueError(f"非法单元格引用：{ref!r}")
    return int(m.group(2)), _col_to_index(m.group(1))


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


def _plan_phases(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = plan.get("phases")
    if isinstance(phases, list):
        return [p for p in phases if isinstance(p, dict)]
    if isinstance(plan.get("writes"), list):
        return [{"phase": "cell_writes", "writes": plan["writes"]}]
    return []


def _iter_writes(plan: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ph in _plan_phases(plan):
        if str(ph.get("phase")) == kind:
            out.extend(w for w in (ph.get("writes") or []) if isinstance(w, dict))
    return out


def _target(write: Dict[str, Any]) -> Tuple[str, int, int]:
    sheet = str(write.get("sheet") or "").strip().strip("'")
    ref = str(write.get("ref") or "").strip()
    if ref:
        row, col = _ref_to_tuple(ref)
    else:
        row, col = int(write.get("row")), int(write.get("col"))
    return sheet, row, col


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


def _range_bounds(ws, token: str) -> Tuple[str, int, int, int, int]:
    """``Sheet!A1:B2`` → (sheet, min_row, min_col, max_row, max_col)；无界用已用范围兜底。"""
    text = str(token).strip()
    sheet = ""
    if "!" in text:
        sheet, _, text = text.partition("!")
        sheet = sheet.strip().strip("'")
    m = _RANGE_RE.match(text.upper())
    if not m:
        raise ValueError(f"非法范围：{token!r}")
    _, c1, r1, c2, r2 = m.groups()
    min_col = _col_to_index(c1) if c1 else 1
    max_col = _col_to_index(c2) if c2 else (_col_to_index(c1) if c1 else ws.max_column or 1)
    min_row = int(r1) if r1 else 1
    max_row = int(r2) if r2 else (int(r1) if r1 else ws.max_row or 1)
    return sheet, min_row, min_col, max_row, max_col


# ---------------------------------------------------------------------------
# 六节检查
# ---------------------------------------------------------------------------


def _check_conformance(
    wb, plan: Dict[str, Any], write_report: Optional[Dict[str, Any]]
) -> _Finding:
    f = _Finding("conformance")
    cell_writes = _iter_writes(plan, "cell_writes")
    formula_writes = _iter_writes(plan, "formula_writes")
    planned_targets: set[Tuple[str, int, int]] = set()

    checked = 0
    for w in cell_writes:
        try:
            sheet, row, col = _target(w)
        except (TypeError, ValueError, KeyError) as exc:
            f.fail(f"计划 cell_writes 条目非法：{exc}", write=w)
            continue
        planned_targets.add((sheet, row, col))
        if sheet not in wb.sheetnames:
            f.fail(f"计划写入的 sheet 不在输出中：{sheet!r}", row=row, col=col)
            continue
        planned = _coerce_planned(w.get("value"), str(w.get("value_type") or ""))
        actual = wb[sheet].cell(row, col).value
        checked += 1
        if not _values_match(planned, actual):
            f.fail(
                "格值与计划不符",
                sheet=sheet,
                row=row,
                col=col,
                planned=str(w.get("value")),
                actual=str(actual),
            )
        nf = w.get("number_format")
        if nf and wb[sheet].cell(row, col).number_format != str(nf):
            f.warn(
                "number_format 与计划不符",
                sheet=sheet,
                row=row,
                col=col,
                planned=str(nf),
                actual=str(wb[sheet].cell(row, col).number_format),
            )

    for w in formula_writes:
        try:
            sheet, row, col = _target(w)
        except (TypeError, ValueError, KeyError) as exc:
            f.fail(f"计划 formula_writes 条目非法：{exc}", write=w)
            continue
        planned_targets.add((sheet, row, col))
        if sheet not in wb.sheetnames:
            f.fail(f"计划公式的 sheet 不在输出中：{sheet!r}", row=row, col=col)
            continue
        actual = wb[sheet].cell(row, col).value
        checked += 1
        if str(actual) != str(w.get("formula")):
            f.fail(
                "公式与计划不符",
                sheet=sheet,
                row=row,
                col=col,
                planned=str(w.get("formula"))[:80],
                actual=str(actual)[:80],
            )

    residues = 0
    for ph in _plan_phases(plan):
        if str(ph.get("phase")) != "clear_ranges":
            continue
        for token in ph.get("ranges") or []:
            text = str(token)
            sheet = text.split("!", maxsplit=1)[0].strip("'") if "!" in text else ""
            if sheet and sheet not in wb.sheetnames:
                f.warn(f"clear 范围 sheet 不在输出中：{sheet!r}")
                continue
            ws = wb[sheet] if sheet else wb.active
            try:
                _, min_row, min_col, max_row, max_col = _range_bounds(ws, token)
            except ValueError:
                f.warn(f"clear 范围无法解析：{token!r}")
                continue
            sheet_name = ws.title
            for r in range(min_row, min(max_row, ws.max_row or max_row) + 1):
                for c in range(min_col, max_col + 1):
                    if (sheet_name, r, c) in planned_targets:
                        continue
                    if ws.cell(r, c).value is not None:
                        residues += 1
                        if residues <= _MAX_SAMPLES:
                            f.fail(
                                "clear 范围内存在计划外残值",
                                sheet=sheet_name,
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

    f.stats = {
        "cell_writes_planned": len(cell_writes),
        "formula_writes_planned": len(formula_writes),
        "cells_checked": checked,
        "clear_residues": residues,
    }
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
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                tpl_v, out_v = ws_tpl.cell(r, c).value, ws_out.cell(r, c).value
                if str(tpl_v) != str(out_v):
                    diffs += 1
                    if diffs <= _MAX_SAMPLES:
                        f.fail(
                            "保护区格与原模板不一致",
                            sheet=sheet,
                            row=r,
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
    f = _Finding("formulas")
    total = 0
    ref_errors = 0
    dangling: set[str] = set()
    names = set(wb.sheetnames)
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
                for m in _SHEET_REF_RE.finditer(v):
                    target = (m.group(1) or m.group(2) or "").strip()
                    if target and target not in names and not target.isdigit():
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


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

_BLAME = {
    "conformance": "writer_or_plan",
    "protection": "writer",
    "expected": "mapper",
    "formulas": "template_or_plan",
    "traceability": "pipeline",
    "structure": "rules_stale",
    "semantic": "semantic_llm",
}


def merge_semantic_section(report: Dict[str, Any], semantic: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 语义审查节并入报告并重算 verdict/blame（确定性节结论不受影响）。"""
    report["sections"]["semantic"] = semantic
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
    if semantic.get("human_summary"):
        report["human_summary"] = semantic["human_summary"]
    summary_bits = [f"{name}:{status}" for name, status in statuses.items()]
    report["summary"] = f"QC {report['verdict']}（" + "，".join(summary_bits) + "）"
    return report


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
            "conformance": _check_conformance(wb, plan, write_report),
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

    statuses = {name: s.status for name, s in sections.items()}
    if any(s == "fail" for s in statuses.values()):
        verdict = "FAIL"
    elif any(s == "warn" for s in statuses.values()):
        verdict = "WARN"
    else:
        verdict = "PASS"
    blame = sorted({_BLAME[name] for name, s in statuses.items() if s == "fail"})

    summary_bits = [f"{name}:{status}" for name, status in statuses.items()]
    return {
        "verdict": verdict,
        "blame": blame,
        "sections": {name: s.as_dict() for name, s in sections.items()},
        "summary": f"QC {verdict}（" + "，".join(summary_bits) + "）",
        "inputs": {
            "filled": str(filled_path),
            "template": str(template_path or ""),
            "rules_provided": rules is not None,
            "write_report_provided": write_report is not None,
        },
    }
