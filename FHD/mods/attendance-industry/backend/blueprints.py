"""跨行业通用考勤模块 FastAPI 入口。"""

from __future__ import annotations

import importlib.util
import logging
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE_RELPATH = "424/考勤-2026-3月份考勤统计表.xlsx"


def _resolve_personnel_roster(db_path: Path, owner: str = "") -> list[tuple[str, str, str]]:
    """The managed owner roster is authoritative, including an empty roster."""
    import sqlite3

    from app.mod_sdk.attendance_roster import ordered_employee_rows

    try:
        from .owner_scope import migrate_owner_column
    except ImportError:
        from owner_scope import migrate_owner_column
    if not owner or not db_path.is_file():
        return []
    migrate_owner_column(db_path)
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='attendance_employees'"
        ).fetchone():
            return []
        conn.row_factory = sqlite3.Row
        return [
            (r["department"], r["position"], r["employee_name"])
            for r in ordered_employee_rows(conn, owner)
            if str(r["employee_name"] or "").strip()
        ]


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
