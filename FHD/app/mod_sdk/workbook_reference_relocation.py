"""Sheet-scoped A1 reference transformation for row insertion.

This module only translates formula operands; workbook mutation and plan error
reporting remain in the template writer.
"""

from __future__ import annotations

import re

XLSX_MAX_ROW = 1_048_576

XLSX_MAX_COL = 16_384

_REF_ROW_RE = re.compile(r"(\$?[A-Za-z]{1,3}\$?)([1-9][0-9]*)")


class ReferenceOverflowError(ValueError):
    """An insertion would move a valid reference outside the XLSX row grid."""


class DefinedNameError(ValueError):
    """A named destination cannot be preserved safely by this insertion."""


def validate_named_control_order(phases):
    """Do not create a dropdown before an unsupported later control-range move."""
    from openpyxl.utils.cell import range_boundaries

    for index, phase in enumerate(phases):
        if phase.get("phase") != "data_validation" or phase.get("rule") != "list":
            continue
        for later in phases[index + 1 :]:
            if later.get("phase") != "insert_rows":
                continue
            for sheet_key, range_key in (("sheet", "range"), ("source_sheet", "source_range")):
                target = str(later.get("sheet") or "").strip().strip("'").casefold()
                owner = str(phase.get(sheet_key) or "").strip().strip("'").casefold()
                if target != owner:
                    continue
                try:
                    bottom = range_boundaries(str(phase.get(range_key)).upper())[3]
                    affected = bottom is None or int(later.get("row")) <= bottom
                except (TypeError, ValueError) as exc:
                    raise DefinedNameError("定义名称下拉与后续插行的范围无法确定") from exc
                if affected:
                    raise DefinedNameError(
                        "定义名称下拉创建后不支持迁移其来源或应用范围；请先插行，再创建下拉"
                    )


def _shift_ref_rows(
    token: str, insert_row: int, count: int, *, formula_sheet: str, target_sheet: str
) -> str:
    from openpyxl.utils.cell import column_index_from_string

    prefix, sep, body = token.rpartition("!")
    reference_sheet = prefix if sep else formula_sheet
    if reference_sheet.startswith("'") and reference_sheet.endswith("'"):
        reference_sheet = reference_sheet[1:-1].replace("''", "'")
    if reference_sheet.casefold() != target_sheet.casefold():
        return token
    parts = body.split(":")
    cells = [_REF_ROW_RE.fullmatch(part) for part in parts]
    whole_rows = len(parts) == 2 and all(re.fullmatch(r"\$?[1-9][0-9]*", p) for p in parts)
    if len(parts) > 2 or not (all(cells) or whole_rows):
        return token  # 名称、结构化引用、整列引用不能按单元格地址替换。
    shifted = []
    for part, cell in zip(parts, cells):
        label, number = (
            cell.groups() if cell else ("$" if part.startswith("$") else "", part.lstrip("$"))
        )
        row = int(number)
        if row > XLSX_MAX_ROW or (
            cell and column_index_from_string(label.replace("$", "")) > XLSX_MAX_COL
        ):
            return token
        row += count if row >= insert_row else 0
        if row > XLSX_MAX_ROW:
            raise ReferenceOverflowError("insert_rows 会使公式引用超出工作表行数上限。")
        shifted.append(f"{label}{row}")
    return f"{prefix}{sep}{':'.join(shifted)}"


def shift_formula_rows(
    formula: str, insert_row: int, count: int, *, formula_sheet: str, target_sheet: str
) -> str:
    """插入行时按 Excel 语义改写公式中的行引用（绝对引用同样随行移动）。"""
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError

    try:
        tokens = Tokenizer(formula).items
    except TokenizerError:
        return formula
    changed = False
    for tok in tokens:
        if tok.type == "OPERAND" and tok.subtype == "RANGE":
            shifted = _shift_ref_rows(
                tok.value, insert_row, count, formula_sheet=formula_sheet, target_sheet=target_sheet
            )
            changed |= shifted != tok.value
            tok.value = shifted
    return "=" + "".join(tok.value for tok in tokens) if changed else formula


def _name_reference_sheets(token, scope, wb, insert_row, target_sheet):
    """Validate a named operand and identify its local workbook dependencies."""
    from openpyxl.utils.cell import range_boundaries

    prefix, separator, body = token.rpartition("!")
    sheet = (
        prefix[1:-1].replace("''", "'")
        if prefix.startswith("'") and prefix.endswith("'")
        else prefix
    )
    if separator and ("[" in sheet or "]" in sheet):
        return set()  # An external workbook is unaffected by this insertion.
    if separator and ":" in sheet:
        order = [title.casefold() for title in wb.sheetnames]
        first, last = (order.index(title.casefold()) for title in sheet.split(":"))
        names = set(order[min(first, last) : max(first, last) + 1])
        if target_sheet.casefold() in names:
            raise ValueError("不支持迁移包含目标表的三维引用")
        return names
    sheet = sheet if separator else scope
    collections = [wb.defined_names]
    owner = next(
        (ws for ws in wb.worksheets if sheet and ws.title.casefold() == sheet.casefold()), None
    )
    if owner is not None:
        collections.append(owner.defined_names)
    if any(body.casefold() == key.casefold() for names in collections for key in names):
        return None  # Symbolic aliases stay intact; their definitions are checked separately.
    if "[" in body:
        table_name = body.split("[", 1)[0].casefold()
        for owner in wb.worksheets:
            for table in owner.tables.values():
                if table.name.casefold() == table_name:
                    return {owner.title.casefold()}
        raise ValueError("无法定位名称中的表格结构引用")
    bounds = range_boundaries(body.upper())
    left, top, right, bottom = bounds
    if not re.fullmatch(
        r"(?:\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?|\$?[1-9]\d*:\$?[1-9]\d*|\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3})",
        body,
    ):
        raise ValueError("不支持的名称目的地")
    if any(value is not None and not 1 <= value <= XLSX_MAX_COL for value in (left, right)) or any(
        value is not None and not 1 <= value <= XLSX_MAX_ROW for value in (top, bottom)
    ):
        raise ValueError("名称目的地超出工作表范围")
    if sheet is None:
        raise ValueError("工作簿级裸引用缺少可确定的工作表作用域")
    return {sheet.casefold()}


def shifted_defined_names(wb, insert_row: int, count: int, target_sheet: str):
    """Preflight all workbook/local names and return updates without mutating them."""
    from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
    from openpyxl.utils import FORMULAE

    ws = wb[target_sheet]
    for owner in wb.worksheets:
        for validation in owner.data_validations.dataValidation:
            if owner is ws and any(insert_row <= area.max_row for area in validation.sqref.ranges):
                label = "下拉验证" if validation.type == "list" else "数据验证"
                raise DefinedNameError(
                    f"既有{label} {owner.title}!{validation.sqref} 暂不支持插行迁移应用范围"
                )
            for value in (validation.formula1, validation.formula2):
                if value is None:
                    continue
                formula = str(value)
                formula = formula if formula.startswith("=") else "=" + formula
                if (
                    shift_formula_rows(
                        formula,
                        insert_row,
                        count,
                        formula_sheet=owner.title,
                        target_sheet=target_sheet,
                    )
                    != formula
                ):
                    raise DefinedNameError(
                        f"既有数据验证 {owner.title}!{validation.sqref} 的公式引用暂不支持插行迁移"
                    )
    for name, value in (
        ("Print_Area", ws.print_area),
        ("Print_Titles", ws.print_title_rows),
        ("FilterDatabase", ws.auto_filter.ref),
    ):
        if value:
            formula = "=" + str(value)
            changed = shift_formula_rows(
                formula, insert_row, count, formula_sheet=ws.title, target_sheet=target_sheet
            )
            if changed != formula:
                raise DefinedNameError(f"保留定义名称 {ws.title}!{name} 暂不支持插行迁移")
    updates = []
    groups = [(None, wb.defined_names)] + [(ws.title, ws.defined_names) for ws in wb.worksheets]
    for scope, names in groups:
        for name, definition in names.items():
            text = definition.attr_text or ""
            formula = text if text.startswith("=") else "=" + text
            try:
                tokens = Tokenizer(formula).items
                functions = {
                    t.value[:-1].upper() for t in tokens if t.type == "FUNC" and t.subtype == "OPEN"
                }
                dependencies = [
                    _name_reference_sheets(t.value, scope, wb, insert_row, target_sheet)
                    for t in tokens
                    if t.type == "OPERAND" and t.subtype == "RANGE"
                ]
                if functions and (
                    not dependencies
                    or any(
                        sheets is None or target_sheet.casefold() in sheets
                        for sheets in dependencies
                    )
                    or "INDIRECT" in functions
                    or not functions <= FORMULAE
                ):
                    raise ValueError("动态公式名称的目的地无法安全迁移")
                updated = shift_formula_rows(
                    formula, insert_row, count, formula_sheet=scope or "", target_sheet=target_sheet
                )
                updates.append((definition, updated if text.startswith("=") else updated[1:]))
            except (ValueError, TokenizerError) as exc:
                raise DefinedNameError(
                    f"定义名称 {scope or '(工作簿)'}!{name} 无法随插行迁移：{exc}"
                ) from exc
    return updates
