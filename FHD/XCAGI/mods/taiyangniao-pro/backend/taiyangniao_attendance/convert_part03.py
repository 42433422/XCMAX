"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("taiyangniao_attendance.convert")


def convert_attendance_file(
    input_path: str,
    output_path: str | None = None,
    *,
    template_path: str | None = None,
    month: str | None = None,
    header_row: int = 0,
    use_llm: bool | None = None,
    personnel_roster: list[tuple[str, str, str]] | None = None,
) -> dict[str, _facade().Any]:
    """把钉钉考勤导出 xlsx 转换为太阳鸟明细模板。

    ``header_row`` 是用户在前端填写的表头所在行（1-based），``0`` 代表自动识别。
    ``use_llm`` 为真时允许在本地规则无法识别必需列时调用 LLM 兜底；
    ``None`` 代表尊重环境变量 ``FHD_ATTENDANCE_LLM``。
    """
    from .header_resolver import llm_enabled_by_env

    if use_llm is None:
        use_llm = llm_enabled_by_env()
    src = _facade().Path(input_path)
    if not src.exists():
        return {"success": False, "error": "input file not found"}
    out = (
        _facade().Path(output_path) if output_path else src.with_name(src.stem + "_converted.xlsx")
    )
    template = _facade().Path(template_path) if template_path else out if out.exists() else None
    try:
        parsed = _facade().parse_attendance_workbook(
            src, month=month, header_row=max(0, int(header_row or 0)), use_llm=bool(use_llm)
        )
        workbook = _facade().open_output_workbook(out, template)
        detail_ws = workbook["明细"] if "明细" in workbook.sheetnames else workbook.active
        if personnel_roster:
            _facade().rebuild_detail_sheet_person_blocks(detail_ws, personnel_roster)
        template_profiles = _facade().build_template_profiles(detail_ws)
        if not template_profiles:
            return {
                "success": False,
                "error": "明细页未解析到任何员工块，请检查固定模板或人员管理名单",
            }
        filtered = _facade()._filter_records_to_template_roster(parsed.records, template_profiles)
        if not filtered and (not personnel_roster):
            return {
                "success": False,
                "error": "钉钉数据与模板明细中的姓名无交集：请核对模板人员名单与「每日统计」姓名列是否一致（含空格/全半角）。",
            }
        (employees, analysis_rows) = _facade()._aggregate_employee_records(
            filtered, template_profiles=template_profiles
        )
        monthly_rows = _facade()._build_monthly_rows_for_template(
            employees, personnel_roster, detail_ws
        )
        template_result = _facade().write_detail_sheet(
            workbook, employees, month_label=month or parsed.month
        )
        _facade().write_monthly_sheet(workbook, monthly_rows, link_detail_side_totals=True)
        _facade()._retain_detail_and_monthly_sheets(workbook)
        output_sheet_names = list(workbook.sheetnames)
        out.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(out)
        workbook.close()
        daily_header = parsed.daily_header
        header_info: dict[str, _facade().Any] | None = None
        if daily_header is not None:
            header_info = {
                "header_row": daily_header.header_row,
                "data_start_row": daily_header.data_start_row,
                "source": daily_header.source,
                "columns": daily_header.columns,
                "clock_time_columns": daily_header.clock_time_columns,
                "leave_columns": daily_header.leave_columns,
            }
        return {
            "success": True,
            "input": str(src),
            "output": str(out),
            "month": month or parsed.month,
            "rows_in": parsed.rows_in,
            "rows_used_for_template": len(filtered),
            "rows_stats": len(analysis_rows),
            "employees_total": len(employees),
            "employees_matched": template_result.matched_employee_count,
            "unmatched_names": template_result.unmatched_employee_names,
            "header_info": header_info,
            "used_llm": bool(use_llm),
            "personnel_roster_count": len(personnel_roster) if personnel_roster else 0,
            "output_sheet_names": output_sheet_names,
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("Attendance conversion failed")
        return {"success": False, "error": str(exc)}
    finally:
        _facade()._clear_attendance_policy()
