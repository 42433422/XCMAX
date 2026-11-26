"""Project explicit worksheet controls onto native openpyxl objects."""

from __future__ import annotations

import re
from copy import copy
from math import isfinite
from typing import Any

from openpyxl.formatting.rule import CellIsRule, FormulaRule, Rule
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils.cell import (
    absolute_coordinate,
    column_index_from_string,
    quote_sheetname,
    range_boundaries,
)
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.page import PageMargins

from app.domain.workbook_write_contract import (
    WORKBOOK_CONTROL_PHASES as WORKBOOK_CONTROL_PHASES,
)
from app.domain.workbook_write_contract import (
    WORKBOOK_NATIVE_PHASES as WORKBOOK_NATIVE_PHASES,
)

_MARGINS = {
    "narrow": (0.25, 0.25, 0.75, 0.75, 0.3, 0.3),
    "normal": (0.7, 0.7, 0.75, 0.75, 0.3, 0.3),
    "wide": (1, 1, 1, 1, 0.5, 0.5),
}
_BOUNDS = (16_384, 1_048_576)


def _area(token: str) -> tuple[str, tuple[int, int, int, int]]:
    ref = token.upper().replace("$", "")
    left, top, right, bottom = range_boundaries(ref)
    if left is None or top is None or right is None or bottom is None:
        raise ValueError("控制规则需要指定单元格边界")
    if not (1 <= left <= right <= _BOUNDS[0] and 1 <= top <= bottom <= _BOUNDS[1]):
        raise ValueError("控制规则范围超出 Excel 工作表边界")
    return ref, (left, top, right, bottom)


def _conditional(phase, bounds):
    color = "FF" + phase["color"].upper()
    fill = PatternFill("solid", fgColor=color)
    kind = phase["rule"]
    if kind == "top_percent":
        return Rule(
            type="top10", percent=True, rank=phase["percent"], dxf=DifferentialStyle(fill=fill)
        )
    if kind == "less_than":
        if not isfinite(phase["threshold"]):
            raise ValueError("条件格式阈值必须为有限数值")
        return CellIsRule(
            operator="lessThan", formula=[str(phase["threshold"])], font=Font(color=color)
        )
    if kind != "duplicate_rows":
        raise ValueError("未知条件格式规则")
    left, top, right, bottom = bounds
    key = phase["key_column"].upper()
    if not left <= column_index_from_string(key) <= right:
        raise ValueError("重复检查列必须在目标区域内")
    cell = f"${key}{top}"
    return FormulaRule(
        formula=[f'AND({cell}<>"",COUNTIF(${key}${top}:${key}${bottom},{cell})>1)'],
        fill=fill,
    )


def _validation(wb, ws, phase):
    options = {"showErrorMessage": True, "errorStyle": "stop", "error": phase["error"]}
    if phase["rule"] == "whole":
        if phase["minimum"] > phase["maximum"]:
            raise ValueError("整数验证下限不得大于上限")
        return (
            DataValidation(
                type="whole",
                operator="between",
                formula1=str(phase["minimum"]),
                formula2=str(phase["maximum"]),
                **options,
            ),
            None,
        )
    if phase["rule"] != "list":
        raise ValueError("未知数据验证规则")
    source, (left, _, right, _) = _area(phase["source_range"])
    name = phase["name"]
    source_sheet = wb[phase["source_sheet"]]
    if source_sheet not in wb.worksheets or left != right:
        raise ValueError("下拉数据源须为工作表中的单列")
    # A defined name cannot be a cell reference or be shadowed by a local name.
    if re.fullmatch(r"(?:[A-Za-z]{1,3}[1-9][0-9]*|[Rr](?:[0-9]+[Cc][0-9]+)?|[Cc])", name):
        raise ValueError("下拉区域名称与 Excel 单元格引用冲突")
    if any(existing.casefold() == name.casefold() for existing in ws.defined_names):
        raise ValueError("下拉名称与工作表本地名称冲突")
    definition = DefinedName(
        name, attr_text=f"{quote_sheetname(source_sheet.title)}!{absolute_coordinate(source)}"
    )
    return DataValidation(type="list", formula1=name, **options), definition


def _print_parts(ws, phase):
    first, last = phase["title_first_row"], phase["title_last_row"]
    if not 1 <= first <= last <= _BOUNDS[1]:
        raise ValueError("打印标题行范围无效")
    paper = ws.PAPERSIZE_A4 if phase["paper"] == "A4" else ws.PAPERSIZE_LETTER
    margins = PageMargins(*_MARGINS[phase["margins"]])
    return f"${first}:${last}", paper, margins


def write_control(wb: Any, phase: dict[str, Any]) -> None:
    ws = wb[phase["sheet"]]
    ref, bounds = _area(phase["range"])
    kind = phase["phase"]
    if kind == "conditional_format":
        ws.conditional_formatting.add(ref, _conditional(phase, bounds))
    elif kind == "data_validation":
        validation, definition = _validation(wb, ws, phase)
        if definition is not None:
            existing = next(
                (
                    item
                    for name, item in wb.defined_names.items()
                    if name.casefold() == definition.name.casefold()
                ),
                None,
            )
            if existing is not None and (
                existing.name != definition.name or existing.attr_text != definition.attr_text
            ):
                raise ValueError("下拉名称已绑定不同引用")
            wb.defined_names.add(definition)
        ws.add_data_validation(validation)
        validation.add(ref)
    elif kind == "print_layout":
        rows, paper, margins = _print_parts(ws, phase)
        ws.print_area = ref
        ws.print_title_rows = rows
        ws.page_setup.paperSize = paper
        ws.page_setup.orientation = phase["orientation"]
        ws.page_setup.fitToWidth = phase["fit_width"]
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins = margins
        ws.oddFooter.center.text = phase["footer"]
    else:
        raise ValueError("未知工作表控制阶段")


def control_matches(wb: Any, phase: dict[str, Any]) -> bool:
    """Compare the independently reopened workbook against the declared phase."""
    ws = wb[phase["sheet"]]
    ref, bounds = _area(phase["range"])
    kind = phase["phase"]
    if kind == "conditional_format":
        expected = _conditional(phase, bounds)
        for actual in ws.conditional_formatting[ref]:
            rule = copy(actual)
            rule.priority = expected.priority
            rule.dxfId = None
            if rule == expected and rule.dxf == expected.dxf:
                return True
        return False
    if kind == "data_validation":
        expected, definition = _validation(wb, ws, phase)
        expected.add(ref)
        if definition is not None:
            actual = wb.defined_names.get(definition.name)
            if actual is None or actual.attr_text != definition.attr_text:
                return False
        return expected in ws.data_validations.dataValidation
    if kind != "print_layout":
        return False
    rows, paper, margins = _print_parts(ws, phase)
    setup = ws.page_setup
    return (
        ws.print_area == f"{quote_sheetname(ws.title)}!{absolute_coordinate(ref)}"
        and ws.print_title_rows == rows
        and setup.paperSize == int(paper)
        and setup.orientation == phase["orientation"]
        and setup.fitToWidth == phase["fit_width"]
        and setup.fitToHeight == 0
        and ws.sheet_properties.pageSetUpPr.fitToPage is True
        and ws.page_margins == margins
        and ws.oddFooter.center.text == phase["footer"]
    )
