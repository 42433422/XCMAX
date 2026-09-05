"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.mapper")


def _detail_side_month_link_column_map(ws) -> dict[str, int]:
    """从明细表 BR..CC 表头解析「月度统计」各指标应对应的侧栏 SUMIF 列号。

    太阳鸟模板常在第 2 行放图示（与 ``_refresh_detail_side_summary_formulas`` 的 ``crit_row`` 一致），
    亦尝试第 3 行与第 1 行，避免模板改版后解析失败导致月度统计退化为静态数。
    """
    crit_rows = (
        1,
        max(1, _facade().DETAIL_HEADER_ROWS - 1),
        _facade().DETAIL_HEADER_ROWS,
    )
    out: dict[str, int] = {}
    for crit_row in crit_rows:
        for c in range(
            _facade().DETAIL_SIDE_SUMMARY_SUMIF_START_COL,
            _facade().DETAIL_SIDE_SUMMARY_SUMIF_END_COL + 1,
        ):
            raw = ws.cell(crit_row, c).value
            t = (
                _facade()
                .unicodedata.normalize("NFKC", _facade()._plain_cell_text(raw))
                .replace(" ", "")
                .replace("\n", "")
            )
            if not t:
                continue
            for key, needles in _facade()._DETAIL_MONTH_LINK_RULES:
                if key in out:
                    continue
                if any(n in t for n in needles):
                    out[key] = c
                    break
    return out


def _detail_side_metric_symbol_columns(ws) -> tuple[int | None, int | None, int | None]:
    """兼容旧调用：从 ``_detail_side_month_link_column_map`` 取前三项。"""
    m = _facade()._detail_side_month_link_column_map(ws)
    return (m.get("正常上班"), m.get("平常加班"), m.get("星期天加班"))


def _refresh_detail_side_summary_formulas(
    ws, *, header_rows: int = _facade().DETAIL_HEADER_ROWS
) -> None:
    """重写明细右侧 BP—CG：侧表从第一个数据行开始连续排列，每人一行。

    左侧考勤主表仍是每人 6 行块；右侧侧表独立压缩为连续单行列表。
    ``SUMIF`` 的 ``OFFSET`` 仍按对应人员 6 行明细块计算，避免侧表每 6 行才出现一条。
    """
    first_body = header_rows + 1
    crit_row = max(1, header_rows - 1)
    block_rows = _facade().iter_detail_sheet_block_base_rows(ws, header_rows)
    if not block_rows:
        return
    ce0 = ws.cell(first_body, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[0]).value
    cf0 = ws.cell(first_body, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[1]).value
    cg0 = ws.cell(first_body, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[2]).value
    side_lo = _facade().DETAIL_SIDE_SUMMARY_BP_COL
    side_hi = max(_facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS)
    mr = ws.max_row
    _facade()._unmerge_cell_rectangle(ws, first_body, mr, side_lo, side_hi)
    for r in range(first_body, mr + 1):
        for c in range(side_lo, side_hi + 1):
            ws.cell(r, c).value = None
    for pidx, base_row in enumerate(block_rows, start=1):
        side_row = first_body + pidx - 1
        off = base_row - first_body
        c_bp = ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_BP_COL)
        c_bp.value = float(pidx)
        _facade()._force_arabic_number_format(c_bp, float(pidx))
        nm = ws.cell(base_row, 3).value
        ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_BQ_COL).value = (
            nm if nm not in (None, "") else None
        )
        c_cd = ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_CD_COL)
        c_cd.value = f"=BQ{side_row}"
        _facade()._force_arabic_number_format(c_cd, None)
        for c in range(
            _facade().DETAIL_SIDE_SUMMARY_SUMIF_START_COL,
            _facade().DETAIL_SIDE_SUMMARY_SUMIF_END_COL + 1,
        ):
            letter = _facade().get_column_letter(c)
            c_sum = ws.cell(side_row, c)
            c_sum.value = (
                f"=SUMIF(OFFSET($E$4:$BM$9,{off},),{letter}${crit_row},OFFSET($F$4:$BN$9,{off},))"
            )
            _facade()._force_arabic_number_format(c_sum, None)
        if isinstance(ce0, str) and ce0.startswith("="):
            n_mark = 1 + (base_row - first_body)

            def _night(tpl: str) -> str:
                out = _facade().re.sub("\\$CD\\d+", f"$CD{side_row}", tpl)
                return _facade().re.sub(
                    "COLUMN\\(([B-D])\\d+\\)",
                    lambda m: f"COLUMN({m.group(1)}{n_mark})",
                    out,
                )

            c_ce = ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[0])
            c_ce.value = _night(ce0)
            _facade()._force_arabic_number_format(c_ce, None)
            if isinstance(cf0, str) and cf0.startswith("="):
                c_cf = ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[1])
                c_cf.value = _night(cf0)
                _facade()._force_arabic_number_format(c_cf, None)
            if isinstance(cg0, str) and cg0.startswith("="):
                c_cg = ws.cell(side_row, _facade().DETAIL_SIDE_SUMMARY_NIGHT_COLS[2])
                c_cg.value = _night(cg0)
                _facade()._force_arabic_number_format(c_cg, None)


def _detail_numeric_addend(value: object) -> float | None:
    """仅统计 int/float（排除 bool、日期时间、公式串等）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (_facade().date, _facade().datetime, _facade().time)):
        return None
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return float(value)
    except ImportError:
        pass
    return None


def _sum_person_block_numeric_cells(
    ws,
    top_row: int,
    *,
    start_col: int = _facade().DETAIL_SUM_COL_START,
    end_col: int = _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1,
) -> float:
    total = 0.0
    for dr in range(_facade().DETAIL_PERSON_BLOCK_ROWS):
        r = top_row + dr
        for c in range(start_col, end_col + 1):
            add = _facade()._detail_numeric_addend(ws.cell(r, c).value)
            if add is not None:
                total += add
    return total


def _ensure_onsheet_block_total_header(ws) -> None:
    """在明细第 2 行标注块内数字总和列（若该格为空）。"""
    cell = ws.cell(2, _facade().DETAIL_ONSHEET_BLOCK_TOTAL_COL)
    if cell.value in (None, ""):
        cell.value = "块内数字计"


def _write_entries(
    ws,
    row_idx: int,
    symbol_col: int,
    entries: list[_facade().DayBandEntry],
    *,
    block_top: int | None = None,
    proto_styles: dict[tuple[int, int], _facade().BlockCellStyle] | None = None,
) -> None:
    for offset, entry in enumerate(entries[:2]):
        target_row = row_idx + offset
        for col, val in (
            (symbol_col, entry.symbol),
            (symbol_col + 1, _facade()._round_display(entry.value)),
        ):
            cell = ws.cell(target_row, col)
            cell.value = val
            if proto_styles is not None and block_top is not None:
                rel_r = target_row - block_top + 1
                st = proto_styles.get((rel_r, col))
                if st:
                    _facade()._apply_style_bundle(cell, st)
            if col == symbol_col + 1 and isinstance(val, (int, float)) and (type(val) is not bool):
                _facade()._force_arabic_number_format(cell)


def write_detail_sheet(
    workbook,
    employees: dict[str, _facade().EmployeeMonthTemplateData],
    *,
    month_label: str,
) -> _facade().TemplateWriteResult:
    ws = workbook["明细"] if "明细" in workbook.sheetnames else workbook.active
    _facade().set_template_month(ws, month_label)
    name_to_base = _facade().find_template_base_rows(ws)
    block_base_rows = _facade().iter_detail_sheet_block_base_rows(ws)
    probe_row = min(name_to_base.values()) if name_to_base else _facade().DETAIL_HEADER_ROWS + 1
    first_sym_col = _facade()._first_attendance_symbol_col(ws, probe_row)
    proto_styles_body = _facade()._snapshot_block_cell_styles(ws, probe_row)
    _facade().clear_template_blocks(ws, block_base_rows, proto_styles_body)
    _facade()._strip_dbnum_column_styles(
        ws, _facade().DETAIL_SUM_COL_START, _facade().DETAIL_ONSHEET_BLOCK_TOTAL_COL
    )
    for br in block_base_rows:
        _facade()._normalize_block_chinese_numerals(
            ws,
            br,
            _facade().DETAIL_SUM_COL_START,
            _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1,
        )
    matched = 0
    unmatched: list[str] = []
    for employee_name, payload in employees.items():
        base_row = name_to_base.get(employee_name)
        if base_row is None:
            unmatched.append(employee_name)
            continue
        matched += 1
        for day, day_payload in payload.days.items():
            symbol_col = first_sym_col + (day - 1) * 2
            _facade()._write_entries(
                ws,
                base_row,
                symbol_col,
                day_payload.morning,
                block_top=base_row,
                proto_styles=proto_styles_body,
            )
            _facade()._write_entries(
                ws,
                base_row + 2,
                symbol_col,
                day_payload.afternoon,
                block_top=base_row,
                proto_styles=proto_styles_body,
            )
            _facade()._write_entries(
                ws,
                base_row + 4,
                symbol_col,
                day_payload.night,
                block_top=base_row,
                proto_styles=proto_styles_body,
            )
    for br in block_base_rows:
        _facade()._normalize_block_chinese_numerals(
            ws,
            br,
            _facade().DETAIL_SUM_COL_START,
            _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1,
        )
    _facade()._refresh_detail_side_summary_formulas(ws)
    _facade()._ensure_onsheet_block_total_header(ws)
    lo_letter = _facade().get_column_letter(_facade().DETAIL_SUM_COL_START)
    hi_letter = _facade().get_column_letter(_facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1)
    for br in block_base_rows:
        c_tot = ws.cell(br, _facade().DETAIL_ONSHEET_BLOCK_TOTAL_COL)
        bottom = br + _facade().DETAIL_PERSON_BLOCK_ROWS - 1
        c_tot.value = f"=SUM({lo_letter}{br}:{hi_letter}{bottom})"
        c_tot.number_format = _facade().DETAIL_BLOCK_TOTAL_NUMBER_DISPLAY
    return _facade().TemplateWriteResult(
        matched_employee_count=matched, unmatched_employee_names=sorted(unmatched)
    )


def _reset_sheet_rows(ws, headers: list[str]) -> None:
    ws.delete_rows(1, ws.max_row)
    ws.append(headers)
