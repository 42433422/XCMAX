# -*- coding: utf-8 -*-
"""演示/离线兜底：修茈市场 LLM 不可用时仍给出可读的考勤助手回复。"""

from __future__ import annotations

import re

_MODSTORE_HINT = (
    "模型服务暂不可用（请确认修茈市场 MODstore 已启动，或设置 XCAGI_USE_REMOTE_MARKET=1 走官网）。"
    "您仍可使用：系统设置 → 移动端配对；智能生态 → 员工商店；导入考勤 Excel 后点快捷芯片。"
)


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def try_demo_attendance_reply(message: str | None) -> str | None:
    """匹配考勤行业常见问法；无匹配时返回通用离线说明。"""
    m = _norm(message)
    if not m:
        return None

    if re.search(r"你好|您好|在吗|hello|hi\b", m, re.I):
        return (
            "你好，我是考勤/排班助手。"
            "你可以问我：今天谁请假、今日出勤、查员工、打印考勤单等。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    if re.search(r"谁请假|请假了|请假名单|休假", m):
        return (
            "当前演示库暂无实时请假明细。"
            "请先在「员工工作台」导入考勤 Excel，或连接 MODstore 后重试在线查询。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    if re.search(r"今日出勤|今天出勤|出勤情况|谁出勤", m):
        return (
            "今日出勤需基于已导入的考勤表。"
            "请上传本月考勤 Excel 后，再说「查员工」或指定部门/工号查询。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    if re.search(r"查员工|员工信息|工号", m):
        return (
            "请提供员工工号或姓名，例如：「查询工号 1001 的出勤」。"
            "导入考勤表后可返回更完整的排班与工时。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    if re.search(r"考勤单|打印考勤|打印", m):
        return (
            "打印考勤单需先有订单/出货或考勤导出任务。"
            "可在对话中说「生成考勤单」或从右侧任务面板触发打印流程。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    if len(m) <= 48:
        return (
            f"已收到：「{m}」。在线模型暂不可用，以上为本地演示指引。"
            f"\n\n（{_MODSTORE_HINT}）"
        )

    return (
        "在线对话模型暂不可用，无法生成完整分析。"
        f"\n\n（{_MODSTORE_HINT}）"
    )


__all__ = ["try_demo_attendance_reply"]
