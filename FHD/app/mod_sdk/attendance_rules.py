"""Shared response for the legacy and installed attendance route families."""

from __future__ import annotations


def attendance_rules_payload(template_relpath: str, *, detailed: bool = False) -> dict:
    schedule_lines = [
        "周一到周六：正班固定 08:00-12:00 / 13:30-17:30",
        "晚上：18:00 后按最后一次打卡计加班",
        "周日：全部按星期天加班处理",
    ]
    groups = [
        {
            "name": name,
            "headcount": "按导出表统计",
            "shift_type": "固定班制",
            "lines": schedule_lines,
        }
        for name in ("公司-考勤 / 公司正班", "惠州工厂-正班 / 工厂正班")
    ]
    behavior = (
        "固定模板版式；勾选按人员管理名单时用 products 重排明细，钉钉按名回填，无则空"
        if detailed
        else "固定模板版式；按人员管理名单重排明细，钉钉按名回填，无则空"
    )
    return {
        "success": True,
        "data": {
            "lines": [
                "优先读取钉钉「每日统计」，再用「原始记录」补充打卡时间与去重。",
                "重复打卡按上午/下午/晚上分段去重，优先保留每段的有效边界打卡。",
                "目标文件会在固定模板基础上回填「明细」工作表。",
                "周一到周六正班固定为 08:00-12:00、13:30-17:30；周日算加班。",
            ],
            "saturday_window_label": "13:30 - 16:00",
            "config": {
                "default_header_row": 0,
                "default_output_relpath": "424/考勤转换输出.xlsx",
                "accepted_extensions": [".xlsx", ".xlsm", ".xls"],
                "allow_template_append": True,
                "default_template_relpath": template_relpath,
                "default_template_behavior": behavior,
            },
            "schedule_groups": groups,
        },
    }
