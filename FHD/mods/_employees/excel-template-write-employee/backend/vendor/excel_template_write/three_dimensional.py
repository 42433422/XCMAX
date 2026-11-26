"""Preflight local 3D dependencies that cannot follow a single-sheet row insertion."""

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import range_boundaries


class ThreeDimensionalReferenceError(ValueError):
    """A local sheet span would require different row coordinates on its members."""


def affected_three_dimensional(formula, sheet_names, target_sheet, row, row_offset=0):
    text = str(formula)
    text = text if text.startswith("=") else "=" + text
    try:
        tokens = Tokenizer(text).items
    except TokenizerError:
        return ":" in text and "!" in text
    order = [name.casefold() for name in sheet_names]
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        prefix, separator, reference = token.value.rpartition("!")
        if not separator or ":" not in prefix or "[" in prefix or "]" in prefix:
            continue
        span = (
            prefix[1:-1].replace("''", "'")
            if prefix.startswith("'") and prefix.endswith("'")
            else prefix
        )
        endpoints = span.split(":")
        try:
            first, last = (order.index(name.casefold()) for name in endpoints)
            target = order.index(target_sheet.casefold())
        except ValueError:
            return True  # A local span with unknown endpoints cannot be proved independent.
        if not min(first, last) <= target <= max(first, last):
            continue
        try:
            reference = Translator.translate_range(reference, row_offset, 0)
            left, top, right, bottom = range_boundaries(reference.upper())
        except (ValueError, TranslatorError):
            return True
        if any(value is not None and value > 16_384 for value in (left, right)) or any(
            value is not None and value > 1_048_576 for value in (top, bottom)
        ):
            return True
        if (
            ":" in reference
            and top is None
            and bottom is None
            and left is not None
            and right is not None
        ):
            continue  # A whole-column range still includes every moved value.
        if top is None or bottom is None or row <= max(top, bottom):
            return True
    return False


def validate_three_dimensional_references(wb, row, count, target_sheet):
    """Reject affected ordinary-cell and validation formulas before workbook mutation."""
    for sheet in wb.worksheets:
        for cell in tuple(sheet._cells.values()):
            if (
                isinstance(cell.value, str)
                and cell.value.startswith("=")
                and affected_three_dimensional(cell.value, wb.sheetnames, target_sheet, row)
            ):
                raise ThreeDimensionalReferenceError(
                    f"三维单元格引用 {sheet.title}!{cell.coordinate} 暂不支持插行迁移"
                )
        for validation in sheet.data_validations.dataValidation:
            anchor = min((area.min_row for area in validation.sqref.ranges), default=1)
            offsets = {
                endpoint - anchor
                for area in validation.sqref.ranges
                for endpoint in (area.min_row, area.max_row)
            } or {0}
            for formula in (validation.formula1, validation.formula2):
                if formula is not None and any(
                    affected_three_dimensional(formula, wb.sheetnames, target_sheet, row, offset)
                    for offset in offsets
                ):
                    raise ThreeDimensionalReferenceError(
                        f"三维数据验证引用 {sheet.title}!{validation.sqref} 暂不支持插行迁移"
                    )
