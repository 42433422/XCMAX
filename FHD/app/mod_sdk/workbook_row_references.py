"""Reference relocation for native Excel row insertion with openpyxl."""

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import column_index_from_string
from openpyxl.xml.constants import MAX_COLUMN, MAX_ROW


def shift_row_reference(ref: str, row: int, count: int) -> str:
    def relocate(number: str) -> str:
        value = int(number.lstrip("$"))
        target = value + count if value >= row else value
        if target > MAX_ROW:
            raise ValueError("插入行后引用超出 Excel 行上限")
        return f"{'$' if number.startswith('$') else ''}{target}"

    if rows := Translator.ROW_RANGE_RE.fullmatch(ref):
        return ":".join(relocate(number) for number in rows.groups())
    operands = ref.split(":")
    coords = [Translator.CELL_REF_RE.fullmatch(part) for part in operands]
    if len(coords) <= 2 and all(coords):
        cells = [match.groups() for match in coords if match is not None]
        if all(column_index_from_string(col.lstrip("$")) <= MAX_COLUMN for col, _ in cells):
            return ":".join(f"{col}{relocate(number)}" for col, number in cells)
    # Whole columns, named ranges and structured table references keep their identity.
    return ref


def shift_formula_rows(
    formula: str, formula_sheet: str, inserted_sheet: str, row: int, count: int
) -> str:
    """Translate only A1 references whose effective sheet received the insertion."""
    has_equals = formula.startswith("=")
    try:
        tokens = Tokenizer(formula if has_equals else "=" + formula).items
    except TokenizerError:
        return formula
    changed = False
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        prefix, delimiter, ref = token.value.rpartition("!")
        target = prefix.removeprefix("'").removesuffix("'").replace("''", "'") if delimiter else formula_sheet
        if target.casefold() != inserted_sheet.casefold():
            continue
        updated = shift_row_reference(ref, row, count)
        if updated != ref:
            token.value = f"{prefix}{delimiter}{updated}"
            changed = True
    if not changed:
        return formula
    return ("=" if has_equals else "") + "".join(token.value for token in tokens)
