"""
子进程执行 employee ``run()``（由 ``employee_run_isolation`` 启动）。

通过 stdin 读取 JSON：``mod_path``, ``mod_id``, ``stem``, ``payload``, ``employee_id``。
stdout 输出 JSON：``{ "ok": true, "data": ... }`` 或 ``{ "ok": false, "error": "..." }``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _minimal_ctx(mod_id: str, employee_id: str) -> dict[str, Any]:
    return {
        "mod_id": mod_id,
        "employee_id": employee_id,
        "logger": logging.getLogger(f"mod.{mod_id}.emp.{employee_id}.subprocess"),
        "call_llm": None,
        "http_get": None,
        "http_post": None,
        "secrets": None,
        "subprocess_isolated": True,
    }


def _run_job(req: dict[str, Any]) -> dict[str, Any]:
    mod_path = str(req.get("mod_path") or "")
    mod_id = str(req.get("mod_id") or "")
    stem = str(req.get("stem") or "")
    employee_id = str(req.get("employee_id") or stem)
    payload = req.get("payload") if isinstance(req.get("payload"), dict) else {}

    if not mod_path or not mod_id or not stem:
        return {"ok": False, "error": "missing mod_path/mod_id/stem"}

    try:
        from app.infrastructure.mods.mod_manager import import_mod_backend_py

        module = import_mod_backend_py(mod_path, mod_id, f"employees/{stem}")
    except Exception as exc:
        return {"ok": False, "error": f"import failed: {exc}"[:500]}

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return {"ok": False, "error": "employee module has no run()"}

    ctx = _minimal_ctx(mod_id, employee_id)
    try:
        out = run_fn(payload, ctx)
        if asyncio.iscoroutine(out):
            return {
                "ok": False,
                "error": "async run() not supported in subprocess mode; disable XCAGI_MOD_EMPLOYEE_SUBPROCESS",
            }
        return {"ok": True, "data": out}
    except Exception as exc:
        logger.exception("employee subprocess run failed")
        return {"ok": False, "error": str(exc)[:500]}


def main() -> int:
    try:
        raw = sys.stdin.read()
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"invalid stdin json: {exc}"}))
        return 1

    result = _run_job(req if isinstance(req, dict) else {})
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
