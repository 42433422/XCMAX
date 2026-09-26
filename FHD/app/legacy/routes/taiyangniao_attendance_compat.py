"""Host-level compatibility routes for Sunbird attendance conversion."""

from __future__ import annotations

import importlib
import logging
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.mod_sdk.attendance_artifacts import allocate_file, owner_for_request, serve_output
from app.mod_sdk.attendance_rules import attendance_rules_payload
from app.mod_sdk.customer_features import require_attendance_conversion
from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path
from app.mod_sdk.workspace import resolve_existing_workspace_file
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

MOD_ID = "taiyangniao-pro"
DEFAULT_TEMPLATE_RELPATH = "424/考勤-2026-3月份考勤统计表.xlsx"
DEFAULT_DB_NAME = "taiyangniao_pro.db"

router = APIRouter(
    prefix=f"/api/mod/{MOD_ID}",
    tags=["sunbird-attendance-compat"],
    dependencies=[Depends(require_attendance_conversion)],
)


def _candidate_mod_roots() -> list[Path]:
    roots: list[Path] = []

    def add(raw: str | os.PathLike[str] | None) -> None:
        if not raw:
            return
        try:
            p = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            return
        if p not in roots:
            roots.append(p)

    for env_name in (
        "XCAGI_MODS_ROOT",
        "XCAGI_MODS_DIR",
        "XCAGI_BUNDLED_MODS_DIR",
    ):
        add(os.environ.get(env_name))

    for env_name in ("XCAGI_DATA_DIR", "XCAGI_DESKTOP_DATA_DIR"):
        raw = (os.environ.get(env_name) or "").strip()
        if raw:
            add(Path(raw) / "mods")

    try:
        from app.desktop_runtime.paths import get_desktop_data_dir

        add(get_desktop_data_dir() / "mods")
    except RECOVERABLE_ERRORS:
        pass

    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        from app.infrastructure.mods.registry import get_mod_registry

        meta = get_mod_registry().get_mod_metadata(MOD_ID)
        if meta and meta.mod_path:
            add(Path(meta.mod_path).parent)
        resolved = get_mod_manager().resolve_mod_directory(MOD_ID)
        if resolved:
            add(Path(resolved).parent)
    except RECOVERABLE_ERRORS:
        pass

    fhd_root = Path(__file__).resolve().parents[2]
    add(fhd_root / "mods")

    cwd = Path.cwd().resolve()
    for base in [cwd, *cwd.parents[:6]]:
        add(base / "mods")

    return roots


def _ensure_sunbird_backend_on_path() -> Path | None:
    for root in _candidate_mod_roots():
        backend = root / MOD_ID / "backend"
        if (backend / "attendance_engine" / "convert.py").is_file():
            backend_str = str(backend)
            if backend_str not in sys.path:
                sys.path.insert(0, backend_str)
            return backend
    return None


def _load_convert_attendance_file() -> Callable[..., dict[str, Any]]:
    _ensure_sunbird_backend_on_path()
    module = importlib.import_module("attendance_engine.convert")
    convert_fn = module.convert_attendance_file
    if not callable(convert_fn):
        raise RuntimeError("attendance_engine.convert.convert_attendance_file 不可用")
    return cast("Callable[..., dict[str, Any]]", convert_fn)


def _load_products_personnel_roster_from_host() -> list[tuple[str, str, str]]:
    try:
        from app.db.models.product import Product
        from app.db.session import get_db
    except RECOVERABLE_ERRORS:
        return []

    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    try:
        with get_db() as db:
            q = db.query(Product).filter(Product.is_active == 1).order_by(Product.id)
            for p in q:
                name = (getattr(p, "name", None) or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                dept = (getattr(p, "unit", None) or "").strip()
                spec = (getattr(p, "specification", None) or "").strip()
                out.append((dept, spec, name))
    except RECOVERABLE_ERRORS:
        logger.exception("读取主库人员(products)失败")
        return []
    return out


def _load_products_personnel_roster(db_path: Path) -> list[tuple[str, str, str]]:
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT unit, specification, name FROM products "
            "WHERE name IS NOT NULL AND TRIM(name) != '' ORDER BY id"
        )
    except sqlite3.Error:
        conn.close()
        return []

    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for row in cur.fetchall():
        name = str(row["name"]).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        dept = str(row["unit"] or "").strip()
        nature = str(row["specification"] or "").strip()
        out.append((dept, nature, name))
    conn.close()
    return out


def _resolve_personnel_roster() -> list[tuple[str, str, str]]:
    host = _load_products_personnel_roster_from_host()
    if host:
        return host
    return _load_products_personnel_roster(resolve_mod_private_sqlite_path(DEFAULT_DB_NAME))


def _normalize_relpath(raw: str, *, field_name: str) -> str:
    rel = unquote(raw or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError(f"missing {field_name}")
    return rel


@router.get("/attendance/rules")
async def attendance_rules() -> dict[str, Any]:
    return attendance_rules_payload(DEFAULT_TEMPLATE_RELPATH, detailed=True)


@router.post("/attendance/convert-upload", response_model=None)
async def attendance_convert_upload(
    file: UploadFile = File(...),
    output_relpath: str = Form("424/考勤转换输出.xlsx"),
    template_relpath: str = Form(DEFAULT_TEMPLATE_RELPATH),
    month: str = Form(""),
    header_row: int = Form(0),
    use_llm: str = Form(""),
    use_personnel_roster: str = Form("1"),
    owner: str = Depends(owner_for_request),
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
        src_path = allocate_file(owner, "upload", suffix)
        content = await file.read()
        src_path.write_bytes(content)
    except RECOVERABLE_ERRORS:
        logger.exception("Failed to save attendance upload")
        return JSONResponse(
            {"success": False, "error": "save upload failed"},
            status_code=500,
        )

    try:
        out_path = allocate_file(owner, "output")
        out_rel = out_path.name
    except RECOVERABLE_ERRORS:
        return JSONResponse({"success": False, "error": "输出路径无效"}, status_code=400)

    raw_tpl_rel = unquote(template_relpath or "").strip()
    if raw_tpl_rel:
        if not raw_tpl_rel.replace("\\", "/").lstrip("/"):
            return JSONResponse(
                {"success": False, "error": "missing template_relpath"}, status_code=400
            )
        try:
            normalized_raw_tpl = _normalize_relpath(raw_tpl_rel, field_name="template_relpath")
        except ValueError:
            return JSONResponse(
                {"success": False, "error": "template_relpath 无效"}, status_code=400
            )
        if normalized_raw_tpl != DEFAULT_TEMPLATE_RELPATH:
            return JSONResponse(
                {"success": False, "error": f"请使用固定模板: {DEFAULT_TEMPLATE_RELPATH}"},
                status_code=400,
            )

    tpl_rel = DEFAULT_TEMPLATE_RELPATH
    try:
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
    except RECOVERABLE_ERRORS:
        return JSONResponse({"success": False, "error": "模板路径无效"}, status_code=400)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    use_llm_flag = unquote(use_llm or "").strip().lower() in {"1", "true", "yes", "on"}
    use_pr = unquote(use_personnel_roster or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    roster: list[tuple[str, str, str]] | None = None
    if use_pr:
        roster = _resolve_personnel_roster()
        if not roster:
            return JSONResponse(
                {
                    "success": False,
                    "error": "已勾选「按人员管理名单」，但主库「人员管理」与 mod 备用库均无人员。请先在侧栏「人员管理」导入或录入后再转换；或取消勾选改用模板内原名单。",
                },
                status_code=400,
            )

    try:
        convert_attendance_file = _load_convert_attendance_file()
        result = convert_attendance_file(
            str(src_path),
            str(out_path),
            template_path=str(template_path),
            month=unquote(month or "").strip() or None,
            header_row=max(0, int(header_row)),
            use_llm=use_llm_flag or None,
            personnel_roster=roster,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("Attendance conversion crashed")
        return JSONResponse(
            {"success": False, "error": "convert failed"},
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
async def attendance_download(relpath: str, owner: str = Depends(owner_for_request)):
    return serve_output(owner, relpath, legacy=True)


__all__ = ["router"]
