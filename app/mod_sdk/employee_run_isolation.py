"""
Employee ``run()`` 可选进程级隔离（子进程，非 Docker）。

默认与宿主同进程（``import_mod_backend_py``）。设置 ``XCAGI_MOD_EMPLOYEE_SUBPROCESS=1`` 时，
通过 ``python -m app.mod_sdk._employee_subprocess_worker`` 在独立进程中执行 **同步** ``run()``；
不提供 ``call_llm`` / HTTP 等宿主能力（见 ``docs/SECURITY_MOD_TRUST_BOUNDARY.md``）。

容器级隔离请使用 ``docker/MOD_SANDBOX.md`` 中的 ``xcagi-mod-sandbox`` 镜像。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


def employee_subprocess_enabled() -> bool:
    return (os.environ.get("XCAGI_MOD_EMPLOYEE_SUBPROCESS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _subprocess_timeout() -> float:
    try:
        return float(os.environ.get("XCAGI_MOD_EMPLOYEE_SUBPROCESS_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def run_employee_in_subprocess(
    *,
    mod_path: str,
    mod_id: str,
    stem: str,
    employee_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """在子进程中执行 employee run（同步）。返回统一 success/data 结构。"""
    job = {
        "mod_path": mod_path,
        "mod_id": mod_id,
        "stem": stem,
        "employee_id": employee_id,
        "payload": payload or {},
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if k.startswith(
            (
                "PATH",
                "PYTHON",
                "LC_",
                "LANG",
                "XCAGI_",
                "FHD_",
                "DATABASE_URL",
                "VECTOR_DB_URL",
            )
        )
        or k in ("HOME", "USER", "TMPDIR", "TEMP", "TMP")
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.mod_sdk._employee_subprocess_worker"],
            input=json.dumps(job, ensure_ascii=False, default=str).encode("utf-8"),
            capture_output=True,
            timeout=_subprocess_timeout(),
            env=env,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"employee subprocess timeout ({_subprocess_timeout():.0f}s)",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:500]}

    stdout = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")[:500]
        return {
            "success": False,
            "error": stderr or f"subprocess exit {proc.returncode}",
        }
    try:
        body = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError:
        return {"success": False, "error": f"invalid subprocess output: {stdout[:300]}"}

    if not body.get("ok"):
        return {"success": False, "error": str(body.get("error") or "subprocess run failed")[:500]}
    return {"success": True, "data": body.get("data")}


async def maybe_run_employee_in_subprocess(
    *,
    mod_id: str,
    emp_id: str,
    stem: str,
    payload: dict[str, Any] | None,
    resolve_mod_path: Callable[[str], str | None],
) -> dict[str, Any] | None:
    """若启用子进程隔离则执行并返回 API 响应 dict；否则返回 None 由调用方走同进程逻辑。"""
    if not employee_subprocess_enabled():
        return None
    mod_path = resolve_mod_path(mod_id)
    if not mod_path:
        return {
            "success": False,
            "error": "mod path not found for subprocess isolation",
        }
    result = await asyncio.to_thread(
        run_employee_in_subprocess,
        mod_path=mod_path,
        mod_id=mod_id,
        stem=stem,
        employee_id=emp_id,
        payload=payload,
    )
    if result.get("success"):
        return {"success": True, "data": result.get("data")}
    return {
        "success": False,
        "data": {
            "ok": False,
            "summary": str(result.get("error") or "subprocess failed")[:400],
            "items": [],
            "warnings": [],
            "error": str(result.get("error") or "")[:1000],
            "meta": {"employee_id": emp_id, "stem": stem, "subprocess": True},
        },
        "error": str(result.get("error") or "")[:500],
    }
