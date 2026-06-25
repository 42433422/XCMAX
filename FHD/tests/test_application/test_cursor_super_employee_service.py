from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx

from app.application.cursor_super_employee_service import (
    CURSOR_DIRECT_MESSAGE_KIND,
    CursorSuperEmployeeService,
)


def fake_cursor_runner(reply: str, seen: list[list[str]] | None = None):
    """CLI runner for Cursor. Wraps reply in stream-json since CURSOR_PROFILE.cli_stream_json=True."""

    def runner(cmd, **kwargs):
        seen.append(list(cmd)) if seen is not None else None
        stream_line = json.dumps({"type": "result", "result": reply})
        return subprocess.CompletedProcess(cmd, 0, stdout=stream_line, stderr="")

    return runner


def test_cursor_super_employee_invoke_writes_outbox_when_dispatch_not_configured(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("XCMAX_CURSOR_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    monkeypatch.setenv("XCMAX_CURSOR_CLI_CHAT_ENABLED", "0")
    monkeypatch.delenv("XCMAX_CURSOR_SUPER_EMPLOYEE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)

    svc = CursorSuperEmployeeService(storage_root=tmp_path)
    # Isolate the local CLI: when dispatch is not accepted, invoke() falls back to a
    # local Cursor CLI reply if one is installed, which rewrites status queued->completed.
    # That CLI-present fallback's status=completed semantics for an un-dispatched task is
    # the known #35 bug recorded in TO_9_PROGRAM §8.1; we deliberately disable the CLI
    # here so this test verifies the intended "dispatch not configured -> outbox -> queued"
    # contract deterministically on any machine (CI without a CLI, or a dev box with one).
    monkeypatch.setattr(svc, "_cli_reply_body", lambda text, context: "")
    result = svc.invoke(user_id=1, message="修复登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "queued"
    assert dispatch["queued"] is True
    assert result["employee"]["id"] == "cursor-super-employee"
    assert result["employee"]["name"] == "超级员工-Cursor"
    assert [m["role"] for m in result["messages"]] == ["user", "system"]
    assert result["assistant_message"]["body"] == "思考中..."
    assert result["assistant_message"]["kind"] == "dispatcher"


def test_cursor_super_employee_answers_identity_without_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XCMAX_CURSOR_SUPER_EMPLOYEE_DISPATCH_MODE", "outbox")
    cursor_bin = tmp_path / "cursor"
    cursor_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    cursor_bin.chmod(0o755)
    monkeypatch.setenv("XCMAX_CURSOR_CLI_PATH", str(cursor_bin))
    seen: list[list[str]] = []

    svc = CursorSuperEmployeeService(
        storage_root=tmp_path,
        cursor_cli_runner=fake_cursor_runner("我是 Cursor，一个真实接入的编程助手。", seen),
    )
    result = svc.invoke(user_id=1, message="你是谁")

    assert result["dispatch"]["status"] == "completed"
    assert result["dispatch"]["dispatcher"] == "cursor_agent_cli"
    assert result["assistant_message"]["kind"] == CURSOR_DIRECT_MESSAGE_KIND
    assert "真实接入" in result["assistant_message"]["body"]
    assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
    # Cursor Agent CLI 用 agent --print 模式，且携带用户问题。
    assert "--print" in seen[0]
    assert any("你是谁" in part for part in seen[0])


def test_cursor_super_employee_dispatches_to_para_cursor_device(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("XCMAX_CURSOR_SUPER_EMPLOYEE_DISPATCH_MODE", raising=False)
    monkeypatch.setenv("XCMAX_CURSOR_SUPER_EMPLOYEE_PARA_API_URL", "http://para.test")
    monkeypatch.delenv("XCMAX_CURSOR_SUPER_EMPLOYEE_PARA_TOKEN", raising=False)
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
                                # CURSOR_PROFILE.tool_name == "cursor_agent"
                                {"toolName": "cursor_agent", "status": "idle", "currentTask": None},
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
                        "devTool": "cursor_agent",
                        "tools": [{"toolName": "cursor_agent", "status": "idle"}],
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
                                "tool_name": "cursor_agent",
                                "progress": 100,
                                "title": "修复管理端登录问题",
                                "device_name": "Mac 工作设备",
                                "completed_at": "2026-06-19T00:00:02Z",
                                "logs": [
                                    {"content": "Cursor 已完成修复并通过验证。"},
                                ],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404, json={"error": request.url.path})

    transport = httpx.MockTransport(handler)
    svc = CursorSuperEmployeeService(
        storage_root=tmp_path,
        http_client_factory=lambda: httpx.Client(transport=transport),
    )

    result = svc.invoke(user_id=1, message="修复管理端登录问题", context={"source": "test"})

    dispatch = result["dispatch"]
    assert dispatch["status"] == "accepted"
    assert dispatch["dispatcher"] == "para_api"
    assert dispatch["task_id"] == "task-1"
    assert dispatch["devices"][0]["tool"] == "cursor_agent"
    assert result["assistant_message"]["body"] == "思考中..."
    assert any(
        item["role"] == "assistant" and "Cursor 已完成修复并通过验证" in item["body"]
        for item in result["messages"]
    )
    # 关键：设备被切换到 cursor_agent dev tool。
    assert ("PUT", "/api/devices/device-1/dev-tool", {"devTool": "cursor_agent"}) in seen
