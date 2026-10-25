"""Build requests and dispatch through scheduler or webhook, with a durable outbox fallback."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import httpx

from app.domain.app_pure.execution_scope import CONTEXT_TOKEN_KEY
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .common import _SUBTASK_LABELS
from .devices import DeviceSelection
from .protocols import ExecutionContext, OutboxWriter, ParaPorts
from .profiles import SuperEmployeeToolProfile


class EmployeeDispatcher:
    def __init__(
        self,
        profile: SuperEmployeeToolProfile,
        scope: ExecutionContext,
        remote: ParaPorts,
        devices: DeviceSelection,
        outbox: OutboxWriter,
        factory_workspace: Callable[[], str],
    ) -> None:
        self._p, self._scope, self._remote = profile, scope, remote
        self._devices, self._outbox = devices, outbox
        self._factory_workspace = factory_workspace

    def build_dispatch_request(
        self,
        *,
        request_id: str,
        created_at: str,
        user_id: int,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self._scope.grant.is_factory:
            workspace_root = self._factory_workspace()
        else:
            workspace_root = ""
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
            "scope": self._scope.grant.scope.value,
            "workspace_id": self._scope.grant.workspace_id or "",
            "raw_context": {k: v for k, v in context.items() if k != CONTEXT_TOKEN_KEY},
        }

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
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
            para_dispatch, para_reason = self.dispatch_to_para(request)
            if para_dispatch is not None:
                return para_dispatch
            if mode != "auto":
                return self._outbox(
                    request,
                    status="queued",
                    accepted=False,
                    reason=para_reason or "para_dispatcher_unavailable",
                )
        else:
            para_reason = ""
        if mode == "outbox":
            return self._outbox(
                request, status="queued", accepted=False, reason="dispatch_mode_outbox"
            )
        webhook = (
            os.environ.get(f"{self._p.env_super_prefix}_WEBHOOK")
            or os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK")
            or ""
        ).strip()
        if not webhook:
            return self._outbox(
                request,
                status="queued",
                accepted=False,
                reason=para_reason or f"{self._p.tool_name}_dispatch_webhook_not_configured",
            )
        try:
            with self._remote.client() as client:
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
            return self._outbox(
                request,
                status="dispatch_failed",
                accepted=False,
                reason=str(body.get("error") or body.get("message") or f"HTTP {resp.status_code}")[
                    :500
                ],
            )
        except RECOVERABLE_ERRORS as exc:
            return self._outbox(
                request, status="dispatch_error", accepted=False, reason=str(exc)[:500]
            )

    def dispatch_to_para(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        api_url = self._remote.api_url()
        if not api_url:
            return (None, "para_dispatcher_disabled")
        try:
            with self._remote.client() as client:
                health = client.get(f"{api_url}/api/health")
                if health.status_code >= 400:
                    return (None, f"para_api_unhealthy_http_{health.status_code}")
                token = self._remote.token(client, api_url)
                devices_body = self._remote.request(client, api_url, token, "GET", "/api/devices")
                devices = devices_body.get("devices") if isinstance(devices_body, dict) else []
                tier, selected = self._devices.select_devices_by_tier(
                    devices if isinstance(devices, list) else [], request
                )
                if not selected:
                    return (
                        self._outbox(
                            request,
                            status="queued",
                            accepted=False,
                            reason=f"para_no_online_{self._p.tool_name}_device",
                        ),
                        f"para_no_online_{self._p.tool_name}_device",
                    )
                prepared = []
                for device in selected:
                    prepared.append(self.ensure_para_device(client, api_url, token, device))
                return (
                    self.create_para_task(client, api_url, token, request, prepared, tier=tier),
                    "",
                )
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.NetworkError,
        ) as exc:
            return (None, f"para_api_unreachable: {exc}")
        except RECOVERABLE_ERRORS as exc:
            return (
                self._outbox(
                    request,
                    status="dispatch_error",
                    accepted=False,
                    reason=f"para_dispatch_error: {str(exc)[:460]}",
                ),
                str(exc)[:500],
            )

    def ensure_para_device(
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
        body = self._remote.request(
            client,
            api_url,
            token,
            "PUT",
            f"/api/devices/{device_id}/dev-tool",
            json_body={"devTool": self._p.tool_name},
        )
        updated = body.get("device")
        return updated if isinstance(updated, dict) else {**device, "devTool": self._p.tool_name}

    def create_para_task(
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
        if not isinstance(raw_context, dict):
            raw_context = {}
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
                "prompt": self.para_prompt(request, device, index, len(devices)),
                "device_id": str(device.get("id") or ""),
                "branch": branch,
                "subtask_title": self.para_subtask_title(title, index, len(devices)),
                "max_attempts": 3,
            }
            if repo_url:
                body["repo_url"] = repo_url
            if task_id:
                body["task_id"] = task_id
            result = self._remote.request(
                client, api_url, token, "POST", "/api/tasks", json_body=body
            )
            task = result.get("task") if isinstance(result.get("task"), dict) else task
            task_id = str((task or {}).get("id") or task_id)
            subtask = result.get("subtask") if isinstance(result.get("subtask"), dict) else {}
            if not isinstance(subtask, dict):
                subtask = {}
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

    def para_prompt(
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
            suffix = f"你是第 {index + 1}/{total} 台 {self._p.display_tool} 工作设备（{device.get('name') or device.get('id')}）。请承担可独立完成的部分，避免和其他设备重复改同一批文件；提交到调度器分配的工作分支，并回写执行日志。"
        parts = [prompt, suffix]
        if workspace_root:
            parts.append(f"管理端来源工作区：{workspace_root}")
        return "\n\n".join(part for part in parts if part)

    def para_subtask_title(self, title: str, index: int, total: int) -> str:
        if total <= 1:
            return title
        label = _SUBTASK_LABELS[index] if index < len(_SUBTASK_LABELS) else f"工作单元 {index + 1}"
        return f"{label}：{title[:60]}"

    def dispatch_reply(self, dispatch: dict[str, Any]) -> str:
        _ = dispatch
        return "思考中..."
