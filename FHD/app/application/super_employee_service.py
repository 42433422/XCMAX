"""Generic super-employee dispatch channel (Codex / Claude / ...).

This is the shared engine behind every "超级员工" entity. A concrete tool
(Codex, Claude, ...) is described by a :class:`SuperEmployeeToolProfile`; the
service logic — persisting software-internal calls, optionally dispatching them
to the Para/DevFleet multi-device scheduler (排比), polling task status and
writing back results — is identical across tools.

Codex behaviour is preserved verbatim through ``CODEX_PROFILE`` so the existing
``CodexSuperEmployeeService`` is a thin subclass with no behavioural change.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

DEFAULT_PARA_API_URL = "http://127.0.0.1:3001"
DISPATCHER_MESSAGE_KIND = "dispatcher"

# Para guest-token 模块级缓存。devfleet 对 /api/auth/guest 限 15min 30 次
# (authLimiter)，原来每次 invoke 都新登 → 用户连发几十条消息就触发
# "登录请求过于频繁，请稍后重试" 429。缓存按 (api_url, env_super_prefix) 隔离，
# TTL 远短于 token 真实寿命，到期重登；任何错误立即清缓存避免脏 token。
_PARA_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_PARA_TOKEN_TTL = float(os.environ.get("MODSTORE_PARA_TOKEN_TTL_SEC") or "600")

PARA_TERMINAL_TASK_STATUSES = {"completed", "failed", "merged", "merge_conflict", "cancelled"}
TASK_ID_RE = re.compile(r"任务\s*ID[:：]\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})")

# 任务类关键词：命中则走 Para 多设备派工，否则走 CLI 直答。工具无关，共享。
_TASK_MARKERS: tuple[str, ...] = (
    "修复",
    "修改",
    "改一下",
    "改成",
    "实现",
    "新增",
    "加一个",
    "接入",
    "打通",
    "任务",
    "测试",
    "验证",
    "跑测试",
    "测试一下",
    "验证一下",
    "打包",
    "构建",
    "build",
    "提交",
    "commit",
    "push",
    "上传git",
    "部署",
    "发布",
    "合并",
    "开分支",
    "派工",
    "调用",
    "调用所有设备",
    "多设备",
    "回写日志",
    "检查当前工作区",
)
# 多设备分工标签，工具无关，共享。
_SUBTASK_LABELS: tuple[str, ...] = ("需求定位与方案", "核心实现", "验证与收尾")


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _codex_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    return [
        cli_path,
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-last-message",
        str(output_path),
        "-C",
        cwd,
        prompt,
    ]


def _claude_cli_command(cli_path: str, prompt: str, output_path: Path, cwd: str) -> list[str]:
    # Claude Code 无头模式（print）。stream-json：工作时持续吐事件(工具调用/文本)，
    # 作为"还在干活"的心跳，配合 idle-timeout 实现"只要在工作就不超时"。
    # stream-json 在 print 模式需 --verbose。acceptEdits 允许在 cwd 内改/建文件。
    perm = (
        os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
    ).strip() or "acceptEdits"
    return [
        cli_path,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        perm,
        prompt,
    ]


@dataclass(frozen=True)
class SuperEmployeeToolProfile:
    """A concrete super-employee tool's identity + dispatch configuration."""

    employee_id: str
    employee_name: str
    display_tool: str  # 用户可见的工具名，如 "Codex" / "Claude"
    tool_name: str  # Para devTool / toolName，如 "codex" / "claude"
    capability_key: str  # Para 设备能力键，如 "codex_cli" / "claude_cli"
    storage_subdir: str  # 持久化子目录
    result_kind: str  # 结果消息 kind
    direct_kind: str  # 直答消息 kind
    env_super_prefix: str  # 形如 "XCMAX_CODEX_SUPER_EMPLOYEE"
    env_tool_prefix: str  # 形如 "XCMAX_CODEX"
    cli_binary: str  # 可执行名，用于 shutil.which
    cli_extra_candidates: tuple[str, ...] = ()
    cli_reads_output_file: bool = True  # 是否从 --output-last-message 文件读结果
    cli_stream_json: bool = False  # stdout 是否为 stream-json(逐事件)，需解析出最终回复
    cli_command_builder: Callable[[str, str, Path, str], list[str]] = _codex_cli_command


CODEX_PROFILE = SuperEmployeeToolProfile(
    employee_id="codex-super-employee",
    employee_name="超级员工-Codex",
    display_tool="Codex",
    tool_name="codex",
    capability_key="codex_cli",
    storage_subdir="codex_super_employee",
    result_kind="codex_result",
    direct_kind="codex_direct",
    env_super_prefix="XCMAX_CODEX_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_CODEX",
    cli_binary="codex",
    cli_extra_candidates=("/Applications/Codex.app/Contents/Resources/codex",),
    cli_reads_output_file=True,
    cli_command_builder=_codex_cli_command,
)

CLAUDE_PROFILE = SuperEmployeeToolProfile(
    employee_id="claude-super-employee",
    employee_name="超级员工-Claude",
    display_tool="Claude",
    tool_name="claude_code",
    capability_key="claude_cli",
    storage_subdir="claude_super_employee",
    result_kind="claude_result",
    direct_kind="claude_direct",
    env_super_prefix="XCMAX_CLAUDE_SUPER_EMPLOYEE",
    env_tool_prefix="XCMAX_CLAUDE",
    cli_binary="claude",
    cli_extra_candidates=(
        os.path.expanduser("~/.claude/local/claude"),
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ),
    cli_reads_output_file=False,
    cli_stream_json=True,
    cli_command_builder=_claude_cli_command,
)


class SuperEmployeeService:
    """Persist software-internal tool calls and optionally dispatch them out."""

    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._p = profile
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._root = root / profile.storage_subdir
        self._root.mkdir(parents=True, exist_ok=True)
        self._messages_path = self._root / "messages.jsonl"
        self._outbox_dir = self._root / "outbox"
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cli_runner = cli_runner or subprocess.run

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
            direct_body = self._cli_reply_body(text, ctx) or self._direct_reply_body(text)
            if not direct_body:
                direct_body = (
                    f"{self._p.display_tool} CLI 暂时没有返回内容，"
                    f"请确认本机 {self._p.display_tool} 已登录后重试。"
                )
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
                "dispatcher": f"{self._p.tool_name}_cli",
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
            fallback_body = self._cli_reply_body(text, ctx)
            if fallback_body:
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
                        "fallback": f"{self._p.tool_name}_cli",
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

    # ── 派工请求构建 ──

    def _build_dispatch_request(
        self,
        *,
        request_id: str,
        created_at: str,
        user_id: int,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        workspace_root = str(
            context.get("workspace_root")
            or os.environ.get(f"{self._p.env_tool_prefix}_WORKSPACE_ROOT")
            or os.environ.get("MODSTORE_PARA_WORKSPACE_ROOT")
            or os.environ.get("MODSTORE_REPO_ROOT")
            or ""
        ).strip()
        raw_source = str(context.get("source") or "admin_im").strip().lower()
        source = "xcagi_mobile_im" if raw_source.startswith("mobile") else "xcagi_admin_im"
        return {
            "request_id": request_id,
            "created_at": created_at,
            "source": source,
            "employee_id": self._p.employee_id,
            "employee_name": self._p.employee_name,
            "mode": str(context.get("mode") or "code"),
            "device_scope": "all_devices",
            "target_devices": context.get("target_devices")
            if isinstance(context.get("target_devices"), list)
            else ["all"],
            "user_id": user_id,
            "title": message[:120],
            "task": message,
            "prompt": message,
            "workspace_root": workspace_root,
            "raw_context": context,
        }

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = (
            (
                os.environ.get(f"{self._p.env_super_prefix}_DISPATCH_MODE")
                or os.environ.get("MODSTORE_PARA_DISPATCH_MODE")
                or "auto"
            )
            .strip()
            .lower()
        )
        if mode in {"auto", "para", "devfleet", "mcp"}:
            para_dispatch, para_reason = self._dispatch_to_para(request)
            if para_dispatch is not None:
                return para_dispatch
            if mode != "auto":
                return self._write_outbox(
                    request,
                    status="queued",
                    accepted=False,
                    reason=para_reason or "para_dispatcher_unavailable",
                )
        else:
            para_reason = ""

        if mode == "outbox":
            return self._write_outbox(
                request,
                status="queued",
                accepted=False,
                reason="dispatch_mode_outbox",
            )

        webhook = (
            os.environ.get(f"{self._p.env_super_prefix}_WEBHOOK")
            or os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK")
            or ""
        ).strip()
        if not webhook:
            return self._write_outbox(
                request,
                status="queued",
                accepted=False,
                reason=para_reason or f"{self._p.tool_name}_dispatch_webhook_not_configured",
            )
        try:
            with self._http_client_factory() as client:
                resp = client.post(webhook, json=request)
            body: Any
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {"raw": resp.text[:1000]}
            accepted = resp.status_code < 400 and (
                body.get("ok") is True
                or body.get("success") is True
                or body.get("accepted") is True
            )
            if accepted:
                return {
                    "request_id": request["request_id"],
                    "status": "accepted",
                    "accepted": True,
                    "queued": False,
                    "device_scope": "all_devices",
                    "response": body,
                }
            return self._write_outbox(
                request,
                status="dispatch_failed",
                accepted=False,
                reason=str(body.get("error") or body.get("message") or f"HTTP {resp.status_code}")[
                    :500
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return self._write_outbox(
                request,
                status="dispatch_error",
                accepted=False,
                reason=str(exc)[:500],
            )

    def _dispatch_to_para(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        api_url = self._para_api_url()
        if not api_url:
            return None, "para_dispatcher_disabled"

        try:
            with self._http_client_factory() as client:
                health = client.get(f"{api_url}/api/health")
                if health.status_code >= 400:
                    return None, f"para_api_unhealthy_http_{health.status_code}"

                token = self._para_token(client, api_url)
                devices_body = self._para_request(client, api_url, token, "GET", "/api/devices")
                devices = devices_body.get("devices") if isinstance(devices_body, dict) else []
                tier, selected = self._select_devices_by_tier(
                    devices if isinstance(devices, list) else [], request
                )
                if not selected:
                    return self._write_outbox(
                        request,
                        status="queued",
                        accepted=False,
                        reason=f"para_no_online_{self._p.tool_name}_device",
                    ), f"para_no_online_{self._p.tool_name}_device"

                prepared = []
                for device in selected:
                    prepared.append(self._ensure_para_device(client, api_url, token, device))

                return (
                    self._create_para_task(client, api_url, token, request, prepared, tier=tier),
                    "",
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            return None, f"para_api_unreachable: {exc}"
        except Exception as exc:  # noqa: BLE001
            return self._write_outbox(
                request,
                status="dispatch_error",
                accepted=False,
                reason=f"para_dispatch_error: {str(exc)[:460]}",
            ), str(exc)[:500]

    def _default_http_client(self) -> httpx.Client:
        timeout = float(
            os.environ.get(f"{self._p.env_tool_prefix}_DISPATCH_TIMEOUT_SEC")
            or os.environ.get(f"{self._p.env_tool_prefix}_WEBHOOK_TIMEOUT_SEC")
            or "30"
        )
        return httpx.Client(timeout=timeout)

    def _para_api_url(self) -> str:
        value = (
            (
                os.environ.get(f"{self._p.env_super_prefix}_PARA_API_URL")
                or os.environ.get("MODSTORE_PARA_API_URL")
                or os.environ.get("DEVFLEET_API_URL")
                or DEFAULT_PARA_API_URL
            )
            .strip()
            .rstrip("/")
        )
        if value.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return ""
        return value

    def _para_token(self, client: httpx.Client, api_url: str) -> str:
        token = (
            os.environ.get(f"{self._p.env_super_prefix}_PARA_TOKEN")
            or os.environ.get("MODSTORE_PARA_TOKEN")
            or os.environ.get("DEVFLEET_TOKEN")
            or ""
        ).strip()
        if token:
            return token
        cache_key = (api_url, self._p.env_super_prefix)
        cached = _PARA_TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]
        resp = client.post(f"{api_url}/api/auth/guest", json={})
        body = self._json_response(resp)
        if resp.status_code >= 400:
            _PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError(
                self._error_message(body, f"Para guest 登录失败 ({resp.status_code})")
            )
        token = str(body.get("token") or body.get("access_token") or "").strip()
        if not token:
            _PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError("Para guest 登录未返回 token")
        _PARA_TOKEN_CACHE[cache_key] = (token, time.time() + _PARA_TOKEN_TTL)
        return token

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
        resp = client.request(
            method,
            f"{api_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
        body = self._json_response(resp)
        if resp.status_code >= 400:
            raise RuntimeError(self._error_message(body, f"Para API 请求失败 ({resp.status_code})"))
        return body

    def _device_eligible(self, item: Any) -> bool:
        """单台设备能否承接派工：在线 + 目标工具已装且非占用 + 具备能力。

        一级(本机单设备)与二级(多设备)选择共用此判定；不含 target_devices
        过滤(由各调用方按需另行处理)。
        """
        if not isinstance(item, dict):
            return False
        if str(item.get("status") or "") != "online":
            return False
        tool = self._device_tool(item, self._p.tool_name)
        if tool and str(tool.get("status") or "") == "not_installed":
            return False
        if tool and str(tool.get("status") or "") == "running" and tool.get("currentTask"):
            return False
        capabilities = (
            item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        )
        if not tool and capabilities.get(self._p.capability_key) is not True:
            return False
        return True

    def _select_para_devices(
        self,
        devices: list[Any],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        target_devices = request.get("target_devices")
        targets = (
            {str(item).strip() for item in target_devices if str(item).strip()}
            if isinstance(target_devices, list)
            else {"all"}
        )
        candidates: list[dict[str, Any]] = []
        for item in devices:
            if not self._device_eligible(item):
                continue
            if (
                "all" not in targets
                and str(item.get("id") or "") not in targets
                and str(item.get("name") or "") not in targets
            ):
                continue
            candidates.append(item)

        workers = [item for item in candidates if not item.get("isPrimary")]
        selected = workers or candidates
        max_devices = self._max_para_devices(request)
        return selected[:max_devices]

    # ── Para 分级派工：一级=本机单设备，二级=多设备协同 ──
    #
    # 「本机 CLI」并入 Para 后不再是绕开派工的进程内旁路，而是 Para 派工状态机里
    # 的显式一级状态(para_tier=1)：把任务派给一台在线的本机/主设备，与二级走同一
    # 条 /api/tasks 管线。默认一级优先，仅当任务确需多设备并行/分工、或本机无可用
    # 设备、或调用方显式要求时升二级。设备的配对(bind_code)与 e2e-agent 拉起属于
    # DevFleet/运维侧，FHD 只消费已在线的设备、不伪造设备行。

    def _local_device_id(self) -> str:
        """配置的本机设备 ID(可选)。未配则按 is_primary / 首台合格设备兜底。"""
        return (
            os.environ.get(f"{self._p.env_super_prefix}_DEVICE_ID")
            or os.environ.get("MODSTORE_PARA_DEVICE_ID")
            or os.environ.get("DEVFLEET_DEVICE_ID")
            or ""
        ).strip()

    def _resolve_para_tier(self, request: dict[str, Any]) -> int:
        """决定该请求走一级(1)还是二级(2)。默认一级，按需升二级。"""
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        forced = (
            (
                os.environ.get(f"{self._p.env_super_prefix}_PARA_FORCE_TIER")
                or os.environ.get("MODSTORE_PARA_FORCE_TIER")
                or ""
            )
            .strip()
            .lower()
        )
        if forced in {"1", "local", "single", "本机"}:
            return 1
        if forced in {"2", "fleet", "multi", "多设备"}:
            return 2

        tier_hint = (
            str(raw_context.get("para_tier") or raw_context.get("tier") or "").strip().lower()
        )
        if tier_hint in {"2", "fleet", "multi", "multi_device", "多设备"}:
            return 2
        if tier_hint in {"1", "local", "single", "本机"}:
            return 1

        if raw_context.get("escalate") in (True, 1, "1", "true", "yes", "on"):
            return 2
        try:
            if int(raw_context.get("max_devices") or 0) > 1:
                return 2
        except (TypeError, ValueError):
            pass

        target = request.get("target_devices")
        if isinstance(target, list):
            specific = [s for s in (str(x).strip() for x in target) if s and s != "all"]
            if len(specific) > 1:
                return 2

        text = f"{request.get('task') or ''} {request.get('prompt') or ''}"
        if any(m in text for m in ("多设备", "所有设备", "全部设备", "调用所有设备", "跨设备")):
            return 2
        return 1

    def _select_local_device(
        self,
        devices: list[Any],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """一级：只挑「本机」一台设备。

        本机识别优先级：① 配置的本机 device_id；② is_primary 主设备；③ 都无从
        识别时退而取首台合格设备(单设备派工)。识别到的本机若不合格(离线/工具未装/
        占用)则返回空，由上层 _select_devices_by_tier 升二级到其它设备——这正是
        「本机无 CLI → 升二级」的语义所在。
        """
        local_id = self._local_device_id()
        if local_id:
            for item in devices:
                if isinstance(item, dict) and str(item.get("id") or "") == local_id:
                    return [item] if self._device_eligible(item) else []
            return []  # 配了本机 id 但不在设备列表 → 本机不可用, 交由升二级

        for item in devices:
            if isinstance(item, dict) and item.get("isPrimary"):
                return [item] if self._device_eligible(item) else []

        for item in devices:
            if self._device_eligible(item):
                return [item]
        return []

    def _select_devices_by_tier(
        self,
        devices: list[Any],
        request: dict[str, Any],
    ) -> tuple[int, list[dict[str, Any]]]:
        """按 tier 选设备，返回 (实际 tier, 选中设备列表)。

        一级优先：先选本机单设备；本机无合格设备则自动升二级选多设备。
        """
        tier = self._resolve_para_tier(request)
        if tier == 1:
            local = self._select_local_device(devices, request)
            if local:
                return 1, local
            # 一级想跑但本机无可用设备 → 升二级
            return 2, self._select_para_devices(devices, request)
        return 2, self._select_para_devices(devices, request)

    def _ensure_para_device(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        device: dict[str, Any],
    ) -> dict[str, Any]:
        if str(device.get("devTool") or "") == self._p.tool_name:
            return device
        device_id = str(device.get("id") or "")
        if not device_id:
            return device
        body = self._para_request(
            client,
            api_url,
            token,
            "PUT",
            f"/api/devices/{device_id}/dev-tool",
            json_body={"devTool": self._p.tool_name},
        )
        updated = body.get("device")
        return updated if isinstance(updated, dict) else {**device, "devTool": self._p.tool_name}

    def _create_para_task(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        request: dict[str, Any],
        devices: list[dict[str, Any]],
        tier: int = 2,
    ) -> dict[str, Any]:
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        title = str(request.get("title") or f"{self._p.employee_name} 任务").strip()[:120]
        branch = (
            str(
                raw_context.get("branch") or os.environ.get("MODSTORE_PARA_BASE_BRANCH") or "main"
            ).strip()
            or "main"
        )
        repo_url = str(
            raw_context.get("repo_url")
            or os.environ.get("MODSTORE_PARA_REPO_URL")
            or os.environ.get("DEVFLEET_REPO_URL")
            or ""
        ).strip()
        task_id = ""
        task: dict[str, Any] | None = None
        dispatched: list[dict[str, Any]] = []

        for index, device in enumerate(devices):
            body: dict[str, Any] = {
                "title": title,
                "prompt": self._para_prompt(request, device, index, len(devices)),
                "device_id": str(device.get("id") or ""),
                "branch": branch,
                "subtask_title": self._para_subtask_title(title, index, len(devices)),
                "max_attempts": 3,
            }
            if repo_url:
                body["repo_url"] = repo_url
            if task_id:
                body["task_id"] = task_id

            result = self._para_request(
                client, api_url, token, "POST", "/api/tasks", json_body=body
            )
            task = result.get("task") if isinstance(result.get("task"), dict) else task
            task_id = str((task or {}).get("id") or task_id)
            subtask = result.get("subtask") if isinstance(result.get("subtask"), dict) else {}
            dispatched.append(
                {
                    "device_id": str(device.get("id") or ""),
                    "device_name": str(device.get("name") or ""),
                    "subtask_id": str(subtask.get("id") or ""),
                    "tool": self._p.tool_name,
                }
            )

        return {
            "request_id": request["request_id"],
            "status": "accepted",
            "accepted": True,
            "queued": False,
            "para_tier": tier,
            "device_scope": "local_device" if tier == 1 else "all_devices",
            "dispatcher": "para_api",
            "mcp_tool_equivalent": "devfleet_dispatch_task",
            "api_url": api_url,
            "task_id": task_id,
            "task_status": str((task or {}).get("status") or ""),
            "devices": dispatched,
            "response": {"task": task, "dispatched": dispatched},
        }

    def _para_prompt(
        self,
        request: dict[str, Any],
        device: dict[str, Any],
        index: int,
        total: int,
    ) -> str:
        prompt = str(request.get("prompt") or request.get("task") or "").strip()
        workspace_root = str(request.get("workspace_root") or "").strip()
        if total <= 1:
            suffix = "请直接完成该任务，提交到调度器分配的工作分支，并回写执行日志。"
        else:
            suffix = (
                f"你是第 {index + 1}/{total} 台 {self._p.display_tool} 工作设备"
                f"（{device.get('name') or device.get('id')}）。"
                "请承担可独立完成的部分，避免和其他设备重复改同一批文件；"
                "提交到调度器分配的工作分支，并回写执行日志。"
            )
        parts = [prompt, suffix]
        if workspace_root:
            parts.append(f"管理端来源工作区：{workspace_root}")
        return "\n\n".join(part for part in parts if part)

    def _para_subtask_title(self, title: str, index: int, total: int) -> str:
        if total <= 1:
            return title
        label = _SUBTASK_LABELS[index] if index < len(_SUBTASK_LABELS) else f"工作单元 {index + 1}"
        return f"{label}：{title[:60]}"

    def _max_para_devices(self, request: dict[str, Any]) -> int:
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        value = (
            raw_context.get("max_devices")
            or os.environ.get(f"{self._p.env_super_prefix}_MAX_DEVICES")
            or 3
        )
        try:
            return max(1, min(8, int(value)))
        except (TypeError, ValueError):
            return 3

    def _device_tool(self, device: dict[str, Any], name: str) -> dict[str, Any] | None:
        tools = device.get("tools")
        if not isinstance(tools, list):
            return None
        for tool in tools:
            if isinstance(tool, dict) and tool.get("toolName") == name:
                return tool
        return None

    def _json_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"raw": resp.text[:1000]}
        return body if isinstance(body, dict) else {"data": body}

    def _error_message(self, body: dict[str, Any], fallback: str) -> str:
        return str(body.get("error") or body.get("message") or fallback)[:500]

    def _write_outbox(
        self,
        request: dict[str, Any],
        *,
        status: str,
        accepted: bool,
        reason: str,
    ) -> dict[str, Any]:
        path = (
            self._outbox_dir
            / f"{request['created_at'].replace(':', '').replace('+', 'Z')}-{request['request_id']}.json"
        )
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "request_id": request["request_id"],
            "status": status,
            "accepted": accepted,
            "queued": True,
            "device_scope": "all_devices",
            "reason": reason,
            "outbox_path": str(path),
        }

    def _dispatch_reply(self, dispatch: dict[str, Any]) -> str:
        # 统一对外提示为"思考中..."，避免暴露派工细节导致用户误以为卡住。
        # 派工细节仍保留在 dispatch 字典中供前端/日志使用。
        _ = dispatch  # 保留参数签名兼容性
        return "思考中..."

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
        row = {
            "id": uuid.uuid4().hex,
            "user_id": int(user_id),
            "role": role,
            "body": body,
            "created_at": created_at,
            "dispatch_request_id": request_id,
            "status": status,
        }
        if extra:
            row.update({k: v for k, v in extra.items() if v not in (None, "")})
        return row

    def _append_messages(self, messages: list[dict[str, Any]]) -> None:
        with self._messages_path.open("a", encoding="utf-8") as fh:
            for msg in messages:
                fh.write(_safe_json_line(msg))

    def _read_all_message_rows(self) -> list[dict[str, Any]]:
        if not self._messages_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self._messages_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _write_all_message_rows(self, rows: list[dict[str, Any]]) -> None:
        with self._messages_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(_safe_json_line(row))

    def _sync_para_task_updates(self, *, user_id: int, rows: list[dict[str, Any]]) -> None:
        changed = False
        synced = 0
        direct_request_ids = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.direct_kind
        }
        result_request_ids = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.result_kind
        }
        result_task_ids = {
            str(item.get("task_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == self._p.result_kind
        }
        for row in reversed(list(rows)):
            if int(row.get("user_id") or 0) != int(user_id):
                continue
            changed = self._upgrade_legacy_dispatcher_row(row) or changed
            if str(row.get("kind") or "") != DISPATCHER_MESSAGE_KIND:
                continue
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                continue
            request_id = str(row.get("dispatch_request_id") or "")
            if request_id and request_id in direct_request_ids:
                continue
            task_status = str(row.get("task_status") or row.get("status") or "").strip()
            if task_status in PARA_TERMINAL_TASK_STATUSES and (
                (request_id and request_id in result_request_ids) or task_id in result_task_ids
            ):
                continue
            if synced >= 8:
                break
            task = self._fetch_para_task(task_id)
            synced += 1
            if not task:
                continue
            changed = self._refresh_dispatcher_row(row, task) or changed
            changed = (
                self._upsert_result_messages(
                    user_id=int(user_id),
                    dispatch_row=row,
                    task=task,
                    rows=rows,
                )
                or changed
            )
        if changed:
            self._write_all_message_rows(rows)

    def _upgrade_legacy_dispatcher_row(self, row: dict[str, Any]) -> bool:
        if str(row.get("kind") or "") == DISPATCHER_MESSAGE_KIND:
            return False
        if str(row.get("role") or "") != "assistant":
            return False
        body = str(row.get("body") or "")
        if not self._is_dispatcher_ack_body(body):
            return False
        row["role"] = "system"
        row["kind"] = DISPATCHER_MESSAGE_KIND
        task_id = self._extract_task_id_from_body(body)
        if task_id and not row.get("task_id"):
            row["task_id"] = task_id
        return True

    def _is_dispatcher_ack_body(self, body: str) -> bool:
        markers = (
            "多设备调度器",
            "调用队列",
            "调度通道",
            f"未发现在线可用 {self._p.display_tool} 设备",
            "任务已派发到",
            f"Para/{self._p.display_tool}",
        )
        return any(marker in body for marker in markers)

    def _extract_task_id_from_body(self, body: str) -> str:
        match = TASK_ID_RE.search(body)
        return match.group(1).strip() if match else ""

    def _should_reply_with_cli(self, text: str, context: dict[str, Any]) -> bool:
        # 全局开关：所有 claude.invoke/codex.invoke 都走 FHD 进程内 CLI 直答，
        # 绕开 Para 派工（watchdog token 不可用时的兜底路径）。FHD 进程继承
        # 用户 Terminal 的 claude/codex 鉴权，无需额外配置。env: XCMAX_<TOOL>_FORCE_CLI_DIRECT=1。
        force_direct = (
            (
                os.environ.get(f"{self._p.env_tool_prefix}_FORCE_CLI_DIRECT")
                or os.environ.get("XCMAX_FORCE_CLI_DIRECT")
                or ""
            )
            .strip()
            .lower()
        )
        if force_direct in {"1", "true", "yes", "on"}:
            return True
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return True
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return False
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        return not any(marker in normalized for marker in _TASK_MARKERS)

    def _cli_reply_body(self, text: str, context: dict[str, Any]) -> str:
        if str(
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_CHAT_ENABLED") or "1"
        ).strip().lower() in {
            "0",
            "false",
            "off",
            "disabled",
        }:
            return ""
        cli_path = self._cli_path()
        if not cli_path:
            return ""
        # 口袋 Claude Code：claude 生产路径走"持久会话续接 + 隔离工作区"——有上下文、能动手、
        # 体验接近直接和 Claude Code 交互。codex / 测试注入仍走原"闲聊 or dev-loop"逻辑。
        if (
            self._p.cli_stream_json
            and self._cli_runner is subprocess.run
            and self._conversation_mode_enabled()
        ):
            return self._run_conversation_turn(cli_path, text, context)
        base_cwd = self._cli_workspace(context)
        # 闲聊→只答不改；开发任务→生产环境走 coding→view→push 闭环(隔离 worktree)，
        # 测试注入或显式关闭(_DEV_LOOP=0)时退回"只改不推"的简单路径。
        if not self._is_task_intent(text, context):
            return self._run_cli_once(cli_path, self._cli_prompt(text), base_cwd)
        if self._cli_runner is not subprocess.run or not self._dev_loop_enabled():
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        return self._run_dev_task_loop(cli_path, text, base_cwd)

    # ===== 口袋 Claude Code：持久会话续接 + 隔离工作区 =====

    def _conversation_mode_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_CONVERSATION")
                or os.environ.get("XCMAX_CLAUDE_CONVERSATION")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def _session_store_path(self) -> Path:
        return Path(get_app_data_dir()) / self._p.storage_subdir / "cli_sessions.json"

    def _session_get(self, key: str) -> dict[str, Any]:
        try:
            data = json.loads(self._session_store_path().read_text(encoding="utf-8"))
            rec = data.get(key) if isinstance(data, dict) else None
            return rec if isinstance(rec, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _session_set(self, key: str, value: dict[str, Any]) -> None:
        p = self._session_store_path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            data = {}
        data[key] = value
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("写 session store 失败", exc_info=True)

    def _session_key(self, context: dict[str, Any]) -> str:
        """会话键：手机端是单一 pinned 会话，按工具名即可隔离 claude/codex 各自一条续接会话。"""
        conv = str((context or {}).get("conversation_id") or "").strip()
        return f"{self._p.tool_name}:{conv}" if conv else self._p.tool_name

    def _ensure_session_workspace(self, key: str) -> tuple[str | None, str | None]:
        """持久隔离工作区：同一会话复用一个 git worktree（不碰 live checkout、不破坏运行中的 FHD）。"""
        rec = self._session_get(key)
        wt = str(rec.get("workspace") or "")
        branch = str(rec.get("branch") or "")
        if wt and Path(wt).exists():
            return wt, branch
        base = self._cli_workspace({})
        if not self._is_git_repo(base):
            return None, None
        slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-") or "session"
        if not branch:
            branch = f"super-employee/{self._p.tool_name}/{slug}"
        wt = str(Path(get_app_data_dir()) / self._p.storage_subdir / f"ws-{slug}")
        try:
            self._git(base, "worktree", "remove", "--force", wt, timeout=30)
        except Exception:  # noqa: BLE001
            pass
        has_branch = (
            self._git(base, "rev-parse", "--verify", "--quiet", branch, timeout=15).returncode == 0
        )
        if has_branch:
            r = self._git(base, "worktree", "add", "--force", wt, branch, timeout=180)
        else:
            r = self._git(base, "worktree", "add", "-b", branch, wt, "HEAD", timeout=180)
        if r.returncode != 0:
            logger.warning("会话工作区创建失败: %s", (r.stderr or r.stdout)[:200])
            return None, None
        rec["workspace"] = wt
        rec["branch"] = branch
        self._session_set(key, rec)
        return wt, branch

    def _conversation_prompt(self, text: str, cwd: str, resuming: bool) -> str:
        if resuming:
            # 续接：claude 已有完整上下文 + 身份，直接发用户原话（像和同事接着聊）。
            return text.strip()
        return (
            f"你是 XCMAX 内的{self._p.employee_name}，像 Claude Code 一样在项目工作区里工作："
            "可以读取/创建/修改文件、运行命令、用 git；用户让你改代码就直接动手，不要只解释。"
            "但普通对话直接回应即可、不要主动遍历整个项目（需要改代码时再读相关文件）；"
            "保持上下文连续，像和同事聊天那样自然。"
            f"\n\n工作区：{cwd}\n\n用户：{text.strip()}"
        )

    def _parse_stream_json_full(self, out: str) -> tuple[str, str]:
        """从 stream-json 取 (最终回复, session_id)。session_id 取最后出现的(result 事件含)。"""
        text = self._parse_claude_stream_json(out)
        sid = ""
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("session_id"):
                sid = str(ev.get("session_id") or "")
        return text, sid

    def _conversation_perm(self) -> str:
        # 默认 acceptEdits：可对话+读写改文件(覆盖大部分 Claude Code 用法)，但不自动跑任意命令，
        # 避免在工程根误伤运行中的 FHD。要全自动(跑命令/git)可 env 切 bypassPermissions。
        return (
            os.environ.get("DEVFLEET_CLAUDE_PERMISSION_MODE") or "acceptEdits"
        ).strip() or "acceptEdits"

    def _conversation_cmd(
        self, cli_path: str, prompt: str, resume_session_id: str | None
    ) -> list[str]:
        cmd = [
            cli_path,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            self._conversation_perm(),
        ]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        cmd.append(prompt)
        return cmd

    def _run_conversation_turn(self, cli_path: str, text: str, context: dict[str, Any]) -> str:
        key = self._session_key(context)
        # 像 Claude Code 一样直接在工程根工作：零额外磁盘(不建 536M/会话的 worktree)、
        # 改动你审了再落地(底部 git 键)。上下文靠 claude session 续接，不靠工作区隔离。
        cwd = self._cli_workspace(context)
        rec = self._session_get(key)
        session_id = str(rec.get("session_id") or "").strip()
        idle_timeout = self._cli_idle_timeout_seconds()
        hard_cap = self._cli_hard_cap_seconds()

        def _run(prompt: str, resume: str | None) -> tuple[int, str, str, str]:
            cmd = self._conversation_cmd(cli_path, prompt, resume)
            return self._run_cli_idle(cmd, cwd, idle_timeout, hard_cap)

        try:
            returncode, stdout, stderr, killed = _run(
                self._conversation_prompt(text, cwd, bool(session_id)),
                session_id or None,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
        body, new_sid = self._parse_stream_json_full(stdout)
        # resume 失效(会话被清/找不到)兜底：清掉 session_id，按新会话重来一次。
        if session_id and not body and not killed:
            low = (stderr + stdout).lower()
            if "no conversation" in low or "session" in low or returncode != 0:
                rec["session_id"] = ""
                self._session_set(key, rec)
                try:
                    returncode, stdout, stderr, killed = _run(
                        self._conversation_prompt(text, cwd, False), None
                    )
                    body, new_sid = self._parse_stream_json_full(stdout)
                except (OSError, subprocess.SubprocessError):
                    pass
        if killed.startswith("idle"):
            return f"{self._p.display_tool} 静默 {idle_timeout:g} 秒判定卡住已结束，请重试。"
        if killed.startswith("hardcap"):
            return f"{self._p.display_tool} 运行超过上限 {hard_cap:g} 秒已停止，请把任务拆小。"
        if new_sid and new_sid != session_id:
            rec["session_id"] = new_sid
            self._session_set(key, rec)
        if body:
            return body
        if returncode != 0:
            return (
                f"{self._p.display_tool} 本次返回失败（code {returncode}）："
                f"{(stderr.strip() or stdout.strip())[:400]}"
            )
        return ""

    def _run_cli_once(self, cli_path: str, prompt: str, cwd: str) -> str:
        """运行一次 CLI 取最终回复文本（coding/闲聊共用；含测试注入与 idle-timeout 两路）。"""
        idle_timeout = self._cli_idle_timeout_seconds()
        hard_cap = self._cli_hard_cap_seconds()
        with tempfile.TemporaryDirectory(prefix=f"xcagi-{self._p.tool_name}-cli-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            # 注入式 runner(测试)走简单路径；生产用 idle-timeout：只要还在产出就不杀，
            # 仅"持续静默"(卡死/挂起)或超绝对上限才结束。
            if self._cli_runner is not subprocess.run:
                try:
                    proc = self._cli_runner(cmd, text=True, capture_output=True, cwd=cwd)
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
                returncode = int(getattr(proc, "returncode", 0) or 0)
                stdout = str(getattr(proc, "stdout", "") or "")
                stderr = str(getattr(proc, "stderr", "") or "")
                killed_reason = ""
            else:
                try:
                    returncode, stdout, stderr, killed_reason = self._run_cli_idle(
                        cmd, cwd, idle_timeout, hard_cap
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    return f"{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}"
            if killed_reason.startswith("idle"):
                return (
                    f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无任何输出，判定卡住已结束。"
                    "可能是网络或工具挂起，请重试。"
                )
            if killed_reason.startswith("hardcap"):
                return (
                    f"{self._p.display_tool} CLI 运行超过上限 {hard_cap:g} 秒仍未结束，已停止。"
                    "请把任务拆小一点再试。"
                )
            # stream-json(claude)：从事件流解析最终回复。
            if self._p.cli_stream_json:
                body = self._parse_claude_stream_json(stdout)
                if body:
                    return body
                if returncode != 0:
                    detail = (stderr.strip() or stdout.strip())[:500]
                    return (
                        f"{self._p.display_tool} CLI 已接入，但本次返回失败"
                        f"（code {returncode}）：{detail}"
                    )
                return ""
            # 非 stream(codex)：先读 last-message 文件，再退 stdout。
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    return body
            cleaned = self._clean_cli_stdout(stdout.strip())
            if cleaned:
                return cleaned
            if returncode != 0:
                return (
                    f"{self._p.display_tool} CLI 已接入，但本次返回失败"
                    f"（code {returncode}）：{stderr.strip()[:500]}"
                )
        return ""

    def _cli_path(self) -> str:
        candidates = [
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_PATH", ""),
            shutil.which(self._p.cli_binary) or "",
            *self._p.cli_extra_candidates,
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value and Path(value).is_file():
                return value
        return ""

    def _cli_workspace(self, context: dict[str, Any]) -> str:
        candidate = str(
            context.get("workspace_root")
            or os.environ.get(f"{self._p.env_tool_prefix}_WORKSPACE_ROOT")
            or os.environ.get("MODSTORE_REPO_ROOT")
            or ""
        ).strip()
        if candidate and Path(candidate).exists():
            return candidate
        # 默认根=包含 FHD 的工程根（如 ~/Desktop/XCMAX），让超级员工覆盖整个工程而非仅 FHD 子目录。
        here = Path(__file__).resolve()
        for parent in here.parents:
            if parent.name == "FHD":
                return str(parent.parent)
        return str(here.parents[3])

    def _cli_timeout_seconds(self) -> float:
        """Backward-compat alias for _cli_idle_timeout_seconds (used by tests)."""
        return self._cli_idle_timeout_seconds()

    def _cli_idle_timeout_seconds(self) -> float:
        # 活性检测：持续静默(无任何 stdout/stderr 输出)超过此值 → 判定卡住。
        # 只要 CLI 还在产出(stream-json 事件/进度行)就一直等，不因总时长被杀。
        raw = (
            os.environ.get(f"{self._p.env_tool_prefix}_CLI_IDLE_TIMEOUT_SEC")
            or os.environ.get(f"{self._p.env_tool_prefix}_CLI_TIMEOUT_SEC")  # 兼容旧变量
            or "180"
        )
        try:
            return max(15.0, float(raw))
        except (TypeError, ValueError):
            return 180.0

    def _cli_hard_cap_seconds(self) -> float:
        # 绝对兜底(防真死循环)；<=0 表示无上限。默认 1 小时。
        raw = os.environ.get(f"{self._p.env_tool_prefix}_CLI_HARD_CAP_SEC") or "3600"
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 3600.0

    def _cli_subprocess_env(self) -> dict[str, str] | None:
        """给 CLI 子进程注入代理。差异化代理：FHD 本身直连自有云端 xiu-ci.com（代理会断 SSL），
        但 claude/codex 调 api.anthropic.com 等需走代理（直连被 403 拦）。
        仅当 XCMAX_CLI_PROXY 设了才注入；否则返回 None（继承当前环境，行为不变）。"""
        proxy = str(os.environ.get("XCMAX_CLI_PROXY") or "").strip()
        if not proxy:
            return None
        env = os.environ.copy()
        for k in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env[k] = proxy
        return env

    def _run_cli_idle(
        self,
        cmd: list[str],
        cwd: str,
        idle_timeout: float,
        hard_cap: float,
    ) -> tuple[int, str, str, str]:
        """跑 cmd，只在「持续 idle_timeout 秒无输出」(卡住)或超 hard_cap 时才 kill；
        只要还在产出就不杀。返回 (returncode, stdout, stderr, killed_reason)。"""
        import threading

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            text=True,
            bufsize=1,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._cli_subprocess_env(),
        )
        out_parts: list[str] = []
        err_parts: list[str] = []
        last_activity = [time.monotonic()]
        lock = threading.Lock()

        def _pump(stream, sink: list[str]) -> None:
            try:
                for line in iter(stream.readline, ""):
                    with lock:
                        sink.append(line)
                        last_activity[0] = time.monotonic()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        t_out = threading.Thread(target=_pump, args=(proc.stdout, out_parts), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, err_parts), daemon=True)
        t_out.start()
        t_err.start()
        started = time.monotonic()
        killed_reason = ""
        while True:
            try:
                proc.wait(timeout=3)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            with lock:
                idle = now - last_activity[0]
            if idle_timeout > 0 and idle > idle_timeout:
                killed_reason = f"idle:{idle_timeout:g}"
            elif hard_cap > 0 and (now - started) > hard_cap:
                killed_reason = f"hardcap:{hard_cap:g}"
            if killed_reason:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                break
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        return int(proc.returncode or 0), "".join(out_parts), "".join(err_parts), killed_reason

    def _parse_claude_stream_json(self, out: str) -> str:
        """从 claude --output-format stream-json 的事件流里取最终回复。"""
        result = ""
        texts: list[str] = []
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith("{"):
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "result":
                r = ev.get("result")
                if isinstance(r, str) and r.strip():
                    result = r.strip()
            elif ev.get("type") == "assistant":
                msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
                for blk in msg.get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        t = str(blk.get("text") or "").strip()
                        if t:
                            texts.append(t)
        return result or "\n".join(texts).strip()

    def _cli_prompt(self, text: str) -> str:
        return (
            f"你是 XCMAX 软件内的{self._p.employee_name}。请直接回答用户的问题。"
            "这是普通对话通道：不要执行命令，不要修改文件，不要调用工具。"
            "如果用户询问额度、账户余额、订阅或实时账户状态，而你无法从当前会话读取真实账户数据，"
            "请明确说明不能查看，不要编造数字。"
            "\n\n用户问题："
            f"{text.strip()}"
        )

    def _is_task_intent(self, text: str, context: dict[str, Any]) -> bool:
        """是否为开发任务（需要真改代码），与 force-direct 无关，仅看 mode/关键词。"""
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", f"{self._p.tool_name}_cli"}:
            return False
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return True
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        return any(marker in normalized for marker in _TASK_MARKERS)

    def _cli_work_prompt(self, text: str, cwd: str) -> str:
        """开发任务 prompt：授权 Claude 真正读写/修改工作区文件（配合 --permission-mode acceptEdits）。"""
        return (
            f"你是 XCMAX 软件内的{self._p.employee_name}，运行在项目工作区，"
            "拥有完整的文件读写与代码修改能力。请直接动手完成下面的开发任务："
            "按需读取、创建、修改工作区内的文件来实现需求；不要只给建议或只解释，要真正改代码。"
            "完成后用一两句话总结你改了哪些文件、做了什么。"
            f"\n\n工作区根目录：{cwd}"
            "\n\n开发任务：\n"
            f"{text.strip()}"
        )

    # ===== coding → view → push 闭环（开发任务）=====

    def _dev_loop_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_DEV_LOOP")
                or os.environ.get("XCMAX_CLAUDE_DEV_LOOP")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def _git(self, cwd: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout
        )

    def _is_git_repo(self, cwd: str) -> bool:
        try:
            r = self._git(cwd, "rev-parse", "--is-inside-work-tree", timeout=15)
            return r.returncode == 0 and r.stdout.strip() == "true"
        except Exception:  # noqa: BLE001
            return False

    def _prepare_worktree(self, base_cwd: str, text: str) -> tuple[str, str] | None:
        """从 base_cwd 的 HEAD 建独立 worktree + 新分支；失败返回 None（退回不隔离）。"""
        if not self._is_git_repo(base_cwd):
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())[:24].strip("-") or "task"
        uniq = f"{os.getpid()}-{int.from_bytes(os.urandom(3), 'big'):x}"
        branch = f"super-employee/{self._p.tool_name}/{slug}-{uniq}"
        wt_path = str(Path(tempfile.gettempdir()) / f"xcagi-wt-{self._p.tool_name}-{uniq}")
        try:
            r = self._git(base_cwd, "worktree", "add", "-b", branch, wt_path, "HEAD", timeout=180)
            if r.returncode != 0:
                logger.warning("worktree add 失败: %s", (r.stderr or r.stdout)[:300])
                return None
            return wt_path, branch
        except Exception:  # noqa: BLE001
            logger.warning("worktree add 异常", exc_info=True)
            return None

    def _remove_worktree(self, base_cwd: str, wt_path: str) -> None:
        try:
            self._git(base_cwd, "worktree", "remove", "--force", wt_path, timeout=60)
        except Exception:  # noqa: BLE001
            logger.warning("worktree remove 失败 %s", wt_path, exc_info=True)

    def _verify_workspace(self, cwd: str) -> tuple[bool, str]:
        """view 阶段：验证改动可编译。优先 XCMAX_CLAUDE_VERIFY_CMD；否则对改动的 .py 做语法编译。"""
        custom = str(os.environ.get("XCMAX_CLAUDE_VERIFY_CMD") or "").strip()
        if custom:
            try:
                cap = self._cli_hard_cap_seconds()
                r = subprocess.run(
                    custom,
                    shell=True,  # nosec B602 – operator-supplied env var, may use shell syntax
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=(cap if cap and cap > 0 else 1800),
                )
                if r.returncode == 0:
                    return True, "自定义验证命令通过"
                return False, (r.stderr.strip() or r.stdout.strip())[:1500]
            except Exception as e:  # noqa: BLE001
                return False, f"验证命令异常：{str(e)[:300]}"
        # 用 status --porcelain 枚举改动：必须含"未跟踪新文件"（claude 常新建文件，
        # 如 PressEffect.kt 就是新建；git diff HEAD 抓不到未跟踪文件会漏验证）。
        changed: list[str] = []
        try:
            st = self._git(cwd, "status", "--porcelain", "--untracked-files=all", timeout=30)
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                path = ln[3:] if len(ln) > 3 else ln.strip()
                if "->" in path:  # 重命名 old -> new
                    path = path.split("->", 1)[1]
                path = path.strip().strip('"')
                if path:
                    changed.append(path)
        except Exception:  # noqa: BLE001
            changed = []
        py = [f for f in changed if f.endswith(".py")]
        if py:
            import py_compile

            errs: list[str] = []
            for f in py:
                p = Path(cwd) / f
                if not p.exists():
                    continue
                try:
                    py_compile.compile(str(p), doraise=True)
                except py_compile.PyCompileError as e:
                    errs.append(str(e)[:400])
            if errs:
                return False, "Python 语法错误：\n" + "\n".join(errs)
            return True, f"已对 {len(py)} 个改动的 .py 通过语法编译"
        if not changed:
            return True, "无文件改动"
        return True, (
            f"改动 {len(changed)} 个文件（非 .py，未做深度编译验证；"
            "如需构建验证可设 XCMAX_CLAUDE_VERIFY_CMD）"
        )

    def _commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        try:
            self._git(cwd, "add", "-A", timeout=120)
            st = self._git(cwd, "status", "--porcelain", timeout=30)
            if not st.stdout.strip():
                return False, "无改动可提交"
            title = (text.strip().splitlines() or ["开发任务"])[0][:60]
            msg = (
                f"{self._p.employee_name}: {title}\n\n手机超级员工自动提交（coding→view→push 闭环）"
            )
            c = self._git(cwd, "commit", "-m", msg, timeout=60)
            if c.returncode != 0:
                return False, "提交失败：" + (c.stderr.strip() or c.stdout.strip())[:300]
            p = self._git(cwd, "push", "-u", "origin", branch, timeout=240)
            if p.returncode != 0:
                return False, "已本地提交，但 push 失败：" + (p.stderr.strip() or p.stdout.strip())[
                    :300
                ]
            return True, f"已 push 到 origin/{branch}"
        except Exception as e:  # noqa: BLE001
            return False, f"git 异常：{str(e)[:300]}"

    def _cli_fix_prompt(self, verify_msg: str, cwd: str) -> str:
        return (
            f"你刚才在工作区 {cwd} 的改动未通过验证。请直接修改文件修复下面的错误，"
            "改到能通过为止，不要只解释。\n\n验证错误：\n" + verify_msg[:1500]
        )

    def _run_dev_task_loop(self, cli_path: str, text: str, base_cwd: str) -> str:
        """开发任务全闭环：隔离 worktree → coding → view(验证,失败修一次) → push → 清理。"""
        prepared = self._prepare_worktree(base_cwd, text)
        if not prepared:
            # 无法隔离（非 git 仓库 / worktree 冲突）→ 退回只改不推，保证仍可用。
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        wt_path, branch = prepared
        try:
            body = self._run_cli_once(cli_path, self._cli_work_prompt(text, wt_path), wt_path)
            ok, vmsg = self._verify_workspace(wt_path)
            if not ok:
                self._run_cli_once(cli_path, self._cli_fix_prompt(vmsg, wt_path), wt_path)
                ok, vmsg = self._verify_workspace(wt_path)
            pushed, pmsg = self._commit_and_push(wt_path, branch, text)
            status = "✅" if (ok and pushed) else ("⚠️" if pushed else "❌")
            tail = (
                f"\n\n— — — 闭环结果 {status} — — —"
                f"\n分支：{branch}"
                f"\n验证：{'通过' if ok else '未通过'}（{vmsg[:200]}）"
                f"\n推送：{pmsg[:200]}"
            )
            base = body.strip() or f"{self._p.display_tool} 已完成开发任务。"
            return base + tail
        finally:
            self._remove_worktree(base_cwd, wt_path)

    def _clean_cli_stdout(self, stdout: str) -> str:
        lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {self._p.tool_name, "codex", "tokens used"}:
                continue
            if re.fullmatch(r"[\d,]+", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _direct_reply_body(self, text: str) -> str:
        normalized = re.sub(r"[\s，。！？!?、,.]+", "", text.strip().lower())
        if not normalized:
            return ""
        tool = self._p.display_tool
        name = self._p.employee_name
        identity_prompts = {
            "你是谁",
            "你是誰",
            "你谁",
            "你是哪个",
            "你是什么",
            "whoareyou",
            "whatareyou",
        }
        help_prompts = {
            "你能做什么",
            "你能干什么",
            "你会什么",
            "怎么用",
            "如何使用",
            "帮助",
            "help",
        }
        greeting_prompts = {"你好", "在吗", "在不在", "hello", "hi"}
        slow_prompts = {"为什么这么慢", "为啥这么慢", "为什么出不来", "怎么出不来"}

        if normalized in identity_prompts:
            return (
                f"我是{name}。你在软件里发普通问题时，我会直接回复；"
                f"你发开发、测试、打包、提交、跨设备协作这类任务时，我会调用可用的 {tool} 工作设备完成。"
            )
        if normalized in help_prompts:
            return (
                "你可以直接给我派开发任务，例如修复某个页面、跑测试、打包移动端、提交代码。"
                "如果只是问身份、用法或状态，我会在这里直接回复，不进入多设备派工。"
            )
        if normalized in greeting_prompts:
            return "我在。需要改代码、跑验证或跨设备协作时，直接把任务发给我。"
        if normalized in slow_prompts:
            return (
                "慢是因为这类消息之前被误当成开发任务派到多设备队列，必须等工作设备回传才显示结果。"
                "现在身份、帮助和问候类消息会直接回复；真正的开发任务才进入派工。"
            )
        return ""

    def _fetch_para_task(self, task_id: str) -> dict[str, Any] | None:
        api_url = self._para_api_url()
        if not api_url or not task_id:
            return None
        try:
            with self._http_client_factory() as client:
                token = self._para_token(client, api_url)
                body = self._para_request(client, api_url, token, "GET", f"/api/tasks/{task_id}")
            task = body.get("task") if isinstance(body, dict) else None
            return task if isinstance(task, dict) else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def _upsert_direct_reply_messages(self, *, user_id: int, rows: list[dict[str, Any]]) -> bool:
        request_ids_with_reply = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and (
                str(item.get("kind") or "") in {self._p.direct_kind, self._p.result_kind}
                or (
                    str(item.get("role") or "") == "assistant"
                    and str(item.get("kind") or "") != DISPATCHER_MESSAGE_KIND
                )
            )
        }
        changed = False
        cli_backfills = 0
        for item in list(rows):
            if int(item.get("user_id") or 0) != int(user_id):
                continue
            if str(item.get("role") or "") != "user":
                continue
            request_id = str(item.get("dispatch_request_id") or "")
            if not request_id or request_id in request_ids_with_reply:
                continue
            body = self._direct_reply_body(str(item.get("body") or ""))
            if not body and cli_backfills < 1:
                text = str(item.get("body") or "")
                if self._should_reply_with_cli(text, {}):
                    body = (
                        self._cli_reply_body(text, {})
                        or f"{self._p.display_tool} CLI 暂时没有返回内容，"
                        f"请确认本机 {self._p.display_tool} 已登录后重试。"
                    )
                    cli_backfills += 1
            if not body:
                continue
            rows.append(
                self._message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=body,
                    created_at=_utc_now(),
                    request_id=request_id,
                    status="completed",
                    extra={"kind": self._p.direct_kind},
                )
            )
            request_ids_with_reply.add(request_id)
            changed = True
        return changed

    def _refresh_dispatcher_row(self, row: dict[str, Any], task: dict[str, Any]) -> bool:
        task_id = str(task.get("id") or row.get("task_id") or "")
        task_status = str(task.get("status") or "").strip()
        body = self._para_task_status_reply(task)
        patch = {
            "body": body,
            "status": task_status or str(row.get("status") or ""),
            "task_id": task_id,
            "task_status": task_status,
        }
        changed = False
        for key, value in patch.items():
            if value and row.get(key) != value:
                row[key] = value
                changed = True
        return changed

    def _para_task_status_reply(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("id") or "").strip()
        status = str(task.get("status") or "").strip()
        tool = self._p.display_tool
        subtasks = self._task_subtasks(task)
        total = len(subtasks)
        completed = sum(1 for item in subtasks if str(item.get("status") or "") == "completed")
        failed = sum(1 for item in subtasks if str(item.get("status") or "") == "failed")
        progress_values = [
            int(item.get("progress") or 0)
            for item in subtasks
            if isinstance(item.get("progress"), (int, float))
        ]
        progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0
        if status in {"completed", "merged"}:
            head = f"Para 任务已完成，{tool} 执行结果已回传。"
        elif status in {"failed", "merge_conflict"} or failed:
            head = f"Para 任务需要处理，{tool} 错误或冲突信息已回传。"
        elif total:
            head = f"Para 任务运行中：{completed}/{total} 个子任务完成，进度 {progress}%。"
        else:
            head = f"Para 任务已创建，等待 {tool} 工作设备回传。"
        return f"{head}{f'任务 ID：{task_id}' if task_id else ''}"

    def _upsert_result_messages(
        self,
        *,
        user_id: int,
        dispatch_row: dict[str, Any],
        task: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> bool:
        changed = False
        task_id = str(task.get("id") or dispatch_row.get("task_id") or "")
        for subtask in self._task_subtasks(task):
            status = str(subtask.get("status") or "").strip()
            if status not in {"completed", "failed"}:
                continue
            body = self._result_body(task, subtask)
            if not body:
                continue
            subtask_id = str(subtask.get("id") or "")
            existing = next(
                (
                    item
                    for item in rows
                    if int(item.get("user_id") or 0) == int(user_id)
                    and str(item.get("kind") or "") == self._p.result_kind
                    and str(item.get("task_id") or "") == task_id
                    and str(item.get("subtask_id") or "") == subtask_id
                ),
                None,
            )
            if existing:
                patch = {
                    "body": body,
                    "status": status,
                    "task_status": str(task.get("status") or ""),
                    "device_name": str(subtask.get("device_name") or ""),
                }
                for key, value in patch.items():
                    if value and existing.get(key) != value:
                        existing[key] = value
                        changed = True
                continue
            rows.append(
                self._message_row(
                    user_id=int(user_id),
                    role="assistant",
                    body=body,
                    created_at=str(subtask.get("completed_at") or _utc_now()),
                    request_id=str(dispatch_row.get("dispatch_request_id") or ""),
                    status=status,
                    extra={
                        "kind": self._p.result_kind,
                        "task_id": task_id,
                        "task_status": str(task.get("status") or ""),
                        "subtask_id": subtask_id,
                        "device_name": str(subtask.get("device_name") or ""),
                    },
                )
            )
            changed = True
        return changed

    def _task_subtasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        subtasks = _coerce_list(task.get("subTasks")) or _coerce_list(task.get("subtasks"))
        return [item for item in subtasks if isinstance(item, dict)]

    def _result_body(self, task: dict[str, Any], subtask: dict[str, Any]) -> str:
        logs = [
            str(log.get("content") or "").strip()
            for log in _coerce_list(subtask.get("logs"))
            if isinstance(log, dict) and str(log.get("content") or "").strip()
        ]
        meaningful = [item for item in logs if not self._is_dispatcher_log(item)]
        tail = self._dedupe_log_tail(meaningful or logs)
        status = str(subtask.get("status") or "").strip()
        tool = self._p.display_tool
        device_name = str(subtask.get("device_name") or subtask.get("device_id") or "").strip()
        title = str(subtask.get("title") or task.get("title") or "").strip()
        prefix = f"{device_name} / {title}".strip(" /")
        if tail:
            return f"{prefix}\n\n{tail}".strip()
        if status == "completed":
            return f"{prefix}\n\n{tool} 已完成该子任务。".strip()
        if status == "failed":
            last_error = str(subtask.get("last_error") or "").strip()
            return f"{prefix}\n\n{tool} 执行失败。{last_error}".strip()
        return ""

    def _is_dispatcher_log(self, content: str) -> bool:
        prefixes = (
            "子任务「",
            "子任务未派发",
            "链路不可用",
            "设备连接已断开",
            "手动",
        )
        return content.startswith(prefixes)

    def _dedupe_log_tail(
        self, logs: list[str], *, max_items: int = 5, max_chars: int = 4000
    ) -> str:
        seen: set[str] = set()
        unique: list[str] = []
        for item in logs:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return "\n\n".join(unique[-max_items:])[-max_chars:].strip()

    def _public_message(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item.get("id") or ""),
            "role": str(item.get("role") or "assistant"),
            "body": str(item.get("body") or ""),
            "created_at": str(item.get("created_at") or ""),
            "status": str(item.get("status") or ""),
            "dispatch_request_id": str(item.get("dispatch_request_id") or ""),
            "kind": str(item.get("kind") or ""),
            "task_id": str(item.get("task_id") or ""),
            "task_status": str(item.get("task_status") or ""),
            "subtask_id": str(item.get("subtask_id") or ""),
            "device_name": str(item.get("device_name") or ""),
        }


__all__ = [
    "DISPATCHER_MESSAGE_KIND",
    "CODEX_PROFILE",
    "CLAUDE_PROFILE",
    "SuperEmployeeService",
    "SuperEmployeeToolProfile",
]
