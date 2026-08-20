"""HTTP routes for the deterministic top-architect employee pack."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "top-architect"
EMPLOYEE_STEM = "top_architect"
EMPLOYEE_LABEL = "顶级架构师员工"


def _resolve_mod_path(mod_id: str) -> str | None:
    """Resolve the installed pack path, with a source-tree fallback."""
    try:
        from app.mod_sdk.mods_bus import resolve_mod_directory

        mod_path = str(resolve_mod_directory(mod_id) or "")
        if mod_path and os.path.isdir(mod_path):
            return mod_path
    except (AttributeError, ImportError, OSError, RuntimeError, ValueError):
        logger.debug("mod directory resolver unavailable for %s", mod_id, exc_info=True)

    source_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return source_path if os.path.isdir(source_path) else None


def _load_employee(mod_id: str) -> Any | None:
    """Load the employee implementation through the host's isolated MOD loader."""
    from app.mod_sdk.mods_bus import import_mod_backend_py

    mod_path = _resolve_mod_path(mod_id)
    if not mod_path:
        return None
    return import_mod_backend_py(
        mod_path,
        mod_id,
        f"employees/{EMPLOYEE_STEM}",
    )


def _error(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "data": {
            "ok": False,
            "status": "failed",
            "summary": message,
            "error_code": "employee_unavailable",
            "read_only": True,
            "side_effects": [],
        },
        "error": message,
    }


async def _dispatch_run(
    mod_id: str,
    _employee_id: str,
    _stem: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Execute the deterministic reviewer and preserve the pack API envelope."""
    try:
        module = _load_employee(mod_id)
        run = getattr(module, "run", None)
        if run is None:
            return _error("top-architect employee implementation is unavailable")
        result = run(payload or {}, {"mod_id": mod_id, "employee_id": EMPLOYEE_ID})
        if asyncio.iscoroutine(result):
            result = await result
        return {"success": True, "data": result}
    except (FileNotFoundError, ImportError, RuntimeError, TypeError, ValueError) as exc:
        logger.exception("top-architect employee run failed")
        return _error(f"top-architect employee run failed: {str(exc)[:300]}")


def register_fastapi_routes(app: Any, mod_id: str) -> None:
    """Register discovery, execution, and health routes for the employee."""
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"emp-pack-{mod_id}"])

    @router.get("/employees")
    async def list_employees() -> dict[str, Any]:
        """List the deterministic architecture reviewer exposed by this pack."""
        return {
            "success": True,
            "data": [
                {
                    "id": EMPLOYEE_ID,
                    "label": EMPLOYEE_LABEL,
                    "summary": "确定性、只读的架构依赖边界审查",
                }
            ],
        }

    @router.post(f"/employees/{EMPLOYEE_ID}/run")
    async def employee_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a read-only architecture dependency review."""
        return await _dispatch_run(mod_id, EMPLOYEE_ID, EMPLOYEE_STEM, payload)

    @router.get(f"/employees/{EMPLOYEE_ID}/status")
    async def employee_status() -> dict[str, Any]:
        """Report whether the stateless reviewer is ready."""
        return {
            "success": True,
            "data": {"employee_id": EMPLOYEE_ID, "status": "ready", "read_only": True},
        }

    app.include_router(router)
    logger.info("top-architect routes registered mod_id=%s", mod_id)


def mod_init() -> None:
    """Initialize the stateless employee pack."""
    logger.info("top-architect employee pack initialized")
