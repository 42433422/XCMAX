"""Column and row contracts of the customer-owned attendance template."""

from __future__ import annotations

import re

DETAIL_HEADER_ROWS = 3

DETAIL_PERSON_BLOCK_ROWS = 6

DETAIL_MAX_COL = 100

DETAIL_SUM_COL_START = 5

DETAIL_TEMPLATE_SUMMARY_BEGIN_COL = 70

DETAIL_SIDE_SUMMARY_BP_COL = 68

DETAIL_SIDE_SUMMARY_BQ_COL = 69

DETAIL_SIDE_SUMMARY_CD_COL = 82

DETAIL_SIDE_SUMMARY_SUMIF_START_COL = 70

DETAIL_SIDE_SUMMARY_SUMIF_END_COL = 81

DETAIL_SIDE_SUMMARY_NIGHT_COLS = (83, 84, 85)

DETAIL_ONSHEET_BLOCK_TOTAL_COL = 86

DETAIL_ARABIC_NUMBER_DISPLAY = "0.0"

DETAIL_BLOCK_TOTAL_NUMBER_DISPLAY = "0.0"

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

_NATURE_OT_RE = re.compile(r"(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})\s*(?:记加班|加班)")

_NATURE_WORK_RE = re.compile(r"(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})\s*上班")

BlockCellStyle = tuple[object | None, object | None, object | None]

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

_MONTHLY_LINKABLE_METRICS: frozenset[str] = frozenset(
    {"正常上班", "平常加班", "星期天加班", "请假", "旷工", "迟到", "早退", "警告"}
)
