"""沙箱执行器：组合 RPC 主机 + 子进程 + 资源限制 + 结果收集。

每次跑脚本都会建一个新的临时工作目录（含 ``inputs/``、``outputs/``、
``modstore_runtime/``、``script.py``），子进程 ``cwd`` 锁到该目录，
``MODSTORE_RUNTIME_PORT`` / ``MODSTORE_RUNTIME_TOKEN`` 通过 env 注入。

返回 :class:`SandboxResult`，外层（``workbench_script_runner`` 或
``script_agent.agent_loop``）据此决定是否进入修复轮。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional

from modstore_server.script_agent.sandbox_host import (
    SandboxHostContext,
    SandboxRpcServer,
)
from modstore_server.script_agent.sandbox_preamble import PREAMBLE_SOURCE

logger = logging.getLogger(__name__)
_DEGRADED_WARNED = False


def _warn_degraded_once() -> None:
    """非 POSIX（如 Windows 开发机）上 RLIMIT 不生效，整机部署应走 Linux。"""
    global _DEGRADED_WARNED
    if _DEGRADED_WARNED or os.name == "posix":
        return
    _DEGRADED_WARNED = True
    logger.warning(
        "[sandbox] running on non-POSIX (%s) — RLIMIT_CPU/AS/FSIZE 不可用，"
        "仅靠 wall-clock timeout + AST 拦截 + preamble FS/网络边界。"
        "生产请部署到 Linux 以启用资源限制。",
        os.name,
    )


SCRIPT_ROOT = Path(__file__).resolve().parent.parent / "workbench_script_runs"

DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_OUTPUT_FILE_LIMIT_BYTES = 50 * 1024 * 1024
DEFAULT_TOTAL_OUTPUT_LIMIT_BYTES = 200 * 1024 * 1024
STDOUT_TAIL_BYTES = 16_000
STDERR_TAIL_BYTES = 16_000


@dataclass
class SandboxResult:
    ok: bool
    work_dir: str
    returncode: int
    stdout: str
    stderr: str
    outputs: List[Dict[str, Any]]
    errors: List[str]
    timed_out: bool
    sdk_calls: List[Dict[str, Any]] = field(default_factory=list)


def _runtime_sdk_source() -> Path:
    return Path(__file__).resolve().parent / "runtime_sdk" / "__init__.py"


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.\-\u4e00-\u9fff]+", "_", name or "file")
    return s.strip("._")[:120] or "file"


def _prepare_work_dir(session_id: str, *, script_root: Path) -> Path:
    script_root.mkdir(parents=True, exist_ok=True)
    safe_id = _safe_name(session_id)
    work = Path(tempfile.mkdtemp(prefix=f"{safe_id}_", dir=str(script_root)))
    (work / "inputs").mkdir()
    (work / "outputs").mkdir()
    runtime_pkg = work / "modstore_runtime"
    runtime_pkg.mkdir()
    shutil.copyfile(_runtime_sdk_source(), runtime_pkg / "__init__.py")
    return work


async def _drain(stream: Optional[asyncio.StreamReader], limit: int) -> bytes:
    """读取 stream 全部数据，超过 ``limit`` 时只保留尾部 ``limit`` 字节。"""
    if stream is None:
        return b""
    buf = bytearray()
    while True:
        try:
            chunk = await stream.read(8192)
        except Exception:  # noqa: BLE001 — 进程被 kill 时可能抛 ConnectionResetError
            break
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit * 2:
            del buf[: len(buf) - limit]
    if len(buf) > limit:
        del buf[: len(buf) - limit]
    return bytes(buf)


def _collect_outputs(
    output_dir: Path,
    *,
    file_limit: int = DEFAULT_OUTPUT_FILE_LIMIT_BYTES,
    total_limit: int = DEFAULT_TOTAL_OUTPUT_LIMIT_BYTES,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    total = 0
    if not output_dir.exists():
        return rows
    for p in sorted(output_dir.iterdir()):
        if not p.is_file():
            continue
        size = p.stat().st_size
        if size > file_limit:
            continue
        total += size
        if total > total_limit:
            break
        rows.append({"filename": p.name, "path": str(p), "size": size})
    return rows


def _make_preexec():  # pragma: no cover — Linux-only 资源限制
    if os.name != "posix":
        return None
    try:
        import resource

        def _setup() -> None:
            cpu = 600  # 600 秒 CPU
            mem = 2 * 1024 * 1024 * 1024  # 2 GiB
            fsize = 200 * 1024 * 1024  # 单文件 200 MiB
            for r, lim in (
                (resource.RLIMIT_CPU, (cpu, cpu)),
                (resource.RLIMIT_AS, (mem, mem)),
                (resource.RLIMIT_FSIZE, (fsize, fsize)),
            ):
                try:
                    resource.setrlimit(r, lim)
                except Exception:  # noqa: BLE001
                    pass

        return _setup
    except ImportError:
        return None


async def run_in_sandbox(
    *,
    user_id: int,
    session_id: str,
    script_text: str,
    files: List[Dict[str, Any]],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    extra_env: Optional[Dict[str, str]] = None,
    script_root: Optional[Path] = None,
    employee_run_allowlist: Optional[List[str]] = None,
) -> SandboxResult:
    """启动子进程跑 ``script_text``，并桥接 RPC、收集 stdout/stderr/产物。

    ``script_text`` 必须事先通过 ``static_checker.validate_script`` 校验，
    否则可能让 RPC 主机被滥用（虽然身份仍受 ``user_id`` 约束）。

    后端切换：``MODSTORE_SANDBOX_BACKEND=docker`` 时改走
    :func:`modstore_server.script_agent.docker_runner.run_in_docker`，
    用 docker-per-run 提供 namespace + cgroup 强隔离；默认仍是 subprocess。
    """
    backend = (os.environ.get("MODSTORE_SANDBOX_BACKEND") or "subprocess").strip().lower()
    if backend == "docker":
        from modstore_server.script_agent.docker_runner import run_in_docker

        return await run_in_docker(
            user_id=user_id,
            session_id=session_id,
            script_text=script_text,
            files=files,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            extra_env=extra_env,
            script_root=script_root,
            employee_run_allowlist=employee_run_allowlist,
        )
    _warn_degraded_once()
    root = script_root or SCRIPT_ROOT
    work_dir = _prepare_work_dir(session_id, script_root=root)
    input_dir = work_dir / "inputs"
    for item in files or []:
        name = _safe_name(str(item.get("filename") or "upload.bin"))
        (input_dir / name).write_bytes(item.get("content") or b"")

    # 在用户脚本前注入 preamble，把 open / os.* / socket 锁到 work_dir 内并禁网。
    # preamble 自包含、读取 MODSTORE_SANDBOX_WORK_DIR 决定边界。
    script_path = work_dir / "script.py"
    script_path.write_text(PREAMBLE_SOURCE + script_text, encoding="utf-8")

    allow_t: Optional[tuple[str, ...]] = None
    if employee_run_allowlist:
        allow_t = tuple(str(x).strip() for x in employee_run_allowlist if str(x).strip())
    ctx = SandboxHostContext(
        user_id=int(user_id),
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        employee_run_allowlist=allow_t,
    )
    rpc = SandboxRpcServer(ctx)
    port = await rpc.start()

    proc: Optional[asyncio.subprocess.Process] = None
    timed_out = False
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["MODSTORE_RUNTIME_PORT"] = str(port)
        env["MODSTORE_RUNTIME_TOKEN"] = rpc.token
        env["MODSTORE_SANDBOX_WORK_DIR"] = str(work_dir.resolve())
        # 子进程默认不应继承 LLM key 等敏感 env
        for sensitive in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            env.pop(sensitive, None)
        if extra_env:
            env.update(extra_env)

        kwargs: Dict[str, Any] = {
            "cwd": str(work_dir),
            "env": env,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        preexec = _make_preexec()
        if preexec is not None:
            kwargs["preexec_fn"] = preexec

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "script.py",
            **kwargs,
        )

        stdout_task = asyncio.create_task(_drain(proc.stdout, STDOUT_TAIL_BYTES))
        stderr_task = asyncio.create_task(_drain(proc.stderr, STDERR_TAIL_BYTES))

        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                rc = await proc.wait()
            except Exception:  # noqa: BLE001
                rc = -9

        stdout_bytes = await stdout_task
        stderr_bytes = await stderr_task
    finally:
        await rpc.stop()
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    outputs = _collect_outputs(work_dir / "outputs")
    errors: List[str] = []
    if timed_out:
        errors.append(f"脚本运行超时（>{timeout_seconds}s）")
    elif rc != 0:
        errors.append(stderr[-1000:].strip() or f"脚本退出码 {rc}")
    return SandboxResult(
        ok=(rc == 0 and not timed_out),
        work_dir=str(work_dir),
        returncode=rc,
        stdout=stdout,
        stderr=stderr,
        outputs=outputs,
        errors=errors,
        timed_out=timed_out,
        sdk_calls=ctx.sdk_calls,
    )
