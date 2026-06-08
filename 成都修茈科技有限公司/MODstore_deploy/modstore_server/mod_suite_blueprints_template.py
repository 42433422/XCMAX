# -*- coding: utf-8 -*-
"""多员工 Mod 套件 FastAPI blueprints 模板（替代 Flask 占位）。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _employee_stem(emp_id: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", (emp_id or "").strip().lower())
    if s and s[0].isdigit():
        s = "e_" + s
    return s or "emp"


def render_suite_blueprints_py(mod_id: str, mod_name: str, employees: List[Dict[str, Any]]) -> str:
    """生成可被 scan_fastapi_router_routes 扫描的 FastAPI 套件路由。"""
    rows: List[Dict[str, str]] = []
    for item in employees or []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or "").strip()
        if not eid:
            continue
        rows.append(
            {
                "id": eid,
                "stem": _employee_stem(eid),
                "label": str(item.get("label") or item.get("panel_title") or eid)[:256],
            }
        )
    employees_lit = json.dumps(rows, ensure_ascii=False)
    mod_lit = json.dumps(mod_id, ensure_ascii=False)
    name_lit = json.dumps(mod_name or mod_id, ensure_ascii=False)

    per_emp_routes: List[str] = []
    for row in rows:
        eid = row["id"]
        stem = row["stem"]
        eid_lit = json.dumps(eid, ensure_ascii=False)
        stem_lit = json.dumps(stem, ensure_ascii=False)
        fn = re.sub(r"[^a-z0-9_]", "_", stem)
        per_emp_routes.append(
            f"    @router.post('/employees/' + {eid_lit} + '/run')\n"
            f"    async def emp_run_{fn}(payload: Dict[str, Any] | None = None):\n"
            f"        return await _dispatch_run(mod_id, {eid_lit}, {stem_lit}, payload)\n\n"
            f"    @router.get('/employees/' + {eid_lit} + '/status')\n"
            f"    async def emp_status_{fn}():\n"
            f"        return {{'success': True, 'data': {{'employee_id': {eid_lit}, 'status': 'ready'}}}}\n"
        )
    routes_block = (
        "\n".join(per_emp_routes) if per_emp_routes else "    pass  # no workflow employees\n"
    )

    return (
        '"""Auto-generated FastAPI blueprints for Mod suite (MODstore)."""\n'
        "from __future__ import annotations\n\n"
        "import asyncio\n"
        "import json\n"
        "import logging\n"
        "import os\n"
        "from typing import Any, Dict, List, Optional\n\n"
        "from fastapi import APIRouter\n\n"
        "logger = logging.getLogger(__name__)\n\n"
        f"MOD_ID = {mod_lit}\n"
        f"MOD_NAME = {name_lit}\n"
        f"EMPLOYEES: List[Dict[str, str]] = json.loads({json.dumps(employees_lit)})\n\n\n"
        "def _resolve_mod_path(mod_id: str) -> Optional[str]:\n"
        "    try:\n"
        "        from app.infrastructure.mods import get_mod_registry  # type: ignore\n\n"
        "        meta = get_mod_registry().get_mod_metadata(mod_id)\n"
        "        mp = getattr(meta, 'mod_path', '') or ''\n"
        "        if mp and os.path.isdir(mp):\n"
        "            return mp\n"
        "    except Exception:\n"
        "        pass\n"
        "    here = os.path.dirname(os.path.abspath(__file__))\n"
        "    guess = os.path.dirname(here)\n"
        "    return guess if os.path.isdir(guess) else None\n\n\n"
        "def _load_employee_module(mod_id: str, stem: str):\n"
        "    try:\n"
        "        from app.mod_sdk.mods_bus import import_mod_backend_py  # type: ignore\n"
        "    except ImportError:\n"
        "        return None\n"
        "    mod_path = _resolve_mod_path(mod_id)\n"
        "    if not mod_path:\n"
        "        return None\n"
        "    try:\n"
        '        return import_mod_backend_py(mod_path, mod_id, f"employees/{stem}")\n'
        "    except Exception:\n"
        "        logger.exception('load employee module failed stem=%s', stem)\n"
        "        return None\n\n\n"
        "def _unified_err(msg: str, **meta):\n"
        "    return {\n"
        "        'success': False,\n"
        "        'data': {'ok': False, 'summary': msg[:400], 'items': [], 'warnings': [], 'error': msg[:1000], 'meta': meta},\n"
        "        'error': msg[:500],\n"
        "    }\n\n\n"
        "async def _build_run_context(mod_id: str, emp_id: str) -> Dict[str, Any]:\n"
        "    ctx: Dict[str, Any] = {\n"
        "        'mod_id': mod_id,\n"
        "        'employee_id': emp_id,\n"
        "        'logger': logging.getLogger(f'mod.{mod_id}.emp.{emp_id}'),\n"
        "    }\n"
        "    try:\n"
        "        from app.mod_sdk.mod_employee_llm import mod_employee_complete  # type: ignore\n\n"
        "        async def _call_llm(messages, *, max_tokens=1024, temperature=0.2, response_format=None):\n"
        "            return await mod_employee_complete(\n"
        "                messages, max_tokens=max_tokens, temperature=temperature, response_format=response_format\n"
        "            )\n\n"
        "        ctx['call_llm'] = _call_llm\n"
        "    except Exception as exc:\n"
        "        logger.warning('mod_employee_complete unavailable: %s', exc)\n\n"
        "        async def _call_llm_disabled(messages, **kwargs):\n"
        "            return {'ok': False, 'content': '', 'error': '宿主 LLM 不可用'}\n\n"
        "        ctx['call_llm'] = _call_llm_disabled\n"
        "    return ctx\n\n\n"
        "async def _dispatch_run(mod_id: str, emp_id: str, stem: str, payload: Optional[Dict[str, Any]]):\n"
        "    module = _load_employee_module(mod_id, stem)\n"
        "    if module is None or not hasattr(module, 'run'):\n"
        "        return _unified_err(\n"
        "            'employee module not loaded：请确认 backend/employees 下存在对应 .py 并实现 async def run',\n"
        "            employee_id=emp_id,\n"
        "            stem=stem,\n"
        "        )\n"
        "    ctx = await _build_run_context(mod_id, emp_id)\n"
        "    try:\n"
        "        out = module.run(payload or {}, ctx)\n"
        "        if asyncio.iscoroutine(out):\n"
        "            out = await out\n"
        "        return {'success': True, 'data': out}\n"
        "    except Exception as exc:\n"
        "        logger.exception('employee run failed')\n"
        "        return _unified_err('employee run failed: ' + str(exc)[:300], employee_id=emp_id)\n\n\n"
        "def register_fastapi_routes(app, mod_id: str) -> None:\n"
        '    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"mod-suite-{mod_id}"])\n\n'
        "    @router.get('/health')\n"
        "    async def health():\n"
        "        return {\n"
        "            'success': True,\n"
        "            'data': {\n"
        "                'ok': True,\n"
        "                'mod_id': mod_id,\n"
        "                'mod_name': MOD_NAME,\n"
        "                'employees': [e.get('id') for e in EMPLOYEES],\n"
        "            },\n"
        "        }\n\n"
        "    @router.get('/employees')\n"
        "    async def list_employees():\n"
        "        return {\n"
        "            'success': True,\n"
        "            'data': [\n"
        "                {'id': e['id'], 'label': e.get('label') or e['id'], 'stem': e.get('stem') or e['id']}\n"
        "                for e in EMPLOYEES\n"
        "            ],\n"
        "        }\n\n"
        f"{routes_block}\n"
        "    app.include_router(router)\n"
        '    logger.info("Mod suite FastAPI routes registered: %s (%d employees)", mod_id, len(EMPLOYEES))\n\n\n'
        "def mod_init():\n"
        '    logger.info("Mod suite backend init: %s", MOD_ID)\n'
    )
