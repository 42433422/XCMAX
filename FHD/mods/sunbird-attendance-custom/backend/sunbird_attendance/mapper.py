# ruff: noqa: E402, F401
from __future__ import annotations

import re
import shutil
import unicodedata
from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

DETAIL_HEADER_ROWS = 3
DETAIL_PERSON_BLOCK_ROWS = 6
# 明细模板实际列可到 85+；日×2 槽约 66 列，右侧多为合计/附注，须一并清空与规范化。
DETAIL_MAX_COL = 100
# 与 ``clear_template_blocks`` 一致：左侧姓名区不参与合计。
DETAIL_SUM_COL_START = 5
# 自该列起为模板右侧符号小计（SUMIF）等，清空/写入考勤时不得覆盖。
DETAIL_TEMPLATE_SUMMARY_BEGIN_COL = 70
# 明细右侧「序号 BP—夜班 CE:CG」等与 SUMIF 区相邻列（用于快照/粘贴排除与侧栏刷新）。
DETAIL_SIDE_SUMMARY_BP_COL = 68  # 序号
DETAIL_SIDE_SUMMARY_BQ_COL = 69  # 侧栏姓名（与块内 C 列对应行）
DETAIL_SIDE_SUMMARY_CD_COL = 82  # =BQn，供夜班公式 MATCH
DETAIL_SIDE_SUMMARY_SUMIF_START_COL = 70  # BR
DETAIL_SIDE_SUMMARY_SUMIF_END_COL = 81  # CC
DETAIL_SIDE_SUMMARY_NIGHT_COLS = (83, 84, 85)  # CE, CF, CG
# 明细表内每人块首行写入「块内数字总和」的列（须避开日×2 槽：first_sym=7 时第 31 日在 67/68）。
# 模板右侧 CH（86）起在块区内多为空。
DETAIL_ONSHEET_BLOCK_TOTAL_COL = 86
# 明细含考勤格与侧栏：模板列上常见 ``[DBNum1]``，会把数字显示成中文或 ``1.`` 等怪样；先清列样式再设单元格为 ``0.0``（如 2 → 2.0）。
DETAIL_ARABIC_NUMBER_DISPLAY = "0.0"
# ``CH``（块内数字合计）：用显式小数格式避免 ``General`` 在保存后变回 ``[DBNum1]``；与考勤格一致一位小数。
DETAIL_BLOCK_TOTAL_NUMBER_DISPLAY = "0.0"
# 考勤符号整格保留，勿把「〇」等当成数字 0 改写。
_ATT_MARK: frozenset[str] = frozenset({"√", "☆", "★", "〇", "o", "O", "¤"})

_CN_BLOCK_DIGITS: dict[str, int] = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


from sunbird_attendance.mapper_part01 import DayBandEntry as DayBandEntry
from sunbird_attendance.mapper_part01 import EmployeeDayTemplateData as EmployeeDayTemplateData
from sunbird_attendance.mapper_part01 import EmployeeMonthTemplateData as EmployeeMonthTemplateData
from sunbird_attendance.mapper_part01 import TemplateEmployeeProfile as TemplateEmployeeProfile
from sunbird_attendance.mapper_part01 import TemplateWriteResult as TemplateWriteResult
from sunbird_attendance.mapper_part01 import (
    _cell_text_replace_chinese_numerals as _cell_text_replace_chinese_numerals,
)
from sunbird_attendance.mapper_part01 import (
    _chinese_block_label_to_int as _chinese_block_label_to_int,
)
from sunbird_attendance.mapper_part01 import _merge_anchor_for_cell as _merge_anchor_for_cell
from sunbird_attendance.mapper_part01 import (
    _normalize_block_chinese_numerals as _normalize_block_chinese_numerals,
)
from sunbird_attendance.mapper_part01 import (
    _normalize_chinese_numerals_in_rect as _normalize_chinese_numerals_in_rect,
)
from sunbird_attendance.mapper_part01 import _plain_cell_text as _plain_cell_text
from sunbird_attendance.mapper_part01 import (
    _replace_line_all_cn_numerals as _replace_line_all_cn_numerals,
)

_NATURE_OT_RE = re.compile(r"(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})\s*(?:记加班|加班)")
_NATURE_WORK_RE = re.compile(r"(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})\s*上班")


from sunbird_attendance.mapper_part02 import _ensure_template_workbook as _ensure_template_workbook
from sunbird_attendance.mapper_part02 import (
    _parse_profile_rules_from_nature_plain as _parse_profile_rules_from_nature_plain,
)
from sunbird_attendance.mapper_part02 import _round_display as _round_display
from sunbird_attendance.mapper_part02 import _safe_hhmm as _safe_hhmm
from sunbird_attendance.mapper_part02 import (
    _snapshot_first_person_block as _snapshot_first_person_block,
)
from sunbird_attendance.mapper_part02 import open_output_workbook as open_output_workbook

# (dr, c) 与 ``proto_vals`` 相同：dr 为块内 1..6 行，c 为列号。
BlockCellStyle = tuple[object | None, object | None, object | None]


from sunbird_attendance.mapper_part03 import _apply_style_bundle as _apply_style_bundle
from sunbird_attendance.mapper_part03 import (
    _detail_calendar_anchor_col as _detail_calendar_anchor_col,
)
from sunbird_attendance.mapper_part03 import (
    _first_attendance_symbol_col as _first_attendance_symbol_col,
)
from sunbird_attendance.mapper_part03 import (
    _force_arabic_number_format as _force_arabic_number_format,
)
from sunbird_attendance.mapper_part03 import _paste_one_person_block as _paste_one_person_block
from sunbird_attendance.mapper_part03 import (
    _snapshot_block_cell_styles as _snapshot_block_cell_styles,
)
from sunbird_attendance.mapper_part03 import (
    _strip_dbnum_column_styles as _strip_dbnum_column_styles,
)
from sunbird_attendance.mapper_part03 import _unmerge_cell_rectangle as _unmerge_cell_rectangle
from sunbird_attendance.mapper_part03 import build_template_profiles as build_template_profiles
from sunbird_attendance.mapper_part03 import clear_template_blocks as clear_template_blocks
from sunbird_attendance.mapper_part03 import find_template_base_rows as find_template_base_rows
from sunbird_attendance.mapper_part03 import (
    find_template_side_summary_rows as find_template_side_summary_rows,
)
from sunbird_attendance.mapper_part03 import (
    iter_detail_sheet_block_base_rows as iter_detail_sheet_block_base_rows,
)
from sunbird_attendance.mapper_part03 import (
    rebuild_detail_sheet_person_blocks as rebuild_detail_sheet_person_blocks,
)
from sunbird_attendance.mapper_part03 import set_template_month as set_template_month

# 月度统计可链到明细侧栏 SUMIF 的列：顺序为「更具体的文案优先」，避免「平常加班」含「正常」子串误匹配。
_DETAIL_MONTH_LINK_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("星期天加班", ("星期天加班", "周日加班", "星期天", "周日", "★")),
    ("平常加班", ("平常加班", "平时加班", "平日加班", "☆")),
    ("正常上班", ("正常上班", "正班工时", "正班", "√")),
    ("请假", ("请假", "事假", "病假", "调休", "年假", "○", "〇")),
    ("旷工", ("旷工", "¤")),
    ("迟到", ("迟到",)),
    ("早退", ("早退",)),
    ("警告", ("警告",)),
)


from sunbird_attendance.mapper_part04 import _detail_numeric_addend as _detail_numeric_addend
from sunbird_attendance.mapper_part04 import (
    _detail_side_metric_symbol_columns as _detail_side_metric_symbol_columns,
)
from sunbird_attendance.mapper_part04 import (
    _detail_side_month_link_column_map as _detail_side_month_link_column_map,
)
from sunbird_attendance.mapper_part04 import (
    _ensure_onsheet_block_total_header as _ensure_onsheet_block_total_header,
)
from sunbird_attendance.mapper_part04 import (
    _refresh_detail_side_summary_formulas as _refresh_detail_side_summary_formulas,
)
from sunbird_attendance.mapper_part04 import _reset_sheet_rows as _reset_sheet_rows
from sunbird_attendance.mapper_part04 import (
    _sum_person_block_numeric_cells as _sum_person_block_numeric_cells,
)
from sunbird_attendance.mapper_part04 import _write_entries as _write_entries
from sunbird_attendance.mapper_part04 import write_detail_sheet as write_detail_sheet

_MONTHLY_LINKABLE_METRICS: frozenset[str] = frozenset(
    {"正常上班", "平常加班", "星期天加班", "请假", "旷工", "迟到", "早退", "警告"}
)


from sunbird_attendance.mapper_part05 import _excel_quoted_sheet as _excel_quoted_sheet
from sunbird_attendance.mapper_part05 import (
    _formula_monthly_detail_metric as _formula_monthly_detail_metric,
)
from sunbird_attendance.mapper_part05 import (
    _monthly_sheet_is_roster_layout as _monthly_sheet_is_roster_layout,
)
from sunbird_attendance.mapper_part05 import (
    _scan_monthly_roster_header_row as _scan_monthly_roster_header_row,
)
from sunbird_attendance.mapper_part05 import write_analysis_sheet as write_analysis_sheet
from sunbird_attendance.mapper_part05 import write_monthly_sheet as write_monthly_sheet
