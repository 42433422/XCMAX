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
