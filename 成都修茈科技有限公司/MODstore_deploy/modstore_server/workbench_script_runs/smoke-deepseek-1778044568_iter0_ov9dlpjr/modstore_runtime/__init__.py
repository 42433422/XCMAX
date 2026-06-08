"""``modstore_runtime`` —— 沙箱内脚本可以 ``import`` 的受控 SDK（"AI 兜底"）。

子进程通过 TCP socket（``127.0.0.1:$MODSTORE_RUNTIME_PORT``）+ 一次性 token
(``$MODSTORE_RUNTIME_TOKEN``) 与父进程的 RPC 服务器通信。所有"非确定性"或
"跨边界"操作（调 LLM、检索知识库、调员工、发 HTTP）都通过 RPC 委派到
父进程执行，由父进程统一计费 / 限流 / 审计。

脚本作者只需::

    from modstore_runtime import ai, kb_search, employee_run, http_get, log, inputs, outputs

注意：本文件在沙箱启动时会被 ``sandbox_runner`` 复制到子进程的
``work_dir/modstore_runtime/__init__.py``，因此**不能**在这里 import 任何
``modstore_server.*`` 内部模块——子进程的 ``sys.path`` 不一定包含项目根。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class RuntimeSdkError(Exception):
    """SDK 调用层的错误（连接、握手、远端报错均归此类）。"""


class _RpcClient:
    """单连接 newline-delimited JSON-RPC 客户端，线程安全。

    握手：连上后第一行发 ``{"hello": <token>}``，等服务器回 ``{"ok": true}``。
    后续每次 ``call(method, params)``：发 ``{"id": int, "method": str, "params": {…}}``，
    收 ``{"id": int, "ok": bool, "result"|"error": …}``。
    """

    def __init__(self) -> None:
        port = os.environ.get("MODSTORE_RUNTIME_PORT")
        token = os.environ.get("MODSTORE_RUNTIME_TOKEN")
        # docker-per-run 后端会把 host 设为 ``host.docker.internal`` 让容器内连出去；
        # 默认子进程后端是 ``127.0.0.1``。
        host = os.environ.get("MODSTORE_RUNTIME_HOST") or "127.0.0.1"
        if not port or not token:
            raise RuntimeSdkError("modstore_runtime: 当前不在受控沙箱内运行，缺少 RPC 配置。")
        self._token = token
        self._sock = socket.create_connection((host, int(port)), timeout=120)
        self._buf = b""
        self._lock = threading.Lock()
        self._next_id = 0
        self._send({"hello": token})
        hello = self._recv()
        if not hello.get("ok"):
            raise RuntimeSdkError(f"modstore_runtime: 握手失败: {hello.get('error') or hello}")

    def _readline(self) -> bytes:
        while b"\n" not in self._buf:
            data = self._sock.recv(65536)
            if not data:
                raise RuntimeSdkError("modstore_runtime: RPC 连接已关闭。")
            self._buf += data
        line, _, rest = self._buf.partition(b"\n")
        self._buf = rest
        return line

    def _send(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self._sock.sendall(line)

    def _recv(self) -> Dict[str, Any]:
        return json.loads(self._readline().decode("utf-8"))

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            self._send({"id": req_id, "method": method, "params": params or {}})
            resp = self._recv()
        if resp.get("id") != req_id:
            raise RuntimeSdkError(f"modstore_runtime: 收到 id 不匹配的响应: {resp}")
        if resp.get("ok"):
            return resp.get("result")
        raise RuntimeSdkError(str(resp.get("error") or "RPC 调用失败"))


_client_lock = threading.Lock()
_client: Optional[_RpcClient] = None


def _client_or_init() -> _RpcClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = _RpcClient()
        return _client


# ----------------------------- 公开 API ----------------------------- #


def ai(
    prompt: str,
    *,
    text: str = "",
    schema: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> Any:
    """非确定性兜底：交给 LLM 处理（提取 / 分类 / 总结）。

    若传 ``schema`` 字典，期望 LLM 输出符合该 JSON Schema 的对象，
    服务端会尝试解析为 ``dict/list``；解析失败则回退为字符串。
    """
    return _client_or_init().call(
        "ai",
        {
            "prompt": prompt,
            "text": text,
            "schema": schema,
            "model": model,
            "max_tokens": max_tokens,
        },
    )


def kb_search(query: str, *, top_k: int = 6) -> list:
    """跨当前用户可见的知识库集合做向量检索，返回前 ``top_k`` 条片段。"""
    return _client_or_init().call("kb_search", {"query": query, "top_k": top_k})


def employee_run(
    employee_id: str,
    task: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """以当前用户身份调用平台员工。权限由父进程二次校验。"""
    return _client_or_init().call(
        "employee_run",
        {"employee_id": employee_id, "task": task, "payload": payload or {}},
    )


def http_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """走父进程的受控 HTTP GET（域名白名单将在 Phase 2 接入）。

    返回 ``{"status": int, "text": str, "headers": dict}``，``text`` 截断到
    1MB 防止响应过大撑爆内存。
    """
    return _client_or_init().call(
        "http_get",
        {
            "url": url,
            "params": params or {},
            "headers": headers or {},
            "timeout": timeout,
        },
    )


# --------------------------- 本地 IO 工具 --------------------------- #


class _Inputs:
    """``inputs/`` 目录：脚本只读访问。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path(self, name: str) -> Path:
        return self._root / name

    def list(self) -> list[str]:
        if not self._root.exists():
            return []
        return [p.name for p in sorted(self._root.iterdir()) if p.is_file()]


class _Outputs:
    """``outputs/`` 目录：脚本最终交付物落在此处。"""

    def __init__(self, root: Path) -> None:
        self._root = root
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @property
    def root(self) -> Path:
        return self._root

    def path(self, name: str) -> Path:
        return self._root / name

    def write_text(self, name: str, text: str, *, encoding: str = "utf-8") -> Path:
        p = self.path(name)
        p.write_text(text, encoding=encoding)
        return p

    def write_bytes(self, name: str, data: bytes) -> Path:
        p = self.path(name)
        p.write_bytes(data)
        return p

    def write_json(self, name: str, data: Any, *, ensure_ascii: bool = False) -> Path:
        p = self.path(name)
        p.write_text(
            json.dumps(data, ensure_ascii=ensure_ascii, indent=2),
            encoding="utf-8",
        )
        return p


inputs = _Inputs(Path("inputs"))
outputs = _Outputs(Path("outputs"))


class _Logger:
    """结构化日志：以 ``LOG <json>\\n`` 写入 stderr，父进程 observer 可以解析。"""

    def _emit(self, level: str, msg: str, **fields: Any) -> None:
        rec: Dict[str, Any] = {"level": level, "msg": msg}
        if fields:
            rec.update(fields)
        sys.stderr.write("LOG " + json.dumps(rec, ensure_ascii=False) + "\n")
        sys.stderr.flush()

    def debug(self, msg: str, **fields: Any) -> None:
        self._emit("DEBUG", msg, **fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._emit("INFO", msg, **fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._emit("WARN", msg, **fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._emit("ERROR", msg, **fields)


log = _Logger()


__all__ = [
    "ai",
    "kb_search",
    "employee_run",
    "http_get",
    "log",
    "inputs",
    "outputs",
    "RuntimeSdkError",
]
