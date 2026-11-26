"""Independent projection of plan coordinates into the final workbook.

Compose row insertions for cells, ranges and formula references without mutating
workbooks. This QC implementation does not import the writer's transformations.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

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


def plan_phases(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = plan.get("phases")
    if isinstance(phases, list):
        return [p for p in phases if isinstance(p, dict)]
    if isinstance(plan.get("writes"), list):
        return [{"phase": "cell_writes", "writes": plan["writes"]}]
    return []


def iter_writes(plan: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ph in plan_phases(plan):
        if str(ph.get("phase")) == kind:
            out.extend(w for w in (ph.get("writes") or []) if isinstance(w, dict))
    return out


def target(write: Dict[str, Any]) -> Tuple[str, int, int]:
    sheet = str(write.get("sheet") or "").strip().strip("'")
    ref = str(write.get("ref") or "").strip()
    if ref:
        row, col = _ref_to_tuple(ref)
    else:
        row, col = int(write.get("row")), int(write.get("col"))
    return sheet, row, col


def range_bounds(ws, token: str) -> Tuple[str, int, int, int, int]:
    """``Sheet!A1:B2`` → (sheet, min_row, min_col, max_row, max_col)；无界用已用范围兜底。"""
    text = str(token).strip()
    sheet = ""
    if "!" in text:
        sheet, _, text = text.partition("!")
        sheet = sheet.strip().strip("'")
    m = _RANGE_RE.match(text.upper().replace("$", ""))
    if not m:
        raise ValueError(f"非法范围：{token!r}")
    _, c1, r1, c2, r2 = m.groups()
    min_col = _col_to_index(c1) if c1 else 1
    max_col = _col_to_index(c2) if c2 else (_col_to_index(c1) if c1 else ws.max_column or 1)
    min_row = int(r1) if r1 else 1
    max_row = int(r2) if r2 else (int(r1) if r1 else ws.max_row or 1)
    return sheet, min_row, min_col, max_row, max_col


_A1_REFERENCE_RE = re.compile(
    r"(?:\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?"
    r"|\$?[1-9]\d*:\$?[1-9]\d*)\Z"
)


def insertions(plan, start=0):
    for phase in plan_phases(plan)[start:]:
        if phase.get("phase") == "insert_rows":
            try:
                row, count = int(phase.get("row")), int(phase.get("count"))
            except (TypeError, ValueError):
                continue  # _check_structural reports invalid phases.
            if row > 0 and count > 0:
                yield str(phase.get("sheet") or "").strip().strip("'"), row, count


def moved_row(sheet, row, insertions):
    for target, start, count in insertions:
        if target.casefold() == sheet.casefold() and row >= start:
            row += count
    return row


def original_row(sheet, row, insertions):
    for target, start, count in reversed(insertions):
        if target.casefold() == sheet.casefold():
            if start <= row < start + count:
                return None
            if row >= start + count:
                row -= count
    return row


def reference_sheet(token, formula_sheet):
    prefix, separator, body = token.rpartition("!")
    name = (
        prefix[1:-1].replace("''", "'")
        if prefix.startswith("'") and prefix.endswith("'")
        else prefix
    )
    if "[" in name or "]" in name or ":" in name:
        return None, prefix + separator, body
    return name if separator else formula_sheet, prefix + separator, body


def shift_formula_rows(formula, formula_sheet, insertions):
    """按目标表及全部插行阶段独立变换 A1 引用，不平移公式所在格的相对偏移。"""
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    from openpyxl.utils.cell import range_boundaries

    try:
        tokens = Tokenizer(formula).items
    except TokenizerError:
        return formula
    changed = False
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        sheet, prefix, reference = reference_sheet(token.value, formula_sheet)
        if sheet is not None and _A1_REFERENCE_RE.fullmatch(reference):
            left, top, right, bottom = range_boundaries(reference.upper())
            if any(col is not None and col > 16_384 for col in (left, right)) or any(
                row is not None and row > 1_048_576 for row in (top, bottom)
            ):
                continue  # Cell-like names outside the worksheet grid are not A1 references.
            updated = prefix + re.sub(
                r"\d+", lambda match: str(moved_row(sheet, int(match[0]), insertions)), reference
            )
            changed |= updated != token.value
            token.value = updated
    if not changed:
        return formula
    body = "".join(token.value for token in tokens)
    return "=" + body if formula.startswith("=") else body


def declared_ranges(plan, kind, wb, finding=None):
    """各阶段涉及的原格最终落点；后续插入的空白行不继承早先样式。"""
    out = []
    for index, ph in enumerate(plan_phases(plan)):
        if str(ph.get("phase")) != kind:
            continue
        tokens = ph.get("ranges") if kind == "clear_ranges" else [ph.get("range")]
        for token in tokens or []:
            text = str(token).strip()
            sheet = str(ph.get("sheet") or wb.active.title).strip("'")
            if "!" in text:
                sheet, _, text = text.partition("!")
                sheet = sheet.strip().strip("'")
            if sheet not in wb.sheetnames:
                if finding is not None:
                    finding.warn(f"{kind} 范围 sheet 不在输出中：{sheet!r}")
                continue
            try:
                _, top, left, bottom, right = range_bounds(wb[sheet], text)
            except (TypeError, ValueError):
                if finding is not None:
                    finding.warn(f"{kind} 范围无法解析：{token!r}")
                continue
            spans = [(top, bottom)]
            for target, row, count in insertions(plan, index + 1):
                if target != sheet:
                    continue
                shifted = []
                for first, last in spans:
                    if first >= row:
                        shifted.append((first + count, last + count))
                    elif last >= row:
                        shifted.extend(((first, row - 1), (row + count, last + count)))
                    else:
                        shifted.append((first, last))
                spans = shifted
            out.extend((sheet, first, left, last, right, ph) for first, last in spans)
    return out


def final_writes(plan, kind):
    out = []
    for index, phase in enumerate(plan_phases(plan)):
        if phase.get("phase") != kind:
            continue
        later = tuple(insertions(plan, index + 1))
        for original in phase.get("writes") or []:
            if not isinstance(original, dict):
                continue
            write = dict(original)
            try:
                sheet, row, col = target(write)
            except (TypeError, ValueError, KeyError):
                out.append(write)
                continue
            write.pop("ref", None)
            write.update(row=moved_row(sheet, row, later), col=col)
            field = "formula" if kind == "formula_writes" else "value"
            if isinstance(write.get(field), str) and write[field].startswith("="):
                write[field] = shift_formula_rows(write[field], sheet, later)
            out.append(write)
    return out


def in_ranges(ranges, sheet: str, row: int, col: int) -> bool:
    return any(
        (not name or name == sheet) and top <= row <= bottom and left <= col <= right
        for name, top, left, bottom, right, *_ in ranges
    )
