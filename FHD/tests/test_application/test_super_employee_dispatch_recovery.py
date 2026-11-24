"""Remote acknowledgement loss must never dispatch a second logical action."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.super_employee.para import ParaRemoteError


def _ack(request, *, task_id="task-original", subtask_id="sub-1"):
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "task": {"id": task_id, "status": "running"},
            "subtask": {
                "id": subtask_id,
                "task_id": task_id,
                "device_id": body["device_id"],
            },
            "request": {
                "client_request_id": body["client_request_id"],
                "payload_sha256": hashlib.sha256(
                    json.dumps(
                        {key: value for key, value in body.items() if key != "client_request_id"},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            },
        },
    )


def _service(
    tmp_path,
    monkeypatch,
    task_handler,
    *,
    devices=1,
    webhook_handler=None,
    receipt_handler=None,
    recovery_version=1,
    task_status="running",
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "auto")
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "https://para.test")
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "test-token")
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", "https://hook.test/execute")
    requests = []

    def handle(request):
        requests.append((request.method, request.url.host, request.url.path))
        if request.url.host == "hook.test":
            if webhook_handler:
                return webhook_handler(request)
            return httpx.Response(200, json={"accepted": True})
        if request.url.path == "/api/health":
            return httpx.Response(
                200, json={"ok": True, "task_request_recovery_version": recovery_version}
            )
        if request.url.path == "/api/devices":
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {
                            "id": f"device-{i}",
                            "name": f"Worker {i}",
                            "status": "online",
                            "devTool": "codex",
                            "tools": [{"toolName": "codex", "status": "idle"}],
                        }
                        for i in range(devices)
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/api/tasks":
            return task_handler(request)
        if request.method == "GET" and request.url.path.startswith("/api/tasks/by-request/"):
            return (
                receipt_handler(request)
                if receipt_handler
                else httpx.Response(404, json={"error": "request_not_found"})
            )
        if request.method == "GET" and request.url.path == "/api/tasks/task-original":
            return httpx.Response(
                200, json={"task": {"id": "task-original", "status": task_status}}
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def create():
        service = CodexSuperEmployeeService(
            storage_root=tmp_path,
            http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handle)),
        )
        monkeypatch.setattr(
            service,
            "_compose_direct_chat_reply",
            lambda *args: pytest.fail("remote dispatch fell through to local CLI"),
        )
        return service

    return create, requests


@pytest.mark.parametrize(
    "error_type", [httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError]
)
def test_lost_ack_is_durable_and_never_falls_through(tmp_path, monkeypatch, error_type):
    effects = []

    def submit(request):
        effects.append(json.loads(request.content))
        raise error_type("ack lost", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "original-request", "mode": "code"}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert first["dispatch"]["status"] == "dispatch_unknown"
    assert first["dispatch"]["queued"] is False
    assert not first["dispatch"].get("task_id")
    assert "按原请求核对" in first["assistant_message"]["body"]
    saved = json.loads(Path(first["dispatch"]["outbox_path"]).read_text())
    assert saved["request_id"] == "original-request"
    assert saved["dispatch_receipt"]["reconciliation_required"] is True

    second_service = create()
    second = second_service.invoke(user_id=7, message="修复登录问题", context=context)
    assert second["dispatch"]["request_id"] == "original-request"
    assert second["dispatch"]["status"] == "dispatch_unknown"
    assert "按原请求核对" in second["assistant_message"]["body"]
    assert len(effects) == 1
    assert not any(host == "hook.test" for _, host, _ in requests)
    assert len(second_service._read_all_message_rows()) == 2
    # A message-list backfill must not turn an unresolved remote action into CLI work.
    monkeypatch.setattr(second_service, "_should_reply_with_cli", lambda *args: True)
    second_service.list_messages(user_id=7)


@pytest.mark.parametrize("status_code", [400, 503])
def test_remote_http_failure_after_send_keeps_original_plan_unknown(
    tmp_path, monkeypatch, status_code
):
    effects = []

    def submit(request):
        effects.append(json.loads(request.content))
        return httpx.Response(status_code, json={"error": "task outcome not confirmed"})

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "http-response-loss", "mode": "code"}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    receipt = first["dispatch"]
    assert receipt["status"] == "dispatch_unknown"
    assert receipt["accepted"] is receipt["queued"] is receipt["safe_to_fallback"] is False
    assert receipt["reason"] == "task outcome not confirmed"
    assert receipt["pending_request_id"] == effects[0]["client_request_id"]
    before = json.loads(Path(receipt["outbox_path"]).read_text())["dispatch_receipt"]
    second = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert second["dispatch"]["status"] == "dispatch_unknown"
    after = json.loads(Path(receipt["outbox_path"]).read_text())["dispatch_receipt"]
    for key in (
        "request_id",
        "pending_request_id",
        "pending_payload_sha256",
        "plan",
        "plan_sha256",
    ):
        assert after[key] == before[key]
    assert len(effects) == 1
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1
    assert not any(host == "hook.test" for _, host, _ in requests)


@pytest.mark.parametrize("entry", ["invoke", "readback"])
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, AttributeError, KeyError])
def test_programming_failure_during_original_lookup_propagates_without_replay(
    tmp_path, monkeypatch, entry, error_type
):
    effects = []
    armed = False
    error = error_type("synthetic lookup defect")

    def submit(request):
        effects.append(json.loads(request.content))
        raise httpx.ReadTimeout("ack lost", request=request)

    def lookup(request):
        if armed:
            raise error
        return httpx.Response(200, json={})

    create, requests = _service(tmp_path, monkeypatch, submit, receipt_handler=lookup)
    context = {"request_id": "lookup-defect", "mode": "code"}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert first["dispatch"]["status"] == "dispatch_unknown"
    path = Path(first["dispatch"]["outbox_path"])
    original = path.read_bytes()
    previous_reads = len(requests)
    armed = True
    service = create()
    with pytest.raises(error_type) as caught:
        if entry == "invoke":
            service.invoke(user_id=7, message="修复登录问题", context=context)
        else:
            service.read_dispatch_receipt(user_id=7, request_id=context["request_id"], task_id="")
    assert caught.value is error
    assert path.read_bytes() == original
    assert len(effects) == 1
    observed = requests[previous_reads:]
    assert len(observed) == 1
    assert observed[0][:2] == ("GET", "para.test")
    assert observed[0][2].startswith("/api/tasks/by-request/")
    assert not any(host == "hook.test" for _, host, _ in requests)


@pytest.mark.parametrize(
    ("operation", "status", "body", "message"),
    [
        ("request", 403, {"error": "request rejected"}, "request rejected"),
        ("guest", 401, {"error": "guest rejected"}, "guest rejected"),
        ("guest", 200, {}, "Para guest 登录未返回 token"),
    ],
)
def test_known_para_response_failure_preserves_runtimeerror_contract(
    tmp_path, monkeypatch, operation, status, body, message
):
    for name in ("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", "MODSTORE_PARA_TOKEN", "DEVFLEET_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    service = CodexSuperEmployeeService(storage_root=tmp_path)
    service._para._token_cache = {}
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    with httpx.Client(transport=transport) as client, pytest.raises(RuntimeError) as caught:
        if operation == "guest":
            service._para_token(client, "https://para.test")
        else:
            service._para_request(client, "https://para.test", "test-token", "GET", "/api/devices")
    assert isinstance(caught.value, ParaRemoteError)
    assert str(caught.value) == message
    assert service._para._token_cache == {}


def test_process_exit_after_send_recovers_the_pre_send_receipt(tmp_path, monkeypatch):
    effects = []

    def submit(request):
        effects.append("created")
        raise SystemExit("process died before ack")

    create, _ = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "crash-request", "mode": "code"}
    with pytest.raises(SystemExit):
        create().invoke(user_id=7, message="修复登录问题", context=context)
    recovered = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert recovered["dispatch"]["status"] == "dispatch_unknown"
    assert "按原请求核对" in recovered["assistant_message"]["body"]
    assert effects == ["created"]


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_partial_fleet_dispatch_keeps_task_and_device_receipts(tmp_path, monkeypatch, error_type):
    effects = []

    def submit(request):
        body = json.loads(request.content)
        effects.append(body)
        if len(effects) == 1:
            return _ack(request)
        assert body["task_id"] == "task-original"
        raise error_type("second device did not acknowledge", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit, devices=2)
    context = {"request_id": "fleet-request", "mode": "code", "para_tier": 2}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    receipt = first["dispatch"]
    assert receipt["status"] == "dispatch_unknown"
    assert receipt["task_id"] == "task-original"
    assert receipt["devices"][0]["subtask_id"] == "sub-1"
    assert receipt["pending_device_id"] == "device-1"
    saved = json.loads(Path(receipt["outbox_path"]).read_text())
    assert saved["dispatch_receipt"]["task_id"] == "task-original"
    resumed = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert resumed["dispatch"]["task_status"] == "running"
    assert resumed["dispatch"]["status"] == "dispatch_unknown"
    assert len(effects) == 2
    assert ("GET", "para.test", "/api/tasks/task-original") in requests
    assert not any(host == "hook.test" for _, host, _ in requests)


def test_readback_keeps_partial_fleet_unknown_after_known_task_completes(tmp_path, monkeypatch):
    effects = []

    def submit(request):
        effects.append(json.loads(request.content))
        if len(effects) == 1:
            return _ack(request)
        raise httpx.ReadTimeout("second device acknowledgement lost", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit, devices=2, task_status="completed")
    first = create().invoke(
        user_id=7,
        message="修复登录问题",
        context={"request_id": "fleet-readback", "mode": "code", "para_tier": 2},
    )
    original = Path(first["dispatch"]["outbox_path"]).read_text()
    before = len(requests)
    receipt = create().read_dispatch_receipt(
        user_id=7, request_id="fleet-readback", task_id="task-original"
    )
    assert receipt["dispatch"]["status"] == "dispatch_unknown"
    assert receipt["dispatch"]["reconciliation_required"] is True
    assert receipt["dispatch"]["task_status"] == "completed"
    assert receipt["dispatch"]["pending_device_id"] == "device-1"
    assert receipt["dispatch"]["devices"][0]["subtask_id"] == "sub-1"
    assert "待核对" in receipt["assistant_message"]["body"]
    observed = requests[before:]
    assert len(observed) == 2
    assert observed[0][:2] == ("GET", "para.test")
    assert observed[0][2].startswith("/api/tasks/by-request/")
    assert observed[1] == ("GET", "para.test", "/api/tasks/task-original")
    assert len(effects) == 2
    assert Path(first["dispatch"]["outbox_path"]).read_text() == original


@pytest.mark.parametrize("receipt_status", [401, 404, 503])
def test_readback_without_ack_queries_only_original_request_and_keeps_unknown(
    tmp_path, monkeypatch, receipt_status
):
    def submit(request):
        raise httpx.ReadTimeout("first acknowledgement lost", request=request)

    create, requests = _service(
        tmp_path,
        monkeypatch,
        submit,
        receipt_handler=lambda request: httpx.Response(
            receipt_status, json={"error": "request_not_found"}
        ),
    )
    first = create().invoke(
        user_id=7,
        message="修复登录问题",
        context={"request_id": "lost-readback", "mode": "code"},
    )
    before = len(requests)
    original = Path(first["dispatch"]["outbox_path"]).read_bytes()
    service = create()
    receipt = service.read_dispatch_receipt(user_id=7, request_id="lost-readback", task_id="")
    assert receipt["dispatch"]["reconciliation_required"] is True
    assert receipt["dispatch"]["status"] == "dispatch_unknown"
    assert not receipt["dispatch"].get("task_id")
    assert len(requests) == before + 1
    assert requests[-1][:2] == ("GET", "para.test")
    assert requests[-1][2].startswith("/api/tasks/by-request/")
    assert Path(first["dispatch"]["outbox_path"]).read_bytes() == original


def test_readback_after_endpoint_change_never_queries_new_target(tmp_path, monkeypatch):
    def submit(request):
        return httpx.Response(200, json={"task": {"id": "task-original", "status": "running"}})

    create, requests = _service(tmp_path, monkeypatch, submit, task_status="completed")
    create().invoke(
        user_id=7,
        message="修复登录问题",
        context={"request_id": "bound-readback", "mode": "code"},
    )
    before = len(requests)
    service = create()
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "https://other-para.test")
    assert (
        service.read_dispatch_receipt(
            user_id=7, request_id="bound-readback", task_id="task-original"
        )
        is None
    )
    assert len(requests) == before


def test_readback_can_observe_send_intent_while_dispatch_lock_is_held(tmp_path, monkeypatch):
    create, requests = _service(
        tmp_path, monkeypatch, lambda request: pytest.fail("readback dispatched a write")
    )
    service = create()
    request = {
        "request_id": "inflight-readback",
        "user_id": 7,
        "employee_id": service._p.employee_id,
        "created_at": "2026-11-21T00:00:00Z",
    }
    with ThreadPoolExecutor(max_workers=1) as observer:
        with service._messages.dispatch_lock(7, "inflight-readback"):
            service._dispatching._persist_receipt(
                request,
                {"status": "dispatching", "dispatcher": "para_api", "api_url": "https://para.test"},
            )
            # A different thread cannot reenter the sender's lock. Its read
            # must return the durable snapshot while the sender still holds it.
            receipt = observer.submit(
                service.read_dispatch_receipt,
                user_id=7,
                request_id="inflight-readback",
                task_id="",
            ).result(timeout=5)
    assert receipt["dispatch"]["status"] == "dispatch_unknown"
    assert receipt["dispatch"]["reconciliation_required"] is True
    assert requests == []


def test_connect_failure_before_first_send_can_use_webhook(tmp_path, monkeypatch):
    def submit(request):
        raise httpx.ConnectError("connection never established", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    service = create()
    context = {"request_id": "connect-request", "mode": "code"}
    result = service.invoke(user_id=7, message="修复登录问题", context=context)
    assert result["dispatch"]["accepted"] is True
    assert result["dispatch"]["dispatcher"] == "webhook"
    create().invoke(user_id=7, message="修复登录问题", context=context)
    assert sum(host == "hook.test" for _, host, _ in requests) == 1


def test_successful_remote_request_replays_without_creating_a_task(tmp_path, monkeypatch):
    def submit(request):
        return _ack(request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "accepted-request", "mode": "code"}
    assert create().invoke(user_id=7, message="修复登录问题", context=context)["dispatch"][
        "accepted"
    ]
    replay = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert replay["dispatch"]["task_id"] == "task-original"
    with pytest.raises(ValueError, match="已绑定其他任务参数"):
        create().invoke(user_id=7, message="部署另一个项目", context=context)
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1


@pytest.mark.parametrize("corrupted_receipt", [None, [], "not-an-object"])
def test_corrupt_dispatch_receipt_cannot_replay_effect(tmp_path, monkeypatch, corrupted_receipt):
    def submit(request):
        return httpx.Response(200, json={"task": {"id": "task-original", "status": "running"}})

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "corrupt-request", "mode": "code"}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    Path(first["dispatch"]["outbox_path"]).write_text(json.dumps(corrupted_receipt))

    with pytest.raises(ValueError, match="持久化执行回执必须是对象"):
        create().invoke(user_id=7, message="修复登录问题", context=context)
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1


def test_receipt_lookup_is_user_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.application.super_employee_service._utc_now",
        lambda: "2026-01-01T00:00:00Z",
    )

    def submit(request):
        raise httpx.ReadTimeout("ack lost", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "same-client-id", "mode": "code"}
    create().invoke(user_id=7, message="修复用户七的问题", context=context)
    create().invoke(user_id=8, message="修复用户八的问题", context=context)
    create().invoke(user_id=7, message="修复用户七的问题", context=context)
    create().invoke(user_id=8, message="修复用户八的问题", context=context)
    assert requests.count(("POST", "para.test", "/api/tasks")) == 2


def test_webhook_lost_ack_does_not_fall_through_to_cli(tmp_path, monkeypatch):
    def submit(request):
        raise httpx.ConnectError("para was never reached", request=request)

    def webhook(request):
        raise httpx.ReadTimeout("webhook may have executed", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit, webhook_handler=webhook)
    context = {"request_id": "webhook-request", "mode": "code"}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    second = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert first["dispatch"]["status"] == second["dispatch"]["status"] == "dispatch_unknown"
    assert first["dispatch"]["dispatcher"] == "webhook"
    assert sum(host == "hook.test" for _, host, _ in requests) == 1


def test_safe_local_fallback_is_saved_before_replay(tmp_path, monkeypatch):
    def not_sent(request):
        raise httpx.ConnectError("connection never established", request=request)

    create, requests = _service(tmp_path, monkeypatch, not_sent, webhook_handler=not_sent)
    service = create()
    cli_calls = []

    def reply(*args):
        cli_calls.append("ran")
        return "本地任务已完成。", "codex_cli"

    monkeypatch.setattr(service, "_compose_direct_chat_reply", reply)
    context = {"request_id": "local-request", "mode": "code"}
    first = service.invoke(user_id=7, message="修复登录问题", context=context)
    second = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert first["dispatch"]["status"] == second["dispatch"]["status"] == "completed"
    assert first["dispatch"]["accepted"] is True
    assert first["dispatch"]["queued"] is False
    stored = json.loads(Path(first["dispatch"]["outbox_path"]).read_text())["dispatch_receipt"]
    assert stored["safe_to_fallback"] is False and stored["queued"] is False
    assert second["assistant_message"]["body"] == "本地任务已完成。"
    assert cli_calls == ["ran"]
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1


def test_malformed_second_ack_retains_first_task_id(tmp_path, monkeypatch):
    effects = []

    def submit(request):
        effects.append(json.loads(request.content))
        if len(effects) == 1:
            return _ack(request)
        return httpx.Response(200, json={"unexpected": "response shape"})

    create, requests = _service(tmp_path, monkeypatch, submit, devices=2)
    context = {"request_id": "malformed-request", "mode": "code", "para_tier": 2}
    result = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert result["dispatch"]["status"] == "dispatch_unknown"
    assert result["dispatch"]["task_id"] == "task-original"
    assert [device["subtask_id"] for device in result["dispatch"]["devices"]] == ["sub-1"]
    create().invoke(user_id=7, message="修复登录问题", context=context)
    assert len(effects) == 2
    assert not any(host == "hook.test" for _, host, _ in requests)


def test_streaming_resume_does_not_escape_unknown_remote_dispatch(tmp_path, monkeypatch):
    def submit(request):
        raise httpx.ReadTimeout("ack lost", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "stream-request", "mode": "code"}
    create().invoke(user_id=7, message="修复登录问题", context=context)

    async def consume():
        return [
            event
            async for event in create().invoke_stream(
                user_id=7, message="修复登录问题", context=context
            )
        ]

    events = asyncio.run(consume())
    assert events[-1]["result"]["dispatch"]["status"] == "dispatch_unknown"
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1


def _process_dispatch(storage, crash):
    """Subprocess probe: persist a synthetic side effect, then lose the process/ACK."""
    storage = Path(storage)

    def submit(request):
        with (storage / "effects").open("a", encoding="utf-8") as stream:
            stream.write("created\n")
            stream.flush()
            os.fsync(stream.fileno())
        if crash:
            os._exit(17)
        return _ack(request)

    with pytest.MonkeyPatch.context() as monkeypatch:
        create, _ = _service(storage, monkeypatch, submit)
        service = create()
        # This text would be classified as chat if the explicit code mode or
        # remote receipt were discarded by historical message backfill.
        result = service.invoke(
            user_id=7,
            message="repair synthetic task",
            context={"request_id": "process-request", "mode": "code"},
        )
        create().list_messages(user_id=7)
        print(json.dumps({key: result["dispatch"][key] for key in ("status", "request_id")}))


def _process_command(storage, *, crash=False):
    return [
        sys.executable,
        "-c",
        "import runpy, sys; runpy.run_path(sys.argv[1])['_process_dispatch'](sys.argv[2], sys.argv[3] == 'crash')",
        str(Path(__file__).resolve()),
        str(storage),
        "crash" if crash else "normal",
    ]


def test_hard_process_exit_keeps_original_request_non_replayable(tmp_path):
    first = subprocess.run(
        _process_command(tmp_path, crash=True),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert first.returncode == 17, first.stderr
    second = subprocess.run(_process_command(tmp_path), capture_output=True, text=True, timeout=20)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == {
        "status": "dispatch_unknown",
        "request_id": "process-request",
    }
    assert (tmp_path / "effects").read_text().splitlines() == ["created"]


def test_two_processes_replay_accepted_code_request_without_cli_backfill(tmp_path):
    workers = [
        subprocess.Popen(
            _process_command(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=20)
            assert worker.returncode == 0, stderr
            assert json.loads(stdout) == {
                "status": "accepted",
                "request_id": "process-request",
            }
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=5)
    assert (tmp_path / "effects").read_text().splitlines() == ["created"]


def test_readback_without_ack_only_queries_the_original_request(tmp_path, monkeypatch):
    def submit(request):
        raise httpx.ReadTimeout("first acknowledgement lost", request=request)

    create, requests = _service(tmp_path, monkeypatch, submit)
    create().invoke(
        user_id=7,
        message="修复登录问题",
        context={"request_id": "lost-readback", "mode": "code"},
    )
    before = len(requests)
    service = create()
    receipt = service.read_dispatch_receipt(user_id=7, request_id="lost-readback", task_id="")
    assert receipt["dispatch"]["reconciliation_required"] is True
    assert receipt["dispatch"]["status"] == "dispatch_unknown"
    assert not receipt["dispatch"].get("task_id")
    assert len(requests) == before + 1
    assert requests[-1][0:2] == ("GET", "para.test")
    assert requests[-1][2].startswith("/api/tasks/by-request/")
