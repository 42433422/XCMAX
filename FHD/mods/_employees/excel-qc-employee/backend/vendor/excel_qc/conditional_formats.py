"""Independently verify conditional-format preservation and declared additions."""

import re
from copy import deepcopy
from math import isfinite

from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formatting.rule import CellIsRule, FormulaRule, Rule
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils.cell import column_index_from_string, range_boundaries
from openpyxl.xml.functions import tostring

from .plan_coordinates import (
    _A1_REFERENCE_RE,
    insertions,
    plan_phases,
    reference_sheet,
    shift_formula_rows,
)


def _affected_formula(value, group, owner, target, row, count, wb):
    formula = "=" + str(value).lstrip("=")
    if shift_formula_rows(formula, owner, [(target, row, count)]) != formula:
        return True
    areas = group.sqref.sorted()
    origin = areas[0].min_row
    lowest = min(area.min_row for area in areas) - origin
    highest = max(area.max_row for area in areas) - origin
    tokens = Tokenizer(formula).items
    functions = {
        item.value[:-1].upper() for item in tokens if item.type == "FUNC" and item.subtype == "OPEN"
    }
    dependencies = []
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        sheet, prefix, reference = reference_sheet(token.value, owner)
        if sheet is None:
            name = prefix.rstrip("!").strip("'").replace("''", "'")
            if "[" in name or "]" in name:
                continue
            if ":" in name:
                names = [title.casefold() for title in wb.sheetnames]
                ends = [names.index(title.casefold()) for title in name.split(":")]
                if target.casefold() in names[min(ends) : max(ends) + 1]:
                    sheet = target
            if sheet is None:
                continue
        depends = sheet.casefold() == target.casefold()
        dependencies.append(depends)
        if not depends or not _A1_REFERENCE_RE.fullmatch(reference):
            continue
        left, top, right, bottom = range_boundaries(reference.upper())
        if any(col is not None and col > 16_384 for col in (left, right)) or any(
            endpoint is not None and endpoint > 1_048_576 for endpoint in (top, bottom)
        ):
            continue
        # Independently bound each A1 endpoint over the whole application range.
        # Absolute row markers keep their original coordinate; relative rows vary.
        for part in reference.split(":"):
            match = re.search(r"(\$?)([1-9]\d*)$", part)
            number = int(match[2])
            minimum = number + (lowest if not match[1] else 0)
            maximum = number + (highest if not match[1] else 0)
            if minimum < 1 or maximum >= row:
                return True
    return "INDIRECT" in functions or (
        "OFFSET" in functions and (not dependencies or any(dependencies))
    )


def _rule_formulas(rule):
    values = list(rule.formula or ())
    for attribute in ("colorScale", "dataBar", "iconSet"):
        definition = getattr(rule, attribute)
        if definition is not None:
            values.extend(item.val for item in definition.cfvo if item.type == "formula")
    return values


def _declared_rule(phase, bounds):
    color = "FF" + phase["color"].upper()
    fill = PatternFill("solid", fgColor=color)
    if phase["rule"] == "top_percent":
        return Rule(
            type="top10", percent=True, rank=phase["percent"], dxf=DifferentialStyle(fill=fill)
        )
    if phase["rule"] == "less_than":
        if not isfinite(phase["threshold"]):
            raise ValueError("条件格式阈值不是有限数值")
        return CellIsRule(
            operator="lessThan", formula=[str(phase["threshold"])], font=Font(color=color)
        )
    if phase["rule"] != "duplicate_rows":
        raise ValueError("未知条件格式规则")
    left, top, right, bottom = bounds
    key = phase["key_column"].upper()
    if not left <= column_index_from_string(key) <= right:
        raise ValueError("重复检查列不在目标区域内")
    cell = f"${key}{top}"
    return FormulaRule(
        formula=[f'AND({cell}<>"",COUNTIF(${key}${top}:${key}${bottom},{cell})>1)'], fill=fill
    )


def _metadata(formats):
    signature = []
    for group in formats:
        rules = []
        for rule in group.rules:
            tree = rule.to_tree()
            # The stylesheet index can change; the referenced differential style
            # and semantic precedence (priority/stopIfTrue) must remain intact.
            tree.attrib.pop("dxfId", None)
            style = tostring(rule.dxf.to_tree()) if rule.dxf is not None else None
            rules.append((tostring(tree), style))
        signature.append((str(group.sqref), group.pivot, tuple(rules)))
    return signature


def check_inserted_conditionals(wb, template_wb, plan, finding):
    for ws in wb.worksheets:
        expected = (
            deepcopy(template_wb[ws.title].conditional_formatting)
            if ws.title in template_wb.sheetnames
            else ConditionalFormattingList()
        )
        for phase in plan_phases(plan):
            try:
                for target, row, count in insertions({"phases": [phase]}):
                    for group in expected:
                        if target.casefold() == ws.title.casefold() and any(
                            row <= area.max_row for area in group.sqref.ranges
                        ):
                            finding.fail(
                                "条件格式应用范围受插行影响，暂不支持迁移",
                                sheet=ws.title,
                                range=str(group.sqref),
                            )
                        for rule in group.rules:
                            if any(
                                _affected_formula(value, group, ws.title, target, row, count, wb)
                                for value in _rule_formulas(rule)
                            ):
                                finding.fail(
                                    "条件格式公式或相对引用受插行影响，暂不支持迁移",
                                    sheet=ws.title,
                                    range=str(group.sqref),
                                )
                if phase.get("phase") == "conditional_format" and phase.get("sheet") == ws.title:
                    ref = str(phase["range"]).upper().replace("$", "")
                    bounds = range_boundaries(ref)
                    left, top, right, bottom = bounds
                    if not (1 <= left <= right <= 16_384 and 1 <= top <= bottom <= 1_048_576):
                        raise ValueError("条件格式范围非法")
                    expected.add(ref, _declared_rule(phase, bounds))
            except (KeyError, TypeError, ValueError, TokenizerError) as exc:
                finding.fail("条件格式无法独立核验", sheet=ws.title, reason=str(exc))
        if _metadata(expected) != _metadata(ws.conditional_formatting):
            finding.fail("条件格式元数据改变、缺失或出现未声明追加", sheet=ws.title)
