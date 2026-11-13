"""Interpret an employee block as its attendance and overtime policy."""

from __future__ import annotations

import unicodedata
from datetime import time

from .attendance_models import TemplateEmployeeProfile
from .template_cells import _plain_cell_text
from .template_layout import iter_detail_sheet_block_base_rows
from .template_schema import _NATURE_OT_RE, _NATURE_WORK_RE


def _safe_hhmm(h: int, m: int) -> time | None:
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    return None


def _parse_profile_rules_from_nature_plain(
    nature_plain: str,
) -> tuple[time, tuple[float, float, float, float], time | None]:
    """从明细 B 列（规格/备注）纯文本解析：加班起算点、上午块、自定义上班点。"""
    overtime_start = time(18, 0)
    block_values: tuple[float, float, float, float] = (2.0, 2.0, 2.0, 2.0)
    morning_work_start: time | None = None
    for m in _NATURE_OT_RE.finditer(nature_plain):
        t = _safe_hhmm(int(m.group("h")), int(m.group("m")))
        if t is not None:
            overtime_start = t
    wm = _NATURE_WORK_RE.search(nature_plain)
    if wm:
        t = _safe_hhmm(int(wm.group("h")), int(wm.group("m")))
        if t is not None:
            morning_work_start = t
            block_values = (1.0, 2.0, 2.0, 2.0)
    elif "09:00" in nature_plain:
        morning_work_start = time(9, 0)
        block_values = (1.0, 2.0, 2.0, 2.0)
    return (overtime_start, block_values, morning_work_start)


def build_template_profiles(ws) -> dict[str, TemplateEmployeeProfile]:
    profiles: dict[str, TemplateEmployeeProfile] = {}
    for base_row in iter_detail_sheet_block_base_rows(ws):
        name = ws.cell(base_row, 3).value
        if name in (None, ""):
            continue
        employee_name = str(name).strip()
        nature_raw = ws.cell(base_row, 2).value
        nature_plain = unicodedata.normalize("NFKC", _plain_cell_text(nature_raw)).strip()
        overtime_start, block_values, morning_work_start = _parse_profile_rules_from_nature_plain(
            nature_plain
        )
        profiles[employee_name] = TemplateEmployeeProfile(
            employee_name=employee_name,
            base_row=base_row,
            department=str(ws.cell(base_row, 1).value or "").strip(),
            nature_text=nature_plain,
            block_values=block_values,
            overtime_start=overtime_start,
            morning_work_start=morning_work_start,
        )
    return profiles
