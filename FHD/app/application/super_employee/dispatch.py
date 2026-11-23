"""Build requests and dispatch through scheduler or webhook, with a durable outbox fallback."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from app.domain.app_pure.execution_scope import CONTEXT_TOKEN_KEY
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .common import _SUBTASK_LABELS
from .devices import DeviceSelection
from .para import ParaRemoteError
from .profiles import SuperEmployeeToolProfile
from .protocols import ExecutionContext, OutboxWriter, ParaPorts

_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_PARA_ERRORS = RECOVERABLE_ERRORS + (ParaRemoteError,)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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
            "target_devices": (
                context.get("target_devices")
                if isinstance(context.get("target_devices"), list)
                else ["all"]
            ),
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
        receipt = request.get("dispatch_receipt")
        if isinstance(receipt, dict) and not receipt.get("safe_to_fallback"):
            return self._resume_dispatch(request, receipt)
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
        self._persist_receipt(request, {"dispatcher": "webhook", "status": "dispatching"})
        try:
            with self._remote.client() as client:
                resp = client.post(
                    webhook,
                    json={k: v for k, v in request.items() if k != "dispatch_receipt"},
                )
            body: Any
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {"raw": resp.text[:1000]}
            if not isinstance(body, dict):
                body = {"raw": body}
            accepted = resp.status_code < 400 and (
                body.get("ok") is True
                or body.get("success") is True
                or body.get("accepted") is True
            )
            if accepted:
                return self._persist_receipt(
                    request,
                    {
                        "request_id": request["request_id"],
                        "status": "accepted",
                        "accepted": True,
                        "queued": False,
                        "device_scope": "all_devices",
                        "response": body,
                        "dispatcher": "webhook",
                    },
                )
            return self._unknown_dispatch(
                request,
                str(body.get("error") or body.get("message") or f"HTTP {resp.status_code}"),
            )
        except _NOT_SENT as exc:
            return self._persist_receipt(
                request,
                {
                    "status": "dispatch_error",
                    "safe_to_fallback": True,
                    "reason": str(exc)[:500],
                },
            )
        except RECOVERABLE_ERRORS as exc:
            return self._unknown_dispatch(request, str(exc))

    def _persist_receipt(self, request: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        receipt = {
            "request_id": request["request_id"],
            "accepted": False,
            "queued": False,
            "safe_to_fallback": False,
            "status": "dispatch_unknown",
            **receipt,
        }
        request["dispatch_receipt"] = receipt
        outbox = self._outbox(
            request,
            status=receipt["status"],
            accepted=receipt["accepted"],
            reason=str(receipt.get("reason") or ""),
        )
        return {**outbox, **receipt}

    def _unknown_dispatch(self, request: dict[str, Any], reason: str) -> dict[str, Any]:
        return self._persist_receipt(
            request,
            {
                **request.get("dispatch_receipt", {}),
                "status": "dispatch_unknown",
                "accepted": False,
                "reconciliation_required": True,
                "safe_to_fallback": False,
                "reason": reason[:500],
            },
        )

    def reconcile(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read the original dispatch only; observation cannot send remaining work."""
        receipt = request.get("dispatch_receipt")
        if not isinstance(receipt, dict):
            return {}
        return self._resume_dispatch(request, receipt, continue_plan=False)

    def read_original_receipt(self, receipt: dict[str, Any]) -> dict[str, Any] | None:
        """Read one bound acknowledgement without writing or dispatching work."""
        api_url = self._remote.api_url()
        pending_key = receipt.get("pending_request_id")
        if (
            receipt.get("dispatcher") != "para_api"
            or not api_url
            or api_url != receipt.get("api_url")
            or not pending_key
            or receipt.get("status") == "dispatching"
        ):
            return None
        try:
            with self._remote.client() as client:
                token = self._remote.token(client, api_url)
                result = self._remote.request(
                    client,
                    api_url,
                    token,
                    "GET",
                    f"/api/tasks/by-request/{quote(str(pending_key), safe='')}",
                )
            return self._original_receipt(receipt, result)
        except _PARA_ERRORS:
            return None

    def _original_receipt(
        self, receipt: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any] | None:
        task, subtask, original = (result.get(key) for key in ("task", "subtask", "request"))
        task_id = receipt.get("task_id")
        pending_key = receipt.get("pending_request_id")
        plan = receipt.get("plan")
        dispatched = list(receipt.get("devices") or [])
        if (
            not isinstance(task, dict)
            or not isinstance(subtask, dict)
            or not isinstance(original, dict)
            or original.get("client_request_id") != pending_key
            or original.get("payload_sha256") != receipt.get("pending_payload_sha256")
            or not task.get("id")
            or not subtask.get("id")
            or subtask.get("task_id") != task["id"]
            or subtask.get("device_id") != receipt.get("pending_device_id")
            or (task_id and task_id != task["id"])
            or not isinstance(plan, list)
            or _digest(plan) != receipt.get("plan_sha256")
            or len(dispatched) >= len(plan)
            or plan[len(dispatched)]["client_request_id"] != pending_key
        ):
            return None
        item = plan[len(dispatched)]
        dispatched.append(
            {
                "device_id": subtask["device_id"],
                "device_name": item["device_name"],
                "subtask_id": subtask["id"],
                "tool": self._p.tool_name,
            }
        )
        receipt = dict(receipt)
        receipt.update(
            task_id=task["id"],
            task_status=str(task.get("status") or ""),
            devices=dispatched,
            response={"task": task, "dispatched": dispatched},
            reconciliation_required=False,
        )
        for key in (
            "pending_request_id",
            "pending_payload_sha256",
            "pending_device_id",
        ):
            receipt.pop(key, None)
        receipt.update(
            status=("accepted" if len(dispatched) == len(plan) else "dispatch_pending"),
            accepted=len(dispatched) == len(plan),
        )
        return receipt

    def _resume_dispatch(
        self,
        request: dict[str, Any],
        receipt: dict[str, Any],
        *,
        continue_plan: bool = True,
    ) -> dict[str, Any]:
        receipt = dict(receipt)
        if receipt.get("status") == "dispatching":
            receipt.update(status="dispatch_unknown", reconciliation_required=True)
        if (
            continue_plan
            and receipt.get("status") == "dispatch_error"
            and receipt.get("reason") == "para_original_request_recovery_unavailable"
            and not receipt.get("plan")
        ):
            resumed, reason = self.dispatch_to_para(request)
            return resumed or self._persist_receipt(request, {**receipt, "reason": reason})
        task_id = receipt.get("task_id")
        api_url = self._remote.api_url()
        pending_key = receipt.get("pending_request_id")
        plan, dispatched = receipt.get("plan"), receipt.get("devices")
        if (
            not pending_key
            and task_id
            and isinstance(plan, list)
            and plan
            and _digest(plan) == receipt.get("plan_sha256")
            and isinstance(dispatched, list)
            and len(dispatched) == len(plan)
            and all(
                isinstance(row, dict)
                and row.get("subtask_id")
                and row.get("device_id") == item["body"]["device_id"]
                for row, item in zip(dispatched, plan, strict=True)
            )
        ):
            receipt.update(status="accepted", accepted=True, reconciliation_required=False)
        if (
            receipt.get("dispatcher") == "para_api"
            and api_url == receipt.get("api_url")
            and pending_key
        ):
            try:
                with self._remote.client() as client:
                    token = self._remote.token(client, api_url)
                    result = self._remote.request(
                        client,
                        api_url,
                        token,
                        "GET",
                        f"/api/tasks/by-request/{quote(str(pending_key), safe='')}",
                    )
                    recovered = self._original_receipt(receipt, result)
                    if recovered is None:
                        return self._unknown_dispatch(
                            request, "para original request receipt mismatch"
                        )
                    receipt = recovered
                    self._persist_receipt(request, receipt)
                    if not receipt["accepted"] and continue_plan:
                        return self.create_para_task(
                            client,
                            api_url,
                            token,
                            request,
                            [],
                            tier=int(receipt.get("para_tier") or 2),
                        )
            except _PARA_ERRORS:
                if not task_id:
                    return self._persist_receipt(request, receipt)
            else:
                return self._persist_receipt(request, receipt)
        if (
            receipt.get("status") == "dispatch_pending"
            and continue_plan
            and api_url == receipt.get("api_url")
        ):
            try:
                with self._remote.client() as client:
                    token = self._remote.token(client, api_url)
                    return self.create_para_task(
                        client,
                        api_url,
                        token,
                        request,
                        [],
                        tier=int(receipt.get("para_tier") or 2),
                    )
            except _PARA_ERRORS as exc:
                return self._persist_receipt(request, {**receipt, "reason": str(exc)[:500]})
        if (
            continue_plan
            and task_id
            and receipt.get("dispatcher") == "para_api"
            and api_url == receipt.get("api_url")
        ):
            # Readback's MessageSynchronizer refreshes the task once after
            # recovering its original request acknowledgement above.
            try:
                with self._remote.client() as client:
                    token = self._remote.token(client, api_url)
                    result = self._remote.request(
                        client, api_url, token, "GET", f"/api/tasks/{task_id}"
                    )
                task = result.get("task")
                if isinstance(task, dict) and str(task.get("id") or "") == task_id:
                    receipt["task_status"] = str(task.get("status") or "")
                    receipt["response"] = {"task": task}
            except _PARA_ERRORS:
                pass
        return self._persist_receipt(request, receipt)

    def dispatch_to_para(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        api_url = self._remote.api_url()
        if not api_url:
            return (None, "para_dispatcher_disabled")
        try:
            with self._remote.client() as client:
                health = client.get(f"{api_url}/api/health")
                if health.status_code >= 400:
                    return (None, f"para_api_unhealthy_http_{health.status_code}")
                if not self._supports_recovery(health):
                    return (
                        self._persist_receipt(
                            request,
                            {
                                "status": "dispatch_error",
                                "dispatcher": "para_api",
                                "api_url": api_url,
                                "reason": "para_original_request_recovery_unavailable",
                            },
                        ),
                        "para_original_request_recovery_unavailable",
                    )
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
                    self.create_para_task(
                        client, api_url, token, request, prepared, tier=tier, recovery_verified=True
                    ),
                    "",
                )
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.NetworkError,
        ) as exc:
            if isinstance(request.get("dispatch_receipt"), dict) and not request[
                "dispatch_receipt"
            ].get("safe_to_fallback"):
                return (self._unknown_dispatch(request, str(exc)), "dispatch_unknown")
            return (None, f"para_api_unreachable: {exc}")
        except _PARA_ERRORS as exc:
            if isinstance(request.get("dispatch_receipt"), dict) and not request[
                "dispatch_receipt"
            ].get("safe_to_fallback"):
                return (self._unknown_dispatch(request, str(exc)), "dispatch_unknown")
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
        *,
        recovery_verified: bool = False,
    ) -> dict[str, Any]:
        if not recovery_verified:
            try:
                health = client.get(f"{api_url}/api/health")
                health.raise_for_status()
                if not self._supports_recovery(health):
                    return self._persist_receipt(
                        request,
                        {
                            "status": "dispatch_error",
                            "dispatcher": "para_api",
                            "api_url": api_url,
                            "reason": "para_original_request_recovery_unavailable",
                        },
                    )
            except RECOVERABLE_ERRORS as exc:
                return self._persist_receipt(
                    request,
                    {
                        **request.get("dispatch_receipt", {}),
                        "status": "dispatch_error",
                        "reason": str(exc)[:500],
                    },
                )
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
        previous = request.get("dispatch_receipt") or {}
        plan = previous.get("plan")
        if plan is not None and (
            not isinstance(plan, list) or _digest(plan) != previous.get("plan_sha256")
        ):
            return self._unknown_dispatch(request, "para frozen dispatch plan changed")
        if plan is None:
            plan = []
            for index, device in enumerate(devices):
                key = "xcmax:" + _digest(
                    [
                        self._p.employee_id,
                        request["user_id"],
                        request.get("scope"),
                        request.get("workspace_id"),
                        request["request_id"],
                        index,
                        device.get("id"),
                    ]
                )
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
                plan.append(
                    {
                        "body": body,
                        "client_request_id": key,
                        "device_name": str(device.get("name") or ""),
                    }
                )
        task_id = str(previous.get("task_id") or "")
        task: dict[str, Any] | None = None
        dispatched: list[dict[str, Any]] = list(previous.get("devices") or [])
        if not plan or len(dispatched) > len(plan):
            return self._unknown_dispatch(request, "para frozen dispatch plan is incomplete")
        frozen = {"plan": plan, "plan_sha256": _digest(plan), "para_tier": tier}
        for item in plan[len(dispatched) :]:
            body = dict(item["body"])
            if task_id:
                body["task_id"] = task_id
            payload_sha = _digest(body)
            body["client_request_id"] = item["client_request_id"]
            self._persist_receipt(
                request,
                {
                    "status": "dispatching",
                    "dispatcher": "para_api",
                    "api_url": api_url,
                    "task_id": task_id,
                    "devices": list(dispatched),
                    "pending_device_id": body["device_id"],
                    "pending_request_id": item["client_request_id"],
                    "pending_payload_sha256": payload_sha,
                    **frozen,
                },
            )
            try:
                result = self._remote.request(
                    client, api_url, token, "POST", "/api/tasks", json_body=body
                )
            except _NOT_SENT as exc:
                if not dispatched:
                    self._persist_receipt(
                        request,
                        {
                            "status": "dispatch_error",
                            "safe_to_fallback": True,
                            "reason": str(exc)[:500],
                        },
                    )
                    raise
                return self._unknown_dispatch(request, str(exc))
            except _PARA_ERRORS as exc:
                return self._unknown_dispatch(request, str(exc))
            result_task = result.get("task")
            result_task_id = (
                str(result_task.get("id") or "") if isinstance(result_task, dict) else ""
            )
            if not result_task_id:
                return self._unknown_dispatch(request, "para response omitted task_id")
            if task_id and result_task_id != task_id:
                request["dispatch_receipt"]["unexpected_task_id"] = result_task_id
                return self._unknown_dispatch(request, "para response changed task_id")
            subtask = result.get("subtask") if isinstance(result.get("subtask"), dict) else {}
            original = result.get("request")
            if (
                not isinstance(original, dict)
                or original.get("client_request_id") != body["client_request_id"]
                or original.get("payload_sha256") != payload_sha
                or not isinstance(subtask, dict)
                or not subtask.get("id")
                or subtask.get("task_id") != result_task_id
                or subtask.get("device_id") != body["device_id"]
            ):
                return self._unknown_dispatch(request, "para original request receipt mismatch")
            task, task_id = result_task, result_task_id
            dispatched.append(
                {
                    "device_id": body["device_id"],
                    "device_name": item["device_name"],
                    "subtask_id": str(subtask.get("id") or ""),
                    "tool": self._p.tool_name,
                }
            )
            self._persist_receipt(
                request,
                {
                    "status": "dispatching",
                    "dispatcher": "para_api",
                    "api_url": api_url,
                    "task_id": task_id,
                    "devices": list(dispatched),
                    **frozen,
                },
            )
        return self._persist_receipt(
            request,
            {
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
                **frozen,
            },
        )

    @staticmethod
    def _supports_recovery(health: httpx.Response) -> bool:
        try:
            body = health.json()
        except ValueError:
            return False
        return (
            isinstance(body, dict)
            and type(body.get("task_request_recovery_version")) is int
            and body["task_request_recovery_version"] == 1
        )

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
        if dispatch.get("status") == "dispatch_pending":
            return "已核对原任务；部分设备尚未派发，等待原任务继续执行。"
        if dispatch.get("status") in {"dispatching", "dispatch_unknown"}:
            if dispatch.get("dispatcher") == "para_api" and not dispatch.get("task_id"):
                if dispatch.get("pending_request_id"):
                    return "Para 的创建回执尚未确认；已保存原请求号，正在等待按原请求核对任务。"
                return (
                    "Para 可能已创建任务，但未能确认任务 ID，需要人工核对；"
                    "已保留原请求，不会重新派发。"
                )
            return "执行结果待核对；已保留原请求和已有回执，不会重新派发。"
        if dispatch.get("status") == "completed":
            return str(dispatch.get("response", {}).get("text") or "任务已完成。")
        return "思考中..."
