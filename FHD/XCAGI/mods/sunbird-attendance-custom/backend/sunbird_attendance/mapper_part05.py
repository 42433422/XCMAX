"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.mapper")


def _excel_quoted_sheet(title: str) -> str:
    return "'" + str(title).replace("'", "''") + "'"


def _monthly_sheet_is_roster_layout(ws) -> bool:
    """识别「序号 + 图示/姓名 + 指标列」类月度模板（勿整表清空）。"""
    v = ws.cell(1, 1).value
    t = (
        _facade()
        .unicodedata.normalize("NFKC", _facade()._plain_cell_text(v))
        .replace(" ", "")
        .replace("\n", "")
    )
    return "序号" in t


def _scan_monthly_roster_header_row(ws, header_row: int = 1) -> tuple[int, dict[str, int]]:
    """返回 (姓名列号, 指标列号→逻辑键)。姓名列默认 2（A 为序号）。"""
    name_col = 2
    metric_cols: dict[str, int] = {}
    max_c = min(ws.max_column or 20, 40)
    for c in range(1, max_c + 1):
        raw = ws.cell(header_row, c).value
        t = (
            _facade()
            .unicodedata.normalize("NFKC", _facade()._plain_cell_text(raw))
            .replace(" ", "")
            .replace("\n", "")
        )
        if not t:
            continue
        if c == 1 and "序号" in t:
            continue
        if (
            ("姓名" in t or "员工" in t)
            and "正常" not in t
            and ("加班" not in t)
            and ("请假" not in t)
        ):
            name_col = c
            continue
        for key, needles in _facade()._DETAIL_MONTH_LINK_RULES:
            if key not in _facade()._MONTHLY_LINKABLE_METRICS:
                continue
            if any(n in t for n in needles):
                metric_cols[key] = c
                break
    return (name_col, metric_cols)


def _formula_monthly_detail_metric(
    detail_title: str,
    sumif_col_letter: str,
    name_col: int,
    ridx: int,
    base_row: int | None,
) -> str:
    """引用明细表侧栏 SUMIF 列；若未知块首行则用 MATCH(姓名, 明细!C:C) 定位。"""
    q = _facade()._excel_quoted_sheet(detail_title)
    nlet = _facade().get_column_letter(name_col)
    nm = f"{nlet}{ridx}"
    col = sumif_col_letter
    if base_row is not None:
        return f"={q}!{col}{base_row}"
    return f'=IFERROR(INDEX({q}!{col}:{col},MATCH(TRIM({nm}),{q}!$C:$C,0)),"")'


def write_analysis_sheet(workbook, rows: list[dict[str, object]]) -> None:
    ws = (
        workbook["钉钉解析"]
        if "钉钉解析" in workbook.sheetnames
        else workbook.create_sheet("钉钉解析")
    )
    headers = [
        "姓名",
        "考勤组",
        "部门",
        "日期",
        "班次",
        "打卡时间",
        "正班工时",
        "平常加班",
        "星期天加班",
        "请假工时",
        "旷工工时",
        "迟到次数",
        "早退次数",
        "备注",
    ]
    _facade()._reset_sheet_rows(ws, headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])


def write_monthly_sheet(
    workbook, rows: list[dict[str, object]], *, link_detail_side_totals: bool = True
) -> None:
    """写入「月度统计」工作表。

    ``link_detail_side_totals`` 为真时，凡能在明细 BR..CC 表头识别到的指标列，均写公式引用
    明细表每人块首行侧栏 ``SUMIF`` 结果（与 ``_refresh_detail_side_summary_formulas`` 一致），
    手改明细符号或数值后汇总会随 Excel 重算更新。

    - 若 A1 为「序号」类排版模板，则**不清空表头样式**，仅在识别到的指标列写公式。
    - 若已知姓名在明细块首行的行号，写 ``='明细'!BRn``；否则用 ``INDEX/MATCH(姓名, 明细!C:C)`` 定位块首行。
    - 未识别到侧栏列的指标（如模板无「警告」列）仍写入聚合静态值。
    """
    ws = (
        workbook["月度统计"]
        if "月度统计" in workbook.sheetnames
        else workbook.create_sheet("月度统计")
    )
    headers = [
        "姓名",
        "考勤组",
        "部门",
        "工号",
        "正常上班",
        "平常加班",
        "星期天加班",
        "请假",
        "旷工",
        "迟到",
        "早退",
        "警告",
    ]
    detail_ws = workbook["明细"] if "明细" in workbook.sheetnames else None
    link_map: dict[str, int] = {}
    name_to_base: dict[str, int] = {}
    if link_detail_side_totals and detail_ws is not None:
        link_map = _facade()._detail_side_month_link_column_map(detail_ws)
        name_to_base = _facade().find_template_side_summary_rows(detail_ws)
    detail_title = str(detail_ws.title) if detail_ws is not None else "明细"
    use_roster = _facade()._monthly_sheet_is_roster_layout(ws)
    name_col_roster, metric_cols_roster = (2, {})
    if use_roster:
        name_col_roster, metric_cols_roster = _facade()._scan_monthly_roster_header_row(ws, 1)
        if not metric_cols_roster:
            use_roster = False
    if use_roster:
        data_end = len(rows) + 1
        for r in range(data_end + 1, (ws.max_row or data_end) + 1):
            for c in metric_cols_roster.values():
                ws.cell(r, c).value = None
        h1 = ws.cell(1, 1).value
        h1t = (
            _facade().unicodedata.normalize("NFKC", _facade()._plain_cell_text(h1)).replace(" ", "")
        )
        use_seq_formula = "序号" in h1t
        for ridx, row in enumerate(rows, start=2):
            if use_seq_formula:
                c_seq = ws.cell(ridx, 1)
                c_seq.value = "=ROW()-1"
                _facade()._force_arabic_number_format(c_seq, None)
            name_key = str(row.get("姓名", "") or "").strip()
            ws.cell(ridx, name_col_roster).value = name_key or None
            base_r = name_to_base.get(name_key) if name_key else None
            for key, cidx in metric_cols_roster.items():
                cell = ws.cell(ridx, cidx)
                dcol = link_map.get(key) if key in _facade()._MONTHLY_LINKABLE_METRICS else None
                if link_detail_side_totals and detail_ws is not None and (dcol is not None):
                    letter = _facade().get_column_letter(int(dcol))
                    cell.value = _facade()._formula_monthly_detail_metric(
                        detail_title, letter, name_col_roster, ridx, base_r
                    )
                    _facade()._force_arabic_number_format(cell, None)
                else:
                    cell.value = row.get(key, "")
                    v = row.get(key)
                    if isinstance(v, (int, float)) and (not isinstance(v, bool)):
                        _facade()._force_arabic_number_format(cell, float(v))
        return
    _facade()._reset_sheet_rows(ws, headers)
    for ridx, row in enumerate(rows, start=2):
        name_key = str(row.get("姓名", "") or "").strip()
        base_r = name_to_base.get(name_key) if name_key else None
        for cidx, h in enumerate(headers, start=1):
            cell = ws.cell(ridx, cidx)
            dcol = link_map.get(h) if h in _facade()._MONTHLY_LINKABLE_METRICS else None
            if link_detail_side_totals and detail_ws is not None and (dcol is not None):
                letter = _facade().get_column_letter(int(dcol))
                cell.value = _facade()._formula_monthly_detail_metric(
                    detail_title, letter, 1, ridx, base_r
                )
                _facade()._force_arabic_number_format(cell, None)
            else:
                cell.value = row.get(h, "")
                if h in {"请假", "旷工", "迟到", "早退"}:
                    v = row.get(h)
                    if isinstance(v, (int, float)) and (not isinstance(v, bool)):
                        _facade()._force_arabic_number_format(cell, float(v))
