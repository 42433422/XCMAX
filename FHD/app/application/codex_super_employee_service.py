"""Codex super-employee dispatch channel for the admin information console."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.utils.path_utils import get_app_data_dir


CODEX_SUPER_EMPLOYEE_ID = "codex-super-employee"
CODEX_SUPER_EMPLOYEE_NAME = "超级员工-Codex"
DEFAULT_PARA_API_URL = "http://127.0.0.1:3001"
DISPATCHER_MESSAGE_KIND = "dispatcher"
CODEX_RESULT_MESSAGE_KIND = "codex_result"
CODEX_DIRECT_MESSAGE_KIND = "codex_direct"
PARA_TERMINAL_TASK_STATUSES = {"completed", "failed", "merged", "merge_conflict", "cancelled"}
TASK_ID_RE = re.compile(r"任务\s*ID[:：]\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})")


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


class CodexSuperEmployeeService:
    """Persist software-internal Codex calls and optionally dispatch them out."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        codex_cli_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        root = Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        self._root = root / "codex_super_employee"
        self._root.mkdir(parents=True, exist_ok=True)
        self._messages_path = self._root / "messages.jsonl"
        self._outbox_dir = self._root / "outbox"
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        self._http_client_factory = http_client_factory or self._default_http_client
        self._codex_cli_runner = codex_cli_runner or subprocess.run

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
            self._public_message(item)
            for item in all_rows
            if int(item.get("user_id") or 0) == uid
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
        if self._should_reply_with_codex_cli(text, ctx):
            direct_body = self._codex_cli_reply_body(text, ctx) or self._direct_reply_body(text)
            if not direct_body:
                direct_body = "Codex CLI 暂时没有返回内容，请确认本机 Codex 已登录后重试。"
            assistant_msg = self._message_row(
                user_id=int(user_id),
                role="assistant",
                body=direct_body,
                created_at=_utc_now(),
                request_id=request_id,
                status="completed",
                extra={"kind": CODEX_DIRECT_MESSAGE_KIND},
            )
            self._append_messages([user_msg, assistant_msg])
            dispatch = {
                "request_id": request_id,
                "status": "completed",
                "accepted": True,
                "queued": False,
                "device_scope": "all_devices",
                "dispatcher": "codex_cli",
            }
            return {
                "employee": {
                    "id": CODEX_SUPER_EMPLOYEE_ID,
                    "name": CODEX_SUPER_EMPLOYEE_NAME,
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
                "devices": dispatch.get("devices") if isinstance(dispatch.get("devices"), list) else [],
            },
        )
        self._append_messages([user_msg, dispatcher_msg])
        return {
            "employee": {
                "id": CODEX_SUPER_EMPLOYEE_ID,
                "name": CODEX_SUPER_EMPLOYEE_NAME,
                "device_scope": "all_devices",
            },
            "dispatch": dispatch,
            "message": self._public_message(user_msg),
            # Kept for API compatibility. The dispatch acknowledgement is a
            # system/dispatcher message; real Codex output is appended later.
            "assistant_message": self._public_message(dispatcher_msg),
            "messages": self.list_messages(user_id=int(user_id)),
        }

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
            or os.environ.get("XCMAX_CODEX_WORKSPACE_ROOT")
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
            "employee_id": CODEX_SUPER_EMPLOYEE_ID,
            "employee_name": CODEX_SUPER_EMPLOYEE_NAME,
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
            os.environ.get("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE")
            or os.environ.get("MODSTORE_PARA_DISPATCH_MODE")
            or "auto"
        ).strip().lower()
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
            os.environ.get("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK")
            or os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK")
            or ""
        ).strip()
        if not webhook:
            return self._write_outbox(
                request,
                status="queued",
                accepted=False,
                reason=para_reason or "codex_dispatch_webhook_not_configured",
            )
        try:
            with self._http_client_factory() as client:
                resp = client.post(webhook, json=request)
            body: Any
            try:
                body = resp.json() if resp.content else {}
            except Exception:
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
                reason=str(body.get("error") or body.get("message") or f"HTTP {resp.status_code}")[:500],
            )
        except Exception as exc:
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
                selected = self._select_para_codex_devices(devices if isinstance(devices, list) else [], request)
                if not selected:
                    return self._write_outbox(
                        request,
                        status="queued",
                        accepted=False,
                        reason="para_no_online_codex_device",
                    ), "para_no_online_codex_device"

                prepared = []
                for device in selected:
                    prepared.append(self._ensure_para_codex_device(client, api_url, token, device))

                return self._create_para_task(client, api_url, token, request, prepared), ""
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            return None, f"para_api_unreachable: {exc}"
        except Exception as exc:
            return self._write_outbox(
                request,
                status="dispatch_error",
                accepted=False,
                reason=f"para_dispatch_error: {str(exc)[:460]}",
            ), str(exc)[:500]

    def _default_http_client(self) -> httpx.Client:
        timeout = float(
            os.environ.get("XCMAX_CODEX_DISPATCH_TIMEOUT_SEC")
            or os.environ.get("XCMAX_CODEX_WEBHOOK_TIMEOUT_SEC")
            or "30"
        )
        return httpx.Client(timeout=timeout)

    def _para_api_url(self) -> str:
        value = (
            os.environ.get("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL")
            or os.environ.get("MODSTORE_PARA_API_URL")
            or os.environ.get("DEVFLEET_API_URL")
            or DEFAULT_PARA_API_URL
        ).strip().rstrip("/")
        if value.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return ""
        return value

    def _para_token(self, client: httpx.Client, api_url: str) -> str:
        token = (
            os.environ.get("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN")
            or os.environ.get("MODSTORE_PARA_TOKEN")
            or os.environ.get("DEVFLEET_TOKEN")
            or ""
        ).strip()
        if token:
            return token
        resp = client.post(f"{api_url}/api/auth/guest", json={})
        body = self._json_response(resp)
        if resp.status_code >= 400:
            raise RuntimeError(self._error_message(body, f"Para guest 登录失败 ({resp.status_code})"))
        token = str(body.get("token") or body.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("Para guest 登录未返回 token")
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

    def _select_para_codex_devices(
        self,
        devices: list[Any],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        target_devices = request.get("target_devices")
        targets = {
            str(item).strip()
            for item in target_devices
            if str(item).strip()
        } if isinstance(target_devices, list) else {"all"}
        candidates: list[dict[str, Any]] = []
        for item in devices:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") != "online":
                continue
            if "all" not in targets and str(item.get("id") or "") not in targets and str(item.get("name") or "") not in targets:
                continue
            codex_tool = self._device_tool(item, "codex")
            if codex_tool and str(codex_tool.get("status") or "") == "not_installed":
                continue
            if codex_tool and str(codex_tool.get("status") or "") == "running" and codex_tool.get("currentTask"):
                continue
            capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
            if not codex_tool and capabilities.get("codex_cli") is not True:
                continue
            candidates.append(item)

        workers = [item for item in candidates if not item.get("isPrimary")]
        selected = workers or candidates
        max_devices = self._max_para_devices(request)
        return selected[:max_devices]

    def _ensure_para_codex_device(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        device: dict[str, Any],
    ) -> dict[str, Any]:
        if str(device.get("devTool") or "") == "codex":
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
            json_body={"devTool": "codex"},
        )
        updated = body.get("device")
        return updated if isinstance(updated, dict) else {**device, "devTool": "codex"}

    def _create_para_task(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        request: dict[str, Any],
        devices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raw_context = request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        title = str(request.get("title") or "超级员工-Codex 任务").strip()[:120]
        branch = str(raw_context.get("branch") or os.environ.get("MODSTORE_PARA_BASE_BRANCH") or "main").strip() or "main"
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

            result = self._para_request(client, api_url, token, "POST", "/api/tasks", json_body=body)
            task = result.get("task") if isinstance(result.get("task"), dict) else task
            task_id = str((task or {}).get("id") or task_id)
            subtask = result.get("subtask") if isinstance(result.get("subtask"), dict) else {}
            dispatched.append(
                {
                    "device_id": str(device.get("id") or ""),
                    "device_name": str(device.get("name") or ""),
                    "subtask_id": str(subtask.get("id") or ""),
                    "tool": "codex",
                }
            )

        return {
            "request_id": request["request_id"],
            "status": "accepted",
            "accepted": True,
            "queued": False,
            "device_scope": "all_devices",
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
                f"你是第 {index + 1}/{total} 台 Codex 工作设备（{device.get('name') or device.get('id')}）。"
                "请承担可独立完成的部分，避免和其他设备重复改同一批文件；提交到调度器分配的工作分支，并回写执行日志。"
            )
        parts = [prompt, suffix]
        if workspace_root:
            parts.append(f"管理端来源工作区：{workspace_root}")
        return "\n\n".join(part for part in parts if part)

    def _para_subtask_title(self, title: str, index: int, total: int) -> str:
        if total <= 1:
            return title
        labels = ["需求定位与方案", "核心实现", "验证与收尾"]
        label = labels[index] if index < len(labels) else f"工作单元 {index + 1}"
        return f"{label}：{title[:60]}"

    def _max_para_devices(self, request: dict[str, Any]) -> int:
        raw_context = request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        value = raw_context.get("max_devices") or os.environ.get("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES") or 3
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
        except Exception:
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
        path = self._outbox_dir / f"{request['created_at'].replace(':', '').replace('+', 'Z')}-{request['request_id']}.json"
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
        if dispatch.get("accepted") and dispatch.get("dispatcher") == "para_api":
            devices = dispatch.get("devices") if isinstance(dispatch.get("devices"), list) else []
            task_id = str(dispatch.get("task_id") or "")
            return f"已接入排比 Para/Codex 多设备调度器，任务已派发到 {len(devices)} 台设备。{f'任务 ID：{task_id}' if task_id else ''}".strip()
        if dispatch.get("accepted"):
            return "已调用全设备 Codex 调度通道，等待执行回传。"
        if dispatch.get("reason") == "para_no_online_codex_device":
            return "未发现在线可用 Codex 设备，任务已进入队列；请启动 Para 工作设备并登录 Codex CLI 后重试。"
        if dispatch.get("queued"):
            return "已进入软件内 Codex 调用队列，等待跨设备调度器接走。"
        return "Codex 调用未完成，请检查调度通道。"

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
            and str(item.get("kind") or "") == CODEX_DIRECT_MESSAGE_KIND
        }
        result_request_ids = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == CODEX_RESULT_MESSAGE_KIND
        }
        result_task_ids = {
            str(item.get("task_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and str(item.get("kind") or "") == CODEX_RESULT_MESSAGE_KIND
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
            changed = self._upsert_codex_result_messages(
                user_id=int(user_id),
                dispatch_row=row,
                task=task,
                rows=rows,
            ) or changed
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
            "未发现在线可用 Codex 设备",
            "任务已派发到",
            "Para/Codex",
        )
        return any(marker in body for marker in markers)

    def _extract_task_id_from_body(self, body: str) -> str:
        match = TASK_ID_RE.search(body)
        return match.group(1).strip() if match else ""

    def _should_reply_with_codex_cli(self, text: str, context: dict[str, Any]) -> bool:
        raw_mode = str(context.get("mode") or "").strip().lower()
        if raw_mode in {"chat", "qa", "direct", "codex_cli"}:
            return True
        if raw_mode in {"code", "task", "dispatch", "dev", "develop"}:
            return False
        normalized = re.sub(r"\s+", "", text.strip().lower())
        if not normalized:
            return False
        task_markers = (
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
        return not any(marker in normalized for marker in task_markers)

    def _codex_cli_reply_body(self, text: str, context: dict[str, Any]) -> str:
        if str(os.environ.get("XCMAX_CODEX_CLI_CHAT_ENABLED") or "1").strip().lower() in {
            "0",
            "false",
            "off",
            "disabled",
        }:
            return ""
        codex_path = self._codex_cli_path()
        if not codex_path:
            return ""
        timeout = self._codex_cli_timeout_seconds()
        cwd = self._codex_cli_workspace(context)
        prompt = self._codex_cli_prompt(text)
        with tempfile.TemporaryDirectory(prefix="xcagi-codex-cli-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            cmd = [
                codex_path,
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
            try:
                proc = self._codex_cli_runner(
                    cmd,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return f"Codex CLI 已接通，但本次回答超过 {timeout:g} 秒还没返回。请把问题拆短一点，或直接发开发任务给我派工。"
            except Exception as exc:
                return f"Codex CLI 调用失败：{str(exc)[:300]}"
            if output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    return body
            stdout = str(getattr(proc, "stdout", "") or "").strip()
            if stdout:
                return self._clean_codex_cli_stdout(stdout)
            stderr = str(getattr(proc, "stderr", "") or "").strip()
            if getattr(proc, "returncode", 1) != 0:
                return f"Codex CLI 已接入，但本次返回失败（code {getattr(proc, 'returncode', 1)}）：{stderr[:500]}"
        return ""

    def _codex_cli_path(self) -> str:
        candidates = [
            os.environ.get("XCMAX_CODEX_CLI_PATH", ""),
            shutil.which("codex") or "",
            "/Applications/Codex.app/Contents/Resources/codex",
        ]
        for item in candidates:
            value = str(item or "").strip()
            if value and Path(value).is_file():
                return value
        return ""

    def _codex_cli_workspace(self, context: dict[str, Any]) -> str:
        candidate = str(
            context.get("workspace_root")
            or os.environ.get("XCMAX_CODEX_WORKSPACE_ROOT")
            or os.environ.get("MODSTORE_REPO_ROOT")
            or ""
        ).strip()
        if candidate and Path(candidate).exists():
            return candidate
        return str(Path(__file__).resolve().parents[2])

    def _codex_cli_timeout_seconds(self) -> float:
        raw = os.environ.get("XCMAX_CODEX_CLI_TIMEOUT_SEC") or "45"
        try:
            return max(5.0, min(120.0, float(raw)))
        except (TypeError, ValueError):
            return 45.0

    def _codex_cli_prompt(self, text: str) -> str:
        return (
            "你是 XCMAX 软件内的超级员工-Codex。请直接回答用户的问题。"
            "这是普通对话通道：不要执行命令，不要修改文件，不要调用工具。"
            "如果用户询问额度、账户余额、订阅或实时账户状态，而你无法从当前会话读取真实账户数据，请明确说明不能查看，不要编造数字。"
            "\n\n用户问题："
            f"{text.strip()}"
        )

    def _clean_codex_cli_stdout(self, stdout: str) -> str:
        lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {"codex", "tokens used"}:
                continue
            if re.fullmatch(r"[\d,]+", stripped):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _direct_reply_body(self, text: str) -> str:
        normalized = re.sub(r"[\s，。！？!?、,.]+", "", text.strip().lower())
        if not normalized:
            return ""
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
                "我是超级员工-Codex。你在软件里发普通问题时，我会直接回复；"
                "你发开发、测试、打包、提交、跨设备协作这类任务时，我会调用可用的 Codex 工作设备完成。"
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
        except Exception:
            return None

    def _upsert_direct_reply_messages(self, *, user_id: int, rows: list[dict[str, Any]]) -> bool:
        request_ids_with_reply = {
            str(item.get("dispatch_request_id") or "")
            for item in rows
            if int(item.get("user_id") or 0) == int(user_id)
            and (
                str(item.get("kind") or "") in {CODEX_DIRECT_MESSAGE_KIND, CODEX_RESULT_MESSAGE_KIND}
                or (
                    str(item.get("role") or "") == "assistant"
                    and str(item.get("kind") or "") != DISPATCHER_MESSAGE_KIND
                )
            )
        }
        changed = False
        codex_cli_backfills = 0
        for item in list(rows):
            if int(item.get("user_id") or 0) != int(user_id):
                continue
            if str(item.get("role") or "") != "user":
                continue
            request_id = str(item.get("dispatch_request_id") or "")
            if not request_id or request_id in request_ids_with_reply:
                continue
            body = self._direct_reply_body(str(item.get("body") or ""))
            if not body and codex_cli_backfills < 1:
                text = str(item.get("body") or "")
                if self._should_reply_with_codex_cli(text, {}):
                    body = self._codex_cli_reply_body(text, {}) or "Codex CLI 暂时没有返回内容，请确认本机 Codex 已登录后重试。"
                    codex_cli_backfills += 1
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
                    extra={"kind": CODEX_DIRECT_MESSAGE_KIND},
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
            head = "Para 任务已完成，Codex 执行结果已回传。"
        elif status in {"failed", "merge_conflict"} or failed:
            head = "Para 任务需要处理，Codex 错误或冲突信息已回传。"
        elif total:
            head = f"Para 任务运行中：{completed}/{total} 个子任务完成，进度 {progress}%。"
        else:
            head = "Para 任务已创建，等待 Codex 工作设备回传。"
        return f"{head}{f'任务 ID：{task_id}' if task_id else ''}"

    def _upsert_codex_result_messages(
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
            body = self._codex_result_body(task, subtask)
            if not body:
                continue
            subtask_id = str(subtask.get("id") or "")
            existing = next(
                (
                    item
                    for item in rows
                    if int(item.get("user_id") or 0) == int(user_id)
                    and str(item.get("kind") or "") == CODEX_RESULT_MESSAGE_KIND
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
                        "kind": CODEX_RESULT_MESSAGE_KIND,
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

    def _codex_result_body(self, task: dict[str, Any], subtask: dict[str, Any]) -> str:
        logs = [
            str(log.get("content") or "").strip()
            for log in _coerce_list(subtask.get("logs"))
            if isinstance(log, dict) and str(log.get("content") or "").strip()
        ]
        meaningful = [item for item in logs if not self._is_dispatcher_log(item)]
        tail = self._dedupe_log_tail(meaningful or logs)
        status = str(subtask.get("status") or "").strip()
        device_name = str(subtask.get("device_name") or subtask.get("device_id") or "").strip()
        title = str(subtask.get("title") or task.get("title") or "").strip()
        prefix = f"{device_name} / {title}".strip(" /")
        if tail:
            return f"{prefix}\n\n{tail}".strip()
        if status == "completed":
            return f"{prefix}\n\nCodex 已完成该子任务。".strip()
        if status == "failed":
            last_error = str(subtask.get("last_error") or "").strip()
            return f"{prefix}\n\nCodex 执行失败。{last_error}".strip()
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

    def _dedupe_log_tail(self, logs: list[str], *, max_items: int = 5, max_chars: int = 4000) -> str:
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
    "CODEX_SUPER_EMPLOYEE_ID",
    "CODEX_SUPER_EMPLOYEE_NAME",
    "CodexSuperEmployeeService",
]
