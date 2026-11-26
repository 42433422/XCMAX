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


def defined_names(wb, retained_sheets=None):
    """Keep scope in the identity: a local name can shadow a global definition."""
    groups = [(None, wb.defined_names)]
    groups.extend(
        (ws.title, ws.defined_names)
        for ws in wb.worksheets
        if retained_sheets is None or ws.title in retained_sheets
    )
    return {
        (scope, name): definition.attr_text or ""
        for scope, names in groups
        for name, definition in names.items()
    }


def declared_validation_name(phase, wb):
    """Derive the one global name explicitly authorized by a list validation phase."""
    from openpyxl.utils.cell import absolute_coordinate, quote_sheetname, range_boundaries

    source = str(phase["source_range"]).upper().replace("$", "")
    left, top, right, bottom = range_boundaries(source)
    if None in (left, top, right, bottom) or not (
        1 <= left == right <= 16_384 and 1 <= top <= bottom <= 1_048_576
    ):
        raise ValueError("命名下拉的数据源必须是有界单列")
    sheet = wb[phase["source_sheet"]]
    name = phase["name"]
    if not isinstance(name, str) or not name or sheet not in wb.worksheets:
        raise ValueError("命名下拉的定义无效")
    return (None, name), f"{quote_sheetname(sheet.title)}!{absolute_coordinate(source)}"


def unsafe_named_control_order(plan):
    """Detect earlier named dropdowns whose metadata a later insertion would move."""
    from openpyxl.utils.cell import range_boundaries

    controls = []
    for phase in plan_phases(plan):
        if phase.get("phase") == "data_validation" and phase.get("rule") == "list":
            controls.append(phase)
        for sheet, row, _ in insertions({"phases": [phase]}):
            for control in controls:
                for owner_key, ref_key in (("sheet", "range"), ("source_sheet", "source_range")):
                    owner = str(control.get(owner_key) or "").strip().strip("'")
                    if owner.casefold() != sheet.casefold():
                        continue
                    try:
                        bottom = range_boundaries(str(control.get(ref_key)).upper())[3]
                        affected = bottom is None or row <= bottom
                    except (TypeError, ValueError):
                        affected = True
                    if affected:
                        yield sheet, control.get("name")


def affected_reserved_names(wb, plan):
    """Special names live on worksheet properties after openpyxl reads the file."""
    values = {
        (ws.title, label): str(value)
        for ws in wb.worksheets
        for label, value in (
            ("Print_Area", ws.print_area),
            ("Print_Titles", ws.print_title_rows),
            ("FilterDatabase", ws.auto_filter.ref),
        )
        if value
    }
    for phase in plan_phases(plan):
        if phase.get("phase") == "print_layout":
            sheet = str(phase.get("sheet") or "")
            values[sheet, "Print_Area"] = str(phase.get("range") or "")
            values[sheet, "Print_Titles"] = (
                f"{phase.get('title_first_row')}:{phase.get('title_last_row')}"
            )
        changes = tuple(insertions({"phases": [phase]}))
        if changes:
            for (sheet, name), text in values.items():
                if shift_formula_rows("=" + text, sheet, changes) != "=" + text:
                    yield sheet, name


def shifted_name_definition(text, scope, wb, changes):
    """Independently project concrete named destinations through all insertions."""
    from openpyxl.formula.tokenizer import Tokenizer
    from openpyxl.utils import FORMULAE
    from openpyxl.utils.cell import range_boundaries

    symbols = {
        (sheet.casefold() if sheet else None, name.casefold()) for sheet, name in defined_names(wb)
    }
    order = [sheet.casefold() for sheet in wb.sheetnames]
    tables = {
        table.name.casefold(): ws.title.casefold()
        for ws in wb.worksheets
        for table in ws.tables.values()
    }
    had_equals = text.startswith("=")
    formula = text if had_equals else "=" + text
    for target_sheet, row, count in changes:
        target_sheet = target_sheet.casefold()
        tokens = Tokenizer(formula).items
        dependencies = []
        for token in tokens:
            if token.type != "OPERAND" or token.subtype != "RANGE":
                continue
            sheet, prefix, body = reference_sheet(token.value, scope)
            if prefix:
                qualified = prefix[:-1]
                if qualified.startswith("'") and qualified.endswith("'"):
                    qualified = qualified[1:-1].replace("''", "'")
                if "[" in qualified or "]" in qualified:
                    dependencies.append(set())
                    continue
                if ":" in qualified:
                    bounds = [order.index(item.casefold()) for item in qualified.split(":")]
                    if len(bounds) != 2:
                        raise ValueError("三维名称范围无法解析")
                    sheets = set(order[min(bounds) : max(bounds) + 1])
                    if target_sheet in sheets:
                        raise ValueError("插行影响三维名称范围")
                    dependencies.append(sheets)
                    continue
            owner = sheet.casefold() if sheet else None
            if (owner, body.casefold()) in symbols or (None, body.casefold()) in symbols:
                dependencies.append(None)
                continue
            if "[" in body:
                table_sheet = tables[body.split("[", 1)[0].casefold()]
                dependencies.append({table_sheet})
                continue
            if not (
                _A1_REFERENCE_RE.fullmatch(body)
                or re.fullmatch(r"\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}", body)
            ):
                raise ValueError("无法独立解析名称目的地")
            left, top, right, bottom = range_boundaries(body.upper())
            if any(col is not None and not 1 <= col <= 16_384 for col in (left, right)) or any(
                value is not None and not 1 <= value <= 1_048_576 for value in (top, bottom)
            ):
                raise ValueError("名称目的地超出工作表范围")
            if owner is None:
                raise ValueError("工作簿名称的裸引用缺少作用域")
            if owner == target_sheet and any(
                value is not None and value >= row and value + count > 1_048_576
                for value in (top, bottom)
            ):
                raise ValueError("名称目的地插行后越界")
            dependencies.append({owner})
        functions = {
            token.value[:-1].upper()
            for token in tokens
            if token.type == "FUNC" and token.subtype == "OPEN"
        }
        if functions and (
            not dependencies
            or any(sheets is None or target_sheet in sheets for sheets in dependencies)
            or "INDIRECT" in functions
            or not functions <= FORMULAE
        ):
            raise ValueError("动态公式名称无法独立确认迁移")
        formula = shift_formula_rows(formula, scope or "", [(target_sheet, row, count)])
    return formula if had_equals else formula[1:]
