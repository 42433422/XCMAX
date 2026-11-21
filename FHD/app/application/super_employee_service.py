"""Public super-employee API and explicit composition of dispatch/execution services.

Codex, Claude, Cursor and Trae retain the same profiles, wire responses and
override seams. Components below own their effects and never import this facade.
"""

from __future__ import annotations

import asyncio

# Shared module objects remain importable for existing process/path test patches.
import json as json
import logging
import os
import re as re
import shutil as shutil
import subprocess
import tempfile as tempfile
import threading as threading
import time as time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing
from pathlib import Path
from typing import Any

import httpx

from app.application.message_repository import MessageRepository
from app.application.message_repository import _safe_json_line as _safe_json_line
from app.application.relay_workspace import resolve_verified_relay_workspace_root
from app.application.workspaces import WorkspaceError as WorkspaceError
from app.application.workspaces import get_workspace_registry
from app.domain.app_pure.execution_scope import CONTEXT_TOKEN_KEY, CapabilityGrant
from app.domain.app_pure.execution_scope import FACTORY_TOKEN_ENV as FACTORY_TOKEN_ENV
from app.domain.app_pure.git_workspace_manager import GitWorkspaceManager
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

from .super_employee.cli import CliExecutionError, CliExecutor
from .super_employee.common import _PARA_TOKEN_CACHE as _PARA_TOKEN_CACHE
from .super_employee.common import _PARA_TOKEN_TTL as _PARA_TOKEN_TTL
from .super_employee.common import _RELAY_WT_LOCKS as _RELAY_WT_LOCKS
from .super_employee.common import _RELAY_WT_LOCKS_GUARD as _RELAY_WT_LOCKS_GUARD
from .super_employee.common import _SUBTASK_LABELS as _SUBTASK_LABELS
from .super_employee.common import _TASK_MARKERS as _TASK_MARKERS
from .super_employee.common import DEFAULT_PARA_API_URL as DEFAULT_PARA_API_URL
from .super_employee.common import DISPATCHER_MESSAGE_KIND, _chunk_text, _utc_now
from .super_employee.common import PARA_TERMINAL_TASK_STATUSES as PARA_TERMINAL_TASK_STATUSES
from .super_employee.common import TASK_ID_RE as TASK_ID_RE
from .super_employee.common import _coerce_list as _coerce_list
from .super_employee.common import _relay_wt_lock as _relay_wt_lock
from .super_employee.conversation import ConversationSessions
from .super_employee.development import DevelopmentWorkflow
from .super_employee.devices import DeviceSelection
from .super_employee.dispatch import EmployeeDispatcher
from .super_employee.execution import ExecutionPolicy
from .super_employee.messages import MessageSynchronizer
from .super_employee.output import CliOutput
from .super_employee.para import ParaClient
from .super_employee.policy import EmployeePolicy
from .super_employee.profiles import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    TRAE_PROFILE,
    SuperEmployeeToolProfile,
)
from .super_employee.profiles import _claude_cli_command as _claude_cli_command
from .super_employee.profiles import _codex_cli_command as _codex_cli_command
from .super_employee.profiles import _cursor_cli_command as _cursor_cli_command
from .super_employee.profiles import _trae_cli_command as _trae_cli_command
from .super_employee.protocols import (
    CliPorts,
    ConversationPorts,
    DevelopmentPorts,
    ExecutionContext,
    MessageSyncPorts,
    ParaPorts,
    WorkspacePorts,
    WorktreePorts,
)

logger = logging.getLogger(__name__)


class SuperEmployeeService:
    """Persist conversations and coordinate scheduler or local tool execution."""

    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._p = profile
        self._scope = ExecutionContext()
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._messages = MessageRepository(root, profile.storage_subdir)
        self._root = self._messages.messages_path.parent
        self._messages_path = self._messages.messages_path
        self._outbox_dir = self._messages.outbox_dir
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cli_runner = cli_runner or subprocess.run
        self._git_mgr = GitWorkspaceManager(
            profile.tool_name,
            profile.employee_name,
            git_call=lambda cwd, *args, **kwargs: self._git(cwd, *args, **kwargs),
        )
        self._policy = EmployeePolicy(profile)
        self._output = CliOutput(profile.tool_name)
        self._devices = DeviceSelection(profile)
        self._execution = ExecutionPolicy(
            profile,
            self._scope,
            WorkspacePorts(
                registry=lambda: get_workspace_registry(),
                verified_relay_root=lambda ctx: resolve_verified_relay_workspace_root(ctx),
                relay_workspace=lambda ctx: self._relay_real_workspace(ctx),
            ),
        )
        self._cli = CliExecutor(
            profile,
            CliPorts(
                runner=lambda: self._cli_runner,
                apply_scope=lambda cmd: self._apply_scope_to_cmd(cmd),
                environment=lambda: self._cli_subprocess_env(),
                idle_timeout=lambda: self._cli_idle_timeout_seconds(),
                hard_cap=lambda: self._cli_hard_cap_seconds(),
                run_idle=lambda cmd, cwd, idle, cap: self._run_cli_idle(cmd, cwd, idle, cap),
            ),
        )
        self._sessions = ConversationSessions(
            profile,
            ConversationPorts(
                data_dir=lambda: Path(get_app_data_dir()),
                workspace=lambda ctx: self._cli_workspace(ctx),
                git=lambda cwd, *args, **kwargs: self._git(cwd, *args, **kwargs),
                is_git_repo=lambda cwd: self._is_git_repo(cwd),
                get_session=lambda key: self._session_get(key),
                set_session=lambda key, value: self._session_set(key, value),
                run_idle=lambda cmd, cwd, idle, cap: self._run_cli_idle(cmd, cwd, idle, cap),
                idle_timeout=lambda: self._cli_idle_timeout_seconds(),
                hard_cap=lambda: self._cli_hard_cap_seconds(),
                apply_scope=lambda cmd: self._apply_scope_to_cmd(cmd),
            ),
        )
        self._development = DevelopmentWorkflow(
            profile,
            WorktreePorts(
                git=lambda cwd, *args, **kwargs: self._git(cwd, *args, **kwargs),
                is_git_repo=lambda cwd: self._is_git_repo(cwd),
                resolve_branch=lambda cwd, branch: self._resolve_branch_ref(cwd, branch),
                persistent_path=lambda: self._relay_persistent_worktree_path(),
            ),
            DevelopmentPorts(
                prepare=lambda cwd, text, branch: self._prepare_worktree(cwd, text, branch),
                verify=lambda cwd: self._verify_workspace(cwd),
                commit=lambda cwd, branch, text: self._commit_and_push(cwd, branch, text),
                remove=lambda cwd, path: self._remove_worktree(cwd, path),
                run_once=lambda cli, prompt, cwd: self._run_cli_once(cli, prompt, cwd),
                work_prompt=lambda text, cwd: self._cli_work_prompt(text, cwd),
                fix_prompt=lambda message, cwd: self._cli_fix_prompt(message, cwd),
                hard_cap=lambda: self._cli_hard_cap_seconds(),
            ),
        )
        remote = ParaPorts(
            client=lambda: self._http_client_factory(),
            api_url=lambda: self._para_api_url(),
            token=lambda client, url: self._para_token(client, url),
            request=lambda client, api_url, token, method, path, *, json_body=None: (
                self._para_request(client, api_url, token, method, path, json_body=json_body)
            ),
        )
        self._para = ParaClient(
            profile,
            remote,
            lambda response: self._json_response(response),
            _PARA_TOKEN_CACHE,
            lambda: _PARA_TOKEN_TTL,
        )
        self._dispatching = EmployeeDispatcher(
            profile,
            self._scope,
            remote,
            self._devices,
            lambda request, **kwargs: self._write_outbox(request, **kwargs),
            lambda: self._factory_workspace_root(),
        )
        self._sync = MessageSynchronizer(
            profile,
            self._messages,
            MessageSyncPorts(
                fetch_task=lambda task: self._fetch_para_task(task),
                direct_reply=lambda text: self._direct_reply_body(text),
                should_reply=lambda text, ctx: self._should_reply_with_cli(text, ctx),
                compose_reply=lambda text, ctx: self._compose_direct_chat_reply(text, ctx),
                refresh=lambda row, task: self._refresh_dispatcher_row(row, task),
                upsert_result=lambda **kwargs: self._upsert_result_messages(**kwargs),
                write_rows=lambda rows: self._write_all_message_rows(rows),
            ),
        )

        # Pure compatibility helpers; effectful operations remain explicit methods.
        self._should_reply_with_cli = self._policy.should_reply_with_cli
        self._is_task_intent = self._policy.is_task_intent
        self._direct_reply_body = self._policy.direct_reply_body
        self._cli_prompt = self._policy.cli_prompt
        self._cli_work_prompt = self._policy.cli_work_prompt
        self._cli_fix_prompt = self._policy.cli_fix_prompt
        self._conversation_mode_enabled = self._policy.conversation_mode_enabled
        self._dev_loop_enabled = self._policy.dev_loop_enabled
        self._cli_path = self._policy.cli_path
        self._cli_idle_timeout_seconds = self._policy.cli_idle_timeout_seconds
        self._cli_hard_cap_seconds = self._policy.cli_hard_cap_seconds
        self._cli_timeout_seconds = self._policy.cli_timeout_seconds
        self._parse_stream_json_line = self._output.parse_stream_json_line
        self._parse_claude_stream_json = self._output.parse_claude_stream_json
        self._parse_stream_json_full = self._output.parse_stream_json_full
        self._clean_cli_stdout = self._output.clean_cli_stdout
        self._device_eligible = self._devices.device_eligible
        self._select_para_devices = self._devices.select_para_devices
        self._local_device_id = self._devices.local_device_id
        self._resolve_para_tier = self._devices.resolve_para_tier
        self._select_local_device = self._devices.select_local_device
        self._select_devices_by_tier = self._devices.select_devices_by_tier
        self._max_para_devices = self._devices.max_para_devices
        self._device_tool = self._devices.device_tool
        self._apply_scope_to_cmd = self._execution.apply_scope_to_cmd
        self._cli_subprocess_env = self._execution.cli_subprocess_env
        self._session_store_path = self._sessions.session_store_path
        self._session_key = self._sessions.session_key
        self._conversation_prompt = self._sessions.conversation_prompt
        self._conversation_perm = self._sessions.conversation_perm
        self._conversation_cmd = self._sessions.conversation_cmd
        self._para_api_url = self._para.para_api_url
        self._json_response = self._para.json_response
        self._error_message = self._para.error_message
        self._para_prompt = self._dispatching.para_prompt
        self._para_subtask_title = self._dispatching.para_subtask_title
        self._dispatch_reply = self._dispatching.dispatch_reply
        self._is_dispatcher_ack_body = self._sync.is_dispatcher_ack_body
        self._extract_task_id_from_body = self._sync.extract_task_id_from_body
        self._para_task_status_reply = self._sync.para_task_status_reply
        self._task_subtasks = self._sync.task_subtasks
        self._result_body = self._sync.result_body
        self._is_dispatcher_log = self._sync.is_dispatcher_log
        self._dedupe_log_tail = self._sync.dedupe_log_tail

    @property
    def _grant(self) -> CapabilityGrant:
        return self._scope.grant

    @_grant.setter
    def _grant(self, value: CapabilityGrant) -> None:
        self._scope.grant = value

    @property
    def _relay_cli_trusted(self) -> bool:
        return self._scope.relay_cli_trusted

    @_relay_cli_trusted.setter
    def _relay_cli_trusted(self, value: bool) -> None:
        self._scope.relay_cli_trusted = value

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

    def _record_direct_reply(
        self,
        user_msg: dict[str, Any],
        body: str,
        dispatch: dict[str, Any],
        failure: CliExecutionError | None = None,
    ) -> dict[str, Any]:
        status = "failed" if failure else "completed"
        details = failure.payload() if failure else {}
        assistant_msg = self._message_row(
            user_id=user_msg["user_id"],
            role="assistant",
            body=body,
            created_at=_utc_now(),
            request_id=user_msg["dispatch_request_id"],
            status=status,
            extra={"kind": self._p.direct_kind, **details},
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
                "status": status,
                **details,
                **({"accepted": False, "queued": False} if failure else {}),
            },
            "message": self._public_message(user_msg),
            "assistant_message": self._public_message(assistant_msg),
            "messages": self.list_messages(user_id=user_msg["user_id"]),
        }

    def read_dispatch_receipt(
        self, *, user_id: int, request_id: str, task_id: str
    ) -> dict[str, Any] | None:
        """Read the original dispatch intent without losing unresolved fleet sends."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request_id):
            return None
        # Atomic outbox replacement permits a snapshot read while its sender
        # still owns the dispatch lock and is waiting for a remote acknowledgement.
        request = self._messages.read_dispatch_request(user_id, request_id)
        if request is None:
            return None
        receipt = request.get("dispatch_receipt")
        if not isinstance(receipt, dict) or receipt.get("request_id") != request_id:
            return None
        original_id = str(receipt.get("task_id") or "")
        if task_id and task_id != original_id:
            return None
        uncertain = bool(
            receipt.get("reconciliation_required")
            or receipt.get("pending_device_id")
            or receipt.get("unexpected_task_id")
            or receipt.get("status") in {"dispatching", "dispatch_unknown", "unknown"}
        )
        dispatch = {
            key: receipt[key]
            for key in (
                "request_id",
                "task_id",
                "status",
                "dispatcher",
                "devices",
                "pending_device_id",
                "unexpected_task_id",
            )
            if key in receipt
        }
        if uncertain:
            dispatch.update(status="dispatch_unknown", reconciliation_required=True)
        if not original_id:
            return (
                {
                    "dispatch": dispatch,
                    "assistant_message": {"body": self._dispatch_reply(dispatch)},
                }
                if uncertain
                else None
            )
        api_url = str(receipt.get("api_url") or "")
        if (
            receipt.get("dispatcher") != "para_api"
            or not api_url
            or api_url != self._para_api_url()
        ):
            return None
        try:
            with self._http_client_factory() as client:
                token = self._para_token(client, api_url)
                result = self._para_request(
                    client, api_url, token, "GET", f"/api/tasks/{original_id}"
                )
        except RECOVERABLE_ERRORS:
            return None
        task = result.get("task")
        task = task if isinstance(task, dict) else None
        if not task or str(task.get("id") or task.get("task_id") or "") != original_id:
            return None
        state = str(task.get("status") or "unknown")
        state = {"merged": "completed", "merge_conflict": "blocked"}.get(state, state)
        dispatch["task_status"] = state
        if not uncertain:
            dispatch["status"] = state
        return {
            "dispatch": dispatch,
            "assistant_message": {
                "body": self._dispatch_reply(dispatch)
                if uncertain
                else self._para_task_status_reply(task)
            },
        }

    def invoke(
        self, *, user_id: int, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        ctx = dict(context) if isinstance(context, dict) else {}
        request_id = str(ctx.get("request_id") or uuid.uuid4().hex)
        with self._messages.dispatch_lock(user_id, request_id):
            return self._invoke_once(
                user_id=user_id, message=message, context=ctx, request_id=request_id
            )

    def _invoke_once(
        self, *, user_id: int, message: str, context: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        text = (message or "").strip()
        if not text:
            raise ValueError("message 不能为空")
        ctx = dict(context) if isinstance(context, dict) else {}
        self._grant = CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        token_attempt = bool(str(ctx.get(CONTEXT_TOKEN_KEY) or "").strip())
        ctx.pop(CONTEXT_TOKEN_KEY, None)
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
        previous_request = self._messages.read_dispatch_request(user_id, request_id)
        created_at = previous_request["created_at"] if previous_request else _utc_now()
        user_msg = self._message_row(
            user_id=int(user_id),
            role="user",
            body=text,
            created_at=created_at,
            request_id=request_id,
            status="sent",
        )
        if not previous_request and self._should_reply_with_cli(text, ctx):
            failure = None
            try:
                direct_body, direct_dispatcher = self._compose_direct_chat_reply(text, ctx)
            except CliExecutionError as exc:
                failure = exc
                direct_body, direct_dispatcher = exc.reply_body(), f"{self._p.tool_name}_cli"
            dispatch = {
                "request_id": request_id,
                "accepted": True,
                "queued": False,
                "para_tier": 1,
                "device_scope": "local_device",
                "dispatcher": direct_dispatcher,
            }
            return self._record_direct_reply(user_msg, direct_body, dispatch, failure)
        dispatch_request = self._build_dispatch_request(
            request_id=request_id,
            created_at=created_at,
            user_id=int(user_id),
            message=text,
            context=ctx,
        )
        if previous_request:
            for key in ("task", "scope", "workspace_id", "mode", "target_devices"):
                if previous_request.get(key) != dispatch_request.get(key):
                    raise ValueError(f"request_id 已绑定其他任务参数：{key}")
            for key in ("branch", "repo_url", "para_tier", "tier", "escalate", "max_devices"):
                if previous_request.get("raw_context", {}).get(key) != ctx.get(key):
                    raise ValueError(f"request_id 已绑定其他任务参数：{key}")
            dispatch_request = previous_request
        dispatch = self._dispatch(dispatch_request)
        if dispatch.get("accepted") is not True and dispatch.get("safe_to_fallback", True):
            self._dispatching._persist_receipt(
                dispatch_request, {"status": "dispatching", "dispatcher": "local_cli"}
            )
            failure = None
            try:
                fallback_body, fallback_dispatcher = self._compose_direct_chat_reply(text, ctx)
            except CliExecutionError as exc:
                failure = exc
                fallback_body, fallback_dispatcher = exc.reply_body(), f"{self._p.tool_name}_cli"
            if fallback_body and (
                not fallback_body.startswith(f"{self._p.display_tool} CLI 暂时没有返回内容")
            ):
                persisted = self._dispatching._persist_receipt(
                    dispatch_request,
                    {
                        **dispatch,
                        "status": "failed" if failure else "completed",
                        "accepted": False if failure else True,
                        "queued": False,
                        "safe_to_fallback": False,
                        "para_tier": 1,
                        "device_scope": "local_device",
                        "dispatcher": fallback_dispatcher,
                        "fallback": fallback_dispatcher,
                        "response": {"text": fallback_body},
                    },
                )
                return self._record_direct_reply(
                    user_msg,
                    fallback_body,
                    {
                        **persisted,
                        "para_tier": 1,
                        "device_scope": "local_device",
                        "fallback": fallback_dispatcher,
                    },
                    failure,
                )
            self._dispatching._persist_receipt(
                dispatch_request, {**dispatch, "safe_to_fallback": True}
            )
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
                "reconciliation_required": dispatch.get("reconciliation_required", False),
                "devices": dispatch.get("devices")
                if isinstance(dispatch.get("devices"), list)
                else [],
            },
        )
        existing_rows = self._read_all_message_rows() if previous_request else []
        existing = next(
            (
                row
                for row in existing_rows
                if int(row.get("user_id") or 0) == int(user_id)
                and row.get("dispatch_request_id") == request_id
                and row.get("kind") == DISPATCHER_MESSAGE_KIND
            ),
            None,
        )
        if existing is not None:
            existing.update(
                {
                    key: value
                    for key, value in dispatcher_msg.items()
                    if key not in {"id", "created_at"}
                }
            )
            self._write_all_message_rows(existing_rows)
        else:
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
        self, *, user_id: int, message: str, context: dict[str, Any] | None = None
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
        ctx = dict(context) if isinstance(context, dict) else {}
        if ctx.get("request_id"):
            # An explicit resume keeps the original remote dispatch even when the
            # caller changes transport to the local streaming endpoint.
            request_id = str(ctx["request_id"])
            with self._messages.dispatch_lock(user_id, request_id):
                previous = self._messages.read_dispatch_request(user_id, request_id)
            if previous and previous.get("dispatch_receipt"):
                result = await asyncio.to_thread(
                    self.invoke, user_id=user_id, message=text, context=ctx
                )
                yield {"type": "done", "result": result}
                return
        self._grant = CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get("force_cli_direct") is True
        ctx.pop(CONTEXT_TOKEN_KEY, None)
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
            fallback_body, dispatcher = self._compose_direct_chat_reply(text, ctx)
            yield {"type": "status", "text": f"已连接 {self._p.display_tool}"}
            for chunk in _chunk_text(fallback_body):
                yield {"type": "token", "text": chunk}
                await asyncio.sleep(0.02)
            yield {"type": "done", "result": {"response": fallback_body, "dispatcher": dispatcher}}
            return
        base_cwd = self._cli_workspace(ctx)
        is_task = self._is_task_intent(text, ctx)
        if is_task and self._dev_loop_enabled() and (self._cli_runner is subprocess.run):
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
            except CliExecutionError as exc:
                yield {"type": "error", **exc.payload()}
            except RECOVERABLE_ERRORS as exc:
                logger.exception("invoke_stream dev_loop failed: %s", exc)
                yield {"type": "error", "message": f"开发任务执行失败：{exc}"}
            return
        prompt = self._cli_prompt(text) if not is_task else self._cli_work_prompt(text, base_cwd)
        yield {"type": "status", "text": f"{self._p.display_tool} 正在思考…"}
        try:
            final_text = ""
            completed = False
            async with aclosing(self._run_cli_streaming(cli_path, prompt, base_cwd)) as stream:
                async for event in stream:
                    if event["type"] == "token":
                        final_text += event["text"]
                        yield event
                    elif event["type"] == "status":
                        yield event
                    elif event["type"] == "done":
                        final_text = event.get("text", final_text)
                        completed = True
                    elif event["type"] == "error":
                        yield event
                        return
            if not completed:
                raise CliExecutionError(
                    f"{self._p.display_tool} CLI 未返回完成回执；请先核对原任务。",
                    partial_output=final_text,
                )
            body = final_text.strip()
            if not body:
                body = f"{self._p.display_tool} CLI 暂时没有返回内容，请确认本机 {self._p.display_tool} 已登录后重试。"
            yield {"type": "done", "result": {"response": body, "dispatcher": "cli_stream"}}
        except CliExecutionError as exc:
            yield {"type": "error", **exc.payload()}
        except RECOVERABLE_ERRORS as exc:
            logger.exception("invoke_stream cli failed: %s", exc)
            yield {"type": "error", "message": f"{self._p.display_tool} CLI 调用失败：{exc}"}

    def _cli_reply_body(self, text: str, context: dict[str, Any]) -> str:
        if str(
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_CHAT_ENABLED") or "1"
        ).strip().lower() in {"0", "false", "off", "disabled"}:
            return ""
        cli_path = self._cli_path()
        if not cli_path:
            return ""
        if (
            self._p.cli_stream_json
            and self._cli_runner is subprocess.run
            and self._conversation_mode_enabled()
            and (not context.get("force_cli_direct"))
        ):
            return self._run_conversation_turn(cli_path, text, context)
        base_cwd = self._cli_workspace(context)
        if not self._is_task_intent(text, context):
            return self._run_cli_once(cli_path, self._cli_prompt(text), base_cwd)
        if self._cli_runner is not subprocess.run or not self._dev_loop_enabled():
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        return self._run_dev_task_loop(cli_path, text, base_cwd, context)

    def _compose_direct_chat_reply(self, text: str, context: dict[str, Any]) -> tuple[str, str]:
        """普通对话直答：FAQ → CLI → 明确不可用提示。"""
        canned = self._direct_reply_body(text)
        if canned:
            return (canned, f"{self._p.tool_name}_direct")
        cli_body = self._cli_reply_body(text, context)
        if cli_body:
            return (cli_body, f"{self._p.tool_name}_cli")
        return (
            f"{self._p.display_tool} CLI 暂时没有返回内容，请确认本机 {self._p.display_tool} 已登录后重试。",
            f"{self._p.tool_name}_cli",
        )

    def _git(self, cwd: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_ASKPASS", "true")
        return subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout, env=env
        )

    def _is_git_repo(self, cwd: str) -> bool:
        return self._git_mgr.is_git_repo(cwd)

    @staticmethod
    def _safe_branch_name(raw: Any) -> str:
        return GitWorkspaceManager.safe_branch_name(raw)

    @classmethod
    def _safe_context_branch(cls, context: dict[str, Any] | None) -> str:
        return GitWorkspaceManager.safe_context_branch(context)

    def _resolve_branch_ref(self, base_cwd: str, branch: str) -> str:
        return self._git_mgr.resolve_branch_ref(base_cwd, branch)

    def _remove_worktree(self, base_cwd: str, wt_path: str) -> None:
        self._git_mgr.remove_worktree(base_cwd, wt_path)

    def _relay_persistent_worktree_path(self) -> str:
        return self._git_mgr.relay_persistent_worktree_path()

    def _commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        return self._git_mgr.commit_and_push(cwd, branch, text)

    def _write_outbox(
        self, request: dict[str, Any], *, status: str, accepted: bool, reason: str
    ) -> dict[str, Any]:
        return self._messages.write_outbox(request, status=status, accepted=accepted, reason=reason)

    def _message_row(
        self,
        *,
        user_id: int,
        role: str,
        body: str,
        created_at: str,
        request_id: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._messages.message_row(
            user_id=user_id,
            role=role,
            body=body,
            created_at=created_at,
            request_id=request_id,
            status=status,
            extra=extra,
        )

    def _append_messages(self, messages: list[dict[str, Any]]) -> None:
        self._messages.append_messages(messages)

    def _read_all_message_rows(self) -> list[dict[str, Any]]:
        return self._messages.read_all_message_rows()

    def _write_all_message_rows(self, rows: list[dict[str, Any]]) -> None:
        self._messages.write_all_message_rows(rows)

    def _public_message(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._messages.public_message(item)

    def _cli_workspace(self, context: dict[str, Any]) -> str:
        return self._execution.cli_workspace(context)

    def _relay_real_workspace(self, context: dict[str, Any]) -> str:
        return self._execution.relay_real_workspace(context)

    def _factory_workspace_root(self) -> str:
        return self._execution.factory_workspace_root()

    def _product_ephemeral_workspace(self) -> str:
        return self._execution.product_ephemeral_workspace()

    def _run_cli_once(self, cli_path: str, prompt: str, cwd: str) -> str:
        return self._cli.run_cli_once(cli_path, prompt, cwd)

    def _run_cli_idle(
        self, cmd: list[str], cwd: str, idle_timeout: float, hard_cap: float
    ) -> tuple[int, str, str, str]:
        return self._cli.run_cli_idle(cmd, cwd, idle_timeout, hard_cap)

    def _run_cli_streaming(
        self, cli_path: str, prompt: str, cwd: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        return self._cli.run_cli_streaming(cli_path, prompt, cwd)

    def _session_get(self, key: str) -> dict[str, Any]:
        return self._sessions.session_get(key)

    def _session_set(self, key: str, value: dict[str, Any]) -> None:
        return self._sessions.session_set(key, value)

    def _ensure_session_workspace(self, key: str) -> tuple[str | None, str | None]:
        return self._sessions.ensure_session_workspace(key)

    def _run_conversation_turn(self, cli_path: str, text: str, context: dict[str, Any]) -> str:
        return self._sessions.run_conversation_turn(cli_path, text, context)

    def _prepare_worktree(
        self, base_cwd: str, text: str, branch_hint: str = ""
    ) -> tuple[str, str] | None:
        return self._development.prepare_worktree(base_cwd, text, branch_hint)

    def _prepare_persistent_worktree(
        self, base_cwd: str, wt_path: str, branch: str
    ) -> tuple[str, str] | None:
        return self._development.prepare_persistent_worktree(base_cwd, wt_path, branch)

    def _verify_workspace(self, cwd: str) -> tuple[bool, str]:
        return self._development.verify_workspace(cwd)

    def _run_dev_task_loop(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        return self._development.run_dev_task_loop(cli_path, text, base_cwd, context)

    def _run_dev_task_loop_locked(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        return self._development.run_dev_task_loop_locked(cli_path, text, base_cwd, context)

    def _default_http_client(self) -> httpx.Client:
        return self._para.default_http_client()

    def _para_token(self, client: httpx.Client, api_url: str) -> str:
        return self._para.para_token(client, api_url)

    def _para_request(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._para.para_request(client, api_url, token, method, path, json_body=json_body)

    def _fetch_para_task(self, task_id: str) -> dict[str, Any] | None:
        return self._para.fetch_para_task(task_id)

    def _build_dispatch_request(
        self,
        *,
        request_id: str,
        created_at: str,
        user_id: int,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return self._dispatching.build_dispatch_request(
            request_id=request_id,
            created_at=created_at,
            user_id=user_id,
            message=message,
            context=context,
        )

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._dispatching.dispatch(request)

    def _dispatch_to_para(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        return self._dispatching.dispatch_to_para(request)

    def _ensure_para_device(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        device: dict[str, Any],
    ) -> dict[str, Any]:
        return self._dispatching.ensure_para_device(client, api_url, token, device)

    def _create_para_task(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        request: dict[str, Any],
        devices: list[dict[str, Any]],
        tier: int = 2,
    ) -> dict[str, Any]:
        return self._dispatching.create_para_task(client, api_url, token, request, devices, tier)

    def _sync_para_task_updates(self, *, user_id: int, rows: list[dict[str, Any]]) -> None:
        return self._sync.sync_para_task_updates(user_id=user_id, rows=rows)

    def _upgrade_legacy_dispatcher_row(self, row: dict[str, Any]) -> bool:
        return self._sync.upgrade_legacy_dispatcher_row(row)

    def _upsert_direct_reply_messages(self, *, user_id: int, rows: list[dict[str, Any]]) -> bool:
        return self._sync.upsert_direct_reply_messages(user_id=user_id, rows=rows)

    def _refresh_dispatcher_row(self, row: dict[str, Any], task: dict[str, Any]) -> bool:
        return self._sync.refresh_dispatcher_row(row, task)

    def _upsert_result_messages(
        self,
        *,
        user_id: int,
        dispatch_row: dict[str, Any],
        task: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> bool:
        return self._sync.upsert_result_messages(
            user_id=user_id, dispatch_row=dispatch_row, task=task, rows=rows
        )


__all__ = [
    "DISPATCHER_MESSAGE_KIND",
    "CODEX_PROFILE",
    "CLAUDE_PROFILE",
    "CURSOR_PROFILE",
    "TRAE_PROFILE",
    "SuperEmployeeService",
    "SuperEmployeeToolProfile",
]
