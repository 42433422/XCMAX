"""Reject row insertions whose conditional-format controls cannot be preserved."""

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.formula.translate import Translator, TranslatorError
from openpyxl.utils.cell import get_column_letter, quote_sheetname

from .workbook_reference_relocation import shift_formula_rows


class ConditionalFormatError(ValueError):
    """Conditional-format migration is not implemented by the template writer."""


def _formula_values(rule):
    yield from rule.formula or ()
    for kind in ("colorScale", "dataBar", "iconSet"):
        control = getattr(rule, kind)
        if control is not None:
            for threshold in control.cfvo:
                if threshold.type == "formula":
                    yield threshold.val


def _target_reference(token, owner, target, wb):
    prefix, separator, _ = token.rpartition("!")
    if not separator:
        return owner.casefold() == target.casefold()
    sheet = prefix[1:-1].replace("''", "'") if prefix.startswith("'") else prefix
    if "[" in sheet or "]" in sheet:
        return False
    if ":" in sheet:
        order = [name.casefold() for name in wb.sheetnames]
        first, last = (order.index(name.casefold()) for name in sheet.split(":"))
        return target.casefold() in order[min(first, last) : max(first, last) + 1]
    return sheet.casefold() == target.casefold()


def validate_conditional_insert(wb, target, row, count):
    for ws in wb.worksheets:
        for group in ws.conditional_formatting:
            label = f"条件格式 {ws.title}!{group.sqref}"
            areas = group.sqref.sorted()
            if ws.title == target and any(row <= area.max_row for area in areas):
                raise ConditionalFormatError(f"{label} 暂不支持插行迁移应用范围")
            if not areas:
                raise ConditionalFormatError(f"{label} 缺少可核验应用范围")
            origin = f"{get_column_letter(areas[0].min_col)}{areas[0].min_row}"
            for rule in group.rules:
                for value in _formula_values(rule):
                    formula = "=" + str(value).lstrip("=")
                    try:
                        tokens = Tokenizer(formula).items
                        dependencies = [
                            _target_reference(token.value, ws.title, target, wb)
                            for token in tokens
                            if token.type == "OPERAND" and token.subtype == "RANGE"
                        ]
                        functions = {
                            token.value[:-1].upper()
                            for token in tokens
                            if token.type == "FUNC" and token.subtype == "OPEN"
                        }
                        if "INDIRECT" in functions or (
                            "OFFSET" in functions and (not dependencies or any(dependencies))
                        ):
                            raise ConditionalFormatError(f"{label} 的动态公式无法证明不受插行影响")
                        if not any(dependencies):
                            continue
                        # Probe the target member of a 3D operand; never rewrite
                        # the workbook rule or claim to migrate the 3D formula.
                        for token in tokens:
                            if token.type == "OPERAND" and token.subtype == "RANGE":
                                prefix, separator, body = token.value.rpartition("!")
                                if (
                                    separator
                                    and ":" in prefix
                                    and _target_reference(token.value, ws.title, target, wb)
                                ):
                                    token.value = f"{quote_sheetname(target)}!{body}"
                        probe = "=" + "".join(token.value for token in tokens)
                        translator = Translator(probe, origin=origin)
                        # Relative references apply to every row in every sqref;
                        # endpoints bound their row extent without expanding cells.
                        for area in areas:
                            for end in (area.min_row, area.max_row):
                                applied = translator.translate_formula(
                                    row_delta=end - areas[0].min_row
                                )
                                if (
                                    shift_formula_rows(
                                        applied,
                                        row,
                                        count,
                                        formula_sheet=ws.title,
                                        target_sheet=target,
                                    )
                                    != applied
                                ):
                                    raise ConditionalFormatError(
                                        f"{label} 的公式引用受插行影响，暂不支持迁移"
                                    )
                    except (ValueError, TokenizerError, TranslatorError) as exc:
                        raise ConditionalFormatError(f"{label} 无法安全插行：{exc}") from exc
