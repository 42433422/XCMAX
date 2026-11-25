"""Independent CSV/workbook comparison against frozen customer reference bytes."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path


def _workbook(raw, *, max_output_bytes):
    from openpyxl import load_workbook

    # Reject oversized zip expansion before openpyxl allocates cell objects.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > max_output_bytes:
            raise ValueError("training_replay_workbook_too_large")
    workbook = load_workbook(io.BytesIO(raw), data_only=False, keep_links=False)
    values = load_workbook(io.BytesIO(raw), data_only=True, keep_links=False)
    try:
        if any(sheet.max_row * sheet.max_column > 250_000 for sheet in workbook):
            raise ValueError("training_replay_workbook_too_large")
        result = []
        for sheet in workbook:
            rows = []
            for row in sheet.iter_rows():
                cells = []
                for cell in row:
                    cached = values[sheet.title][cell.coordinate].value
                    if cell.data_type == "f" and cached is None:
                        raise ValueError("training_replay_formula_value_unverified")
                    cells.append((cell.data_type, cell.value, cached, cell.number_format))
                rows.append(cells)
            result.append(
                (
                    sheet.title,
                    sorted(str(item) for item in sheet.merged_cells.ranges),
                    rows,
                )
            )
        return result
    finally:
        workbook.close()
        values.close()


def _equal_files(path, actual, expected, *, workbook):
    if Path(path).suffix.lower() == ".xlsx":
        return workbook(actual) == workbook(expected)
    if actual == expected:
        return True
    try:
        reference = expected.decode("utf-8-sig")
        dialects = []
        for delimiter in ",;\t|":
            try:
                dialect = csv.Sniffer().sniff(reference, delimiters=delimiter)
                # Match the native DictWriter's defaults: whitespace is cell data,
                # and doubled quote characters are escapes, even if absent in gold.
                dialect.skipinitialspace = False
                dialect.doublequote = True
                rows = list(csv.reader(io.StringIO(reference, newline=""), dialect, strict=True))
            except csv.Error:
                continue
            if rows and len(rows[0]) > 1 and all(len(row) == len(rows[0]) for row in rows):
                dialects.append((dialect, rows))
        # Only the frozen oracle chooses the dialect. Ambiguous/single-column
        # references can establish exact bytes, never inferred semantic success.
        if len(dialects) != 1:
            return False
        dialect, rows = dialects[0]
        return (
            list(
                csv.reader(
                    io.StringIO(actual.decode("utf-8-sig"), newline=""), dialect, strict=True
                )
            )
            == rows
        )
    except (csv.Error, UnicodeError):
        return False
