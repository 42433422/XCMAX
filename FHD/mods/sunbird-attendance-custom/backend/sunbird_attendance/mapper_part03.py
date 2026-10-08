from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.mapper")


def _snapshot_block_cell_styles(
    ws, block_top: int
) -> dict[tuple[int, int], _facade().BlockCellStyle]:
    """快照首块 6×DETAIL_MAX_COL 的字体、边框、对齐（供粘贴、清空与写入后恢复版式）。"""
    styles: dict[tuple[int, int], _facade().BlockCellStyle] = {}
    for dr in range(_facade().DETAIL_PERSON_BLOCK_ROWS):
        for c in range(1, _facade().DETAIL_MAX_COL + 1):
            cell = ws.cell(block_top + dr, c)
            try:
                font = _facade().copy(cell.font)
                border = _facade().copy(cell.border)
                alignment = _facade().copy(cell.alignment)
            except (TypeError, ValueError):
                font = border = alignment = None
            styles[dr + 1, c] = (font, border, alignment)
    return styles


def _apply_style_bundle(cell, bundle: _facade().BlockCellStyle | None) -> None:
    if not bundle:
        return
    for attribute, value in zip(("font", "border", "alignment"), bundle):
        if value is not None:
            setattr(cell, attribute, value)


def _force_arabic_number_format(cell, value: object | None = None) -> None:
    """单元格数字显示为常规阿拉伯数字（须配合列级 ``_strip_dbnum_column_styles``）。"""
    cell.number_format = _facade().DETAIL_ARABIC_NUMBER_DISPLAY


def _strip_dbnum_column_styles(ws, col_lo: int, col_hi: int) -> None:
    """去掉 ``column_dimensions`` 上的 ``[DBNum1]``，否则保存后仍按列样式显示中文数或 ``2.`` 等。"""
    for c in range(col_lo, col_hi + 1):
        letter = _facade().get_column_letter(c)
        dim = ws.column_dimensions.get(letter)
        if dim is None:
            continue
        fmt = str(dim.number_format or "")
        if "DBNum" in fmt or "dbnum" in fmt.lower():
            dim.number_format = _facade().DETAIL_ARABIC_NUMBER_DISPLAY


def _paste_one_person_block(
    ws,
    block_top: int,
    proto_vals: dict[tuple[int, int], object],
    rel_merges: list[tuple[int, int, int, int]],
    department: str,
    nature: str,
    name: str,
    proto_styles: dict[tuple[int, int], _facade().BlockCellStyle] | None = None,
) -> None:
    for (dr, c), v in proto_vals.items():
        if c >= _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL:
            continue
        tgt = ws.cell(block_top + dr - 1, c)
        tgt.value = None if c >= 5 else v
        if proto_styles:
            _facade()._apply_style_bundle(tgt, proto_styles.get((dr, c)))
    for col, value in enumerate((department, nature, name), 1):
        cell = ws.cell(block_top, col, value)
        cell.data_type = "s"
    for min_c, r1, max_c, r2 in rel_merges:
        ref = f"{_facade().get_column_letter(min_c)}{block_top + r1 - 1}:{_facade().get_column_letter(max_c)}{block_top + r2 - 1}"
        try:
            ws.merge_cells(ref)
        except ValueError:
            pass
    _facade()._normalize_block_chinese_numerals(
        ws,
        block_top,
        _facade().DETAIL_SUM_COL_START,
        _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1,
    )


def rebuild_detail_sheet_person_blocks(
    ws,
    people: list[tuple[str, str, str]],
    *,
    header_rows: int = _facade().DETAIL_HEADER_ROWS,
    prototype_block_top: int = 4,
) -> None:
    """Rebuild whole six-row blocks; preserve prototype merges and night formulas."""
    if not people:
        return
    if ws.max_row < prototype_block_top + _facade().DETAIL_PERSON_BLOCK_ROWS - 1:
        raise ValueError("明细表过短：缺少模板首个人员 6 行块")
    night_tpl = tuple(
        ws.cell(prototype_block_top, col).value for col in _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS
    )
    proto_vals, rel_merges = _facade()._snapshot_first_person_block(ws, prototype_block_top)
    proto_styles = _facade()._snapshot_block_cell_styles(ws, prototype_block_top)
    last = ws.max_row
    for merged in list(ws.merged_cells.ranges):
        if merged.max_row > header_rows:
            ws.unmerge_cells(str(merged))
    if last > header_rows:
        ws.delete_rows(header_rows + 1, last - header_rows)
    for i, (dept, nature, name) in enumerate(people):
        top = header_rows + 1 + i * _facade().DETAIL_PERSON_BLOCK_ROWS
        _facade()._paste_one_person_block(
            ws, top, proto_vals, rel_merges, dept, nature, name, proto_styles
        )
    first_body = header_rows + 1
    for col, val in zip(_facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS, night_tpl):
        if val not in (None, ""):
            ws.cell(first_body, col).value = val


def find_template_base_rows(ws) -> dict[str, int]:
    """每人块仅认第 1 行（块首）C 列姓名，与 ``rebuild_detail_sheet_person_blocks`` 的 6 行步进一致。"""
    mapping: dict[str, int] = {}
    for row in _facade().iter_detail_sheet_block_base_rows(ws):
        name = ws.cell(row, 3).value
        if name not in (None, ""):
            key = str(name).strip()
            if key:
                mapping[key] = row
    return mapping


def find_template_side_summary_rows(
    ws, header_rows: int = _facade().DETAIL_HEADER_ROWS
) -> dict[str, int]:
    """Map each identity to its consecutive side-summary row."""
    block_rows = _facade().iter_detail_sheet_block_base_rows(ws, header_rows)
    if not block_rows:
        return {}
    first_body = header_rows + 1
    mapping: dict[str, int] = {}
    for pidx, base_row in enumerate(block_rows, start=1):
        name = ws.cell(base_row, 3).value
        if name in (None, ""):
            continue
        key = str(name).strip()
        if key:
            mapping[key] = first_body + pidx - 1
    return mapping


def _unmerge_cell_rectangle(ws, r1: int, r2: int, c1: int, c2: int) -> None:
    """解除与矩形 [r1..r2]×[c1..c2] 相交的合并，便于清空侧栏单元格。"""
    for rng in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = _facade().range_boundaries(str(rng))
        if max_row < r1 or min_row > r2 or max_col < c1 or (min_col > c2):
            continue
        ws.unmerge_cells(str(rng))


def iter_detail_sheet_block_base_rows(
    ws, header_rows: int = _facade().DETAIL_HEADER_ROWS
) -> list[int]:
    """按「每人 6 行」几何位置枚举明细块首行（自上而下）。"""
    first_body = header_rows + 1
    rows: list[int] = []
    row = first_body
    while row + _facade().DETAIL_PERSON_BLOCK_ROWS - 1 <= ws.max_row:
        rows.append(row)
        row += _facade().DETAIL_PERSON_BLOCK_ROWS
    return rows


def build_template_profiles(ws) -> dict[str, _facade().TemplateEmployeeProfile]:
    profiles: dict[str, _facade().TemplateEmployeeProfile] = {}
    for base_row in _facade().iter_detail_sheet_block_base_rows(ws):
        name = ws.cell(base_row, 3).value
        if name in (None, ""):
            continue
        employee_name = str(name).strip()
        nature_raw = ws.cell(base_row, 2).value
        nature_plain = (
            _facade().unicodedata.normalize("NFKC", _facade()._plain_cell_text(nature_raw)).strip()
        )
        overtime_start, block_values, morning_work_start = (
            _facade()._parse_profile_rules_from_nature_plain(nature_plain)
        )
        profiles[employee_name] = _facade().TemplateEmployeeProfile(
            employee_name=employee_name,
            base_row=base_row,
            department=str(ws.cell(base_row, 1).value or "").strip(),
            nature_text=nature_plain,
            block_values=block_values,
            overtime_start=overtime_start,
            morning_work_start=morning_work_start,
        )
    return profiles


def set_template_month(ws, month_label: str) -> None:
    if not month_label:
        return
    year_str, month_str = month_label.split("-", 1)
    ws["M1"] = int(year_str)
    ws["S1"] = int(month_str)


def _detail_calendar_anchor_col(ws, header_rows: int = _facade().DETAIL_HEADER_ROWS) -> int | None:
    """表头行中「1 日」所在列（上午格），作为日×2 槽起点；与 ``DETAIL_TEMPLATE_SUMMARY_BEGIN_COL`` 之前扫描。"""
    row = header_rows
    hi = min(_facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1, _facade().DETAIL_MAX_COL)
    for c in range(5, hi + 1):
        v = ws.cell(row, c).value
        if v in (1, "1", "１"):
            return c
        if isinstance(v, str) and _facade().unicodedata.normalize("NFKC", v).strip() in {"1", "１"}:
            return c
    return None


def _first_attendance_symbol_col(ws, sample_row: int) -> int:
    """日×2 考勤写入起始列：优先用表头「1 日」列，避免首格为空时误把第 2 日当作起点（会侵占 BP 侧栏）。"""
    anchor = _facade()._detail_calendar_anchor_col(ws, _facade().DETAIL_HEADER_ROWS)
    if anchor is not None:
        return int(anchor)
    for c in range(5, _facade().DETAIL_MAX_COL + 1):
        v = ws.cell(sample_row, c).value
        text = _facade()._plain_cell_text(v).strip()
        if not text:
            continue
        text = _facade().unicodedata.normalize("NFKC", text).strip()
        if text in _facade()._ATT_MARK:
            return c
    return 5


def clear_template_blocks(
    ws,
    base_rows: _facade().Iterable[int],
    proto_styles: dict[tuple[int, int], _facade().BlockCellStyle] | None = None,
) -> None:
    for base_row in base_rows:
        for row_idx in range(base_row, base_row + 6):
            for col_idx in range(5, _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL):
                cell = ws.cell(row_idx, col_idx)
                cell.value = None
                if proto_styles:
                    rel_r = row_idx - base_row + 1
                    st = proto_styles.get((rel_r, col_idx))
                    if st:
                        _facade()._apply_style_bundle(cell, st)
