"""跨行业通用考勤模块 FastAPI 入口。"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)


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
    attendance_routes.register(router)
    _load_local_module("management_routes").register(
        router, logger=logger, get_database_path=get_database_path
    )
    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("Mod %s unified attendance routes registered", mod_id)


def mod_init():
    logger.info("Mod attendance-industry initialized")
