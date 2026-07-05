"""employee_pack HTTP facade."""

from __future__ import annotations

from fastapi import APIRouter

EMPLOYEE_ID = "avatar-generation-employee"
LABEL = "头像生成员"


def mod_init(app):
    router = APIRouter()

    @router.post("/employees/avatar-generation-employee/run")
    async def run_avatar_generation(payload: dict | None = None):
        from backend.employees.avatar_generation_employee import run

        result = await run(payload or {}, {"employee_id": EMPLOYEE_ID})
        return {"success": bool(result.get("ok")), "data": result, "error": result.get("error", "")}

    app.include_router(router)
    return {"ok": True, "employee_id": EMPLOYEE_ID, "label": LABEL}
