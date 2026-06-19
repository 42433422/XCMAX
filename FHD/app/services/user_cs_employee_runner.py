"""Shared runner for the user customer-service employee pack."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EMPLOYEE_MOD_ID = "user-customer-service-officer"
EMPLOYEE_STEM = "user_customer_service_officer"


def _resolve_employee_mod_path() -> str:
    try:
        from app.infrastructure.mods import get_mod_registry  # type: ignore

        meta = get_mod_registry().get_mod_metadata(EMPLOYEE_MOD_ID)
        mod_path = getattr(meta, "mod_path", "") if meta else ""
        if mod_path and os.path.isdir(mod_path):
            return str(mod_path)
    except (ImportError, AttributeError, OSError):
        logger.debug("user-cs employee registry lookup failed", exc_info=True)

    repo_guess = Path(__file__).resolve().parents[2] / "mods" / "_employees" / EMPLOYEE_MOD_ID
    if repo_guess.is_dir():
        return str(repo_guess)
    return ""


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
        return await value
    return value


async def run_user_cs_employee(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the same employee pack used by the enterprise customer-service bridge."""

    try:
        from app.mod_sdk.mods_bus import import_mod_backend_py  # type: ignore

        mod_path = _resolve_employee_mod_path()
        if not mod_path:
            return {
                "success": False,
                "error": "user-customer-service-officer 未安装",
                "data": {
                    "ok": False,
                    "error": "请确认 mods/_employees/user-customer-service-officer 已安装并在岗",
                },
            }

        blueprints = import_mod_backend_py(mod_path, EMPLOYEE_MOD_ID, "blueprints")
        dispatch = getattr(blueprints, "_dispatch_run", None) if blueprints else None
        if callable(dispatch):
            return await _maybe_await(
                dispatch(EMPLOYEE_MOD_ID, EMPLOYEE_MOD_ID, EMPLOYEE_STEM, payload or {})
            )

        employee = import_mod_backend_py(
            mod_path,
            EMPLOYEE_MOD_ID,
            f"employees/{EMPLOYEE_STEM}",
        )
        run = getattr(employee, "run", None) if employee else None
        if callable(run):
            out = await _maybe_await(run(payload or {}, {}))
            return {"success": True, "data": out}
    except Exception as exc:
        logger.exception("user-cs employee run failed")
        return {
            "success": False,
            "error": str(exc)[:500],
            "data": {"ok": False, "error": str(exc)[:500]},
        }

    return {
        "success": False,
        "error": "user-customer-service-officer 未安装",
        "data": {
            "ok": False,
            "error": "请确认 mods/_employees/user-customer-service-officer 已安装并在岗",
        },
    }
