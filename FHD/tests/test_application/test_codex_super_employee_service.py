from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx

from app.application.codex_super_employee_service import (
    CODEX_DIRECT_MESSAGE_KIND,
    CodexSuperEmployeeService,
)

def fake_codex_runner(reply: str, seen: list[list[str]] | None = None):
    def runner(cmd, **kwargs):
        seen.append(list(cmd)) if seen is not None else None
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text(reply, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    return runner


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


def test_codex_super_employee_answers_identity_without_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", str(codex_bin))
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_WEBHOOK", raising=False)
    seen: list[list[str]] = []

    svc = CodexSuperEmployeeService(
        storage_root=tmp_path,
        codex_cli_runner=fake_codex_runner("我是 Codex，一个真实接入的编程助手。", seen),
    )
    result = svc.invoke(user_id=1, message="你是谁")

    assert result["dispatch"]["status"] == "completed"
    assert result["dispatch"]["dispatcher"] == "codex_cli"
    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["kind"] == CODEX_DIRECT_MESSAGE_KIND
    assert "真实接入" in result["assistant_message"]["body"]
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
    assert not list((tmp_path / "codex_super_employee" / "outbox").glob("*.json"))
    assert seen and seen[0][:4] == [str(codex_bin), "--ask-for-approval", "never", "exec"]


def test_codex_super_employee_natural_question_uses_codex_cli_without_dispatch(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", str(codex_bin))
    seen: list[list[str]] = []
    svc = CodexSuperEmployeeService(
        storage_root=tmp_path,
        codex_cli_runner=fake_codex_runner("我不能查看你的真实账户额度。", seen),
    )

    result = svc.invoke(user_id=1, message="你有多少额度的")

    assert result["dispatch"]["dispatcher"] == "codex_cli"
    assert "不能查看你的真实账户额度" in result["assistant_message"]["body"]
    assert not list((tmp_path / "codex_super_employee" / "outbox").glob("*.json"))
    assert any("你有多少额度的" in part for part in seen[0])


def test_codex_super_employee_backfills_stuck_identity_dispatch(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
    messages_dir = tmp_path / "codex_super_employee"
    messages_dir.mkdir(parents=True)
    request_id = "req-identity"
    rows = [
        {
            "id": "user-1",
            "user_id": 1,
            "role": "user",
            "body": "你是谁",
            "created_at": "2026-06-19T00:00:00Z",
            "dispatch_request_id": request_id,
            "status": "sent",
        },
        {
            "id": "dispatcher-1",
            "user_id": 1,
            "role": "system",
            "body": "Para 任务运行中：0/1 个子任务完成，进度 40%。任务 ID：task-identity",
            "created_at": "2026-06-19T00:00:01Z",
            "dispatch_request_id": request_id,
            "status": "running",
            "kind": "dispatcher",
            "task_id": "task-identity",
        },
    ]
    (messages_dir / "messages.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    svc = CodexSuperEmployeeService(storage_root=tmp_path)

    first = svc.list_messages(user_id=1)
    second = svc.list_messages(user_id=1)

    direct = [item for item in first if item["kind"] == CODEX_DIRECT_MESSAGE_KIND]
    assert len(direct) == 1
    assert direct[0]["dispatch_request_id"] == request_id
    assert "我是超级员工-Codex" in direct[0]["body"]
    assert sum(1 for item in second if item["kind"] == CODEX_DIRECT_MESSAGE_KIND) == 1


def test_codex_super_employee_backfills_stuck_natural_question_with_codex_cli(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_API_URL", "disabled")
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    monkeypatch.setenv("XCMAX_CODEX_CLI_PATH", str(codex_bin))
    messages_dir = tmp_path / "codex_super_employee"
    messages_dir.mkdir(parents=True)
    request_id = "req-quota"
    rows = [
        {
            "id": "user-quota",
            "user_id": 1,
            "role": "user",
            "body": "你有多少额度的",
            "created_at": "2026-06-19T00:00:00Z",
            "dispatch_request_id": request_id,
            "status": "sent",
        },
        {
            "id": "dispatcher-quota",
            "user_id": 1,
            "role": "system",
            "body": "已进入软件内 Codex 任务队列，等待全设备 Codex 接走。",
            "created_at": "2026-06-19T00:00:01Z",
            "dispatch_request_id": request_id,
            "status": "queued",
            "kind": "dispatcher",
        },
    ]
    (messages_dir / "messages.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    seen: list[list[str]] = []
    svc = CodexSuperEmployeeService(
        storage_root=tmp_path,
        codex_cli_runner=fake_codex_runner("我不能查看你的真实账户额度。", seen),
    )

    first = svc.list_messages(user_id=1)
    second = svc.list_messages(user_id=1)

    direct = [item for item in first if item["kind"] == CODEX_DIRECT_MESSAGE_KIND]
    assert len(direct) == 1
    assert "不能查看你的真实账户额度" in direct[0]["body"]
    assert sum(1 for item in second if item["kind"] == CODEX_DIRECT_MESSAGE_KIND) == 1
    assert len(seen) == 1


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
