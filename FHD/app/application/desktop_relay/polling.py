"""Relay task admission, owned worker cleanup and completion reporting."""

from __future__ import annotations

import logging
import os
from _thread import LockType
from collections.abc import Callable
from dataclasses import dataclass

from app.application.desktop_relay import e2ee
from app.application.desktop_relay.messages import _BLOCKED_STATUSES, _FAILED_STATUSES
from app.application.desktop_relay.protocols import (
    ApiUrlCall,
    CompletionCall,
    ConditionalConfigUpdate,
    HttpClientFactory,
    JsonObject,
    ReadConfig,
    RelayBinding,
    StopSignal,
    WorkerFactory,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class PollingPorts:
    read_config: ReadConfig
    update_config: ConditionalConfigUpdate
    base_url: Callable[[], str]
    api_url: ApiUrlCall
    http_client: HttpClientFactory
    timeout: Callable[[], float]
    now: Callable[[], float]
    monotonic: Callable[[], float]
    state_lock: Callable[[], LockType]
    stop_signal: Callable[[], StopSignal]
    inflight: Callable[[], set[str]]
    inflight_lock: Callable[[], LockType]
    max_concurrent: Callable[[], int]
    create_worker: WorkerFactory
    complete_task: Callable[[], CompletionCall]
    execute_task: Callable[[JsonObject], JsonObject]


class RelayTaskDelivery:
    def __init__(self, ports: PollingPorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger
        self._polling = False
        self._claims: dict[str, object] = {}

    def poll_once(self) -> None:
        with self.ports.state_lock():
            if self._polling or self.ports.stop_signal().is_set():
                return
            self._polling = True
        try:
            self._fetch_tasks()
        finally:
            with self.ports.state_lock():
                self._polling = False

    def _fetch_tasks(self) -> None:
        config = self.ports.read_config()
        binding = RelayBinding.from_config(config, self.ports.base_url())
        if not binding.valid:
            return
        with self.ports.inflight_lock():
            free = self.ports.max_concurrent() - len(self.ports.inflight())
        if free <= 0:
            return
        with self.ports.http_client(self.ports.timeout()) as client:
            response = client.post(
                self.ports.api_url("/api/mobile/v1/relay/desktop/poll", binding.base_url),
                json={
                    "relay_id": binding.relay_id,
                    "desktop_token": binding.desktop_token,
                    "max_tasks": free,
                },
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else {}
            tasks = data.get("tasks") if isinstance(data, dict) else []
        changes: JsonObject = {}
        now_epoch = int(self.ports.now())
        try:
            sync_persist_interval = max(
                4, int(os.environ.get("XCAGI_RELAY_SYNC_PERSIST_INTERVAL_SEC") or "60")
            )
        except (TypeError, ValueError):
            sync_persist_interval = 60
        # 心跳时间戳不需要每轮 poll 都写盘；降频可显著降低 Windows 上
        # 临时文件替换次数，也减少异常退出时配置被破坏的窗口。
        if now_epoch - int(config.get("last_relay_sync_at") or 0) >= sync_persist_interval:
            changes["last_relay_sync_at"] = now_epoch
        desktop = data.get("desktop") if isinstance(data, dict) else None
        if isinstance(desktop, dict):
            is_paired = (
                str(desktop.get("status") or "") == "paired"
                or int(desktop.get("mobile_user_id") or 0) > 0
            )
            if is_paired:
                changes["paired"] = True
            mobile_username = str(desktop.get("mobile_username") or "").strip()
            if mobile_username:
                changes["mobile_username"] = mobile_username
        if self.ports.update_config(binding, changes) is None:
            return
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "")
            if task_id:
                self._submit(task, task_id, binding)

    def _release(self, task_id: str, claim: object | None = None) -> None:
        with self.ports.inflight_lock():
            if claim is not None and self._claims.get(task_id) is not claim:
                return
            self._claims.pop(task_id, None)
            self.ports.inflight().discard(task_id)

    def _submit(self, task: JsonObject, task_id: str, binding: RelayBinding) -> None:
        stop = self.ports.stop_signal()
        with self.ports.state_lock():
            if stop.is_set():
                return
            with self.ports.inflight_lock():
                inflight = self.ports.inflight()
                if task_id in inflight or len(inflight) >= self.ports.max_concurrent():
                    return
                claim = self._claims[task_id] = object()
                inflight.add(task_id)
        started = False
        try:
            complete = self.ports.complete_task()

            def run() -> None:
                try:
                    with self.ports.state_lock():
                        admitted = not stop.is_set()
                    if admitted:
                        complete(task, binding.relay_id, binding.desktop_token, binding.base_url)
                finally:
                    self._release(task_id, claim)

            worker = self.ports.create_worker(run, f"relay-task-{task_id[:8]}")
            if stop.is_set():
                return
            worker.start()
            started = True
        finally:
            if not started:
                self._release(task_id, claim)

    def _post_result(
        self,
        task_id: str,
        relay_id: str,
        desktop_token: str,
        base_url: str,
        result: JsonObject,
        started: float,
        *,
        shared: bytes | None,
        ref: str = "",
    ) -> None:
        relay_status = str(result.pop("_relay_status", "") or "").strip()
        if not relay_status:
            relay_status = "failed" if result.get("error") else "completed"
        result["elapsed_seconds"] = round(max(0.0, self.ports.monotonic() - started), 1)
        if relay_status in _FAILED_STATUSES or relay_status in _BLOCKED_STATUSES:
            result.setdefault("error_code", relay_status)
            result.setdefault("error_message", str(result.get("error") or "").strip())
        body = e2ee.seal_result(result, shared, ref=ref) if shared else result
        with self.ports.http_client(self.ports.timeout()) as client:
            client.post(
                self.ports.api_url(
                    f"/api/mobile/v1/relay/desktop/tasks/{task_id}/complete", base_url
                ),
                json={
                    "relay_id": relay_id,
                    "desktop_token": desktop_token,
                    "status": relay_status,
                    "result": body,
                },
            ).raise_for_status()

    def complete(self, task: JsonObject, relay_id: str, desktop_token: str, base_url: str) -> None:
        task_id = str(task.get("task_id") or "")
        started = self.ports.monotonic()
        try:
            config = self.ports.read_config()
            private_key = str(config.get("e2ee_private_key") or "").strip()
            envelope = task.get("payload")
            if not e2ee.is_envelope(envelope) or not private_key:
                # 兼容尚未生成密钥的旧执行端（服务端对其不强制加密）。
                try:
                    result = self.ports.execute_task(task)
                except RECOVERABLE_ERRORS:
                    self.logger.warning("mobile relay task %s failed", task_id, exc_info=True)
                    return
                self._safe_post(
                    task_id, relay_id, desktop_token, base_url, result, started, shared=None
                )
                return
            ref = str(envelope.get("ref") or "") if isinstance(envelope, dict) else ""
            try:
                payload, shared = e2ee.open_envelope(envelope, private_key)
                result = self.ports.execute_task({**task, "payload": payload})
            except RECOVERABLE_ERRORS:
                self.logger.warning("mobile relay task %s failed", task_id, exc_info=True)
                # 解密或执行失败时只回传错误标记，绝不把明文内容带到云端。
                self._safe_post(
                    task_id,
                    relay_id,
                    desktop_token,
                    base_url,
                    {"e2ee_error": True},
                    started,
                    shared=None,
                    status="failed",
                )
                return
            self._safe_post(
                task_id, relay_id, desktop_token, base_url, result, started, shared=shared, ref=ref
            )
        finally:
            self._release(task_id)

    def _safe_post(
        self,
        task_id: str,
        relay_id: str,
        desktop_token: str,
        base_url: str,
        result: JsonObject,
        started: float,
        *,
        shared: bytes | None,
        ref: str = "",
        status: str = "",
    ) -> None:
        try:
            if status:
                self._post_raw_result(task_id, relay_id, desktop_token, base_url, status, result)
                return
            self._post_result(
                task_id, relay_id, desktop_token, base_url, result, started, shared=shared, ref=ref
            )
        except RECOVERABLE_ERRORS:
            self.logger.warning("mobile relay task %s result report failed", task_id)

    def _post_raw_result(
        self,
        task_id: str,
        relay_id: str,
        desktop_token: str,
        base_url: str,
        status: str,
        result: JsonObject,
    ) -> None:
        with self.ports.http_client(self.ports.timeout()) as client:
            client.post(
                self.ports.api_url(
                    f"/api/mobile/v1/relay/desktop/tasks/{task_id}/complete", base_url
                ),
                json={
                    "relay_id": relay_id,
                    "desktop_token": desktop_token,
                    "status": status,
                    "result": result,
                },
            ).raise_for_status()
