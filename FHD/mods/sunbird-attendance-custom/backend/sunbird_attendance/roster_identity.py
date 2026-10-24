"""Match same-name employees by department without changing their display names."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .parser import AttendanceDayRecord

PersonnelRoster = list[tuple[str, str, str]]


def identify_roster_records(
    records: list[AttendanceDayRecord], roster: PersonnelRoster
) -> tuple[list[AttendanceDayRecord], PersonnelRoster, dict[str, str]]:
    """Keep homonyms separate; reject sources that cannot establish an identity."""
    counts = Counter(name for _, _, name in roster)
    display: dict[str, str] = {}
    keyed: PersonnelRoster = []
    candidates: dict[str, list[tuple[str, str]]] = {}
    for index, (department, nature, name) in enumerate(roster):
        key = f"\u241f{index}:{name}" if counts[name] > 1 else name
        display[key] = name
        keyed.append((department, nature, key))
        candidates.setdefault(name, []).append((department, key))
    matched_records = []
    for record in records:
        matches = candidates.get(record.employee_name, [])
        if len(matches) > 1:
            if record.raw_times:
                raise ValueError("同名人员的原始打卡记录缺少唯一身份，请使用可按部门区分的每日统计")
            matches = [(dept, key) for dept, key in matches if dept == record.department]
            if len(matches) != 1:
                raise ValueError(
                    f"同名人员 {record.employee_name} 无法按部门唯一匹配，请核对名单和考勤源文件"
                )
        matched_records.append(replace(record, employee_name=matches[0][1]) if matches else record)
    return matched_records, keyed, display


def restore_display_names(workbook: Workbook, display: dict[str, str]) -> None:
    for sheet in workbook:
        if isinstance(sheet, Worksheet):
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value, str) and cell.value in display:
                        cell.value = display[cell.value]
                        cell.data_type = "s"
