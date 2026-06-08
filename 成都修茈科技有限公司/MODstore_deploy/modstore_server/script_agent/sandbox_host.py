"""沙箱 RPC 主机：在主进程内为 ``modstore_runtime`` SDK 提供后端实现。

子进程脚本通过 TCP 连入此 RPC 服务器，发起的方法由这里 dispatch 到
``llm_chat_proxy`` / ``rag_service`` / ``employee_executor`` 等已有模块。
所有调用都强制注入 ``user_id`` 上下文，避免子进程 forge 身份。

每次跑脚本都用一个新的 :class:`SandboxRpcServer`，绑到一个本机 ephemeral
端口 + 32 字节 token，脚本结束后立即关闭。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

RPC_TIMEOUT_SECONDS = 120.0
DEFAULT_AI_MODEL = "gpt-4o-mini"


@dataclass
class SandboxHostContext:
    """RPC handlers 调用 LLM/知识库/员工时需要的上下文。

    ``api_key`` 在 sandbox 启动前由调用方解析（用 ``llm_key_resolver``）；
    若未传，``ai()`` 调用直接报错而不是静默回退。
    """

    user_id: int
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    sdk_calls: List[Dict[str, Any]] = field(default_factory=list)
    #: 非 None 时 ``employee_run`` 仅能调用列表内的 ``employee_id``（脚本工作流 RPC 边界）。
    employee_run_allowlist: Optional[tuple[str, ...]] = None


class SandboxRpcServer:
    """asyncio TCP server，使用 newline-delimited JSON-RPC 协议。

    协议（与 ``runtime_sdk._RpcClient`` 对齐）::

        client -> server: {"hello": <token>}
        server -> client: {"ok": true}                  # 握手成功
        client -> server: {"id": 1, "method": "ai", "params": {…}}
        server -> client: {"id": 1, "ok": true, "result": …}

    握手失败立即关闭连接（不发任何后续帧）。
    """

    def __init__(self, ctx: SandboxHostContext) -> None:
        self.ctx = ctx
        self.token = secrets.token_urlsafe(32)
        self._server: Optional[asyncio.AbstractServer] = None
        self._port: int = 0
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[Any]]] = {
            "ai": self._handle_ai,
            "kb_search": self._handle_kb_search,
            "employee_run": self._handle_employee_run,
            "http_get": self._handle_http_get,
        }

    @property
    def port(self) -> int:
        return self._port

    async def start(self) -> int:
        """绑定到 127.0.0.1 上随机端口，返回端口号供 child env 注入。"""
        self._server = await asyncio.start_server(self._handle_conn, host="127.0.0.1", port=0)
        sock = self._server.sockets[0] if self._server.sockets else None
        if sock is None:
            raise RuntimeError("无法分配本地端口启动沙箱 RPC server")
        self._port = sock.getsockname()[1]
        return self._port

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception:  # noqa: BLE001 — 关闭路径不要因小错失败
            pass
        self._server = None

    async def _handle_conn(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            hello_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            try:
                hello = json.loads(hello_line.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                hello = {}
            if hello.get("hello") != self.token:
                writer.write(json.dumps({"ok": False, "error": "invalid token"}).encode() + b"\n")
                try:
                    await writer.drain()
                except Exception:  # noqa: BLE001
                    pass
                return
            writer.write(json.dumps({"ok": True}).encode() + b"\n")
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    break
                await self._dispatch(line, writer)
        except asyncio.TimeoutError:
            logger.warning("sandbox rpc handshake timeout")
        except Exception as e:  # noqa: BLE001
            logger.warning("sandbox rpc connection error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _dispatch(self, line: bytes, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        req_id = req.get("id")
        method = str(req.get("method") or "")
        params = req.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        handler = self._handlers.get(method)
        if handler is None:
            resp = {"id": req_id, "ok": False, "error": f"unknown method: {method}"}
            self.ctx.sdk_calls.append({"method": method, "ok": False, "error": "unknown"})
        else:
            try:
                result = await asyncio.wait_for(handler(params), timeout=RPC_TIMEOUT_SECONDS)
                resp = {"id": req_id, "ok": True, "result": result}
                self.ctx.sdk_calls.append({"method": method, "ok": True})
            except asyncio.TimeoutError:
                resp = {"id": req_id, "ok": False, "error": f"{method} timeout"}
                self.ctx.sdk_calls.append({"method": method, "ok": False, "error": "timeout"})
            except Exception as e:  # noqa: BLE001
                msg = str(e)[:500]
                resp = {"id": req_id, "ok": False, "error": msg}
                self.ctx.sdk_calls.append({"method": method, "ok": False, "error": msg[:200]})
        try:
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        except Exception as e:  # noqa: BLE001
            logger.warning("sandbox rpc write error: %s", e)

    # ---------------------- handlers ---------------------- #

    async def _handle_ai(self, params: Dict[str, Any]) -> Any:
        from modstore_server.llm_chat_proxy import chat_dispatch

        prompt = str(params.get("prompt") or "")
        text = str(params.get("text") or "")
        schema = params.get("schema")
        model = (
            str(params.get("model"))
            if params.get("model")
            else (self.ctx.model or DEFAULT_AI_MODEL)
        )
        provider = self.ctx.provider or "openai"
        max_tokens = int(params.get("max_tokens") or 1024)
        if not self.ctx.api_key:
            raise RuntimeError("沙箱缺少 LLM API Key（用户未配置 BYOK 或未传入）。")

        sys_prompt = "你是受控运行时的辅助 AI。严格按用户要求输出，不要附加多余解释。"
        if schema:
            sys_prompt += "\n输出必须是合法 JSON 且符合下述 JSON Schema:\n" + json.dumps(
                schema, ensure_ascii=False
            )
        user_prompt = prompt
        if text:
            user_prompt += "\n\n=== 输入文本 ===\n" + text

        res = await chat_dispatch(
            provider,
            api_key=self.ctx.api_key,
            base_url=self.ctx.base_url,
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        if not res.get("ok"):
            raise RuntimeError(f"LLM 调用失败: {res.get('error') or res.get('status') or ''}")
        content = str(res.get("content") or "")
        if schema:
            stripped = content.strip()
            if stripped.startswith("```"):
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.I)
                if m:
                    stripped = m.group(1).strip()
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                # 解析失败回退到原始字符串，让脚本作者自己兜底
                return content
        return content

    async def _handle_kb_search(self, params: Dict[str, Any]) -> Any:
        from modstore_server.rag_service import retrieve

        query = str(params.get("query") or "")
        top_k = max(1, min(int(params.get("top_k") or 6), 50))
        chunks = await retrieve(user_id=self.ctx.user_id, query=query, top_k=top_k)
        rows: List[Dict[str, Any]] = []
        for c in chunks:
            rows.append(
                {
                    "collection_id": int(getattr(c, "collection_id", 0) or 0),
                    "collection_name": str(getattr(c, "collection_name", "") or ""),
                    "score": float(getattr(c, "score", 0) or 0),
                    "text": str(getattr(c, "text", "") or ""),
                    "metadata": dict(getattr(c, "metadata", {}) or {}),
                }
            )
        return rows

    async def _handle_employee_run(self, params: Dict[str, Any]) -> Any:
        from modstore_server.services.employee import get_default_employee_client

        eid = str(params.get("employee_id") or "").strip()
        task = str(params.get("task") or "")
        payload = params.get("payload") or {}
        if not eid:
            raise RuntimeError("employee_id 不能为空")
        if not isinstance(payload, dict):
            raise RuntimeError("payload 必须是对象")

        allow = self.ctx.employee_run_allowlist
        if allow is not None and eid not in allow:
            raise RuntimeError(
                f"employee_run({eid!r}) 不在本会话允许列表内；当前允许 {list(allow)}。"
                "可在 Brief.references['employee_run_allowlist'] 或 run_in_sandbox(employee_run_allowlist=...) 声明。"
            )

        def _run():
            return get_default_employee_client().execute_task(
                employee_id=eid,
                task=task,
                input_data=payload,
                user_id=self.ctx.user_id,
            )

        return await asyncio.to_thread(_run)

    async def _handle_http_get(self, params: Dict[str, Any]) -> Any:
        import httpx

        url = str(params.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise RuntimeError("仅允许 http/https URL")
        timeout = float(params.get("timeout") or 30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                url,
                params=params.get("params") or {},
                headers=params.get("headers") or {},
            )
            return {
                "status": r.status_code,
                "text": r.text[:1_000_000],
                "headers": dict(r.headers),
            }
