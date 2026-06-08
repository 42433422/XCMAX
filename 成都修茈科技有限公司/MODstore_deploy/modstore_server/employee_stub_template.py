"""员工 FastAPI 占位路由模板（workflow 脚手架与 employee_pack zip 共用）。"""

from __future__ import annotations

import re

_EMP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _sanitize_py_module(emp_id: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


def safe_stub_module_name(emp_id: str) -> str:
    """与 workflow_employee_scaffold 的 safe_mod 一致：``e_`` + 净化后的员工 id。"""
    return "e_" + _sanitize_py_module(emp_id)


def stub_module_body(emp_id: str, safe_mod: str) -> str:
    """与 workflow_employee_scaffold 生成物一致（safe_mod 须已含 e_ 前缀且为合法模块名）。"""
    return (
        f'"""Auto-generated stub for workflow employee `{emp_id}` (MODstore scaffold)."""\n\n'
        "from __future__ import annotations\n\n"
        "import logging\n\n"
        "from fastapi import APIRouter\n\n"
        "logger = logging.getLogger(__name__)\n\n\n"
        "def mount_employee_router(app, mod_id: str) -> None:\n"
        '    """在宿主 ``register_fastapi_routes`` 中挂载本员工占位 API。"""\n'
        f'    prefix = f"/api/mod/{{mod_id}}/emp/{emp_id}"\n'
        f'    r = APIRouter(prefix=prefix, tags=[f"mod-{{mod_id}}-emp-{emp_id}"])\n\n'
        '    @r.get("/status")\n'
        "    async def _status():\n"
        "        return {\n"
        '            "ok": True,\n'
        f'            "employee_id": "{emp_id}",\n'
        '            "mod_id": mod_id,\n'
        '            "message": "占位路由：请在此文件实现真实业务逻辑。",\n'
        "        }\n\n"
        "    app.include_router(r)\n"
        f'    logger.info("Mounted employee stub router: %s emp={emp_id}", mod_id)\n'
    )


def validate_employee_id_for_stub(emp_id: str) -> bool:
    return bool(_EMP_ID_RE.match((emp_id or "").strip()))
