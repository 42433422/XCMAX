"""太阳鸟 PRO — FastAPI 路由入口（考勤等）；无 Flask 依赖。

路由实现按域拆分至同目录子模块（attendance_routes / product_routes / customer_routes），
由本文件以唯一模块名加载并注册到同一个 router，注册顺序与拆分前一致（行为零变更）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter

from app.mod_sdk.errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE_RELPATH = "424/考勤-2026-3月份考勤统计表.xlsx"


def _load_products_personnel_roster_from_host() -> list[tuple[str, str, str]]:
    """主应用「人员管理」同一套 Product 表（model 为 app.db.models.product.Product）。"""
    try:
        from app.mod_sdk.host_services import Product, get_db
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - optional host models may be unavailable
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


def _resolve_personnel_roster(db_path: Path) -> list[tuple[str, str, str]]:
    host = _load_products_personnel_roster_from_host()
    if host:
        return host
    return _load_products_personnel_roster(db_path)


def _load_products_personnel_roster(db_path: Path) -> list[tuple[str, str, str]]:
    """侧栏「人员管理」对应 ``products`` 表：(部门/单位列, 规格/性质列, 姓名)，按 id 顺序、姓名去重。"""
    import sqlite3

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


def _normalize_relpath(raw: str, *, field_name: str) -> str:
    rel = unquote(raw or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError(f"missing {field_name}")
    return rel


def _load_backend_submodule(stem: str):
    """以唯一模块名加载同目录 ``backend/<stem>.py``（与 import_mod_backend_py 同策略，避免 sys.modules 冲突）。"""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parent / f"{stem}.py"
    spec_name = f"{__name__}.{stem}"
    existing = sys.modules.get(spec_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(spec_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load mod backend submodule: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec_name] = module
    spec.loader.exec_module(module)
    return module


def register_fastapi_routes(app, mod_id: str) -> None:
    """在 FastAPI 上注册示例 hello 与考勤接口。"""
    # import_mod_backend_py 以独立模块名加载本文件时无包上下文，相对导入会失败。
    try:
        from .database import get_database_path
    except ImportError:
        import sys
        from pathlib import Path

        _backend_dir = str(Path(__file__).resolve().parent)
        if _backend_dir not in sys.path:
            sys.path.insert(0, _backend_dir)
        from database import get_database_path

    # 拆分出的路由子模块与本文件同目录，按唯一模块名加载。
    attendance_routes = _load_backend_submodule("attendance_routes")
    product_routes = _load_backend_submodule("product_routes")
    customer_routes = _load_backend_submodule("customer_routes")

    router = APIRouter(tags=[f"mod-{mod_id}"])

    @router.get("/hello")
    async def hello():
        return {
            "success": True,
            "data": {"message": f"Hello from {mod_id}", "mod": "taiyangniao-pro"},
        }

    # 注册顺序即路由匹配顺序：attendance → products → customers，与拆分前逐字一致。
    attendance_routes.register(
        router,
        logger=logger,
        get_database_path=get_database_path,
        DEFAULT_TEMPLATE_RELPATH=DEFAULT_TEMPLATE_RELPATH,
        _normalize_relpath=_normalize_relpath,
        _resolve_personnel_roster=_resolve_personnel_roster,
    )
    product_routes.register(router, get_database_path=get_database_path)
    customer_routes.register(
        router,
        logger=logger,
        get_database_path=get_database_path,
        _load_products_personnel_roster_from_host=_load_products_personnel_roster_from_host,
    )

    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info(
        "Mod %s FastAPI routes: /api/mods/%s/* and /api/mod/%s/*",
        mod_id,
        mod_id,
        mod_id,
    )


def mod_init():
    logger.info("Mod taiyangniao-pro initialized")
