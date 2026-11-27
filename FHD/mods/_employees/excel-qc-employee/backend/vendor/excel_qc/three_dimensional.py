"""Independently replay the plan to reject affected local 3D formula dependencies."""

import re

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils.cell import get_column_letter, range_boundaries

from app.mod_sdk.workbook_reference_relocation import fill_formula_rows

from .plan_coordinates import insertions, moved_row, plan_phases, shift_formula_rows, target


def affected_three_dimensional(formula, sheet_names, target_sheet, row, row_offset=0):
    expression = str(formula)
    if not expression.startswith("="):
        expression = "=" + expression
    try:
        operands = Tokenizer(expression).items
    except TokenizerError:
        return ":" in expression and "!" in expression
    positions = {name.casefold(): position for position, name in enumerate(sheet_names)}
    for operand in operands:
        if (operand.type, operand.subtype) != ("OPERAND", "RANGE") or "!" not in operand.value:
            continue
        owner, address = operand.value.rsplit("!", 1)
        if "[" in owner or "]" in owner:
            continue
        if owner.startswith("'") and owner.endswith("'"):
            owner = owner[1:-1].replace("''", "'")
        if ":" not in owner:
            continue
        names = owner.split(":")
        if len(names) != 2 or any(name.casefold() not in positions for name in names):
            return True
        low, high = sorted(positions[name.casefold()] for name in names)
        if (
            target_sheet.casefold() not in positions
            or not low <= positions[target_sheet.casefold()] <= high
        ):
            continue
        try:
            address = re.sub(
                r"(\$?)([1-9]\d*)",
                lambda part: part[0] if part[1] else str(int(part[2]) + row_offset),
                address,
            )
            min_col, min_row, max_col, max_row = range_boundaries(address.upper())
        except ValueError:
            return True
        if any(col is not None and col > 16_384 for col in (min_col, max_col)) or any(
            bound is not None and bound > 1_048_576 for bound in (min_row, max_row)
        ):
            return True
        if (
            ":" in address
            and min_row is None
            and max_row is None
            and min_col is not None
            and max_col is not None
        ):
            continue
        if min_row is None or max_row is None or max(min_row, max_row) >= row:
            return True
    return False


def _write_phase(values, phase):
    kind = phase.get("phase")
    if kind in {"cell_writes", "formula_writes"}:
        for write in phase.get("writes") or []:
            try:
                key = target(write)
                value = write.get("formula") if kind == "formula_writes" else write.get("value")
                values[key] = (
                    value.strip() if kind == "formula_writes" and isinstance(value, str) else value
                )
            except (KeyError, TypeError, ValueError):
                continue  # Existing conformance checks report malformed writes.
    elif kind == "clear_ranges":
        for token in phase.get("ranges") or []:
            sheet, separator, address = str(token).rpartition("!")
            if not separator:
                continue
            sheet = sheet.strip().strip("'")
            try:
                left, top, right, bottom = range_boundaries(address.upper())
            except ValueError:
                continue
            for key in list(values):
                owner, row, column = key
                if (
                    owner == sheet
                    and (top or 1) <= row <= (bottom or 1_048_576)
                    and (left or 1) <= column <= (right or 16_384)
                ):
                    del values[key]
    elif kind == "create_table":
        try:
            sheet = phase["sheet"]
            left, top, right, bottom = range_boundaries(phase["range"])
            formula, summed = phase.get("calculated_formula"), phase.get("sum_column")
            calculated = phase.get("calculated_column", summed if formula is not None else None)
            columns = {values.get((sheet, top, col)): col for col in range(left, right + 1)}
            if calculated is not None:
                column = columns[calculated]
                formulas = fill_formula_rows(
                    formula, origin=f"{get_column_letter(column)}{top + 1}", count=bottom - top
                )
                for row, expected in enumerate(formulas, start=top + 1):
                    values[sheet, row, column] = expected
            if summed is not None:
                column = columns[summed]
                values[sheet, bottom + 1, column] = f"=SUBTOTAL(109,{phase['name']}[{summed}])"
                values[sheet, bottom + 1, left if column != left else left + 1] = "合计"
        except (KeyError, TypeError, ValueError):
            pass  # Native-table conformance checks independently validate this phase.


def check_three_dimensional_references(wb, template_wb, plan, finding):
    """Check dependencies at each insertion, including earlier writes and removals."""
    values = {
        (sheet.title, cell.row, cell.column): cell.value
        for sheet in template_wb.worksheets
        for cell in sheet._cells.values()
        if cell.value is not None
    }
    sheets = list(template_wb.sheetnames)
    validations = {
        sheet.title: [
            (formula, offset)
            for rule in sheet.data_validations.dataValidation
            for offset in {
                0,
                max((area.max_row for area in rule.sqref.ranges), default=1)
                - min((area.min_row for area in rule.sqref.ranges), default=1),
            }
            for formula in (rule.formula1, rule.formula2)
            if formula is not None
        ]
        for sheet in template_wb.worksheets
    }
    for phase in plan_phases(plan):
        for target_sheet, row, count in insertions({"phases": [phase]}):
            for (owner, cell_row, column), value in values.items():
                if (
                    isinstance(value, str)
                    and value.startswith("=")
                    and affected_three_dimensional(value, sheets, target_sheet, row)
                ):
                    finding.fail(
                        "三维单元格引用受插行影响，无法独立确认迁移",
                        sheet=owner,
                        row=cell_row,
                        col=column,
                    )
                    return
            for owner, formulas in validations.items():
                if any(
                    affected_three_dimensional(formula, sheets, target_sheet, row, offset)
                    for formula, offset in formulas
                ):
                    finding.fail("三维数据验证引用受插行影响，无法独立确认迁移", sheet=owner)
                    return
            changes = [(target_sheet, row, count)]
            values = {
                (owner, moved_row(owner, cell_row, changes), column): shift_formula_rows(
                    value, owner, changes
                )
                if isinstance(value, str) and value.startswith("=")
                else value
                for (owner, cell_row, column), value in values.items()
            }
        kind = phase.get("phase")
        if kind in {"remove_sheets", "retain_sheets"}:
            named = {str(name).strip() for name in phase.get("names") or []}
            sheets = [name for name in sheets if (name in named) == (kind == "retain_sheets")]
            values = {key: value for key, value in values.items() if key[0] in sheets}
            validations = {
                name: formulas for name, formulas in validations.items() if name in sheets
            }
        elif kind == "create_combo_chart":
            sheets.append(phase.get("sheet"))
        elif kind == "data_validation":
            formulas = (
                [phase.get("name")]
                if phase.get("rule") == "list"
                else [phase.get("minimum"), phase.get("maximum")]
            )
            try:
                _, first, _, last = range_boundaries(phase["range"].upper())
                validations.setdefault(phase.get("sheet"), []).extend(
                    (value, offset)
                    for value in formulas
                    if value is not None
                    for offset in {0, last - first}
                )
            except (KeyError, TypeError, ValueError):
                pass  # Existing validation conformance checks report malformed ranges.
        _write_phase(values, phase)
