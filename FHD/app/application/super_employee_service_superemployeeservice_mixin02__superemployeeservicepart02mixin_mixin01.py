# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart02MixinPart01Mixin:
    def _resolve_para_tier(self, request: dict[str, _facade().Any]) -> int:
        """决定该请求走一级(1)还是二级(2)。默认一级，按需升二级。"""
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        forced = (
            (
                _facade().os.environ.get(f"{self._p.env_super_prefix}_PARA_FORCE_TIER")
                or _facade().os.environ.get("MODSTORE_PARA_FORCE_TIER")
                or ""
            )
            .strip()
            .lower()
        )
        if forced in {"1", "local", "single", "本机"}:
            return 1
        if forced in {"2", "fleet", "multi", "多设备"}:
            return 2
        if not isinstance(raw_context, dict):
            raw_context = {}
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
        self, devices: list[_facade().Any], request: dict[str, _facade().Any]
    ) -> list[dict[str, _facade().Any]]:
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
            return []
        for item in devices:
            if isinstance(item, dict) and item.get("isPrimary"):
                return [item] if self._device_eligible(item) else []
        for item in devices:
            if self._device_eligible(item):
                return [item]
        return []

    def _select_devices_by_tier(
        self, devices: list[_facade().Any], request: dict[str, _facade().Any]
    ) -> tuple[int, list[dict[str, _facade().Any]]]:
        """按 tier 选设备，返回 (实际 tier, 选中设备列表)。

        一级优先：先选本机单设备；本机无合格设备则自动升二级选多设备。
        """
        tier = self._resolve_para_tier(request)
        if tier == 1:
            local = self._select_local_device(devices, request)
            if local:
                return (1, local)
            return (2, self._select_para_devices(devices, request))
        return (2, self._select_para_devices(devices, request))

    def _ensure_para_device(
        self,
        client: _facade().httpx.Client,
        api_url: str,
        token: str,
        device: dict[str, _facade().Any],
    ) -> dict[str, _facade().Any]:
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
        client: _facade().httpx.Client,
        api_url: str,
        token: str,
        request: dict[str, _facade().Any],
        devices: list[dict[str, _facade().Any]],
        tier: int = 2,
    ) -> dict[str, _facade().Any]:
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        title = str(request.get("title") or f"{self._p.employee_name} 任务").strip()[:120]
        if not isinstance(raw_context, dict):
            raw_context = {}
        branch = (
            str(
                raw_context.get("branch")
                or _facade().os.environ.get("MODSTORE_PARA_BASE_BRANCH")
                or "main"
            ).strip()
            or "main"
        )
        repo_url = str(
            raw_context.get("repo_url")
            or _facade().os.environ.get("MODSTORE_PARA_REPO_URL")
            or _facade().os.environ.get("DEVFLEET_REPO_URL")
            or ""
        ).strip()
        task_id = ""
        task: dict[str, _facade().Any] | None = None
        dispatched: list[dict[str, _facade().Any]] = []
        for index, device in enumerate(devices):
            body: dict[str, _facade().Any] = {
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

    def _para_prompt(
        self,
        request: dict[str, _facade().Any],
        device: dict[str, _facade().Any],
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

    def _para_subtask_title(self, title: str, index: int, total: int) -> str:
        if total <= 1:
            return title
        label = (
            _facade()._SUBTASK_LABELS[index]
            if index < len(_facade()._SUBTASK_LABELS)
            else f"工作单元 {index + 1}"
        )
        return f"{label}：{title[:60]}"

    def _max_para_devices(self, request: dict[str, _facade().Any]) -> int:
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        if not isinstance(raw_context, dict):
            raw_context = {}
        value = (
            raw_context.get("max_devices")
            or _facade().os.environ.get(f"{self._p.env_super_prefix}_MAX_DEVICES")
            or 3
        )
        try:
            return max(1, min(8, int(value)))
        except (TypeError, ValueError):
            return 3

    def _device_tool(
        self, device: dict[str, _facade().Any], name: str
    ) -> dict[str, _facade().Any] | None:
        tools = device.get("tools")
        if not isinstance(tools, list):
            return None
        for tool in tools:
            if isinstance(tool, dict) and tool.get("toolName") == name:
                return tool
        return None

    def _json_response(self, resp: _facade().httpx.Response) -> dict[str, _facade().Any]:
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {"raw": resp.text[:1000]}
        return body if isinstance(body, dict) else {"data": body}

    def _error_message(self, body: dict[str, _facade().Any], fallback: str) -> str:
        return str(body.get("error") or body.get("message") or fallback)[:500]

    def _write_outbox(
        self, request: dict[str, _facade().Any], *, status: str, accepted: bool, reason: str
    ) -> dict[str, _facade().Any]:
        return self._messages.write_outbox(request, status=status, accepted=accepted, reason=reason)

    def _dispatch_reply(self, dispatch: dict[str, _facade().Any]) -> str:
        _ = dispatch
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
        extra: dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        return self._messages.message_row(
            user_id=user_id,
            role=role,
            body=body,
            created_at=created_at,
            request_id=request_id,
            status=status,
            extra=extra,
        )

    def _append_messages(self, messages: list[dict[str, _facade().Any]]) -> None:
        self._messages.append_messages(messages)

    def _read_all_message_rows(self) -> list[dict[str, _facade().Any]]:
        return self._messages.read_all_message_rows()

    def _write_all_message_rows(self, rows: list[dict[str, _facade().Any]]) -> None:
        self._messages.write_all_message_rows(rows)

    def _sync_para_task_updates(
        self, *, user_id: int, rows: list[dict[str, _facade().Any]]
    ) -> None:
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
            if str(row.get("kind") or "") != _facade().DISPATCHER_MESSAGE_KIND:
                continue
            task_id = str(row.get("task_id") or "").strip()
            if not task_id:
                continue
            request_id = str(row.get("dispatch_request_id") or "")
            if request_id and request_id in direct_request_ids:
                continue
            task_status = str(row.get("task_status") or row.get("status") or "").strip()
            if task_status in _facade().PARA_TERMINAL_TASK_STATUSES and (
                request_id and request_id in result_request_ids or task_id in result_task_ids
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
                    user_id=int(user_id), dispatch_row=row, task=task, rows=rows
                )
                or changed
            )
        if changed:
            self._write_all_message_rows(rows)
