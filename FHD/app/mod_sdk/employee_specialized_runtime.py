"""Runtime helpers for employee specialized tools."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

_FACADE_MODULE = "app.mod_sdk.employee_specialized_tools"


def _facade_attr(name: str, default: Any) -> Any:
    """Read monkeypatched symbol from facade module when present."""
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is None:
        return default
    return mod.__dict__.get(name, default)

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_FHD_ROOT = Path(__file__).resolve().parents[2]  # .../FHD
_SCRIPTS = _FHD_ROOT / "scripts"
_VENV_PYTHON = str(_FHD_ROOT / ".venv" / "bin" / "python")
_PYTHON = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable
_EMPLOYEES_DIR = _FHD_ROOT / "mods" / "_employees"
_DUTY_ROSTER = _FHD_ROOT / "config" / "duty_roster.json"

# 本机 API base（executor 注入的 ctx 可覆盖）
_DEFAULT_API_BASE = os.environ.get("XCAGI_EMPLOYEE_API_BASE", "http://127.0.0.1:5102")

# subprocess 超时（秒）
_DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 工具结果构造
# ---------------------------------------------------------------------------


def _ok(summary: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "summary": summary[:4000]}
    out.update(extra)
    return out


def _err(error: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error[:1000]}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# subprocess 执行器
# ---------------------------------------------------------------------------


async def _run_cmd(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """执行命令并返回结构化结果。"""
    override = _facade_attr("_run_cmd", None)
    if override is not None and override is not _run_cmd:
        return await override(args, cwd=cwd, timeout=timeout, env=env)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "ok": proc.returncode == 0,
        }
    except TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"timeout after {timeout}s", "ok": False}
    except FileNotFoundError as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc), "ok": False}
    except Exception as exc:  # noqa: BLE001  工具执行边界：任何异常都转为结构化结果
        return {"returncode": -1, "stdout": "", "stderr": repr(exc), "ok": False}


async def _run_python_script(script: str | Path, *extra_args: str, **kw: Any) -> dict[str, Any]:
    """用项目 venv python 跑一个脚本。"""
    return await _run_cmd([_PYTHON, str(script), *extra_args], **kw)


# ---------------------------------------------------------------------------
# httpx 内部 API 调用
# ---------------------------------------------------------------------------


async def _api_call(
    method: str, path: str, *, api_base: str | None = None, **kw: Any
) -> dict[str, Any]:
    override = _facade_attr("_api_call", None)
    if override is not None and override is not _api_call:
        return await override(method, path, api_base=api_base, **kw)
    hx = _facade_attr("httpx", httpx)
    if hx is None:
        return {"ok": False, "error": "httpx 未安装"}
    base = (api_base or _facade_attr("_DEFAULT_API_BASE", _DEFAULT_API_BASE)).rstrip("/")
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        async with hx.AsyncClient(timeout=kw.pop("timeout", 30)) as client:
            resp = await client.request(method, url, **kw)
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001  JSON 解析失败时降级为文本
                body = resp.text
            return {"ok": resp.is_success, "status": resp.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001  API 调用边界：网络/解析异常转结构化结果
        return {"ok": False, "error": repr(exc)}

