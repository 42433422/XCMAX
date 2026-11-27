"""Independent row-insertion integrity checks retained from the product mainline.

Use QC-owned coordinate and metadata projections; never share the writer's
transformations as proof that the saved workbook is correct.
"""

from __future__ import annotations

from .chart_integrity import check_inserted_charts
from .conditional_formats import check_inserted_conditionals
from .plan_coordinates import (
    affected_reserved_names as _affected_reserved_names,
)
from .plan_coordinates import (
    declared_ranges as _declared_ranges,
)
from .plan_coordinates import (
    declared_validation_name as _declared_validation_name,
)
from .plan_coordinates import (
    defined_names as _defined_names,
)
from .plan_coordinates import (
    final_writes as _final_writes,
)
from .plan_coordinates import (
    in_ranges as _in_ranges,
)
from .plan_coordinates import (
    insertions as _insertions,
)
from .plan_coordinates import (
    moved_row as _moved_row,
)
from .plan_coordinates import (
    original_row as _original_row,
)
from .plan_coordinates import (
    plan_phases as _plan_phases,
)
from .plan_coordinates import (
    shift_formula_rows as _shift_formula_rows,
)
from .plan_coordinates import (
    shifted_name_definition as _shifted_name_definition,
)
from .plan_coordinates import (
    target as _target,
)
from .plan_coordinates import (
    unsafe_named_control_order as _unsafe_named_control_order,
)
from .styles import style_signature as _style_signature
from .table_integrity import check_inserted_tables
from .three_dimensional import check_three_dimensional_references

_MAX_SAMPLES = 8


def _check_validations(wb, template_wb, plan, finding):
    from collections import Counter

    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.xml.functions import tostring

    for ws in wb.worksheets:
        original = template_wb[ws.title] if ws.title in template_wb.sheetnames else None
        validations = list(original.data_validations.dataValidation) if original is not None else []
        for phase in _plan_phases(plan):
            for target, row, count in _insertions({"phases": [phase]}):
                for item in validations:
                    if target.casefold() == ws.title.casefold() and any(
                        row <= area.max_row for area in item.sqref.ranges
                    ):
                        label = "下拉验证" if item.type == "list" else "数据验证"
                        finding.fail(
                            f"既有{label}的应用范围受插行影响，暂不支持迁移",
                            sheet=ws.title,
                            range=str(item.sqref),
                        )
                    for value in (item.formula1, item.formula2):
                        if value is None:
                            continue
                        formula = str(value)
                        formula = formula if formula.startswith("=") else "=" + formula
                        if (
                            _shift_formula_rows(formula, ws.title, [(target, row, count)])
                            != formula
                        ):
                            finding.fail(
                                "既有数据验证的公式引用受插行影响，暂不支持迁移",
                                sheet=ws.title,
                                range=str(item.sqref),
                            )
            if phase.get("phase") == "data_validation" and phase.get("sheet") == ws.title:
                try:
                    if phase["rule"] == "list":
                        options = {"formula1": phase["name"]}
                    elif phase["rule"] == "whole":
                        if phase["minimum"] > phase["maximum"]:
                            raise ValueError("整数验证下限不得大于上限")
                        options = {
                            "operator": "between",
                            "formula1": str(phase["minimum"]),
                            "formula2": str(phase["maximum"]),
                        }
                    else:
                        raise ValueError("未知数据验证规则")
                    item = DataValidation(
                        type=phase["rule"],
                        showErrorMessage=True,
                        errorStyle="stop",
                        error=phase["error"],
                        **options,
                    )
                    item.add(str(phase["range"]).upper().replace("$", ""))
                    validations.append(item)
                except (KeyError, TypeError, ValueError) as exc:
                    finding.fail("声明的数据验证元数据无法核验", sheet=ws.title, reason=str(exc))
        expected = Counter(tostring(item.to_tree()) for item in validations)
        actual = Counter(tostring(item.to_tree()) for item in ws.data_validations.dataValidation)
        if actual != expected:
            finding.fail("既有数据验证元数据改变、缺失或出现未声明追加", sheet=ws.title)


def _check_defined_names(wb, template_wb, plan, finding):
    from openpyxl.formula.tokenizer import TokenizerError

    _check_validations(wb, template_wb, plan, finding)
    for sheet, name in _unsafe_named_control_order(plan):
        finding.fail("定义名称下拉创建后的受影响插行暂不支持", sheet=sheet, name=name)
    for sheet, name in _affected_reserved_names(template_wb, plan):
        finding.fail("受影响的保留定义名称暂不支持插行迁移", sheet=sheet, name=name)
    layouts = {
        phase.get("sheet") for phase in _plan_phases(plan) if phase.get("phase") == "print_layout"
    }
    for sheet in wb.worksheets:
        original = template_wb[sheet.title] if sheet.title in template_wb.sheetnames else None
        for attribute in ("print_area", "print_title_rows", "print_title_cols"):
            if sheet.title in layouts and attribute != "print_title_cols":
                continue  # The declared fields are checked by control_matches.
            before, after = (
                str(getattr(original, attribute, None) or ""),
                str(getattr(sheet, attribute) or ""),
            )
            if before != after:
                finding.fail(
                    "未经授权的保留定义名称改变",
                    sheet=sheet.title,
                    name=attribute,
                    planned=before,
                    actual=after,
                )
    expected = _defined_names(template_wb, wb.sheetnames)
    for phase in _plan_phases(plan):
        changes = tuple(_insertions({"phases": [phase]}))
        if changes:
            for (scope, name), text in list(expected.items()):
                try:
                    expected[scope, name] = _shifted_name_definition(
                        text, scope, template_wb, changes
                    )
                except (ValueError, KeyError, TokenizerError) as exc:
                    finding.fail(
                        "定义名称无法独立核验插行迁移", sheet=scope, name=name, reason=str(exc)
                    )
        elif phase.get("phase") == "data_validation" and phase.get("rule") == "list":
            try:
                key, text = _declared_validation_name(phase, wb)
                if key in expected and expected[key] != text:
                    raise ValueError("计划定义名称覆盖既有绑定")
                expected[key] = text
            except (ValueError, KeyError, TypeError) as exc:
                finding.fail("计划创建的定义名称无效", reason=str(exc))
    actual = _defined_names(wb)
    for scope, name in expected.keys() ^ actual.keys():
        finding.fail("定义名称新增、缺失或作用域改变", sheet=scope, name=name)
    for (scope, name), text in expected.items():
        if actual.get((scope, name)) != text:
            finding.fail(
                "定义名称目的地未按插行迁移",
                sheet=scope,
                name=name,
                planned=text,
                actual=actual.get((scope, name)),
            )


def check_inserted_rows(wb, plan, template_wb, planned_targets, f, values_match) -> None:
    if template_wb is None:
        f.warn("未提供原模板，插入行后的数据与公式迁移无法独立核验")
        return
    insertions = tuple(_insertions(plan))
    _check_defined_names(wb, template_wb, plan, f)
    check_three_dimensional_references(wb, template_wb, plan, f)
    check_inserted_charts(wb, template_wb, plan, f)
    check_inserted_conditionals(wb, template_wb, plan, f)
    check_inserted_tables(wb, template_wb, plan, f)
    style_ranges = _declared_ranges(plan, "cell_styles", wb)
    for target, _, _ in insertions:
        if target not in template_wb.sheetnames:
            f.fail("插入行的 sheet 不在原模板中", sheet=target)
    clear_ranges = _declared_ranges(plan, "clear_ranges", wb)
    formats = {
        _target(w)
        for kind in ("cell_writes", "formula_writes")
        for w in _final_writes(plan, kind)
        if w.get("number_format")
    }
    issues = 0
    for tpl in template_wb.worksheets:
        sheet = tpl.title
        if sheet not in wb.sheetnames:
            continue
        out = wb[sheet]
        coordinates = set(tpl._cells)
        for target_row, col in tuple(out._cells):
            source_row = _original_row(sheet, target_row, insertions)
            if source_row is not None and source_row <= tpl.max_row and col <= tpl.max_column:
                coordinates.add((source_row, col))
        for row, col in sorted(coordinates):
            original = tpl.cell(row, col)
            r, c = _moved_row(sheet, original.row, insertions), original.column
            target, actual = (sheet, r, c), out.cell(r, c)
            expected = original.value
            if isinstance(expected, str) and expected.startswith("="):
                expected = _shift_formula_rows(expected, sheet, insertions)
            overridden = target in planned_targets or _in_ranges(clear_ranges, sheet, r, c)
            if not overridden and not values_match(expected, actual.value):
                issues += 1
                f.fail(
                    "插入行后原数据或公式引用未按行迁移",
                    sheet=sheet,
                    template_ref=original.coordinate,
                    actual_ref=actual.coordinate,
                    planned=str(expected)[:80],
                    actual=str(actual.value)[:80],
                )
            changed = {"number_format"} if target in formats else set()
            for *bounds, style in style_ranges:
                if _in_ranges([bounds], sheet, r, c):
                    changed.update(
                        key for key in ("bold", "font_size") if style.get(key) is not None
                    )
                    changed.update(
                        key
                        for key in (
                            "horizontal",
                            "vertical",
                            "fill_color",
                            "border",
                            "number_format",
                        )
                        if str(style.get(key) or "").strip()
                    )
            if _style_signature(original, changed) != _style_signature(actual, changed):
                issues += 1
                f.fail(
                    "插入行后原样式未保留",
                    sheet=sheet,
                    template_ref=original.coordinate,
                    actual_ref=actual.coordinate,
                )
            if issues >= _MAX_SAMPLES * 4:
                return
        for cell in tuple(out._cells.values()):
            if (
                cell.value is not None
                and _original_row(sheet, cell.row, insertions) is None
                and (sheet, cell.row, cell.column) not in planned_targets
            ):
                f.fail("插入空行出现计划外数据", sheet=sheet, ref=cell.coordinate)
        merged = {(r.min_row, r.min_col, r.max_row, r.max_col) for r in out.merged_cells.ranges}
        for region in tpl.merged_cells.ranges:
            bounds = (
                _moved_row(sheet, region.min_row, insertions),
                region.min_col,
                _moved_row(sheet, region.max_row, insertions),
                region.max_col,
            )
            if bounds not in merged:
                f.fail("插入行后原合并区域未保留", sheet=sheet, range=str(region))
        heights = {
            _moved_row(sheet, int(ph["row"]), _insertions(plan, index + 1))
            for index, ph in enumerate(_plan_phases(plan))
            if ph.get("phase") == "set_row_height" and ph.get("sheet") == sheet
        }
        for row, dimension in tpl.row_dimensions.items():
            target_row = _moved_row(sheet, row, insertions)
            if (
                target_row not in heights
                and dimension.height != out.row_dimensions[target_row].height
            ):
                f.fail("插入行后原行高未保留", sheet=sheet, row=target_row)
