from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.application.codex_super_employee_service import CodexSuperEmployeeService


def test_codex_super_employee_invoke_writes_outbox_when_dispatch_not_configured(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)

    svc = CodexSuperEmployeeService(storage_root=tmp_path)
    result = svc.invoke(user_id=1, message="修复登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "queued"
    assert dispatch["queued"] is True
    assert dispatch["device_scope"] == "all_devices"
    assert Path(dispatch["outbox_path"]).is_file()
    assert result["employee"]["id"] == "codex-super-employee"
    assert [m["role"] for m in result["messages"]] == ["user", "system"]
    assert "软件内 Codex 调用队列" in result["assistant_message"]["body"]
    assert result["assistant_message"]["kind"] == "dispatcher"


def test_codex_super_employee_list_messages_is_user_scoped(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
    svc = CodexSuperEmployeeService(storage_root=tmp_path)
    svc.invoke(user_id=1, message="任务 A")
    svc.invoke(user_id=2, message="任务 B")

    user_one_messages = svc.list_messages(user_id=1)

    assert len(user_one_messages) == 2
    assert user_one_messages[0]["body"] == "任务 A"


def test_codex_super_employee_upgrades_legacy_dispatch_ack_and_syncs_status(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")

    messages_dir = tmp_path / "codex_super_employee"
    messages_dir.mkdir(parents=True)
    (messages_dir / "messages.jsonl").write_text(
        json.dumps(
            {
                "id": "legacy-1",
                "user_id": 1,
                "role": "assistant",
                "body": "已接入排比 Para/Codex 多设备调度器，任务已派发到 1 台设备。任务 ID：task-legacy-1",
                "created_at": "2026-06-19T00:00:00Z",
                "dispatch_request_id": "req-legacy",
                "status": "accepted",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/auth/guest":
            return httpx.Response(200, json={"token": "token-1"})
        if request.method == "GET" and request.url.path == "/api/tasks/task-legacy-1":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "id": "task-legacy-1",
                        "status": "running",
                        "subTasks": [
                            {
                                "id": "sub-legacy-1",
                                "status": "running",
                                "progress": 40,
                                "logs": [{"content": "[e2e-agent] 调用 Codex CLI 修改代码"}],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404, json={"error": request.url.path})

    svc = CodexSuperEmployeeService(
        storage_root=tmp_path,
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    messages = svc.list_messages(user_id=1)

    assert messages[0]["role"] == "system"
    assert messages[0]["kind"] == "dispatcher"
    assert messages[0]["task_id"] == "task-legacy-1"
    assert messages[0]["status"] == "running"
    assert "Para 任务运行中" in messages[0]["body"]


def test_codex_super_employee_marks_mobile_im_source_in_dispatch_request(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    svc = CodexSuperEmployeeService(storage_root=tmp_path)

    result = svc.invoke(user_id=1, message="手机派工", context={"source": "mobile_im"})
    outbox_path = Path(result["dispatch"]["outbox_path"])
    payload = json.loads(outbox_path.read_text(encoding="utf-8"))

    assert payload["source"] == "xcagi_mobile_im"
    assert payload["raw_context"]["source"] == "mobile_im"


def test_codex_super_employee_dispatches_to_para_codex_device(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", raising=False)
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_TOKEN", raising=False)

    seen: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8") or "{}") if request.content else {}
        seen.append((request.method, request.url.path, payload))
        if request.method == "GET" and request.url.path == "/api/health":
            return httpx.Response(200, json={"success": True})
        if request.method == "POST" and request.url.path == "/api/auth/guest":
            return httpx.Response(200, json={"token": "token-1"})
        if request.method == "GET" and request.url.path == "/api/devices":
            return httpx.Response(
                200,
                json={
                    "devices": [
                        {
                            "id": "device-1",
                            "name": "Mac 主设备 MODstore Bridge",
                            "status": "online",
                            "devTool": "trae",
                            "isPrimary": True,
                            "tools": [
                                {"toolName": "codex", "status": "idle", "currentTask": None},
                            ],
                        }
                    ]
                },
            )
        if request.method == "PUT" and request.url.path == "/api/devices/device-1/dev-tool":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "device": {
                        "id": "device-1",
                        "name": "Mac 主设备 MODstore Bridge",
                        "status": "online",
                        "devTool": "codex",
                        "isPrimary": True,
                        "tools": [{"toolName": "codex", "status": "idle"}],
                    },
                },
            )
        if request.method == "POST" and request.url.path == "/api/tasks":
            assert payload["device_id"] == "device-1"
            assert payload["branch"] == "main"
            assert "提交到调度器分配的工作分支" in str(payload["prompt"])
            return httpx.Response(
                200,
                json={
                    "task": {"id": "task-1", "status": "running"},
                    "subtask": {"id": "sub-1"},
                },
            )
        if request.method == "GET" and request.url.path == "/api/tasks/task-1":
            return httpx.Response(
                200,
                json={
                    "task": {
                        "id": "task-1",
                        "status": "completed",
                        "subTasks": [
                            {
                                "id": "sub-1",
                                "status": "completed",
                                "tool_name": "codex",
                                "progress": 100,
                                "title": "修复管理端登录问题",
                                "device_name": "Mac 主设备 MODstore Bridge",
                                "completed_at": "2026-06-19T00:00:02Z",
                                "logs": [
                                    {"content": "子任务「修复管理端登录问题」已派发至 Mac"},
                                    {"content": "Codex 已完成修复并通过验证。"},
                                ],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404, json={"error": request.url.path})

    transport = httpx.MockTransport(handler)
    svc = CodexSuperEmployeeService(
        storage_root=tmp_path,
        http_client_factory=lambda: httpx.Client(transport=transport),
    )

    result = svc.invoke(user_id=1, message="修复管理端登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "accepted"
    assert dispatch["dispatcher"] == "para_api"
    assert dispatch["task_id"] == "task-1"
    assert dispatch["devices"][0]["device_id"] == "device-1"
    assert "排比 Para/Codex 多设备调度器" in result["assistant_message"]["body"]
    assert result["assistant_message"]["role"] == "system"
    assert any(
        item["role"] == "assistant" and "Codex 已完成修复并通过验证" in item["body"]
        for item in result["messages"]
    )
    assert ("PUT", "/api/devices/device-1/dev-tool", {"devTool": "codex"}) in seen
