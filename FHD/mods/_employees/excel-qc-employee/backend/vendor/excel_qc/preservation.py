"""Check every original/output cell against the approved mutation footprint.

Use openpyxl's sparse objects and the QC's existing coordinate projection. Never
replay the writer or trust its report; missing and newly introduced cells count.
"""

from copy import copy

from openpyxl.cell.cell import TIME_TYPES, Cell, get_time_format
from openpyxl.styles import PatternFill, Side
from openpyxl.styles.numbers import is_date_format
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.worksheet.worksheet import Worksheet

from .plan_coordinates import (
    declared_ranges,
    in_ranges,
    insertions,
    moved_row,
    original_row,
    plan_phases,
    range_bounds,
    shift_formula_rows,
    target,
)
from .styles import style_signature


def _value(cell, changes):
    value = cell.value
    if cell.data_type == "f":
        if isinstance(value, str):
            value = shift_formula_rows(value, cell.parent.title, changes)
        elif isinstance(value, (ArrayFormula, DataTableFormula)):
            value = vars(value)
    # Blank serialization can switch n/inlineStr without introducing a value.
    return (cell.data_type if value is not None else None, value)


def declared_merges(plan, wb):
    for index, phase in enumerate(plan_phases(plan)):
        if phase.get("phase") == "merge_cells" and phase.get("sheet") in wb.sheetnames:
            sheet = phase["sheet"]
            _, top, left, bottom, right = range_bounds(wb[sheet], phase["range"])
            later = tuple(insertions(plan, index + 1))
            yield sheet, moved_row(sheet, top, later), left, moved_row(sheet, bottom, later), right


class StyleProjection:
    """Project only approved style fields, independently of the writer's output.

    Merged-cell normalization uses openpyxl on at most nine cells: only the
    anchor, bottom-right and edge/interior categories determine the result.
    """

    def __init__(self, wb, template_wb, plan, coerce):
        self.wb, self.template, self.coerce = wb, template_wb, coerce
        self.phases = plan_phases(plan)
        self.changes = tuple(insertions(plan))
        style_ranges = declared_ranges(plan, "cell_styles", wb)
        self.styles = {
            index: [area for area in style_ranges if area[-1] is phase]
            for index, phase in enumerate(self.phases)
            if phase.get("phase") == "cell_styles"
        }
        self.writes, self.merges, self.totals = {}, {}, {}
        self.cache, self.merge_cache = {}, {}
        self.final_merges = [
            (
                ws.title,
                moved_row(ws.title, area.min_row, self.changes),
                area.min_col,
                moved_row(ws.title, area.max_row, self.changes),
                area.max_col,
            )
            for ws in template_wb.worksheets
            for area in ws.merged_cells.ranges
            if ws.title in wb.sheetnames
        ]
        for index, phase in enumerate(self.phases):
            kind, sheet = phase.get("phase"), phase.get("sheet")
            later = tuple(insertions(plan, index + 1))
            if kind in {"cell_writes", "formula_writes"}:
                entries = []
                for write in phase.get("writes") or []:
                    try:
                        owner, row, col = target(write)
                    except (TypeError, ValueError, KeyError):
                        continue  # The ordinary conformance check reports invalid writes.
                    entries.append(((owner, moved_row(owner, row, later), col), write))
                self.writes[index] = entries
            elif kind in {"merge_cells", "create_table"} and sheet in wb.sheetnames:
                _, top, left, bottom, right = range_bounds(wb[sheet], phase["range"])
                bounds = (
                    sheet,
                    moved_row(sheet, top, later),
                    left,
                    moved_row(sheet, bottom, later),
                    right,
                )
                if kind == "merge_cells":
                    self.merges[index] = bounds
                    self.final_merges.append(bounds)
                else:
                    # Header values are independently checked for conformance;
                    # number formats always come from the original/approved plan.
                    for col in range(left, right + 1):
                        if wb[sheet].cell(bounds[1], col).value == phase.get("sum_column"):
                            self.totals[index] = (
                                (sheet, moved_row(sheet, bottom + 1, later), col),
                                (sheet, bounds[3], col),
                            )

    def _base(self, address):
        sheet, row, col = address
        parent = self.template[sheet] if sheet in self.template.sheetnames else self.template.active
        cell = Cell(parent, row=row, column=col)
        source_row = original_row(sheet, row, self.changes)
        if sheet in self.template.sheetnames and source_row is not None:
            original = parent._cells.get((source_row, col))
            if original is not None:
                cell._style = copy(original._style)
        return cell

    def _merged_style(self, bounds, address, before):
        key = (bounds, before)
        if key not in self.merge_cache:
            sheet, top, left, bottom, right = bounds
            height, width = min(bottom - top + 1, 3), min(right - left + 1, 3)
            small = Worksheet(self.template)
            small.cell(1, 1)._style = copy(self._at((sheet, top, left), before)._style)
            small.cell(height, width)._style = copy(self._at((sheet, bottom, right), before)._style)
            small.merge_cells(start_row=1, start_column=1, end_row=height, end_column=width)
            self.merge_cache[key] = small
        sheet, top, left, bottom, right = bounds
        _, row, col = address
        r = 1 if row == top else min(bottom - top + 1, 3) if row == bottom else 2
        c = 1 if col == left else min(right - left + 1, 3) if col == right else 2
        return copy(self.merge_cache[key].cell(r, c)._style)

    def _at(self, address, before):
        key = (address, before)
        if key in self.cache:
            return self.cache[key]
        cell = self._base(address)
        for index, phase in enumerate(self.phases[:before]):
            bounds = self.merges.get(index)
            if bounds and in_ranges([bounds], *address):
                cell._style = self._merged_style(bounds, address, index)
            for *bounds, style in self.styles.get(index, ()):
                if in_ranges([bounds], *address):
                    font, alignment = copy(cell.font), copy(cell.alignment)
                    if style.get("bold") is not None:
                        font.bold = bool(style["bold"])
                    if style.get("font_size") is not None:
                        font.sz = float(style["font_size"])
                    cell.font = font
                    for attr in ("horizontal", "vertical"):
                        if style.get(attr):
                            setattr(alignment, attr, str(style[attr]))
                    cell.alignment = alignment
                    if style.get("fill_color"):
                        color = "FF" + str(style["fill_color"]).strip().upper()
                        cell.fill = PatternFill("solid", fgColor=color, bgColor=color)
                    if style.get("border"):
                        border = copy(cell.border)
                        for edge in ("left", "right", "top", "bottom"):
                            setattr(border, edge, Side(style=str(style["border"])))
                        cell.border = border
            for location, write in self.writes.get(index, ()):
                if location != address:
                    continue
                if phase.get("phase") == "cell_writes":
                    value = self.coerce(write.get("value"), str(write.get("value_type") or ""))
                    if isinstance(value, TIME_TYPES) and not is_date_format(cell.number_format):
                        cell.number_format = get_time_format(type(value))
                if write.get("number_format"):
                    cell.number_format = str(write["number_format"])
            total = self.totals.get(index)
            if total and total[0] == address and cell.number_format == "General":
                cell.number_format = self._at(total[1], index).number_format
        # Retain only intermediate anchor/format dependencies, never one extra
        # Cell per final workbook position during the sparse preservation scan.
        if before < len(self.phases):
            self.cache[key] = cell
        return cell

    def __call__(self, sheet, row, col):
        address, before = (sheet, row, col), len(self.phases)
        cell = self._at(address, before)
        # Reopening an OOXML output normalizes its merged cells once more.
        for bounds in self.final_merges:
            if in_ranges([bounds], *address):
                normalized = self._base(address)
                normalized._style = self._merged_style(bounds, address, before)
                return normalized
        return cell


def check_preserved_cells(wb, template_wb, plan, planned_targets, finding, projection):
    changes = tuple(insertions(plan))
    cleared = declared_ranges(plan, "clear_ranges", wb)
    merges = tuple(declared_merges(plan, wb))
    checked = 0
    for out in wb.worksheets:
        sheet = out.title
        original_sheet = template_wb[sheet] if sheet in template_wb.sheetnames else out
        originals = (
            {
                (moved_row(sheet, cell.row, changes), cell.column): cell
                for cell in original_sheet._cells.values()
            }
            if sheet in template_wb.sheetnames
            else {}
        )
        # No iter_rows over a bounding rectangle: a far-away single cell stays sparse.
        for row, col in originals.keys() | out._cells.keys():
            original = originals.get((row, col)) or Cell(original_sheet, row=row, column=col)
            actual = out._cells.get((row, col)) or Cell(out, row=row, column=col)
            address = (sheet, row, col)
            for bounds in merges:
                if in_ranges([bounds], sheet, row, col):
                    # Merging discards non-anchor cells and combines edge borders.
                    if (row, col) != (bounds[1], bounds[2]):
                        original = Cell(original_sheet, row=row, column=col)
            overridden = address in planned_targets or in_ranges(cleared, sheet, row, col)
            if not overridden and _value(original, changes) != _value(actual, ()):
                finding.fail("批准范围外的原数据或公式改变", sheet=sheet, ref=actual.coordinate)
            if style_signature(projection(*address)) != style_signature(actual):
                finding.fail("未获批准的单元格样式改变", sheet=sheet, ref=actual.coordinate)
            if original.comment != actual.comment:
                finding.fail("未获批准的单元格批注改变", sheet=sheet, ref=actual.coordinate)
            before, after = original.hyperlink, actual.hyperlink
            fields = ("target", "location", "tooltip", "display")
            if tuple(getattr(before, key, None) for key in fields) != tuple(
                getattr(after, key, None) for key in fields
            ):
                finding.fail("未获批准的单元格超链接改变", sheet=sheet, ref=actual.coordinate)
            checked += 1
    return checked
