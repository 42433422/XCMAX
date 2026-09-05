"""跨行业通用考勤模块 FastAPI 入口。"""

from __future__ import annotations

import importlib.util
import logging
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter

from app.mod_sdk.errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE_RELPATH = "424/考勤-2026-3月份考勤统计表.xlsx"


def _load_products_personnel_roster_from_host() -> list[tuple[str, str, str]]:
    """读取统一宿主的人员表，转换不再依赖太阳鸟私有库。"""
    try:
        from app.mod_sdk.host_services import Product, get_db
    except RECOVERABLE_ERRORS:
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    try:
        with get_db() as db:
            rows = db.query(Product).filter(Product.is_active == 1).order_by(Product.id)
            for row in rows:
                name = str(getattr(row, "name", "") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(
                    (
                        str(getattr(row, "unit", "") or "").strip(),
                        str(getattr(row, "specification", "") or "").strip(),
                        name,
                    )
                )
    except RECOVERABLE_ERRORS:
        logger.exception("读取统一人员表失败")
        return []
    return out


def _load_private_roster(db_path: Path) -> list[tuple[str, str, str]]:
    """兼容尚未迁入主库的统一考勤侧库花名册。"""
    import sqlite3

    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT unit, specification, name FROM products "
            "WHERE name IS NOT NULL AND TRIM(name) != '' ORDER BY id"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return []
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for row in rows:
        name = str(row["name"] or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(
            (
                str(row["unit"] or "").strip(),
                str(row["specification"] or "").strip(),
                name,
            )
        )
    conn.close()
    return out


def _resolve_personnel_roster(db_path: Path) -> list[tuple[str, str, str]]:
    """与独立人员管理同源；已维护的空名单也不能回退复活旧人员。"""
    import sqlite3

    if db_path.is_file():
        with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attendance_employees'"
            ).fetchone()
            if exists:
                rows = conn.execute(
                    "SELECT department, position, employee_name FROM attendance_employees "
                    "WHERE TRIM(employee_name) <> '' ORDER BY id"
                ).fetchall()
                seen: set[str] = set()
                roster: list[tuple[str, str, str]] = []
                for department, position, employee_name in rows:
                    name = str(employee_name or "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        roster.append(
                            (str(department or "").strip(), str(position or "").strip(), name)
                        )
                return roster
    return _load_products_personnel_roster_from_host() or _load_private_roster(db_path)


def _normalize_relpath(raw: str, *, field_name: str) -> str:
    rel = unquote(raw or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError(f"missing {field_name}")
    return rel


def _load_local_module(stem: str):
    backend = Path(__file__).resolve().parent
    backend_text = str(backend)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    path = backend / f"{stem}.py"
    module_name = f"xcagi_attendance_industry_{stem}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load attendance module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def register_fastapi_routes(app, mod_id: str) -> None:
    try:
        from .database import get_database_path
    except ImportError:
        _load_local_module("database")
        from database import get_database_path

    router = APIRouter(tags=[f"mod-{mod_id}"])

    @router.get("/status")
    async def status() -> dict:
        return {
            "success": True,
            "mod_id": mod_id,
            "message": "attendance-industry unified attendance system",
        }

    attendance_routes = _load_local_module("attendance_routes")
    attendance_routes.register(
        router,
        logger=logger,
        get_database_path=get_database_path,
        DEFAULT_TEMPLATE_RELPATH=DEFAULT_TEMPLATE_RELPATH,
        _normalize_relpath=_normalize_relpath,
        _resolve_personnel_roster=_resolve_personnel_roster,
    )
    _load_local_module("management_routes").register(
        router, logger=logger, get_database_path=get_database_path
    )
    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("Mod %s unified attendance routes registered", mod_id)


def mod_init():
    logger.info("Mod attendance-industry initialized")
