"""SuperEmployeeService composed from mixins."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from app.application.execution_scope import (
    CONTEXT_TOKEN_KEY,
    CapabilityGrant,
)
from app.application.git_workspace_manager import GitWorkspaceManager
from app.application.message_repository import MessageRepository
from app.utils.path_utils import get_app_data_dir

from .cli_runtime import SuperEmployeeCliRuntimeMixin
from .dev_loop import SuperEmployeeDevLoopMixin
from .para_dispatch import SuperEmployeeParaDispatchMixin
from .profiles import (
    DISPATCHER_MESSAGE_KIND,
    SuperEmployeeToolProfile,
    _chunk_text,
    _facade_attr,
    _utc_now,
)

logger = logging.getLogger(__name__)


class SuperEmployeeService(
    SuperEmployeeCliRuntimeMixin,
    SuperEmployeeParaDispatchMixin,
    SuperEmployeeDevLoopMixin,
):
    """Persist software-internal tool calls and optionally dispatch them out."""

    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._p = profile
        root = Path(storage_root) if storage_root is not None else Path(_facade_attr("get_app_data_dir", get_app_data_dir)())
        self._messages = MessageRepository(root, profile.storage_subdir)
        # git_call 延迟回调 self._git，使测试 monkeypatch svc._git 仍能作用于
        # GitWorkspaceManager 内部的所有 git 调用（_git 是唯一 mockable seam）。
        self._git_mgr = GitWorkspaceManager(
            profile.tool_name,
            profile.employee_name,
            git_call=lambda cwd, *a, **k: self._git(cwd, *a, **k),
        )
        # 向后兼容：子类/测试历史地直接读取这些路径属性。
        self._root = self._messages.messages_path.parent
        self._messages_path = self._messages.messages_path
        self._outbox_dir = self._messages.outbox_dir
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cli_runner = cli_runner or _facade_attr("subprocess", subprocess).run
        # 执行授权（deny-by-default）。每个 Service 实例按请求新建（见路由），无跨请求竞态；
        # 默认产品域，invoke() 里据 context 重解析。任何绕过 invoke 的路径也仍是安全档。
        self._grant = CapabilityGrant.product()

    # ── 公开 API ──

    def list_messages(self, *, user_id: int, limit: int = 80) -> list[dict[str, Any]]:
        uid = int(user_id)
        all_rows = self._read_all_message_rows()
        if not all_rows:
            return []
        direct_changed = self._upsert_direct_reply_messages(user_id=uid, rows=all_rows)
        self._sync_para_task_updates(user_id=uid, rows=all_rows)
        if direct_changed:
            self._write_all_message_rows(all_rows)
        rows = [
            self._public_message(item) for item in all_rows if int(item.get("user_id") or 0) == uid
        ]
        return rows[-max(1, min(int(limit), 200)) :]

    def invoke(
        self,
        *,
        user_id: int,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = (message or "").strip()
        if not text:
            raise ValueError("message 不能为空")
        ctx = context if isinstance(context, dict) else {}
        # 解析执行授权（deny-by-default：缺/错平台令牌即产品域），随后立即把令牌抹出 context，
        # 确保它绝不流入 dispatch 请求 / messages.jsonl / Para 载荷 / 日志。
        self._grant = CapabilityGrant.resolve(ctx)
        # 中继工单(force_cli_direct)是操作者自己桌面派给超级员工的开发任务 → 本地全权限,
        # CLI 不该被产品域限制(否则 Claude 的 --disallowedTools 把 prompt 也吞了、还禁写,
        # 根本干不了活)。这与"在真实仓库交付"配套。仅影响 CLI 工具面,不动工作区/派工的安全分流。
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        token_attempt = bool(str(ctx.get(CONTEXT_TOKEN_KEY) or "").strip())
        ctx.pop(CONTEXT_TOKEN_KEY, None)
        # 审计留痕（信任决策咽喉点）：工厂派工记 who/which-workspace；带令牌却被降级=可疑越权。
        if self._grant.is_factory:
            logger.info(
                "super_employee factory dispatch user=%s workspace=%s tool=%s",
                user_id,
                self._grant.workspace_id,
                self._p.tool_name,
            )
        elif token_attempt:
            logger.warning(
                "super_employee factory token rejected, downgraded to product user=%s tool=%s",
                user_id,
                self._p.tool_name,
            )
        request_id = uuid.uuid4().hex
        created_at = _utc_now()
        user_msg = self._message_row(
            user_id=int(user_id),
            role="user",
            body=text,
            created_at=created_at,
            request_id=request_id,
            status="sent",
        )
        if self._should_reply_with_cli(text, ctx):
            direct_body, direct_dispatcher = self._compose_direct_chat_reply(text, ctx)
            assistant_msg = self._message_row(
                user_id=int(user_id),
                role="assistant",
                body=direct_body,
                created_at=_utc_now(),
                request_id=request_id,
                status="completed",
                extra={"kind": self._p.direct_kind},
            )
            self._append_messages([user_msg, assistant_msg])
            dispatch = {
                "request_id": request_id,
                "status": "completed",
                "accepted": True,
                "queued": False,
                "para_tier": 1,
                "device_scope": "local_device",
                "dispatcher": direct_dispatcher,
            }
            return {
                "employee": {
                    "id": self._p.employee_id,
                    "name": self._p.employee_name,
                    "device_scope": "all_devices",
                },
                "dispatch": dispatch,
                "message": self._public_message(user_msg),
                "assistant_message": self._public_message(assistant_msg),
                "messages": self.list_messages(user_id=int(user_id)),
            }

        dispatch_request = self._build_dispatch_request(
            request_id=request_id,
            created_at=created_at,
            user_id=int(user_id),
            message=text,
            context=ctx,
        )
        dispatch = self._dispatch(dispatch_request)
        # 派工不可用兜底：dispatch 未被接受时，若本机装有该工具 CLI 则直接 CLI 直答，
        # 把原本的"已排队/调度器不可用"红字升级为可用回答。
        # 派工成功路径(accepted is True)完全不走这里；云端无 CLI 时 _cli_reply_body 返回空，自动跳过。
        if dispatch.get("accepted") is not True:
            fallback_body, fallback_dispatcher = self._compose_direct_chat_reply(text, ctx)
            # 未装 CLI / 空输出诊断文案不算「成功直答」，继续走派工排队提示。
            if fallback_body and not self._is_cli_unavailable_message(fallback_body):
                assistant_msg = self._message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=fallback_body,
                    created_at=_utc_now(),
                    request_id=request_id,
                    status="completed",
                    extra={"kind": self._p.direct_kind},
                )
                self._append_messages([user_msg, assistant_msg])
                return {
                    "employee": {
                        "id": self._p.employee_id,
                        "name": self._p.employee_name,
                        "device_scope": "all_devices",
                    },
                    "dispatch": {
                        **dispatch,
                        "status": "completed",
                        "para_tier": 1,
                        "device_scope": "local_device",
                        "fallback": fallback_dispatcher,
                    },
                    "message": self._public_message(user_msg),
                    "assistant_message": self._public_message(assistant_msg),
                    "messages": self.list_messages(user_id=int(user_id)),
                }
        dispatcher_msg = self._message_row(
            user_id=int(user_id),
            role="system",
            body=self._dispatch_reply(dispatch),
            created_at=_utc_now(),
            request_id=request_id,
            status=str(dispatch.get("status") or "queued"),
            extra={
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": str(dispatch.get("task_id") or ""),
                "task_status": str(dispatch.get("task_status") or ""),
                "dispatcher": str(dispatch.get("dispatcher") or ""),
                "scope": self._grant.scope.value,
                "workspace_id": self._grant.workspace_id or "",
                "para_tier": dispatch.get("para_tier"),
                "devices": dispatch.get("devices")
                if isinstance(dispatch.get("devices"), list)
                else [],
            },
        )
        self._append_messages([user_msg, dispatcher_msg])
        return {
            "employee": {
                "id": self._p.employee_id,
                "name": self._p.employee_name,
                "device_scope": "all_devices",
            },
            "dispatch": dispatch,
            "message": self._public_message(user_msg),
            "assistant_message": self._public_message(dispatcher_msg),
            "messages": self.list_messages(user_id=int(user_id)),
        }

    # ── LAN SSE 流式直答 ──

    async def invoke_stream(
        self,
        *,
        user_id: int,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """LAN 模式下的流式直答：跳过 Para 派工，直接本地 CLI 执行并逐事件 yield。

        yield 事件格式：
        - {"type": "status", "text": "..."} — 状态提示（已连接/思考中/执行中）
        - {"type": "token", "text": "..."} — 文本片段（逐字/逐块）
        - {"type": "done", "result": {...}} — 完成，含最终回复
        - {"type": "error", "message": "..."} — 失败
        """
        text = (message or "").strip()
        if not text:
            yield {"type": "error", "message": "message 不能为空"}
            return
        ctx = context if isinstance(context, dict) else {}
        self._grant = CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        ctx.pop(CONTEXT_TOKEN_KEY, None)

        # FAQ 直答（"你是谁"等）→ 直接 yield 完整回复
        canned = self._direct_reply_body(text)
        if canned:
            yield {"type": "status", "text": f"已连接 {self._p.display_tool}"}
            for chunk in _chunk_text(canned):
                yield {"type": "token", "text": chunk}
                await asyncio.sleep(0.02)
            yield {"type": "done", "result": {"response": canned, "dispatcher": "faq"}}
            return

        cli_path = self._cli_path()
        if not cli_path:
            # CLI 不可用 → 走派工兜底文案
            fallback_body, dispatcher = self._compose_direct_chat_reply(text, ctx)
            yield {"type": "status", "text": f"已连接 {self._p.display_tool}"}
            for chunk in _chunk_text(fallback_body):
                yield {"type": "token", "text": chunk}
                await asyncio.sleep(0.02)
            yield {
                "type": "done",
                "result": {"response": fallback_body, "dispatcher": dispatcher},
            }
            return

        # 闲聊/开发任务分流
        base_cwd = self._cli_workspace(ctx)
        is_task = self._is_task_intent(text, ctx)
        if is_task and self._dev_loop_enabled() and self._cli_runner is _facade_attr("subprocess", subprocess).run:
            # dev-loop 是多步骤闭环（isolate → CLI → verify → push），不适合逐 token 流式
            # 走原同步路径，但用 status 事件推送阶段进度
            yield {"type": "status", "text": f"{self._p.display_tool} 开始开发任务…"}
            try:
                body = await asyncio.to_thread(
                    self._run_dev_task_loop, cli_path, text, base_cwd, ctx
                )
                yield {"type": "status", "text": "开发任务完成，正在整理回复…"}
                for chunk in _chunk_text(body):
                    yield {"type": "token", "text": chunk}
                    await asyncio.sleep(0.03)
                yield {"type": "done", "result": {"response": body, "dispatcher": "dev_loop"}}
            except Exception as exc:  # noqa: BLE001
                logger.exception("invoke_stream dev_loop failed: %s", exc)
                yield {"type": "error", "message": f"开发任务执行失败：{exc}"}
            return

        # 闲聊或简单 dev-loop（非多步骤）→ CLI 流式
        prompt = self._cli_prompt(text) if not is_task else self._cli_work_prompt(text, base_cwd)
        yield {"type": "status", "text": f"{self._p.display_tool} 正在思考…"}
        try:
            final_text = ""
            async for event in self._run_cli_streaming(cli_path, prompt, base_cwd):
                if event["type"] == "token":
                    final_text += event["text"]
                    yield event
                elif event["type"] == "status":
                    yield event
                elif event["type"] == "done":
                    final_text = event.get("text", final_text)
                elif event["type"] == "error":
                    yield event
                    return
            body = final_text.strip()
            if not body:
                body = self._empty_cli_user_message(ran=True, stderr="")
            yield {"type": "done", "result": {"response": body, "dispatcher": "cli_stream"}}
        except Exception as exc:  # noqa: BLE001
            logger.exception("invoke_stream cli failed: %s", exc)
            yield {"type": "error", "message": f"{self._p.display_tool} CLI 调用失败：{exc}"}

