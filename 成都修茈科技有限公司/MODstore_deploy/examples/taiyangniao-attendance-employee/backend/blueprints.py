"""太阳鸟考勤员 employee_pack HTTP 面。"""
from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "taiyangniao-attendance"
EMPLOYEE_LABEL = "太阳鸟考勤员"
STEM = "taiyangniao_attendance"


def _unified_err(msg: str, **meta):
    return {
        "success": False,
        "data": {
            "ok": False,
            "summary": msg[:400],
            "items": [],
            "warnings": [],
            "error": msg[:1000],
            "meta": meta,
        },
        "error": msg[:500],
    }


def _load_employee_module():
    try:
        return importlib.import_module(f"employees.{STEM}")
    except Exception:
        logger.exception("load employee module failed stem=%s", STEM)
        return None


async def _dispatch_run(mod_id: str, payload: Optional[Dict[str, Any]]):
    module = _load_employee_module()
    if module is None or not hasattr(module, "run"):
        return _unified_err(
            "employee module not loaded：请确认 backend/employees/taiyangniao_attendance.py 存在并实现 async def run",
            employee_id=EMPLOYEE_ID,
            stem=STEM,
        )

    ctx: Dict[str, Any] = {
        "mod_id": mod_id,
        "employee_id": EMPLOYEE_ID,
        "logger": logging.getLogger(f"mod.{mod_id}.emp.{EMPLOYEE_ID}"),
        "call_llm": None,
        "http_get": None,
        "http_post": None,
        "host_base_url": "",
    }

    try:
        import httpx

        async def _http_get(url, *, headers=None, timeout=30):
            try:
                async with httpx.AsyncClient(timeout=float(timeout)) as client:
                    res = await client.get(url, headers=headers or {})
                return {
                    "ok": res.status_code < 400,
                    "status": res.status_code,
                    "text": res.text,
                    "error": "" if res.status_code < 400 else res.text[:500],
                }
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "status": 0, "text": "", "error": str(exc)[:500]}

        ctx["http_get"] = _http_get
    except ImportError:
        logger.warning("httpx 不可用，规则读取和上传会由员工实现返回明确错误")

    try:
        run_fn = getattr(module, "run")
        out = run_fn(payload or {}, ctx)
        if asyncio.iscoroutine(out):
            out = await out
        return {"success": True, "data": out}
    except Exception as exc:  # noqa: BLE001
        logger.exception("employee run failed")
        return _unified_err("employee run failed: " + str(exc)[:300], employee_id=EMPLOYEE_ID)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"emp-pack-{mod_id}"])

    @router.get("/employees")
    async def list_employees():
        return {
            "success": True,
            "data": [
                {
                    "id": EMPLOYEE_ID,
                    "label": EMPLOYEE_LABEL,
                    "summary": "上传钉钉考勤表，调用 taiyangniao-pro 完成考勤转换。",
                }
            ],
        }

    @router.post("/employees/" + EMPLOYEE_ID + "/run")
    async def emp_run(payload: Dict[str, Any] | None = None):
        return await _dispatch_run(mod_id, payload)

    @router.get("/employees/" + EMPLOYEE_ID + "/status")
    async def emp_status():
        return {
            "success": True,
            "data": {
                "employee_id": EMPLOYEE_ID,
                "label": EMPLOYEE_LABEL,
                "status": "ready",
                "source_mod_id": "taiyangniao-pro",
            },
        }

    app.include_router(router)
    logger.info("taiyangniao attendance employee routes registered mod_id=%s", mod_id)


def mod_init():
    logger.info("taiyangniao attendance employee backend init")
