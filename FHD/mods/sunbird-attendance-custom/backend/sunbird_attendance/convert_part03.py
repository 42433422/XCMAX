from __future__ import annotations

import importlib
from collections import Counter
from dataclasses import replace


def _facade():
    return importlib.import_module("sunbird_attendance.convert")


def identify_roster_records(records, roster):
    """Keep homonyms as separate blocks; ambiguous source identity fails closed."""
    counts = Counter(name for _, _, name in roster)
    display = {}
    keyed = []
    candidates = {}
    for index, (department, nature, name) in enumerate(roster):
        key = f"\u241f{index}:{name}" if counts[name] > 1 else name
        display[key] = name
        keyed.append((department, nature, key))
        candidates.setdefault(name, []).append((department, key))
    out = []
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
        out.append(replace(record, employee_name=matches[0][1]) if matches else record)
    return out, keyed, display


def restore_display_names(workbook, display):
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str) and cell.value in display:
                    cell.value = display[cell.value]
                    cell.data_type = "s"


def write_records(records, out, template, month_label, personnel_roster):
    display = {}
    if personnel_roster:
        records, personnel_roster, display = identify_roster_records(records, personnel_roster)
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
    filtered = _facade()._filter_records_to_template_roster(records, template_profiles)
    if not filtered and (not personnel_roster):
        return {
            "success": False,
            "error": "钉钉数据与模板明细中的姓名无交集：请核对模板人员名单与「每日统计」姓名列是否一致（含空格/全半角）。",
        }
    employees, analysis_rows = _facade()._aggregate_employee_records(
        filtered, template_profiles=template_profiles
    )
    monthly_rows = _facade()._build_monthly_rows_for_template(
        employees, personnel_roster, detail_ws
    )
    template_result = _facade().write_detail_sheet(workbook, employees, month_label=month_label)
    _facade().write_monthly_sheet(workbook, monthly_rows, link_detail_side_totals=True)
    _facade()._retain_detail_and_monthly_sheets(workbook)
    output_sheet_names = list(workbook.sheetnames)
    out.parent.mkdir(parents=True, exist_ok=True)
    restore_display_names(workbook, display)
    workbook.save(out)
    result = {
        "success": True,
        "output": str(out),
        "month": month_label,
        "rows_used_for_template": len(filtered),
        "rows_stats": len(analysis_rows),
        "employees_total": len(employees),
        "employees_matched": template_result.matched_employee_count,
        "unmatched_names": [display.get(n, n) for n in template_result.unmatched_employee_names],
        "personnel_roster_count": len(personnel_roster) if personnel_roster else 0,
        "output_sheet_names": output_sheet_names,
    }
    workbook.close()
    return result


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
    """把钉钉考勤导出 xlsx 转换为太阳鸟明细模板。"""
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
    _facade()._install_owner_policy()
    try:
        parsed = _facade().parse_attendance_workbook(
            src,
            month=month,
            header_row=max(0, int(header_row or 0)),
            use_llm=bool(use_llm),
        )
        result = write_records(
            parsed.records, out, template, month or parsed.month, personnel_roster
        )
        if not result.get("success"):
            return result
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
        result.update(
            input=str(src), rows_in=parsed.rows_in, header_info=header_info, used_llm=bool(use_llm)
        )
        return result
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("Attendance conversion failed")
        return {"success": False, "error": str(exc)}
    finally:
        _facade()._clear_attendance_policy()
