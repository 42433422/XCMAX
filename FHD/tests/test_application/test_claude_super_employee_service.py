from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx

from app.application.claude_super_employee_service import (
    CLAUDE_DIRECT_MESSAGE_KIND,
    ClaudeSuperEmployeeService,
)


def fake_claude_runner(reply: str, seen: list[list[str]] | None = None):
    def runner(cmd, **kwargs):
        seen.append(list(cmd)) if seen is not None else None
        # Claude CLI 走 print 模式，回答打到 stdout（不写 last-message 文件）。
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    return runner


def test_claude_super_employee_invoke_writes_outbox_when_dispatch_not_configured(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    monkeypatch.setenv("XCMAX_CLAUDE_CLI_CHAT_ENABLED", "0")
    monkeypatch.delenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)

    svc = ClaudeSuperEmployeeService(storage_root=tmp_path)
    result = svc.invoke(user_id=1, message="修复登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "queued"
    assert dispatch["queued"] is True
    assert result["employee"]["id"] == "claude-super-employee"
    assert result["employee"]["name"] == "超级员工-Claude"
    assert [m["role"] for m in result["messages"]] == ["user", "system"]
    assert result["assistant_message"]["body"] == "思考中..."
    assert result["assistant_message"]["kind"] == "dispatcher"


def test_claude_super_employee_answers_identity_without_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    claude_bin = tmp_path / "claude"
    claude_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    claude_bin.chmod(0o755)
    monkeypatch.setenv("XCMAX_CLAUDE_CLI_PATH", str(claude_bin))
    seen: list[list[str]] = []

    svc = ClaudeSuperEmployeeService(
        storage_root=tmp_path,
        claude_cli_runner=fake_claude_runner("我是 Claude，一个真实接入的编程助手。", seen),
    )
    result = svc.invoke(user_id=1, message="你是谁")

    assert result["dispatch"]["status"] == "completed"
    assert result["dispatch"]["dispatcher"] == "claude_code_cli"
    assert result["assistant_message"]["kind"] == CLAUDE_DIRECT_MESSAGE_KIND
    assert "真实接入" in result["assistant_message"]["body"]
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
    # Claude CLI 用 print 模式，命令里带 --print，且携带用户问题。
    assert "--print" in seen[0]
    assert any("你是谁" in part for part in seen[0])


def test_claude_super_employee_dispatches_to_para_claude_device(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_DISPATCH_MODE", raising=False)
    monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
    monkeypatch.delenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
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
                            "name": "Mac 工作设备",
                            "status": "online",
                            "devTool": "trae",
                            "isPrimary": False,
                            "tools": [
                                # CLAUDE_PROFILE.tool_name == "claude_code"
                                {"toolName": "claude_code", "status": "idle", "currentTask": None},
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
                        "name": "Mac 工作设备",
                        "status": "online",
                        "devTool": "claude_code",
                        "tools": [{"toolName": "claude_code", "status": "idle"}],
                    },
                },
            )
        if request.method == "POST" and request.url.path == "/api/tasks":
            assert payload["device_id"] == "device-1"
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
                                "tool_name": "claude",
                                "progress": 100,
                                "title": "修复管理端登录问题",
                                "device_name": "Mac 工作设备",
                                "completed_at": "2026-06-19T00:00:02Z",
                                "logs": [
                                    {"content": "Claude 已完成修复并通过验证。"},
                                ],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404, json={"error": request.url.path})

    transport = httpx.MockTransport(handler)
    svc = ClaudeSuperEmployeeService(
        storage_root=tmp_path,
        http_client_factory=lambda: httpx.Client(transport=transport),
    )

    result = svc.invoke(user_id=1, message="修复管理端登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "accepted"
    assert dispatch["dispatcher"] == "para_api"
    assert dispatch["task_id"] == "task-1"
    assert dispatch["devices"][0]["tool"] == "claude_code"
    assert result["assistant_message"]["body"] == "思考中..."
    assert any(
        item["role"] == "assistant" and "Claude 已完成修复并通过验证" in item["body"]
        for item in result["messages"]
    )
    # 关键：设备被切换到 claude_code dev tool。
    assert ("PUT", "/api/devices/device-1/dev-tool", {"devTool": "claude_code"}) in seen
