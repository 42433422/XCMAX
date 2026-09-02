"""跨行业通用考勤模块 FastAPI 路由。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi import File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.mod_sdk.errors import BOUNDARY_ERRORS
from app.mod_sdk.host_services import workspace_root


def register(
    router,
    *,
    logger,
    get_database_path,
    DEFAULT_TEMPLATE_RELPATH,
    _normalize_relpath,
    _resolve_personnel_roster,
) -> None:
    """在给定 router 上注册 /attendance/*、/employees、/departments 路由。"""
    # 考勤转换的实现放在 mod 私有包 ``taiyangniao_attendance/``
    # （被 mod_manager 加到 sys.path 的 ``backend/`` 可直接绝对 import）。
    from taiyangniao_attendance.convert import convert_attendance_file

    @router.get("/attendance/policy", response_model=None)
    async def attendance_policy_get() -> dict:
        """通用考勤裁窗配置（读写 approval_config.yaml 的 attendance_policy 段）。"""
        try:
            from resources.config.approval_config import get_approval_config

            pol = getattr(get_approval_config(), "attendance_policy", None) or {}
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            logger.exception("读取考勤策略失败")
            return JSONResponse(
                {"success": False, "message": "读取考勤策略失败"},
                status_code=500,
            )
        return {"success": True, "attendance_policy": pol}

    @router.post("/attendance/policy", response_model=None)
    async def attendance_policy_post(body: dict) -> dict:
        payload = body if isinstance(body, dict) else {}
        raw = payload.get("attendance_policy")
        if not isinstance(raw, dict):
            return JSONResponse(
                {"success": False, "message": "请提供 attendance_policy 对象"},
                status_code=400,
            )
        try:
            from resources.config.approval_config import (
                get_approval_config,
                normalize_attendance_policy,
                reload_approval_config,
            )

            config = get_approval_config()
            config.attendance_policy = normalize_attendance_policy(raw)
            config.save()
            reload_approval_config()
            return {
                "success": True,
                "message": "考勤规则已保存",
                "attendance_policy": config.attendance_policy,
            }
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            logger.exception("保存考勤策略失败")
            return JSONResponse(
                {"success": False, "message": "保存考勤策略失败"},
                status_code=500,
            )

    @router.get("/attendance/rules")
    async def attendance_rules() -> dict:
        lines = [
            "优先读取钉钉「每日统计」，再用「原始记录」补充打卡时间与去重。",
            "重复打卡按上午/下午/晚上分段去重，优先保留每段的有效边界打卡。",
            "目标文件会在固定模板基础上回填「明细」工作表。",
            "周一到周六正班固定为 08:00-12:00、13:30-17:30；周日算加班。",
        ]
        config = {
            "default_header_row": 0,
            "default_output_relpath": "424/考勤转换输出.xlsx",
            "accepted_extensions": [".xlsx", ".xlsm", ".xls"],
            "allow_template_append": True,
            "default_template_relpath": DEFAULT_TEMPLATE_RELPATH,
            "default_template_behavior": "固定模板版式；勾选按人员管理名单时用 products 重排明细，钉钉按名回填，无则空",
        }
        schedule_groups = [
            {
                "name": "公司-考勤 / 公司正班",
                "headcount": "按导出表统计",
                "shift_type": "固定班制",
                "lines": [
                    "周一到周六：正班固定 08:00-12:00 / 13:30-17:30",
                    "晚上：18:00 后按最后一次打卡计加班",
                    "周日：全部按星期天加班处理",
                ],
            },
            {
                "name": "惠州工厂-正班 / 工厂正班",
                "headcount": "按导出表统计",
                "shift_type": "固定班制",
                "lines": [
                    "周一到周六：正班固定 08:00-12:00 / 13:30-17:30",
                    "晚上：18:00 后按最后一次打卡计加班",
                    "周日：全部按星期天加班处理",
                ],
            },
        ]
        return {
            "success": True,
            "data": {
                "lines": lines,
                "saturday_window_label": "13:30 - 16:00",
                "config": config,
                "schedule_groups": schedule_groups,
            },
        }

    @router.post("/attendance/convert-upload", response_model=None)
    async def attendance_convert_upload(
        file: UploadFile = File(...),
        output_relpath: str = Form("424/考勤转换输出.xlsx"),
        template_relpath: str = Form(DEFAULT_TEMPLATE_RELPATH),
        month: str = Form(""),
        header_row: int = Form(0),
        use_llm: str = Form(""),
        use_personnel_roster: str = Form("1"),
    ):
        if not file.filename:
            return JSONResponse(
                {"success": False, "error": "missing file name"},
                status_code=400,
            )
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".xlsx", ".xlsm", ".xls"}:
            return JSONResponse(
                {"success": False, "error": "unsupported file type"},
                status_code=400,
            )

        _ = output_relpath

        try:
            from app.mod_sdk.workspace import allocate_generated_workspace_file

            upload_kind = {
                ".xlsx": "attendance-upload-xlsx",
                ".xlsm": "attendance-upload-xlsm",
                ".xls": "attendance-upload-xls",
            }[suffix]
            src_path = allocate_generated_workspace_file(upload_kind)
            content = await file.read()
            with src_path.open("wb") as f:
                f.write(content)
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            logger.exception("Failed to save attendance upload")
            return JSONResponse(
                {"success": False, "error": "保存上传文件失败"},
                status_code=500,
            )

        try:
            from app.mod_sdk.workspace import allocate_generated_workspace_file

            out_path = allocate_generated_workspace_file("attendance-output")
            out_rel = out_path.relative_to(workspace_root()).as_posix()
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            return JSONResponse({"success": False, "error": "输出路径无效"}, status_code=400)

        raw_tpl_rel = unquote(template_relpath or "").strip()
        if raw_tpl_rel:
            try:
                normalized_raw_tpl = _normalize_relpath(raw_tpl_rel, field_name="template_relpath")
            except ValueError:
                return JSONResponse({"success": False, "error": "模板路径无效"}, status_code=400)
            if normalized_raw_tpl != DEFAULT_TEMPLATE_RELPATH:
                return JSONResponse(
                    {"success": False, "error": f"请使用固定模板: {DEFAULT_TEMPLATE_RELPATH}"},
                    status_code=400,
                )

        tpl_rel = DEFAULT_TEMPLATE_RELPATH
        try:
            from app.mod_sdk.workspace import resolve_existing_workspace_file

            template_path = resolve_existing_workspace_file(tpl_rel)
            if not template_path.exists():
                return JSONResponse(
                    {"success": False, "error": f"模板文件不存在: {tpl_rel}"},
                    status_code=400,
                )
            if not template_path.is_file():
                return JSONResponse(
                    {"success": False, "error": f"模板路径不是文件: {tpl_rel}"},
                    status_code=400,
                )
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            return JSONResponse({"success": False, "error": "模板文件无效"}, status_code=400)

        out_path.parent.mkdir(parents=True, exist_ok=True)

        use_llm_flag = (unquote(use_llm or "").strip().lower()) in (
            "1",
            "true",
            "yes",
            "on",
        )
        use_pr = (unquote(use_personnel_roster or "").strip().lower()) in (
            "1",
            "true",
            "yes",
            "on",
        )
        roster: list[tuple[str, str, str]] | None = None
        if use_pr:
            roster = _resolve_personnel_roster(get_database_path())
            if not roster:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "已勾选「按人员管理名单」，但主库「人员管理」与 mod 备用库均无人员。请先在侧栏「人员管理」导入或录入后再转换；或取消勾选改用模板内原名单。",
                    },
                    status_code=400,
                )

        try:
            result = convert_attendance_file(
                str(src_path),
                str(out_path),
                template_path=str(template_path),
                month=unquote(month or "").strip() or None,
                header_row=max(0, int(header_row)),
                use_llm=use_llm_flag or None,  # None -> 交给 env 开关决定
                personnel_roster=roster,
            )
        except BOUNDARY_ERRORS:
            logger.exception("Attendance conversion crashed")
            return JSONResponse(
                {"success": False, "error": "考勤转换失败"},
                status_code=500,
            )
        if not result.get("success"):
            return JSONResponse(
                {"success": False, "error": str(result.get("error") or "convert failed")},
                status_code=400,
            )

        rows_in = int(result.get("rows_in") or 0)
        rows_stats = int(result.get("rows_stats") or 0)
        if rows_in == 0:
            header_info = result.get("header_info") or {}
            msg = (
                "未从 ‘每日统计’ 工作表中解析到任何数据行。"
                "通常原因是表头行号与实际不符，或必需列缺失。"
                "可尝试：1) 填写正确的 ‘表头所在行’；2) 勾选 ‘启用 LLM 智能识别表头’ 重试。"
            )
            return JSONResponse(
                {
                    "success": False,
                    "error": msg,
                    "data": {
                        "rows_in": 0,
                        "rows_stats": rows_stats,
                        "header_info": header_info,
                        "used_llm": bool(result.get("used_llm")),
                    },
                },
                status_code=422,
            )

        src_display = result.get("input") or str(src_path)
        out_display = result.get("output") or str(out_path)
        mon = result.get("month") or unquote(month or "").strip()
        return {
            "success": True,
            "data": {
                "input_path": src_display,
                "output_path": out_display,
                "output_relpath": out_rel,
                "rows_in": rows_in,
                "rows_used_for_template": int(result.get("rows_used_for_template") or 0),
                "personnel_roster_count": int(result.get("personnel_roster_count") or 0),
                "rows_stats": rows_stats,
                "template_relpath": tpl_rel,
                "month": mon,
                "header_row": max(0, int(header_row)),
                "employees_total": int(result.get("employees_total") or 0),
                "employees_matched": int(result.get("employees_matched") or 0),
                "unmatched_names": result.get("unmatched_names") or [],
                "header_info": result.get("header_info"),
                "used_llm": bool(result.get("used_llm")),
                "output_sheet_names": result.get("output_sheet_names") or [],
            },
        }

    @router.get("/attendance/download", response_model=None)
    async def attendance_download(relpath: str):
        try:
            rel = _normalize_relpath(relpath, field_name="relpath")
            from app.mod_sdk.workspace import resolve_existing_workspace_file

            p = resolve_existing_workspace_file(rel)
        except ValueError:
            return JSONResponse({"success": False, "error": "下载路径无效"}, status_code=400)
        except BOUNDARY_ERRORS:  # noqa: BLE001 - route boundary returns a generic error
            return JSONResponse({"success": False, "error": "下载路径无效"}, status_code=400)

        if not p.exists() or not p.is_file():
            return JSONResponse({"success": False, "error": "file not found"}, status_code=404)

        return FileResponse(path=str(p), filename=p.name, media_type="application/octet-stream")

    @router.get("/employees", response_model=None)
    async def list_employees(page: int = 1, page_size: int = 50, search: str = ""):
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{search}%"
        cur.execute(
            "SELECT COUNT(*) FROM attendance_employees WHERE employee_name LIKE ? OR department LIKE ?",
            (like, like),
        )
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT id, employee_name, department, main_department, attendance_group, employee_no, position, user_id "
            "FROM attendance_employees WHERE employee_name LIKE ? OR department LIKE ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (like, like, page_size, offset),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "success": True,
            "data": {"items": items, "total": total, "page": page, "page_size": page_size},
        }

    @router.get("/departments", response_model=None)
    async def list_departments(page: int = 1, page_size: int = 50, search: str = ""):
        import sqlite3

        db_path = get_database_path()
        if not db_path.exists():
            return {
                "success": True,
                "data": {"items": [], "total": 0, "page": page, "page_size": page_size},
            }
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        like = f"%{search}%"
        cur.execute(
            "SELECT COUNT(*) FROM attendance_departments WHERE department LIKE ? OR main_department LIKE ?",
            (like, like),
        )
        total = cur.fetchone()[0]
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT id, department, main_department, attendance_group "
            "FROM attendance_departments WHERE department LIKE ? OR main_department LIKE ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (like, like, page_size, offset),
        )
        items = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {
            "success": True,
            "data": {"items": items, "total": total, "page": page, "page_size": page_size},
        }
