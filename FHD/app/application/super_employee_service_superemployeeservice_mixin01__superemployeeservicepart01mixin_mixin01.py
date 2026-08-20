# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart01MixinPart01Mixin:
    def __init__(
        self,
        profile: _facade().SuperEmployeeToolProfile,
        storage_root: str | _facade().Path | None = None,
        http_client_factory: _facade().Callable[[], _facade().httpx.Client] | None = None,
        cli_runner: _facade().Callable[..., _facade().subprocess.CompletedProcess[str]]
        | None = None,
    ) -> None:
        self._p = profile
        root = (
            _facade().Path(storage_root)
            if storage_root is not None
            else _facade().Path(_facade().get_app_data_dir())
        )
        self._messages = _facade().MessageRepository(root, profile.storage_subdir)
        self._git_mgr = _facade().GitWorkspaceManager(
            profile.tool_name,
            profile.employee_name,
            git_call=lambda cwd, *a, **k: self._git(cwd, *a, **k),
        )
        self._root = self._messages.messages_path.parent
        self._messages_path = self._messages.messages_path
        self._outbox_dir = self._messages.outbox_dir
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cli_runner = cli_runner or _facade().subprocess.run
        self._grant = _facade().CapabilityGrant.product()

    def list_messages(self, *, user_id: int, limit: int = 80) -> list[dict[str, _facade().Any]]:
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
        self, *, user_id: int, message: str, context: dict[str, _facade().Any] | None = None
    ) -> dict[str, _facade().Any]:
        text = (message or "").strip()
        if not text:
            raise ValueError("message 不能为空")
        ctx = context if isinstance(context, dict) else {}
        self._grant = _facade().CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        token_attempt = bool(str(ctx.get(_facade().CONTEXT_TOKEN_KEY) or "").strip())
        ctx.pop(_facade().CONTEXT_TOKEN_KEY, None)
        if self._grant.is_factory:
            _facade().logger.info(
                "super_employee factory dispatch user=%s workspace=%s tool=%s",
                user_id,
                self._grant.workspace_id,
                self._p.tool_name,
            )
        elif token_attempt:
            _facade().logger.warning(
                "super_employee factory token rejected, downgraded to product user=%s tool=%s",
                user_id,
                self._p.tool_name,
            )
        request_id = _facade().uuid.uuid4().hex
        created_at = _facade()._utc_now()
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
                created_at=_facade()._utc_now(),
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
        if dispatch.get("accepted") is not True:
            fallback_body, fallback_dispatcher = self._compose_direct_chat_reply(text, ctx)
            if fallback_body and (
                not fallback_body.startswith(f"{self._p.display_tool} CLI 暂时没有返回内容")
            ):
                assistant_msg = self._message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=fallback_body,
                    created_at=_facade()._utc_now(),
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
            created_at=_facade()._utc_now(),
            request_id=request_id,
            status=str(dispatch.get("status") or "queued"),
            extra={
                "kind": _facade().DISPATCHER_MESSAGE_KIND,
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

    async def invoke_stream(
        self, *, user_id: int, message: str, context: dict[str, _facade().Any] | None = None
    ) -> _facade().AsyncIterator[dict[str, _facade().Any]]:
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
        self._grant = _facade().CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        ctx.pop(_facade().CONTEXT_TOKEN_KEY, None)
        canned = self._direct_reply_body(text)
        if canned:
            yield {"type": "status", "text": f"已连接 {self._p.display_tool}"}
            for chunk in _facade()._chunk_text(canned):
                yield {"type": "token", "text": chunk}
                await _facade().asyncio.sleep(0.02)
            yield {"type": "done", "result": {"response": canned, "dispatcher": "faq"}}
            return
        cli_path = self._cli_path()
        if not cli_path:
            fallback_body, dispatcher = self._compose_direct_chat_reply(text, ctx)
            yield {"type": "status", "text": f"已连接 {self._p.display_tool}"}
            for chunk in _facade()._chunk_text(fallback_body):
                yield {"type": "token", "text": chunk}
                await _facade().asyncio.sleep(0.02)
            yield {"type": "done", "result": {"response": fallback_body, "dispatcher": dispatcher}}
            return
        base_cwd = self._cli_workspace(ctx)
        is_task = self._is_task_intent(text, ctx)
        if is_task and self._dev_loop_enabled() and (self._cli_runner is _facade().subprocess.run):
            yield {"type": "status", "text": f"{self._p.display_tool} 开始开发任务…"}
            try:
                body = await _facade().asyncio.to_thread(
                    self._run_dev_task_loop, cli_path, text, base_cwd, ctx
                )
                yield {"type": "status", "text": "开发任务完成，正在整理回复…"}
                for chunk in _facade()._chunk_text(body):
                    yield {"type": "token", "text": chunk}
                    await _facade().asyncio.sleep(0.03)
                yield {"type": "done", "result": {"response": body, "dispatcher": "dev_loop"}}
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.exception("invoke_stream dev_loop failed: %s", exc)
                yield {"type": "error", "message": f"开发任务执行失败：{exc}"}
            return
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
                body = f"{self._p.display_tool} CLI 暂时没有返回内容，请确认本机 {self._p.display_tool} 已登录后重试。"
            yield {"type": "done", "result": {"response": body, "dispatcher": "cli_stream"}}
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.exception("invoke_stream cli failed: %s", exc)
            yield {"type": "error", "message": f"{self._p.display_tool} CLI 调用失败：{exc}"}
