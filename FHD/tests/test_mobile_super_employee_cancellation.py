from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.application import super_employee_service as super_employee_module
from app.application.mobile_super_employee_cancellation import (
    MobileSuperEmployeeCancellationRegistry,
    MobileSuperEmployeeTaskConflict,
    MobileSuperEmployeeTaskIdError,
)
from app.application.super_employee_service import CODEX_PROFILE, SuperEmployeeService
from app.fastapi_routes import mobile_api as _mobile_api_module  # noqa: F401
from app.fastapi_routes import mobile_api_extensions as mobile_ext
from app.fastapi_routes.mobile_extensions.models import CodexSuperEmployeeMobileMessageBody


def _mobile_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [(b"host", b"192.168.10.2:17500")],
            "client": ("192.168.10.8", 45678),
            "server": ("192.168.10.2", 17500),
        }
    )


def _enterprise_user(user_id: int, tenant_id: int):
    return SimpleNamespace(
        id=user_id,
        role="enterprise",
        tier="enterprise",
        tenant_id=tenant_id,
        is_active=True,
    )


def test_usage_limit_result_is_not_reported_as_http_success() -> None:
    response = mobile_ext._mobile_super_employee_result_response(
        {
            "ok": False,
            "error_code": "usage_limit",
            "error_message": "Codex 当前用量已耗尽，请在 3:27 PM 后重试",
        }
    )

    assert response.status_code == 429
    body = json.loads(response.body)
    assert body["success"] is False
    assert body["code"] == 429
    assert body["data"]["error_code"] == "usage_limit"


def test_registry_cancellation_is_tenant_and_user_scoped() -> None:
    registry = MobileSuperEmployeeCancellationRegistry()
    lease = registry.acquire(
        tenant_id=11,
        user_id=7,
        client_task_id="mobile-task-123",
    )

    assert registry.cancel(tenant_id=11, user_id=8, client_task_id="mobile-task-123") is False
    assert registry.cancel(tenant_id=12, user_id=7, client_task_id="mobile-task-123") is False
    assert lease.event.is_set() is False

    assert registry.cancel(tenant_id=11, user_id=7, client_task_id="mobile-task-123") is True
    assert lease.event.is_set() is True
    assert registry.release(lease) is True
    assert registry.active_count() == 0
    # SSE -> direct fallback is the same logical mobile run and reuses its id.
    fallback = registry.acquire(
        tenant_id=11,
        user_id=7,
        client_task_id="mobile-task-123",
    )
    assert fallback.event.is_set() is False
    assert registry.release(fallback) is True


def test_late_cancel_is_opaque_and_task_id_reuse_waits_for_tombstone() -> None:
    now = [100.0]
    registry = MobileSuperEmployeeCancellationRegistry(
        tombstone_ttl_seconds=10,
        clock=lambda: now[0],
    )
    lease = registry.acquire(tenant_id=0, user_id=5, client_task_id="late-task")
    assert registry.release(lease) is True

    assert registry.cancel(tenant_id=0, user_id=5, client_task_id="late-task") is False
    assert registry.release(lease) is False
    with pytest.raises(MobileSuperEmployeeTaskConflict):
        registry.acquire(tenant_id=0, user_id=5, client_task_id="late-task")

    now[0] = 111.0
    replacement = registry.acquire(tenant_id=0, user_id=5, client_task_id="late-task")
    assert replacement.event.is_set() is False
    assert registry.release(replacement) is True


@pytest.mark.parametrize(
    ("tenant_id", "user_id", "task_id"),
    [
        (0, 0, "valid-task"),
        (-1, 1, "valid-task"),
        (0, 1, ""),
        (0, 1, "bad/task"),
        (0, 1, "x" * 129),
    ],
)
def test_registry_rejects_invalid_principal_or_task_id(
    tenant_id: int, user_id: int, task_id: str
) -> None:
    registry = MobileSuperEmployeeCancellationRegistry()
    with pytest.raises(MobileSuperEmployeeTaskIdError):
        registry.acquire(
            tenant_id=tenant_id,
            user_id=user_id,
            client_task_id=task_id,
        )


@pytest.mark.asyncio
async def test_stream_cancel_route_is_scoped_and_late_cancel_is_not_acknowledged(
    monkeypatch,
) -> None:
    registry = MobileSuperEmployeeCancellationRegistry(tombstone_ttl_seconds=30)
    monkeypatch.setattr(mobile_ext, "mobile_super_employee_cancellations", registry)

    class BlockingStreamService:
        def __init__(self) -> None:
            self.event: threading.Event | None = None
            self.started = asyncio.Event()

        def set_cancellation_event(self, event: threading.Event | None) -> None:
            self.event = event

        async def invoke_stream(self, **_kwargs):
            self.started.set()
            yield {"type": "status", "text": "running"}
            while self.event is not None and not self.event.is_set():
                await asyncio.sleep(0.01)
            yield {"type": "error", "message": "任务已取消", "error_code": "cancelled"}

    service = BlockingStreamService()
    monkeypatch.setattr(mobile_ext, "_super_employee_service_for_tool", lambda _tool: service)
    owner = _enterprise_user(7, 11)
    other_user = _enterprise_user(8, 11)
    request = _mobile_request("/api/mobile/v1/admin/codex-super-employee/messages/stream")
    response = await mobile_ext._stream_super_employee_invoke(
        request,
        "codex",
        {
            "message": "run until cancelled",
            "context": {"client_task_id": "route-stream-task"},
        },
        owner,
    )
    assert response.status_code == 200
    assert response.headers["x-xcagi-client-task-id"] == "route-stream-task"

    async def consume() -> list[str | bytes]:
        return [chunk async for chunk in response.body_iterator]

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(service.started.wait(), timeout=1)
    cross_user = await mobile_ext.mobile_admin_super_employee_cancel(
        request,
        "route-stream-task",
        user=other_user,
    )
    assert cross_user.status_code == 404
    assert service.event is not None and service.event.is_set() is False

    acknowledged = await mobile_ext.mobile_admin_super_employee_cancel(
        request,
        "route-stream-task",
        user=owner,
    )
    assert acknowledged["data"]["ack"] is True
    chunks = await asyncio.wait_for(consumer, timeout=2)
    assert any("cancelled" in str(chunk) for chunk in chunks)
    assert registry.active_count() == 0

    late = await mobile_ext.mobile_admin_super_employee_cancel(
        request,
        "route-stream-task",
        user=owner,
    )
    assert late.status_code == 404


@pytest.mark.asyncio
async def test_direct_fallback_registers_task_and_cancel_route_stops_worker(
    monkeypatch,
) -> None:
    registry = MobileSuperEmployeeCancellationRegistry(tombstone_ttl_seconds=0)
    monkeypatch.setattr(mobile_ext, "mobile_super_employee_cancellations", registry)

    class BlockingDirectService:
        def __init__(self) -> None:
            self.event: threading.Event | None = None
            self.started = threading.Event()

        def set_cancellation_event(self, event: threading.Event | None) -> None:
            self.event = event

        def invoke(self, **_kwargs):
            self.started.set()
            assert self.event is not None
            assert self.event.wait(timeout=3)
            raise super_employee_module.SuperEmployeeExecutionCancelled("cancelled")

    service = BlockingDirectService()
    monkeypatch.setattr(mobile_ext, "CodexSuperEmployeeService", lambda: service)
    owner = _enterprise_user(21, 31)
    request = _mobile_request("/api/mobile/v1/admin/codex-super-employee/messages")
    invocation = asyncio.create_task(
        mobile_ext.mobile_admin_codex_super_employee_invoke(
            request,
            CodexSuperEmployeeMobileMessageBody(
                message="direct long task",
                context={"client_task_id": "route-direct-task"},
            ),
            user=owner,
        )
    )
    assert await asyncio.to_thread(service.started.wait, 1)

    acknowledged = await mobile_ext.mobile_admin_super_employee_cancel(
        request,
        "route-direct-task",
        user=owner,
    )
    assert acknowledged["data"]["ack"] is True
    result = await asyncio.wait_for(invocation, timeout=2)
    assert result.status_code == 409
    assert registry.active_count() == 0


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group lifecycle assertion")
async def test_lan_cancellation_terminates_a_real_cli_subprocess(tmp_path) -> None:
    pid_path = tmp_path / "cli.pid"

    def command_builder(_cli_path, _prompt, _output_path, _cwd):
        script = (
            "import json, os, time\n"
            f"open({str(pid_path)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
            "print(json.dumps({'type':'result','result':'started'}), flush=True)\n"
            "time.sleep(30)\n"
        )
        return [sys.executable, "-u", "-c", script]

    profile = replace(
        CODEX_PROFILE,
        cli_reads_output_file=False,
        cli_stream_json=True,
        cli_command_builder=command_builder,
    )
    service = SuperEmployeeService(profile, storage_root=tmp_path / "state")
    registry = MobileSuperEmployeeCancellationRegistry(tombstone_ttl_seconds=0)
    lease = registry.acquire(
        tenant_id=3,
        user_id=9,
        client_task_id="real-cli-task",
    )
    service.set_cancellation_event(lease.event)

    async def collect() -> list[dict]:
        return [
            event
            async for event in service._run_cli_streaming(
                sys.executable,
                "unused",
                str(tmp_path),
            )
        ]

    run = asyncio.create_task(collect())
    for _ in range(300):
        if pid_path.is_file():
            break
        await asyncio.sleep(0.01)
    assert pid_path.is_file(), "real CLI process did not start"
    assert (
        registry.cancel(
            tenant_id=3,
            user_id=9,
            client_task_id="real-cli-task",
        )
        is True
    )

    events = await asyncio.wait_for(run, timeout=5)
    assert events[-1] == {
        "type": "error",
        "message": "任务已取消",
        "error_code": "cancelled",
    }
    assert registry.release(lease) is True

    pid = int(pid_path.read_text(encoding="utf-8"))
    for _ in range(200):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("cancelled CLI subprocess is still alive")
