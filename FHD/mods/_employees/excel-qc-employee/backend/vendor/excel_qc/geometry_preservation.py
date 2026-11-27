"""Preserve native row/column dimensions and panes outside approved operations."""

from copy import copy

from openpyxl.worksheet.dimensions import RowDimension
from openpyxl.worksheet.worksheet import Worksheet

from .plan_coordinates import insertions, moved_row, plan_phases
from .styles import style_signature


def _dimension(dimension):
    # Native style IDs are workbook-local; compare the actual style components.
    fields = {key: value for key, value in dict(dimension).items() if key not in {"s", "style"}}
    return fields, style_signature(dimension)


def check_preserved_geometry(wb, template_wb, plan, finding):
    phases = plan_phases(plan)
    changes = tuple(insertions(plan))
    for original in template_wb.worksheets:
        sheet = original.title
        if sheet not in wb.sheetnames:
            continue  # The workbook inventory check validates approved removals.
        actual = wb[sheet]
        rows = {
            moved_row(sheet, row, changes): copy(dimension)
            for row, dimension in original.row_dimensions.items()
        }
        expected_pane = original.sheet_view.pane
        for index, phase in enumerate(phases):
            if str(phase.get("sheet") or "").strip().strip("'") != sheet:
                continue
            try:
                if phase.get("phase") == "set_row_height":
                    row = moved_row(sheet, int(phase["row"]), insertions(plan, index + 1))
                    dimension = rows.setdefault(row, RowDimension(original, index=row))
                    dimension.height = float(phase["height"])
                elif phase.get("phase") == "freeze_panes":
                    # Use the pinned parser's pane semantics on an empty sheet,
                    # independently of the writer and without materializing cells.
                    projected = Worksheet(original.parent)
                    projected.freeze_panes = str(phase.get("ref") or "").strip().upper()
                    expected_pane = projected.sheet_view.pane
            except (TypeError, ValueError, KeyError):
                continue  # The existing structural check reports invalid phases.
        for row in rows.keys() | actual.row_dimensions.keys():
            expected = rows.get(row) or RowDimension(original, index=row)
            found = actual.row_dimensions.get(row) or RowDimension(actual, index=row)
            if _dimension(expected) != _dimension(found):
                finding.fail("未获批准的行尺寸、隐藏、分组或样式改变", sheet=sheet, row=row)
        before = {key: _dimension(value) for key, value in original.column_dimensions.items()}
        after = {key: _dimension(value) for key, value in actual.column_dimensions.items()}
        if before != after:
            finding.fail("未获批准的列尺寸、隐藏、分组或样式改变", sheet=sheet)
        if original.sheet_format != actual.sheet_format:
            finding.fail("默认行列尺寸或工作表尺寸属性改变", sheet=sheet)
        if expected_pane != actual.sheet_view.pane:
            finding.fail("冻结或拆分窗格不符合原模板及批准计划", sheet=sheet)


def check_printer_settings(filled_path, template_path, retained_sheets, finding):
    from app.mod_sdk.host_services import printer_settings_facts

    if template_path is None:
        return
    try:
        before = printer_settings_facts(template_path)
        expected = {sheet: values for sheet, values in before.items() if sheet in retained_sheets}
        if expected != printer_settings_facts(filled_path):
            finding.fail("原生打印机配置关联或内容摘要改变")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        finding.fail("原生打印机配置无法独立核验", error=str(exc))
