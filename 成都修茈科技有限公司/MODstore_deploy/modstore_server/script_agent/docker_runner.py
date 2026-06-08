"""Docker-per-run 沙箱后端（opt-in，强隔离档）。

何时启用：环境变量 ``MODSTORE_SANDBOX_BACKEND=docker``。

设计：

- **每次 run 一个 ephemeral 容器**：``docker run --rm`` 跑完即销毁；
  容器是脚本的 namespace + cgroup 边界，比 subprocess 强一档。
- **资源限制走 Docker**：``--memory``、``--cpus``、``--pids-limit``、
  ``--ulimit`` —— Linux/macOS 上比 ``RLIMIT`` 更稳，Windows Docker 也支持。
- **文件系统**：根文件系统 ``--read-only``；只 ``-v <work_dir>:/work:rw``
  挂载 per-session 工作目录，``--tmpfs /tmp``；脚本 cwd=``/work``。
  preamble 仍然注入到 ``script.py`` 头部做 Python 层防护，二者叠加。
- **网络**：不 ``--network=none``（那样 SDK 没法回调）。改成 ``--network=bridge``
  + ``--add-host=host.docker.internal:host-gateway``，把 RPC host 改写成
  ``host.docker.internal``；preamble 的 socket 拦截只放行 ``host.docker.internal:port``，
  其它一律拒绝。所以即便 docker bridge 默认能联网，脚本也连不出去。
- **特权丢弃**：``--cap-drop=ALL``、``--security-opt=no-new-privileges``、
  ``--user 65534:65534``（nobody）。
- **回退**：未检测到 docker 二进制 / 镜像不存在 → 抛错，不静默回退到 subprocess
  （强隔离意图必须显式）。

依赖镜像：``MODSTORE_SANDBOX_DOCKER_IMAGE``，默认 ``python:3.11-slim``。
注意：默认镜像里没有 ``openpyxl`` 等第三方包；管理员 allowlist 加包后需自建镜像，
预装好这些包并通过环境变量切到自己的 image 标签。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional

from modstore_server.script_agent.sandbox_host import (
    SandboxHostContext,
    SandboxRpcServer,
)
from modstore_server.script_agent.sandbox_preamble import PREAMBLE_SOURCE
from modstore_server.script_agent.sandbox_runner import (
    DEFAULT_OUTPUT_FILE_LIMIT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOTAL_OUTPUT_LIMIT_BYTES,
    SCRIPT_ROOT,
    STDERR_TAIL_BYTES,
    STDOUT_TAIL_BYTES,
    SandboxResult,
    _collect_outputs,
    _drain,
    _prepare_work_dir,
    _safe_name,
)

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.11-slim"
DEFAULT_MEMORY = "2g"
DEFAULT_CPUS = "1.0"
DEFAULT_PIDS = 256


def _docker_bin() -> Optional[str]:
    return shutil.which("docker")


def docker_available() -> bool:
    return _docker_bin() is not None


async def run_in_docker(
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
    image: Optional[str] = None,
    employee_run_allowlist: Optional[List[str]] = None,
) -> SandboxResult:
    """与 ``run_in_sandbox`` 同签名的 docker-per-run 后端。"""
    docker = _docker_bin()
    if docker is None:
        raise RuntimeError(
            "MODSTORE_SANDBOX_BACKEND=docker 但本机找不到 docker 二进制；"
            "请安装 Docker Engine 或改回 subprocess 后端"
        )

    image = image or os.environ.get("MODSTORE_SANDBOX_DOCKER_IMAGE") or DEFAULT_IMAGE
    memory = os.environ.get("MODSTORE_SANDBOX_DOCKER_MEMORY") or DEFAULT_MEMORY
    cpus = os.environ.get("MODSTORE_SANDBOX_DOCKER_CPUS") or DEFAULT_CPUS
    try:
        pids = int(os.environ.get("MODSTORE_SANDBOX_DOCKER_PIDS") or DEFAULT_PIDS)
    except Exception:
        pids = DEFAULT_PIDS

    root = script_root or SCRIPT_ROOT
    work_dir = _prepare_work_dir(session_id, script_root=root)
    input_dir = work_dir / "inputs"
    for item in files or []:
        name = _safe_name(str(item.get("filename") or "upload.bin"))
        (input_dir / name).write_bytes(item.get("content") or b"")

    script_path = work_dir / "script.py"
    script_path.write_text(PREAMBLE_SOURCE + script_text, encoding="utf-8")

    # RPC 绑到 0.0.0.0 让 docker bridge 上的容器能访问到宿主网关
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
    # NOTE: SandboxRpcServer 默认绑 127.0.0.1；docker 容器无法回连。
    # 这里通过 monkeypatch 起在 0.0.0.0 上：
    rpc._server = await asyncio.start_server(  # type: ignore[attr-defined]
        rpc._handle_conn, host="0.0.0.0", port=0  # type: ignore[attr-defined]
    )
    sock = rpc._server.sockets[0] if rpc._server.sockets else None  # type: ignore[attr-defined]
    if sock is None:
        raise RuntimeError("无法分配 RPC 端口（docker 后端）")
    rpc._port = sock.getsockname()[1]  # type: ignore[attr-defined]
    port = rpc._port  # type: ignore[attr-defined]

    proc: Optional[asyncio.subprocess.Process] = None
    timed_out = False
    try:
        # docker run 命令：尽量收紧
        cmd = [
            docker,
            "run",
            "--rm",
            "--network=bridge",
            "--add-host=host.docker.internal:host-gateway",
            f"--memory={memory}",
            f"--cpus={cpus}",
            f"--pids-limit={pids}",
            "--read-only",
            "--tmpfs=/tmp:size=100m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "-v",
            f"{work_dir.resolve()}:/work:rw",
            "--workdir=/work",
            "-e",
            "PYTHONIOENCODING=utf-8",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"MODSTORE_RUNTIME_PORT={port}",
            "-e",
            f"MODSTORE_RUNTIME_TOKEN={rpc.token}",
            "-e",
            "MODSTORE_RUNTIME_HOST=host.docker.internal",
            "-e",
            "MODSTORE_SANDBOX_WORK_DIR=/work",
        ]
        # 注意：不继承宿主敏感 env；只给最小集
        for k, v in (extra_env or {}).items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.extend([image, "python", "/work/script.py"])

        logger.info("[docker] starting container session=%s image=%s", session_id, image)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            except Exception:
                rc = -9

        stdout_bytes = await stdout_task
        stderr_bytes = await stderr_task
    finally:
        await rpc.stop()
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    outputs = _collect_outputs(work_dir / "outputs")
    errors: List[str] = []
    if timed_out:
        errors.append(f"脚本运行超时（>{timeout_seconds}s，docker）")
    elif rc != 0:
        errors.append(stderr[-1000:].strip() or f"容器退出码 {rc}")
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


__all__ = ["run_in_docker", "docker_available"]
