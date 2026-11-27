"""Present-row iteration using the pinned openpyxl 3.1.5 native parser.

The public read-only iterator inserts missing rows up to the declared rectangle.
Business projections need actual XML row numbers instead; values, date handling
and styles still come from openpyxl. No second OOXML value parser is maintained.
"""

from itertools import groupby

from openpyxl.cell.read_only import EMPTY_CELL, ReadOnlyCell
from openpyxl.worksheet._reader import WorkSheetParser


def _native_rows(worksheet):
    with worksheet._get_source() as source:
        yield from WorkSheetParser(
            source,
            worksheet._shared_strings,
            data_only=worksheet.parent.data_only,
            epoch=worksheet.parent.epoch,
            date_formats=worksheet.parent._date_formats,
            timedelta_formats=worksheet.parent._timedelta_formats,
        ).parse()


def iter_present_cells(worksheet):
    """Yield native cells without filling even the gaps within an actual row."""
    if hasattr(worksheet, "_get_source"):
        for _, cells in _native_rows(worksheet):
            for cell in cells:
                yield ReadOnlyCell(worksheet, **cell)
    else:
        yield from worksheet._cells.values()


def iter_present_rows(worksheet, *, min_row=1):
    if hasattr(worksheet, "_get_source"):
        for row_number, cells in _native_rows(worksheet):
            if row_number >= min_row:
                yield (
                    row_number,
                    worksheet._get_row(
                        cells, max_col=max((cell["column"] for cell in cells), default=None)
                    ),
                )
        return
    if hasattr(worksheet, "_cells"):
        for row_number, group in groupby(sorted(worksheet._cells), key=lambda pos: pos[0]):
            if row_number < min_row:
                continue
            positions = list(group)
            row = [EMPTY_CELL] * positions[-1][1]
            for position in positions:
                row[position[1] - 1] = worksheet._cells[position]
            yield row_number, tuple(row)
        return
    # Retain the existing worksheet protocol for non-openpyxl adapters.
    yield from enumerate(worksheet.iter_rows(min_row=min_row), start=min_row)
