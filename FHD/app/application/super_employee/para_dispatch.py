"""Para / DevFleet dispatch mixin."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.application.execution_scope import (
    CONTEXT_TOKEN_KEY,
)

from .profiles import (  # noqa: F401
    _PARA_TOKEN_CACHE,
    _PARA_TOKEN_TTL,
    _RELAY_WT_LOCKS,
    _RELAY_WT_LOCKS_GUARD,
    _SUBTASK_LABELS,
    _TASK_MARKERS,
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DEFAULT_PARA_API_URL,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    TASK_ID_RE,
    TRAE_PROFILE,
    SuperEmployeeToolProfile,
    _chunk_text,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _facade_attr,
    _relay_wt_lock,
    _safe_json_line,
    _trae_cli_command,
    _utc_now,
)

logger = logging.getLogger(__name__)


class SuperEmployeeParaDispatchMixin:
    def _build_dispatch_request(
        self,
        *,
        request_id: str,
        created_at: str,
        user_id: int,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # 工作区只在工厂域解析为真实工程路径；产品域绝不向派工/远端设备暴露服务端 repo 路径。
        if self._grant.is_factory:
            workspace_root = self._factory_workspace_root()
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
            "scope": self._grant.scope.value,
            "workspace_id": self._grant.workspace_id or "",
            # 纵深防御：无论调用方是否经 invoke 抹除，平台令牌都不得进派工/持久化载荷。
            "raw_context": {k: v for k, v in context.items() if k != CONTEXT_TOKEN_KEY},
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
        return self._messages.write_outbox(request, status=status, accepted=accepted, reason=reason)

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
            text = str(item.get("body") or "")
            body = self._direct_reply_body(text)
            if not body and cli_backfills < 1 and self._should_reply_with_cli(text, {}):
                body, _ = self._compose_direct_chat_reply(text, {})
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
        return self._messages.public_message(item)
