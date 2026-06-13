"""智能表头识别：把钉钉考勤导出的 ``每日统计`` / ``原始记录`` 表头
解析为"语义列名 -> 列索引"映射，本地规则失败时可选择调用 LLM 兜底。

调用方应优先依赖本地正则匹配；LLM 只作为环境变量或参数显式开启时的兜底。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


_SEMANTIC_PATTERNS: dict[str, list[str]] = {
    "employee_name": [r"^姓名$", r"^员工姓名$"],
    "attendance_group": [r"^考勤组$"],
    "department": [r"^部门$"],
    "main_department": [r"^主部门$"],
    "employee_no": [r"^工号$", r"^员工工号$", r"^员工编号$"],
    "position": [r"^职位$", r"^岗位$"],
    "user_id": [r"^UserId$", r"^userid$", r"^用户ID$"],
    "work_date": [r"^日期$", r"^考勤日期$"],
    "work_date_epoch": [r"^workDate$"],
    "shift_name": [r"^班次$"],
    "punch_time": [r"^打卡时间$", r"^考勤时间$"],
    "attendance_days": [r"^出勤天数$"],
    "rest_days": [r"^休息天数$"],
    "work_hours": [r"^工作时长$"],
    "late_count": [r"^迟到次数$"],
    "late_duration": [r"^迟到时长$"],
    "severe_late_count": [r"^严重迟到次数$"],
    "severe_late_duration": [r"^严重迟到时长$"],
    "absent_late_days": [r"^旷工迟到天数$"],
    "early_count": [r"^早退次数$"],
    "early_duration": [r"^早退时长$"],
    "miss_on_duty": [r"^上班缺卡次数$"],
    "miss_off_duty": [r"^下班缺卡次数$"],
    "absent_days": [r"^旷工天数$"],
    "business_trip_duration": [r"^出差时长$"],
    "out_duration": [r"^外出时长$"],
    "leave_group": [r"^请假$"],
    "overtime_total": [r"^加班总时长$"],
    "overtime_to_pay": [r"^加班时长（转加班费）$"],
    "overtime_to_leave": [r"^加班时长（转调休）$"],
    "approval_linked": [r"^关联的审批单$"],
}

_CLOCK_TIME_RX = re.compile(r"^(上班|下班)\d+打卡时间$")

_REQUIRED_DAILY = ("employee_name", "work_date")
_REQUIRED_RAW = ("employee_name", "work_date", "punch_time")


def _norm(text: object) -> str:
    if text is None:
        return ""
    return str(text).strip()


@dataclass
class ResolvedHeader:
    """某个 sheet 的表头解析结果。"""

    header_row: int               # 1-based
    data_start_row: int           # 1-based，首个有效数据行
    columns: dict[str, int]       # semantic_key -> 0-based col index
    clock_time_columns: list[int] # 上班N/下班N 打卡时间列，按表头顺序
    leave_columns: list[int]      # 请假 合并表头下的子列（不含 请假 自身）
    raw_header: list[str]         # 原始表头文字
    source: str                   # "local" | "llm"
    a1_text: str = ""             # 表格左上角 A1 原文（供抽取月份）

    def col(self, key: str) -> int | None:
        return self.columns.get(key)


def _match(header: list[str], patterns: list[str], used: set[int]) -> int | None:
    for pat in patterns:
        rx = re.compile(pat)
        for i, cell in enumerate(header):
            if i in used:
                continue
            if rx.search(cell):
                return i
    return None


def _scan_top_rows(ws, *, max_scan: int = 20) -> list[tuple[object, ...]]:
    """一次性读取前若干行；``read_only`` 模式下迭代器无法回头，因此各处共用。"""
    return list(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True))


def _detect_header_row_from(rows: list[tuple[object, ...]], *, hint: int = 0) -> int:
    """在预读行里找出包含 ``姓名`` 与 ``日期/考勤日期`` 的那一行。"""
    order: list[int] = []
    if hint and hint > 0:
        order.append(hint)
    order.extend(i for i in range(1, len(rows) + 1) if i not in order)

    for idx in order:
        if idx - 1 >= len(rows):
            continue
        values = [_norm(v) for v in rows[idx - 1]]
        if not values:
            continue
        has_name = any(v == "姓名" or v == "员工姓名" for v in values[:12])
        has_date = any(v in ("日期", "考勤日期") for v in values[:20])
        if has_name and has_date:
            return idx
    raise ValueError("未能在前若干行内找到考勤表表头（需要同时包含 ‘姓名’ 与 ‘日期/考勤日期’）")


def _compute_leave_columns(header: list[str], leave_start: int) -> list[int]:
    """``请假`` 是合并单元格的上层标签，其下方的子列在 openpyxl 读表头时是 None/空。
    收集 ``leave_start`` 之后的连续空表头列。"""
    cols: list[int] = []
    i = leave_start + 1
    while i < len(header):
        if header[i]:
            break
        cols.append(i)
        i += 1
    return cols


def _try_local_resolve(
    header: list[str],
    *,
    required_keys: tuple[str, ...],
) -> tuple[dict[str, int], set[int]]:
    columns: dict[str, int] = {}
    used: set[int] = set()

    md = _match(header, _SEMANTIC_PATTERNS["main_department"], used)
    if md is not None:
        columns["main_department"] = md
        used.add(md)

    for key, pats in _SEMANTIC_PATTERNS.items():
        if key == "main_department":
            continue
        idx = _match(header, pats, used)
        if idx is not None:
            columns[key] = idx
            used.add(idx)

    return columns, used


def _peek_data_start(
    rows: list[tuple[object, ...]],
    header_row: int,
    *,
    name_col: int | None = 0,
) -> int:
    """表头后如果紧跟一行"非数据行"（全空行，或首列为空的二级子表头，比如钉钉
    请假子项/加班子项的标签），把数据起点前移一行。"""
    data_start = header_row + 1
    if data_start - 1 < len(rows):
        peek = rows[data_start - 1]
        fully_empty = all(_norm(v) == "" for v in peek)
        # 二级子表头：行首姓名列为空，但在中后段有若干文字（如 ‘事假(小时)’）
        name_idx = 0 if name_col is None else name_col
        leading_empty = (
            name_idx < len(peek) and _norm(peek[name_idx]) == ""
        )
        if fully_empty or leading_empty:
            data_start += 1
    return data_start


def resolve_daily_stats_header(
    ws,
    *,
    hint_header_row: int = 0,
    use_llm: bool = False,
) -> ResolvedHeader:
    top_rows = _scan_top_rows(ws)
    header_row = _detect_header_row_from(top_rows, hint=hint_header_row)
    header = [_norm(c) for c in top_rows[header_row - 1]]

    columns, used = _try_local_resolve(header, required_keys=_REQUIRED_DAILY)

    clock_cols = [i for i, v in enumerate(header) if _CLOCK_TIME_RX.match(v)]

    leave_cols: list[int] = []
    if "leave_group" in columns:
        leave_cols = _compute_leave_columns(header, columns["leave_group"])

    missing = [k for k in _REQUIRED_DAILY if k not in columns]
    source = "local"
    if missing and use_llm:
        llm_map = _llm_resolve_columns(header, missing=missing)
        for k, v in llm_map.items():
            if k in columns or v in used:
                continue
            columns[k] = v
            used.add(v)
        missing = [k for k in _REQUIRED_DAILY if k not in columns]
        if not missing:
            source = "llm"

    if missing:
        raise ValueError(
            f"每日统计 表头未识别必需列 {missing}；表头原文: {header}"
        )

    a1_text = _norm(top_rows[0][0]) if top_rows and top_rows[0] else ""

    return ResolvedHeader(
        header_row=header_row,
        data_start_row=_peek_data_start(
            top_rows, header_row, name_col=columns.get("employee_name", 0)
        ),
        columns=columns,
        clock_time_columns=clock_cols,
        leave_columns=leave_cols,
        raw_header=header,
        source=source,
        a1_text=a1_text,
    )


def resolve_raw_records_header(
    ws,
    *,
    hint_header_row: int = 0,
    use_llm: bool = False,
) -> ResolvedHeader:
    top_rows = _scan_top_rows(ws)
    header_row = _detect_header_row_from(top_rows, hint=hint_header_row)
    header = [_norm(c) for c in top_rows[header_row - 1]]

    columns, used = _try_local_resolve(header, required_keys=_REQUIRED_RAW)

    missing = [k for k in _REQUIRED_RAW if k not in columns]
    source = "local"
    if missing and use_llm:
        llm_map = _llm_resolve_columns(header, missing=missing)
        for k, v in llm_map.items():
            if k in columns or v in used:
                continue
            columns[k] = v
            used.add(v)
        missing = [k for k in _REQUIRED_RAW if k not in columns]
        if not missing:
            source = "llm"

    if missing:
        raise ValueError(
            f"原始记录 表头未识别必需列 {missing}；表头原文: {header}"
        )

    a1_text = _norm(top_rows[0][0]) if top_rows and top_rows[0] else ""

    return ResolvedHeader(
        header_row=header_row,
        data_start_row=_peek_data_start(
            top_rows, header_row, name_col=columns.get("employee_name", 0)
        ),
        columns=columns,
        clock_time_columns=[],
        leave_columns=[],
        raw_header=header,
        source=source,
        a1_text=a1_text,
    )


def llm_enabled_by_env() -> bool:
    """读取 ``FHD_ATTENDANCE_LLM`` 环境变量决定默认是否调 LLM 兜底。"""
    flag = (os.environ.get("FHD_ATTENDANCE_LLM") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _llm_resolve_columns(header: list[str], *, missing: list[str]) -> dict[str, int]:
    """调用项目配置的 LLM（OpenAI 兼容客户端）把未识别的语义键定位到列索引。

    任何失败都静默返回 ``{}``，不让业务流程爆炸。
    """
    try:
        from app.infrastructure.llm.client import get_llm_client, resolve_chat_model
    except Exception as exc:
        logger.info("attendance LLM resolver unavailable (import failed): %s", exc)
        return {}

    try:
        client = get_llm_client()
    except Exception as exc:
        logger.info("attendance LLM resolver unavailable (no credentials): %s", exc)
        return {}
    if client is None:
        return {}

    numbered_header = "\n".join(f"{i}: {cell or '(空)'}" for i, cell in enumerate(header))
    if len(numbered_header) > 2000:
        raise ValueError(
            f"表头列数过多（{len(header)} 列，约 {len(numbered_header)} 字符），"
            "超出 LLM 处理上限。请在前端填写「表头所在行」或减少列数后重试。"
        )
    descriptions = {
        "employee_name": "员工姓名",
        "attendance_group": "考勤组名称",
        "department": "部门",
        "main_department": "主部门（钉钉新版特有）",
        "employee_no": "工号",
        "position": "职位/岗位",
        "user_id": "钉钉 UserId",
        "work_date": "考勤日期（形如 2025-09-01 或 25-09-01 星期一）",
        "work_date_epoch": "workDate 毫秒时间戳",
        "shift_name": "班次名称",
        "punch_time": "打卡时间",
    }
    wanted = {k: descriptions.get(k, k) for k in missing}
    system_msg = (
        "你是考勤表表头识别助手。输入是 Excel 某一行的表头列表，格式为 ‘col_index: header_text’。"
        "请把每个请求的语义键映射到对应的列索引（整数，从 0 开始）。"
        "未能确认的键请直接省略。只输出严格合法的 JSON 对象，例如 {\"employee_name\": 0, \"work_date\": 7}。"
        "不要输出任何额外文字或解释。"
    )
    user_msg = (
        f"表头列表:\n{numbered_header}\n\n"
        f"需要定位的语义键:\n{json.dumps(wanted, ensure_ascii=False, indent=2)}"
    )
    if len(user_msg) > 4000:
        raise ValueError(
            f"LLM 请求体过大（{len(user_msg)} 字符），请减少列数或拆分处理。"
        )

    try:
        resp = client.chat.completions.create(
            model=resolve_chat_model(),
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
        data = json.loads(content or "{}")
    except Exception as exc:
        logger.warning("attendance LLM column resolver failed: %s", exc)
        return {}

    result: dict[str, int] = {}
    for k, v in data.items() if isinstance(data, dict) else []:
        try:
            idx = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(header):
            result[k] = idx
    return result


__all__ = [
    "ResolvedHeader",
    "resolve_daily_stats_header",
    "resolve_raw_records_header",
    "llm_enabled_by_env",
]
