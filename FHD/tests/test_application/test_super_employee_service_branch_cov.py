"""Branch-coverage tests for app/application/super_employee_service.py.

Focus areas not covered by the existing cov files (test_super_employee_service_cov.py,
test_super_employee_service_branch_cov2.py, test_codex_super_employee_service_branch_cov.py):

- ``invoke`` 全流程（CLI 直答 / 派工接受 / 派工兜底回退）
- ``invoke_stream`` 与 ``_run_cli_streaming``（异步流式）
- ``_parse_stream_json_line`` 各事件类型
- ``_build_dispatch_request`` 工厂/产品域与 source 映射
- 设备选择套件：``_device_eligible`` / ``_select_para_devices`` / ``_resolve_para_tier``
  / ``_select_local_device`` / ``_select_devices_by_tier``
- ``_para_prompt`` / ``_para_subtask_title`` / ``_max_para_devices``
- ``_result_body`` / ``_para_task_status_reply`` / ``_sync_para_task_updates``
- ``_run_conversation_turn`` / ``_apply_scope_to_cmd`` / ``_conversation_cmd``
- ``_clean_cli_stdout`` / ``_chunk_text`` / ``_trae_cli_command`` / ``_relay_wt_lock``
- ``_cli_workspace`` / ``_factory_workspace_root`` / ``_product_ephemeral_workspace``
- ``_json_response`` / ``_error_message`` / ``_dispatch_reply``
- ``_upsert_direct_reply_messages`` / ``_prepare_persistent_worktree``
- ``_direct_reply_body`` slow/help/greeting/identity 提示

所有外部 I/O（httpx、subprocess、文件系统）均被 mock，遵循 Mock 最小化原则。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application.execution_scope import CONTEXT_TOKEN_KEY, CapabilityGrant, ExecutionScope
from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DISPATCHER_MESSAGE_KIND,
    TRAE_PROFILE,
    SuperEmployeeService,
    SuperEmployeeToolProfile,
    _chunk_text,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _relay_wt_lock,
    _safe_json_line,
    _trae_cli_command,
    _utc_now,
)

# ─────────────────────────── helpers ────────────────────────────


def _make_svc(tmp_path: Path, profile: SuperEmployeeToolProfile = CODEX_PROFILE, **kwargs):
    kwargs.setdefault("cli_runner", _null_runner)
    return SuperEmployeeService(profile=profile, storage_root=tmp_path, **kwargs)


def _null_runner(cmd, **kw):
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _stdout_runner(stdout: str, returncode: int = 0):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return _run


def _error_runner(exc):
    def _run(cmd, **kw):
        raise exc

    return _run


def _mock_response(status_code: int = 200, json_data=None, text: str = "", content=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = (
        content if content is not None else (json.dumps(json_data).encode() if json_data else b"")
    )
    resp.text = text or (json.dumps(json_data) if json_data else "")
    resp.json = MagicMock(return_value=json_data or {})
    return resp


def _mock_http_client(
    *,
    post_resp=None,
    get_resp=None,
    request_resp=None,
    post_exc=None,
    get_exc=None,
    request_exc=None,
):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    if post_exc is not None:
        client.post.side_effect = post_exc
    elif post_resp is not None:
        client.post.return_value = post_resp
    if get_exc is not None:
        client.get.side_effect = get_exc
    elif get_resp is not None:
        client.get.return_value = get_resp
    if request_exc is not None:
        client.request.side_effect = request_exc
    elif request_resp is not None:
        client.request.return_value = request_resp
    return client


def _make_request(request_id: str = "req-1", **overrides) -> dict:
    base = {
        "request_id": request_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": "xcagi_admin_im",
        "employee_id": "codex-super-employee",
        "employee_name": "超级员工-Codex",
        "mode": "code",
        "device_scope": "all_devices",
        "target_devices": ["all"],
        "user_id": 1,
        "title": "test task",
        "task": "test task",
        "prompt": "test task",
        "workspace_root": "",
        "raw_context": {},
    }
    base.update(overrides)
    return base


def _run_agen(agen):
    async def _collect():
        return [event async for event in agen]

    return asyncio.run(_collect())


class _FakeStream:
    """Async line stream used to fake an asyncio subprocess stdout/stderr."""

    def __init__(self, lines):
        self._lines = list(lines)
        self._read_data = b"stderr data" if lines == [] else b""

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self):
        return self._read_data


def _fake_proc(stdout_lines, returncode=0):
    proc = MagicMock()
    proc.stdout = _FakeStream(stdout_lines)
    proc.stderr = _FakeStream([])
    proc.returncode = returncode
    proc.kill = MagicMock()

    async def _wait():
        return returncode

    proc.wait = _wait
    return proc


# ───────────────────── async 收集辅助（invoke_stream）────────────


class TestInvokeStream:
    """invoke_stream 的流式直答分支。"""

    def test_empty_message_yields_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = _run_agen(svc.invoke_stream(user_id=1, message="  "))
        assert events == [{"type": "error", "message": "message 不能为空"}]

    def test_faq_canned_direct(self, tmp_path):
        svc = _make_svc(tmp_path)
        events = _run_agen(svc.invoke_stream(user_id=1, message="你是谁"))
        assert events[0]["type"] == "status"
        assert events[-1]["type"] == "done"
        assert events[-1]["result"]["dispatcher"] == "faq"
        assert "我是" in events[-1]["result"]["response"]

    def test_no_cli_path_falls_back_to_text(self, tmp_path):
        svc = _make_svc(tmp_path)
        # 非 FAQ 且 CLI 不可用 → 走派工兜底文案
        with patch.object(svc, "_cli_path", return_value=""):
            events = _run_agen(svc.invoke_stream(user_id=1, message="你好呀普通对话"))
        assert events[-1]["type"] == "done"
        assert events[-1]["result"]["dispatcher"] in ("codex_cli", "codex_direct")

    def test_dev_loop_task_yields_progress(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "1")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=True),
            patch.object(svc, "_dev_loop_enabled", return_value=True),
            patch.object(svc, "_run_dev_task_loop", return_value="任务完成啦"),
        ):
            events = _run_agen(
                svc.invoke_stream(user_id=1, message="修复 bug", context={"mode": "code"})
            )
        assert events[0]["type"] == "status"
        assert events[-1]["type"] == "done"
        assert events[-1]["result"]["dispatcher"] == "dev_loop"

    def test_dev_loop_exception_yields_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "1")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=True),
            patch.object(svc, "_dev_loop_enabled", return_value=True),
            patch.object(svc, "_run_dev_task_loop", side_effect=RuntimeError("boom")),
        ):
            events = _run_agen(
                svc.invoke_stream(user_id=1, message="修复 bug", context={"mode": "code"})
            )
        assert events[-1]["type"] == "error"
        assert "boom" in events[-1]["message"]

    def test_cli_streaming_flow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "0")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=False),
            patch.object(svc, "_cli_prompt", return_value="prompt"),
            patch.object(svc, "_run_cli_streaming") as stream,
        ):

            async def _fake_stream(cli_path, prompt, cwd):
                yield {"type": "status", "text": "thinking"}
                yield {"type": "token", "text": "part1"}
                yield {"type": "token", "text": "part2"}
                yield {"type": "done"}

            stream.return_value = _fake_stream("/fake/codex", "prompt", "cwd")
            events = _run_agen(
                svc.invoke_stream(user_id=1, message="讲个故事吧", context={"mode": "chat"})
            )
        assert events[-1]["type"] == "done"
        assert events[-1]["result"]["response"] == "part1part2"
        assert events[-1]["result"]["dispatcher"] == "cli_stream"

    def test_cli_streaming_error_event(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "0")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=False),
            patch.object(svc, "_run_cli_streaming") as stream,
        ):

            async def _fake_stream(cli_path, prompt, cwd):
                yield {"type": "error", "message": "cli crashed"}
                yield {"type": "done"}

            stream.return_value = _fake_stream("/fake/codex", "prompt", "cwd")
            events = _run_agen(
                svc.invoke_stream(user_id=1, message="讲个故事吧", context={"mode": "chat"})
            )
        assert events[-1]["type"] == "error"
        assert events[-1]["message"] == "cli crashed"

    def test_cli_streaming_body_empty_uses_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_DEV_LOOP", "0")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=False),
            patch.object(svc, "_run_cli_streaming") as stream,
        ):

            async def _fake_stream(cli_path, prompt, cwd):
                yield {"type": "status", "text": "thinking"}
                yield {"type": "done"}

            stream.return_value = _fake_stream("/fake/codex", "prompt", "cwd")
            events = _run_agen(
                svc.invoke_stream(user_id=1, message="讲讲天气", context={"mode": "chat"})
            )
        assert events[-1]["type"] == "done"
        assert "暂时没有返回内容" in events[-1]["result"]["response"]


# ───────────────────── _run_cli_streaming ─────────────────────


class TestRunCliStreaming:
    def test_stream_json_token_events(self, tmp_path):
        svc = _make_svc(tmp_path)  # 默认 codex → 非 stream-json
        # 用 CLAUDE profile 测 stream-json 分支
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        proc = _fake_proc(
            [b'{"type":"content_block_delta","delta":{"text":"hello"}}\n'],
            returncode=0,
        )
        with patch(
            "app.application.super_employee_service.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            events = _run_agen(svc._run_cli_streaming("/cli", "prompt", str(tmp_path)))
        assert events == [{"type": "token", "text": "hello"}, {"type": "done", "text": "hello"}]

    def test_stream_json_empty_then_error(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        proc = _fake_proc([], returncode=3)
        with patch(
            "app.application.super_employee_service.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            events = _run_agen(svc._run_cli_streaming("/cli", "prompt", str(tmp_path)))
        assert events[0]["type"] == "error"
        assert "返回失败" in events[0]["message"]

    def test_non_stream_output_file_read(self, tmp_path):
        svc = _make_svc(tmp_path)  # codex：非 stream-json
        proc = _fake_proc([], returncode=0)
        # 让 output_path.read_text 返回内容：patch Path.read_text
        with (
            patch(
                "app.application.super_employee_service.asyncio.create_subprocess_exec",
                return_value=proc,
            ),
            patch(
                "app.application.super_employee_service.Path.read_text", return_value="file body"
            ),
            patch("app.application.super_employee_service.Path.exists", return_value=True),
        ):
            events = _run_agen(svc._run_cli_streaming("/cli", "prompt", str(tmp_path)))
        assert events == [{"type": "done", "text": "file body"}]

    def test_non_stream_failure(self, tmp_path):
        svc = _make_svc(tmp_path)
        proc = _fake_proc([], returncode=2)
        with patch(
            "app.application.super_employee_service.asyncio.create_subprocess_exec",
            return_value=proc,
        ):
            events = _run_agen(svc._run_cli_streaming("/cli", "prompt", str(tmp_path)))
        assert events[0]["type"] == "error"
        assert "返回失败" in events[0]["message"]

    def test_subprocess_launch_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.asyncio.create_subprocess_exec",
            side_effect=OSError("no cli"),
        ):
            events = _run_agen(svc._run_cli_streaming("/cli", "prompt", str(tmp_path)))
        assert events[0]["type"] == "error"
        assert "启动失败" in events[0]["message"]


# ───────────────────── _parse_stream_json_line ─────────────────────


class TestParseStreamJsonLine:
    def test_assistant_text_block(self, tmp_path):
        svc = _make_svc(tmp_path)
        line = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
        )
        assert svc._parse_stream_json_line(line) == "hi"

    def test_assistant_text_block_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        line = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": ""}]}}
        )
        assert svc._parse_stream_json_line(line) == ""

    def test_result_string(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert (
            svc._parse_stream_json_line(json.dumps({"type": "result", "result": "done"})) == "done"
        )

    def test_result_empty_string(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._parse_stream_json_line(json.dumps({"type": "result", "result": "  "})) == ""

    def test_content_block_delta(self, tmp_path):
        svc = _make_svc(tmp_path)
        line = json.dumps({"type": "content_block_delta", "delta": {"text": "tok"}})
        assert svc._parse_stream_json_line(line) == "tok"

    def test_message_delta(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert (
            svc._parse_stream_json_line(json.dumps({"type": "message_delta", "text": "delta"}))
            == "delta"
        )

    def test_unknown_type(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._parse_stream_json_line(json.dumps({"type": "thinking", "x": 1})) == ""

    def test_invalid_json(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._parse_stream_json_line("not json") == ""

    def test_non_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._parse_stream_json_line("[1, 2]") == ""


# ───────────────────── _chunk_text ─────────────────────


class TestChunkText:
    def test_empty_returns_empty(self):
        assert _chunk_text("") == []

    def test_short_text_single_chunk(self):
        assert _chunk_text("你好") == ["你好"]

    def test_split_on_punctuation(self):
        parts = _chunk_text("第一段。第二段。第三段", max_len=5)
        assert len(parts) >= 2
        assert "".join(parts) == "第一段。第二段。第三段"

    def test_long_chunk_forced_split(self):
        # 单一超长 part：实现不细分超长 part，整体保留（校验拼接不丢字）。
        text = "一" * 200
        parts = _chunk_text(text, max_len=50)
        assert "".join(parts) == text

    def test_flush_buffer_across_parts(self):
        # 累计超过 max_len 时 flush 缓冲区，覆盖 `if buf:` 分支。
        text = "第一段。" * 10
        parts = _chunk_text(text, max_len=30)
        assert "".join(parts) == text
        assert all(len(p) <= 30 for p in parts)
        assert len(parts) >= 2


# ───────────────────── _trae_cli_command ─────────────────────


class TestTraeCliCommand:
    def test_yolo_enabled_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEVFLEET_TRAE_YOLO", raising=False)
        monkeypatch.delenv("XCMAX_TRAE_YOLO", raising=False)
        cmd = _trae_cli_command("/usr/bin/trae-cli", "prompt", tmp_path / "out", str(tmp_path))
        assert cmd[0] == "/usr/bin/trae-cli"
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert "--yolo" in cmd
        assert cmd[-1] == "prompt"

    def test_yolo_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEVFLEET_TRAE_YOLO", "0")
        cmd = _trae_cli_command("/usr/bin/trae-cli", "prompt", tmp_path / "out", str(tmp_path))
        assert "--yolo" not in cmd

    def test_xcmax_yolo_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEVFLEET_TRAE_YOLO", raising=False)
        monkeypatch.setenv("XCMAX_TRAE_YOLO", "off")
        cmd = _trae_cli_command("/usr/bin/trae-cli", "prompt", tmp_path / "out", str(tmp_path))
        assert "--yolo" not in cmd


# ───────────────────── _relay_wt_lock ─────────────────────


class TestRelayWtLock:
    def test_same_key_same_lock(self):
        a = _relay_wt_lock("key1")
        b = _relay_wt_lock("key1")
        assert a is b

    def test_different_key_different_lock(self):
        a = _relay_wt_lock("keyA")
        b = _relay_wt_lock("keyB")
        assert a is not b


# ───────────────────── invoke 全流程 ─────────────────────


class TestInvoke:
    def test_empty_message_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="不能为空"):
            svc.invoke(user_id=1, message="  ")

    def test_cli_direct_canned_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.invoke(user_id=1, message="你是谁", context={"mode": "chat"})
        assert result["dispatch"]["accepted"] is True
        assert result["dispatch"]["status"] == "completed"
        assert result["dispatch"]["dispatcher"] == "codex_direct"
        assert "我是" in result["assistant_message"]["body"]

    def test_dispatch_accepted_path(self, tmp_path):
        svc = _make_svc(tmp_path)
        accepted = {
            "request_id": "req-1",
            "status": "accepted",
            "accepted": True,
            "queued": False,
            "para_tier": 2,
            "device_scope": "all_devices",
            "task_id": "t1",
            "task_status": "pending",
            "devices": ["d1"],
        }
        with (
            patch.object(svc, "_dispatch", return_value=accepted),
            patch.object(svc, "_fetch_para_task", return_value=None),
        ):
            result = svc.invoke(user_id=1, message="修复 bug", context={"mode": "code"})
        assert result["dispatch"]["accepted"] is True
        assert result["assistant_message"]["kind"] == DISPATCHER_MESSAGE_KIND

    def test_dispatch_not_accepted_fallback(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"request_id": "req-1", "status": "queued", "accepted": False}
        with (
            patch.object(svc, "_dispatch", return_value=dispatch),
            patch.object(svc, "_compose_direct_chat_reply", return_value=("兜底答案", "codex_cli")),
        ):
            result = svc.invoke(user_id=1, message="修复 bug", context={"mode": "code"})
        assert result["dispatch"]["accepted"] is False
        assert result["dispatch"]["fallback"] == "codex_cli"
        assert "兜底答案" in result["assistant_message"]["body"]

    def test_dispatch_not_accepted_fallback_no_body(self, tmp_path):
        svc = _make_svc(tmp_path)
        dispatch = {"request_id": "req-1", "status": "queued", "accepted": False}
        with (
            patch.object(svc, "_dispatch", return_value=dispatch),
            patch.object(
                svc,
                "_compose_direct_chat_reply",
                return_value=(f"{svc._p.display_tool} CLI 暂时没有返回内容 xxx", "codex_cli"),
            ),
        ):
            result = svc.invoke(user_id=1, message="修复 bug", context={"mode": "code"})
        # body starts with placeholder → 不落 assistant 兜底，走 dispatcher 消息
        assert result["assistant_message"]["kind"] == DISPATCHER_MESSAGE_KIND

    def test_factory_token_rejected_logs_warning(self, tmp_path, caplog):
        svc = _make_svc(tmp_path)
        with patch("app.application.super_employee_service.logger") as mock_logger:
            svc.invoke(
                user_id=1, message="增强功能", context={"mode": "code", CONTEXT_TOKEN_KEY: "wrong"}
            )
        mock_logger.warning.assert_called_once()
        # token 不应流入持久化
        rows = svc._read_all_message_rows()
        for row in rows:
            assert CONTEXT_TOKEN_KEY not in json.dumps(row)


# ───────────────────── _build_dispatch_request ─────────────────────


class TestBuildDispatchRequest:
    def test_product_scope_empty_workspace(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="t",
            user_id=1,
            message="hi",
            context={"source": "mobile_app"},
        )
        assert req["workspace_root"] == ""
        assert req["source"] == "xcagi_mobile_im"
        assert req["raw_context"] == {"source": "mobile_app"}

    def test_factory_scope_resolves_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "secret")
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
        ctx = {"_factory_token": "secret", "workspace_id": "xcmax", "mode": "code"}
        with patch.object(svc, "_factory_workspace_root", return_value="/repo/root"):
            req = svc._build_dispatch_request(
                request_id="r1", created_at="t", user_id=1, message="hi", context=ctx
            )
        assert req["workspace_root"] == "/repo/root"
        assert req["scope"] == "factory"

    def test_target_devices_list_and_default(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = svc._build_dispatch_request(
            request_id="r1",
            created_at="t",
            user_id=1,
            message="hi",
            context={"target_devices": ["d1", "d2"]},
        )
        assert req["target_devices"] == ["d1", "d2"]
        req2 = svc._build_dispatch_request(
            request_id="r2",
            created_at="t",
            user_id=1,
            message="hi",
            context={"target_devices": "oops"},
        )
        assert req2["target_devices"] == ["all"]


# ───────────────────── 设备选择套件 ─────────────────────


class TestDeviceEligible:
    def test_not_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible("oops") is False

    def test_not_online(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible({"id": "d1", "status": "offline"}) is False

    def test_tool_not_installed(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {
            "id": "d1",
            "status": "online",
            "tools": [{"toolName": "codex", "status": "not_installed"}],
        }
        assert svc._device_eligible(device) is False

    def test_tool_running_with_task(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {
            "id": "d1",
            "status": "online",
            "tools": [{"toolName": "codex", "status": "running", "currentTask": "t"}],
        }
        assert svc._device_eligible(device) is False

    def test_no_tool_and_no_capability(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._device_eligible({"id": "d1", "status": "online", "capabilities": {}}) is False

    def test_eligible_via_capability(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}
        assert svc._device_eligible(device) is True

    def test_eligible_via_tool(self, tmp_path):
        svc = _make_svc(tmp_path)
        device = {
            "id": "d1",
            "status": "online",
            "tools": [{"toolName": "codex", "status": "idle"}],
        }
        assert svc._device_eligible(device) is True


class TestSelectParaDevices:
    def test_filters_by_target_and_workers(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "d1",
                "name": "dev1",
                "status": "online",
                "capabilities": {"codex_cli": True},
                "isPrimary": True,
            },
            {"id": "d2", "name": "dev2", "status": "online", "capabilities": {"codex_cli": True}},
            {"id": "d3", "name": "dev3", "status": "offline", "capabilities": {"codex_cli": True}},
        ]
        req = _make_request(target_devices=["all"])
        selected = svc._select_para_devices(devices, req)
        # 有可用 worker（非 primary）时只选 worker：primary d1 被排除，仅剩 d2
        assert [d["id"] for d in selected] == ["d2"]

    def test_target_specific(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "d1", "name": "a", "status": "online", "capabilities": {"codex_cli": True}},
            {"id": "d2", "name": "b", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        req = _make_request(target_devices=["d2"])
        selected = svc._select_para_devices(devices, req)
        assert [d["id"] for d in selected] == ["d2"]


class TestResolveParaTier:
    def test_forced_1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "1")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request()) == 1

    def test_forced_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "fleet")
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request()) == 2

    def test_tier_hint_2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(raw_context={"tier": "fleet"})) == 2

    def test_tier_hint_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(raw_context={"para_tier": "本机"})) == 1

    def test_escalate(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(raw_context={"escalate": True})) == 2

    def test_max_devices_gt_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(raw_context={"max_devices": 3})) == 2

    def test_max_devices_invalid(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(raw_context={"max_devices": "abc"})) == 1

    def test_specific_targets_gt_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(target_devices=["d1", "d2"])) == 2

    def test_multi_device_keyword(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request(task="调用所有设备干活")) == 2

    def test_default_tier_1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._resolve_para_tier(_make_request()) == 1


class TestSelectLocalDevice:
    def test_local_id_matches_eligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "d1")
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}]
        assert svc._select_local_device(devices, _make_request()) == [devices[0]]

    def test_local_id_matches_not_eligible(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "d1")
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "offline"}]
        assert svc._select_local_device(devices, _make_request()) == []

    def test_local_id_not_in_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "d9")
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}]
        assert svc._select_local_device(devices, _make_request()) == []

    def test_primary_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {
                "id": "d1",
                "isPrimary": True,
                "status": "online",
                "capabilities": {"codex_cli": True},
            },
            {"id": "d2", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        selected = svc._select_local_device(devices, _make_request())
        assert [d["id"] for d in selected] == ["d1"]

    def test_primary_not_eligible_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "d1", "isPrimary": True, "status": "offline"},
            {"id": "d2", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        # 识别到本机主设备但不合格 → 返回空，交由上层升二级
        assert svc._select_local_device(devices, _make_request()) == []

    def test_no_primary_falls_to_first_eligible(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [
            {"id": "d1", "status": "offline"},
            {"id": "d2", "status": "online", "capabilities": {"codex_cli": True}},
        ]
        selected = svc._select_local_device(devices, _make_request())
        assert [d["id"] for d in selected] == ["d2"]

    def test_no_eligible_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._select_local_device([], _make_request()) == []


class TestSelectDevicesByTier:
    def test_tier_1_with_local(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}]
        tier, selected = svc._select_devices_by_tier(devices, _make_request())
        assert tier == 1
        assert selected == [devices[0]]

    def test_tier_1_escalates_to_2(self, tmp_path):
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "offline"}]
        tier, selected = svc._select_devices_by_tier(devices, _make_request())
        assert tier == 2
        assert selected == []

    def test_tier_2_multi(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "multi")
        svc = _make_svc(tmp_path)
        devices = [{"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}]
        tier, selected = svc._select_devices_by_tier(devices, _make_request())
        assert tier == 2
        assert selected == [devices[0]]


# ───────────────────── _para_prompt / _para_subtask_title / _max_para_devices ─────────────────────


class TestParaPrompt:
    def test_single_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = _make_request(prompt="做一件事")
        out = svc._para_prompt(req, {"id": "d1"}, 0, 1)
        assert "请直接完成该任务" in out
        assert "做一件事" in out

    def test_multi_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = _make_request(prompt="做一件事")
        out = svc._para_prompt(req, {"id": "d1", "name": "设备A"}, 1, 2)
        assert "你是第 2/2 台 Codex 工作设备" in out
        assert "设备A" in out

    def test_workspace_root_appended(self, tmp_path):
        svc = _make_svc(tmp_path)
        req = _make_request(prompt="做一件事", workspace_root="/srv/repo")
        out = svc._para_prompt(req, {"id": "d1"}, 0, 1)
        assert "管理端来源工作区：/srv/repo" in out


class TestParaSubtaskTitle:
    def test_single_device(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._para_subtask_title("任务", 0, 1) == "任务"

    def test_with_label(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._para_subtask_title("任务", 0, 3) == "需求定位与方案：任务"

    def test_index_out_of_range(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._para_subtask_title("任务", 10, 11) == "工作单元 11：任务"


class TestMaxParaDevices:
    def test_from_raw_context(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices(_make_request(raw_context={"max_devices": 5})) == 5

    def test_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", "4")
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices(_make_request()) == 4

    def test_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_MAX_DEVICES", raising=False)
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices(_make_request()) == 3

    def test_invalid_falls_back(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices(_make_request(raw_context={"max_devices": "oops"})) == 3

    def test_clamped(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._max_para_devices(_make_request(raw_context={"max_devices": 99})) == 8
        # 负数是 truthy → 触发 max(1, ...) 下界钳制
        assert svc._max_para_devices(_make_request(raw_context={"max_devices": -5})) == 1
        # 0 是 falsy → 被 `or 3` 兜底为默认值
        assert svc._max_para_devices(_make_request(raw_context={"max_devices": 0})) == 3


# ───────────────────── _json_response / _error_message / _dispatch_reply ─────────────────────


class TestJsonResponse:
    def test_valid_dict(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = _mock_response(status_code=200, json_data={"a": 1})
        assert svc._json_response(resp) == {"a": 1}

    def test_value_error_falls_to_raw(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = MagicMock()
        resp.content = b"not json"
        resp.text = "not json"
        resp.json.side_effect = ValueError("bad")
        body = svc._json_response(resp)
        assert body == {"raw": "not json"}

    def test_non_dict_wrapped(self, tmp_path):
        svc = _make_svc(tmp_path)
        resp = _mock_response(status_code=200, json_data=[1, 2])
        assert svc._json_response(resp) == {"data": [1, 2]}


class TestErrorMessage:
    def test_error_field(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._error_message({"error": "boom"}, "fallback") == "boom"

    def test_message_field(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._error_message({"message": "oops"}, "fallback") == "oops"

    def test_fallback(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._error_message({}, "fallback") == "fallback"


class TestDispatchReply:
    def test_returns_thinking(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._dispatch_reply({}) == "思考中..."


# ───────────────────── _para_task_status_reply / _result_body ─────────────────────


class TestParaTaskStatusReply:
    def test_completed(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._para_task_status_reply({"id": "t1", "status": "completed"})
        assert "已完成" in out
        assert "任务 ID：t1" in out

    def test_failed(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._para_task_status_reply({"id": "t1", "status": "failed"})
        assert "需要处理" in out

    def test_failed_via_subtask(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {"id": "t1", "status": "running", "subTasks": [{"status": "failed"}]}
        out = svc._para_task_status_reply(task)
        assert "需要处理" in out

    def test_running_with_progress(self, tmp_path):
        svc = _make_svc(tmp_path)
        task = {
            "id": "t1",
            "status": "running",
            "subTasks": [
                {"status": "completed", "progress": 50},
                {"status": "running", "progress": 100},
            ],
        }
        out = svc._para_task_status_reply(task)
        assert "运行中" in out
        assert "1/2" in out

    def test_created(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._para_task_status_reply({"id": "t1", "status": "pending"})
        assert "已创建" in out


class TestResultBody:
    def test_with_tail(self, tmp_path):
        svc = _make_svc(tmp_path)
        subtask = {
            "device_name": "dev1",
            "title": "子任",
            "status": "completed",
            "logs": [{"content": "日志内容"}],
        }
        out = svc._result_body({"title": "总任务"}, subtask)
        assert "dev1 / 子任" in out
        assert "日志内容" in out

    def test_completed_no_logs(self, tmp_path):
        svc = _make_svc(tmp_path)
        subtask = {"device_name": "dev1", "status": "completed", "logs": []}
        out = svc._result_body({"title": "总任务"}, subtask)
        assert "已完成该子任务" in out

    def test_failed_with_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        subtask = {"device_id": "d1", "status": "failed", "last_error": "boom", "logs": []}
        out = svc._result_body({"title": "总任务"}, subtask)
        assert "执行失败" in out
        assert "boom" in out

    def test_skips_dispatcher_logs(self, tmp_path):
        svc = _make_svc(tmp_path)
        subtask = {
            "device_name": "dev1",
            "status": "completed",
            "logs": [{"content": "子任务「x」派发"}, {"content": "真实结果"}],
        }
        out = svc._result_body({"title": "总任务"}, subtask)
        assert "真实结果" in out
        assert "子任务「x」" not in out


class TestTaskSubtasks:
    def test_subtasks_list(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._task_subtasks({"subTasks": [{"id": "s1"}, "skip"]}) == [{"id": "s1"}]

    def test_subtasks_lowercase(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._task_subtasks({"subtasks": [{"id": "s1"}]}) == [{"id": "s1"}]

    def test_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._task_subtasks({}) == []


# ───────────────────── _sync_para_task_updates ─────────────────────


class TestSyncParaTaskUpdates:
    def test_no_dispatcher_rows_no_change(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [{"user_id": 1, "role": "user", "kind": "", "dispatch_request_id": "r1"}]
        with patch.object(svc, "_write_all_message_rows") as write:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        write.assert_not_called()

    def test_terminal_status_with_result_skips_fetch(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "t1",
                "task_status": "completed",
                "status": "completed",
                "dispatch_request_id": "r1",
            },
            # 已有 result 消息 → result_task_ids 含 t1 → 终态则跳过 fetch
            {
                "user_id": 1,
                "role": "assistant",
                "kind": svc._p.result_kind,
                "task_id": "t1",
                "dispatch_request_id": "r1",
            },
        ]
        with patch.object(svc, "_fetch_para_task") as fetch:
            svc._sync_para_task_updates(user_id=1, rows=rows)
        fetch.assert_not_called()

    def test_fetches_and_writes_when_changed(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {
                "user_id": 1,
                "role": "system",
                "kind": DISPATCHER_MESSAGE_KIND,
                "task_id": "t1",
                "task_status": "",
                "status": "queued",
                "dispatch_request_id": "r1",
                "body": "x",
            }
        ]
        task = {"id": "t1", "status": "running"}
        with (
            patch.object(svc, "_fetch_para_task", return_value=task),
            patch.object(svc, "_refresh_dispatcher_row", return_value=True),
            patch.object(svc, "_upsert_result_messages", return_value=False),
            patch.object(svc, "_write_all_message_rows") as write,
        ):
            svc._sync_para_task_updates(user_id=1, rows=rows)
        write.assert_called_once()


# ───────────────────── _upgrade_legacy_dispatcher_row ─────────────────────


class TestUpgradeLegacyDispatcherRow:
    def test_already_dispatcher_kind(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": DISPATCHER_MESSAGE_KIND, "role": "assistant"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_not_assistant_role(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "user", "body": "多设备调度器已派发"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_not_ack_body(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "assistant", "body": "普通回复"}
        assert svc._upgrade_legacy_dispatcher_row(row) is False

    def test_upgrade_with_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "assistant", "body": "多设备调度器，任务 ID：abc1234567"}
        changed = svc._upgrade_legacy_dispatcher_row(row)
        assert changed is True
        assert row["role"] == "system"
        assert row["kind"] == DISPATCHER_MESSAGE_KIND
        assert row["task_id"] == "abc1234567"

    def test_upgrade_without_task_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        row = {"kind": "", "role": "assistant", "body": "调用队列已满", "task_id": "existing"}
        changed = svc._upgrade_legacy_dispatcher_row(row)
        assert changed is True
        assert "existing" in row["task_id"]


# ───────────────────── _upsert_direct_reply_messages ─────────────────────


class TestUpsertDirectReplyMessages:
    def test_appends_canned_reply(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [{"user_id": 1, "role": "user", "dispatch_request_id": "r1", "body": "你好"}]
        changed = svc._upsert_direct_reply_messages(user_id=1, rows=rows)
        assert changed is True
        assert len(rows) == 2
        assert rows[1]["kind"] == "codex_direct"

    def test_existing_reply_skips(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {"user_id": 1, "role": "user", "dispatch_request_id": "r1", "body": "你好"},
            {
                "user_id": 1,
                "role": "assistant",
                "dispatch_request_id": "r1",
                "kind": "codex_direct",
            },
        ]
        changed = svc._upsert_direct_reply_messages(user_id=1, rows=rows)
        assert changed is False
        assert len(rows) == 2

    def test_cli_backfill_once(self, tmp_path):
        svc = _make_svc(tmp_path)
        rows = [
            {"user_id": 1, "role": "user", "dispatch_request_id": "r1", "body": "随便聊点什么"},
            {"user_id": 1, "role": "user", "dispatch_request_id": "r2", "body": "再聊点别的"},
        ]
        with patch.object(
            svc, "_compose_direct_chat_reply", return_value=("cli 回填", "codex_cli")
        ):
            changed = svc._upsert_direct_reply_messages(user_id=1, rows=rows)
        assert changed is True
        assert len(rows) == 3  # 只回填一条（cli_backfills < 1）


# ───────────────────── _direct_reply_body 各类提示 ─────────────────────


class TestDirectReplyBody:
    def test_identity(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert "我是" in svc._direct_reply_body("你是谁")

    def test_help(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert "开发任务" in svc._direct_reply_body("你能做什么")

    def test_greeting(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert "我在" in svc._direct_reply_body("你好")

    def test_slow_prompt(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert "慢是因为" in svc._direct_reply_body("为什么这么慢")

    def test_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._direct_reply_body("  ") == ""


# ───────────────────── _compose_direct_chat_reply ─────────────────────


class TestComposeDirectChatReply:
    def test_canned_wins(self, tmp_path):
        svc = _make_svc(tmp_path)
        body, dispatcher = svc._compose_direct_chat_reply("你是谁", {})
        assert dispatcher == "codex_direct"

    def test_cli_body(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_direct_reply_body", return_value=""),
            patch.object(svc, "_cli_reply_body", return_value="cli 结果"),
        ):
            body, dispatcher = svc._compose_direct_chat_reply("随意", {})
        assert dispatcher == "codex_cli"
        assert body == "cli 结果"

    def test_fallback_message(self, tmp_path):
        svc = _make_svc(tmp_path)
        with (
            patch.object(svc, "_direct_reply_body", return_value=""),
            patch.object(svc, "_cli_reply_body", return_value=""),
        ):
            body, dispatcher = svc._compose_direct_chat_reply("随意", {})
        assert "暂时没有返回内容" in body
        assert dispatcher == "codex_cli"


# ───────────────────── _apply_scope_to_cmd / _conversation_cmd ─────────────────────


class TestApplyScopeToCmd:
    def test_empty_cmd(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._apply_scope_to_cmd([]) == []

    def test_factory_scope_unchanged(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
        cmd = ["codex", "--print"]
        assert svc._apply_scope_to_cmd(cmd) == cmd

    def test_non_claude_unchanged(self, tmp_path):
        svc = _make_svc(tmp_path)  # codex
        cmd = ["codex", "--print"]
        assert svc._apply_scope_to_cmd(cmd) == cmd

    def test_relay_trusted_unchanged(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        svc._relay_cli_trusted = True
        cmd = ["claude", "--print"]
        assert svc._apply_scope_to_cmd(cmd) == cmd

    def test_claude_product_restricts(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        svc._grant = CapabilityGrant(ExecutionScope.PRODUCT, None)
        cmd = ["claude", "--permission-mode", "acceptEdits", "hello"]
        out = svc._apply_scope_to_cmd(cmd)
        assert "--permission-mode" in out
        assert "default" in out
        assert "--disallowedTools" in out
        assert out[-1] == "hello"


class TestConversationCmd:
    def test_without_resume(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        cmd = svc._conversation_cmd("/cli", "prompt", None)
        assert "--resume" not in cmd
        assert cmd[-1] == "prompt"

    def test_with_resume(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        cmd = svc._conversation_cmd("/cli", "prompt", "sess-1")
        assert "--resume" in cmd
        assert "sess-1" in cmd


# ───────────────────── _run_conversation_turn ─────────────────────


class TestRunConversationTurn:
    @pytest.fixture(autouse=True)
    def _isolate_session_store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.application.super_employee_service.get_app_data_dir",
            lambda: str(tmp_path),
        )

    def test_success(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with (
            patch.object(
                svc,
                "_run_cli_idle",
                return_value=(0, '{"type":"result","result":"ok","session_id":"s1"}', "", ""),
            ),
            patch.object(svc, "_session_get", return_value={}),
            patch.object(svc, "_session_set") as sset,
        ):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert result == "ok"
        sset.assert_called_once()

    def test_idle_killed(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with patch.object(svc, "_run_cli_idle", return_value=(0, "", "", "idle:180")):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert "静默" in result

    def test_hardcap_killed(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with patch.object(svc, "_run_cli_idle", return_value=(0, "", "", "hardcap:3600")):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert "超过上限" in result

    def test_returncode_failure(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with patch.object(svc, "_run_cli_idle", return_value=(2, "", "stderr text", "")):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert "返回失败" in result
        assert "stderr text" in result

    def test_resume_fail_retries(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with (
            patch.object(svc, "_session_get", return_value={"session_id": "old-sess"}),
            patch.object(
                svc,
                "_run_cli_idle",
                side_effect=[
                    (0, "no conversation found", "", ""),
                    (0, '{"type":"result","result":"retried","session_id":"new"}', "", ""),
                ],
            ),
            patch.object(svc, "_session_set") as sset,
        ):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert result == "retried"
        sset.assert_called()

    def test_cli_oserror(self, tmp_path):
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE)
        with patch.object(svc, "_run_cli_idle", side_effect=OSError("no cli")):
            result = svc._run_conversation_turn("/cli", "hello", {})
        assert "CLI 调用失败" in result


# ───────────────────── _cli_workspace 相关 ─────────────────────


class TestCliWorkspace:
    def test_factory_uses_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_FACTORY_CAPABILITY_TOKEN", "secret")
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
        with patch("app.application.super_employee_service.get_workspace_registry") as reg:
            fake_reg = MagicMock()
            fake_reg.get.return_value = MagicMock()
            fake_reg.checkout.return_value = Path(str(tmp_path / "ws"))
            reg.return_value = fake_reg
            cwd = svc._cli_workspace({})
            assert cwd == str(tmp_path / "ws")

    def test_factory_workspace_error_fallback(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "unknown")
        with patch("app.application.super_employee_service.get_workspace_registry") as reg:
            from app.application.workspaces import WorkspaceError

            fake_reg = MagicMock()

            def _get(ws):
                if ws is None:  # 回退默认工作区
                    m = MagicMock()
                    m.root = Path("/fallback")
                    return m
                raise WorkspaceError("unknown workspace: unknown")

            fake_reg.get.side_effect = _get
            reg.return_value = fake_reg
            cwd = svc._cli_workspace({})
        assert cwd == "/fallback"

    def test_product_ephemeral(self, tmp_path):
        svc = _make_svc(tmp_path)
        cwd = svc._cli_workspace({})
        assert "xcmax_product_scratch" in cwd

    def test_relay_real_workspace(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_relay_real_workspace", return_value="/real/repo"):
            assert svc._cli_workspace({"force_cli_direct": True}) == "/real/repo"


class TestFactoryWorkspaceRoot:
    def test_resolves_root(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
        with patch("app.application.super_employee_service.get_workspace_registry") as reg:
            fake_reg = MagicMock()
            fake_reg.get.return_value = MagicMock(root=Path("/repo/root"))
            reg.return_value = fake_reg
            assert svc._factory_workspace_root() == "/repo/root"

    def test_workspace_error_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "unknown")
        with patch("app.application.super_employee_service.get_workspace_registry") as reg:
            from app.application.workspaces import WorkspaceError

            fake_reg = MagicMock()
            fake_reg.get.side_effect = WorkspaceError("boom")
            reg.return_value = fake_reg
            assert svc._factory_workspace_root() == ""


class TestProductEphemeralWorkspace:
    def test_returns_scratch_path(self, tmp_path):
        svc = _make_svc(tmp_path)
        cwd = svc._product_ephemeral_workspace()
        assert "xcmax_product_scratch" in cwd
        assert Path(cwd).exists()


class TestRelayRealWorkspace:
    def test_not_relay(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._relay_real_workspace({"source": "admin"}) == ""

    def test_relay_force_direct(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.resolve_verified_relay_workspace_root",
            return_value="/relay/root",
        ):
            assert svc._relay_real_workspace({"force_cli_direct": True}) == "/relay/root"

    def test_relay_mobile_source(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch(
            "app.application.super_employee_service.resolve_verified_relay_workspace_root",
            return_value="/relay/root",
        ):
            assert svc._relay_real_workspace({"source": "mobile_relay"}) == "/relay/root"


# ───────────────────── _clean_cli_stdout ─────────────────────


class TestCleanCliStdout:
    def test_removes_junk_lines(self, tmp_path):
        svc = _make_svc(tmp_path)
        out = svc._clean_cli_stdout("codex\n123,456\ntokens used\nreal line\n")
        assert out == "real line"

    def test_removes_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._clean_cli_stdout("  \n\n") == ""

    def test_keeps_meaningful(self, tmp_path):
        svc = _make_svc(tmp_path)
        assert svc._clean_cli_stdout("第一行\n第二行") == "第一行\n第二行"


# ───────────────────── _cli_reply_body dev-loop 分支 ─────────────────────


class TestCliReplyBody:
    def test_disabled_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "off")
        svc = _make_svc(tmp_path)
        assert svc._cli_reply_body("你好", {}) == ""

    def test_no_cli_path_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_cli_path", return_value=""):
            assert svc._cli_reply_body("你好", {}) == ""

    def test_chat_goes_to_cli_once(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("chat answer"))
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=False),
        ):
            result = svc._cli_reply_body("你好", {"mode": "chat"})
        assert "chat answer" in result

    def test_task_no_dev_loop_goes_to_cli_once(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, cli_runner=_stdout_runner("work answer"))
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=True),
            patch.object(svc, "_dev_loop_enabled", return_value=False),
        ):
            result = svc._cli_reply_body("修复 bug", {"mode": "code"})
        assert "work answer" in result

    def test_task_dev_loop_runs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/codex"),
            patch.object(svc, "_is_task_intent", return_value=True),
            patch.object(svc, "_dev_loop_enabled", return_value=True),
            patch.object(svc, "_run_dev_task_loop", return_value="loop done"),
        ):
            result = svc._cli_reply_body("修复 bug", {"mode": "code"})
        assert result == "loop done"

    def test_conversation_mode_for_stream_json(self, tmp_path, monkeypatch):
        # claude 生产路径（stream-json + 真实 runner + conversation 开启）→ 走会话
        monkeypatch.setenv("XCMAX_CLAUDE_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/claude"),
            patch.object(svc, "_conversation_mode_enabled", return_value=True),
            patch.object(svc, "_run_conversation_turn", return_value="会话回复"),
        ):
            result = svc._cli_reply_body("你好", {"mode": "chat"})
        assert result == "会话回复"

    def test_force_cli_direct_skips_conversation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCMAX_CODEX_CLI_CHAT_ENABLED", "1")
        svc = _make_svc(tmp_path, profile=CLAUDE_PROFILE, cli_runner=subprocess.run)
        with (
            patch.object(svc, "_cli_path", return_value="/fake/claude"),
            patch.object(svc, "_is_task_intent", return_value=True),
            patch.object(svc, "_dev_loop_enabled", return_value=True),
            patch.object(svc, "_run_dev_task_loop", return_value="devloop"),
        ):
            result = svc._cli_reply_body("修复 bug", {"mode": "code", "force_cli_direct": True})
        assert result == "devloop"


# ───────────────────── _prepare_persistent_worktree ─────────────────────


class TestPreparePersistentWorktree:
    def test_reuse_existing_worktree(self, tmp_path):
        svc = _make_svc(tmp_path)
        wt = tmp_path / "wt"
        (wt / ".git").mkdir(parents=True)
        base_ref = MagicMock()
        base_ref.stdout = "sha123\n"
        reset = MagicMock()
        reset.returncode = 0
        clean = MagicMock()
        clean.returncode = 0
        checkout = MagicMock()
        checkout.returncode = 0
        with patch.object(svc, "_git", side_effect=[base_ref, reset, clean, checkout]):
            result = svc._prepare_persistent_worktree(str(tmp_path), str(wt), "branch")
        assert result == (str(wt), "branch")

    def test_create_new_worktree(self, tmp_path):
        svc = _make_svc(tmp_path)
        wt = tmp_path / "new-wt"
        base_ref = MagicMock()
        base_ref.stdout = "sha123\n"
        prune = MagicMock()
        prune.returncode = 0
        add = MagicMock()
        add.returncode = 0
        add.stderr = ""
        add.stdout = ""
        with patch.object(svc, "_git", side_effect=[base_ref, prune, add]):
            result = svc._prepare_persistent_worktree(str(tmp_path), str(wt), "branch")
        assert result == (str(wt), "branch")

    def test_create_fails_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        wt = tmp_path / "new-wt"
        base_ref = MagicMock()
        base_ref.stdout = "sha123\n"
        prune = MagicMock()
        prune.returncode = 0
        add = MagicMock()
        add.returncode = 1
        add.stderr = "error"
        add.stdout = ""
        with patch.object(svc, "_git", side_effect=[base_ref, prune, add]):
            assert svc._prepare_persistent_worktree(str(tmp_path), str(wt), "branch") is None

    def test_exception_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        with patch.object(svc, "_git", side_effect=Exception("crash")):
            assert (
                svc._prepare_persistent_worktree(str(tmp_path), str(tmp_path / "wt"), "branch")
                is None
            )
