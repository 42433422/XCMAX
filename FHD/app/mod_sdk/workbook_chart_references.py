"""Reject chart dependencies that cannot safely follow a row insertion."""

from copy import deepcopy

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError

from .workbook_reference_relocation import shift_formula_rows
from .workbook_three_dimensional import affected_three_dimensional


class ChartReferenceError(ValueError):
    """An existing chart source cannot be preserved by this insertion."""


def _affected_source(value, owner, target, row, count, sheets):
    formula = "=" + str(value).lstrip("=")
    if affected_three_dimensional(formula, sheets, target, row):
        return True
    if shift_formula_rows(formula, row, count, formula_sheet=owner, target_sheet=target) != formula:
        return True
    tokens = Tokenizer(formula).items
    functions = {
        token.value[:-1].upper()
        for token in tokens
        if token.type == "FUNC" and token.subtype == "OPEN"
    }
    if not functions:
        return False
    if "INDIRECT" in functions:
        return True  # A source assembled from strings has no statically provable owner.
    dependencies = []
    for token in tokens:
        if (token.type, token.subtype) != ("OPERAND", "RANGE"):
            continue
        prefix, separator, _ = token.value.rpartition("!")
        name = prefix.strip("'").replace("''", "'") if separator else owner
        if "[" in name or "]" in name:
            dependencies.append(False)
        elif ":" in name:
            dependencies.append(affected_three_dimensional(prefix + "!A1", sheets, target, 1))
        else:
            dependencies.append(name.casefold() == target.casefold() or not separator)
    # OFFSET/INDEX and other source expressions can refer past their literal base.
    # Do not infer their extent; only explicit unrelated/external owners are safe.
    return not dependencies or any(dependencies)


def validate_chart_insert(wb, target, row, count):
    """Inspect every serialized chart formula without mutating the live chart."""
    for sheet in wb.worksheets:
        for chart in sheet._charts:
            try:
                tree = deepcopy(chart)._write()
                for node in tree.iter():
                    if node.tag.rsplit("}", 1)[-1] == "f" and _affected_source(
                        node.text, sheet.title, target, row, count, wb.sheetnames
                    ):
                        raise ChartReferenceError(
                            f"图表来源引用受 {target} 插行影响，暂不支持迁移：{sheet.title}"
                        )
            except (TypeError, ValueError, AttributeError, TokenizerError) as exc:
                if isinstance(exc, ChartReferenceError):
                    raise
                raise ChartReferenceError(f"图表来源引用无法安全核验：{sheet.title}") from exc
