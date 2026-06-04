"""Employee pack 统一分发入口（含可选子进程隔离）。"""

from __future__ import annotations

from typing import Any, Callable

from app.mod_sdk.employee_run_isolation import maybe_run_employee_in_subprocess


async def try_subprocess_dispatch(
    mod_id: str,
    emp_id: str,
    stem: str,
    payload: dict[str, Any] | None,
    resolve_mod_path: Callable[[str], str | None],
) -> dict[str, Any] | None:
    """若启用 ``XCAGI_MOD_EMPLOYEE_SUBPROCESS`` 则返回 API 响应；否则 ``None`` 走同进程逻辑。"""
    return await maybe_run_employee_in_subprocess(
        mod_id=mod_id,
        emp_id=emp_id,
        stem=stem,
        payload=payload,
        resolve_mod_path=resolve_mod_path,
    )
