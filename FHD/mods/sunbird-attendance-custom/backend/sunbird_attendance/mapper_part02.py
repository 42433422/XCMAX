"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.mapper")


def _safe_hhmm(h: int, m: int) -> _facade().time | None:
    if 0 <= h <= 23 and 0 <= m <= 59:
        return _facade().time(h, m)
    return None


def _parse_profile_rules_from_nature_plain(
    nature_plain: str,
) -> tuple[_facade().time, tuple[float, float, float, float], _facade().time | None]:
    """从明细 B 列（规格/备注）纯文本解析：加班起算点、上午块、自定义上班点。"""
    overtime_start = _facade().time(18, 0)
    block_values: tuple[float, float, float, float] = (2.0, 2.0, 2.0, 2.0)
    morning_work_start: _facade().time | None = None
    for m in _facade()._NATURE_OT_RE.finditer(nature_plain):
        t = _facade()._safe_hhmm(int(m.group("h")), int(m.group("m")))
        if t is not None:
            overtime_start = t
    wm = _facade()._NATURE_WORK_RE.search(nature_plain)
    if wm:
        t = _facade()._safe_hhmm(int(wm.group("h")), int(wm.group("m")))
        if t is not None:
            morning_work_start = t
            block_values = (1.0, 2.0, 2.0, 2.0)
    elif "09:00" in nature_plain:
        morning_work_start = _facade().time(9, 0)
        block_values = (1.0, 2.0, 2.0, 2.0)
    return (overtime_start, block_values, morning_work_start)


def _round_display(value: float) -> float:
    """一律保留一位小数的 float（如 2.0），避免整数在列格式下被显示成 ``2.``。"""
    return round(float(value), 1)


def _ensure_template_workbook(
    output_path: _facade().Path, template_path: _facade().Path | None = None
):
    if template_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if template_path.resolve() != output_path.resolve():
            _facade().shutil.copy2(template_path, output_path)
            return _facade().load_workbook(output_path)
    if output_path.exists():
        return _facade().load_workbook(output_path)
    wb = _facade().Workbook()
    ws = wb.active
    ws.title = "明细"
    ws["A1"] = "未提供模板，已生成基础明细页"
    return wb


def open_output_workbook(output_path: _facade().Path, template_path: _facade().Path | None = None):
    return _facade()._ensure_template_workbook(output_path, template_path)


def _snapshot_first_person_block(
    ws, block_top: int
) -> tuple[dict[tuple[int, int], object], list[tuple[int, int, int, int]]]:
    """复制首个人员块（6 行）的单元格值与合并区域（相对块内行 1-6）。

    不含 ``DETAIL_TEMPLATE_SUMMARY_BEGIN_COL`` 及以右列，避免每人块粘贴时覆盖侧栏 SUMIF/夜班公式。
    """
    cap = _facade().DETAIL_TEMPLATE_SUMMARY_BEGIN_COL - 1
    vals: dict[tuple[int, int], object] = {}
    for dr in range(_facade().DETAIL_PERSON_BLOCK_ROWS):
        for c in range(1, cap + 1):
            vals[dr + 1, c] = ws.cell(block_top + dr, c).value
    rel_merges: list[tuple[int, int, int, int]] = []
    for rng in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = _facade().range_boundaries(str(rng))
        if (
            min_row >= block_top
            and max_row <= block_top + _facade().DETAIL_PERSON_BLOCK_ROWS - 1
            and (min_col >= 1)
            and (max_col <= cap)
        ):
            rel_merges.append((min_col, min_row - block_top + 1, max_col, max_row - block_top + 1))
    return (vals, rel_merges)
