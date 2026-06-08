"""``script_agent.sandbox_runner`` 的端到端单测：真起子进程跑代码。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from modstore_server.script_agent import sandbox_runner


def test_run_simple_print(tmp_path: Path) -> None:
    code = (
        "import json\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/r.json').write_text(json.dumps({'ok': True}))\n"
        "print('done')\n"
    )
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t1",
            script_text=code,
            files=[],
            script_root=tmp_path,
        )
    )
    assert res.ok is True
    assert res.returncode == 0
    assert "done" in res.stdout
    assert any(o["filename"] == "r.json" for o in res.outputs)


def test_run_uses_uploaded_inputs(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path\n"
        "data = (Path('inputs') / 'hello.txt').read_text(encoding='utf-8')\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "(Path('outputs') / 'echo.txt').write_text(data + '!', encoding='utf-8')\n"
    )
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t2",
            script_text=code,
            files=[{"filename": "hello.txt", "content": "world".encode()}],
            script_root=tmp_path,
        )
    )
    assert res.ok is True
    out_file = next(p for p in res.outputs if p["filename"] == "echo.txt")
    assert Path(out_file["path"]).read_text(encoding="utf-8") == "world!"


def test_run_timeout(tmp_path: Path) -> None:
    code = "import time\ntime.sleep(5)\nprint('finished')\n"
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t3",
            script_text=code,
            files=[],
            timeout_seconds=2,
            script_root=tmp_path,
        )
    )
    assert res.ok is False
    assert res.timed_out is True
    assert any("超时" in e for e in res.errors)


def test_run_failed_returns_stderr(tmp_path: Path) -> None:
    code = "raise RuntimeError('boom')\n"
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t4",
            script_text=code,
            files=[],
            script_root=tmp_path,
        )
    )
    assert res.ok is False
    assert res.returncode != 0
    assert "boom" in res.stderr


def test_runtime_sdk_module_is_importable_in_sandbox(tmp_path: Path) -> None:
    """脚本能 ``import modstore_runtime``（即 SDK 文件被复制进 work_dir）。

    本测试不调 RPC 方法（那需要 LLM key），只验证 ``import``/对象存在。
    """
    code = (
        "import modstore_runtime as r\n"
        "from modstore_runtime import ai, kb_search, employee_run, http_get, log, inputs, outputs\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/ok.txt').write_text('imported', encoding='utf-8')\n"
        "print('imports-ok')\n"
    )
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t5",
            script_text=code,
            files=[],
            script_root=tmp_path,
        )
    )
    assert res.ok is True, f"stderr: {res.stderr}"
    assert "imports-ok" in res.stdout


def test_runtime_sdk_rpc_round_trip(tmp_path: Path, monkeypatch) -> None:
    """覆盖 RPC：mock ``chat_dispatch`` 让 ``ai()`` 返回固定值并写入 outputs。"""
    import modstore_server.script_agent.sandbox_host as host

    async def fake_chat_dispatch(provider, *, api_key, base_url, model, messages, max_tokens=None):
        # 简单 echo：把 user prompt 回成 JSON
        return {"ok": True, "content": json.dumps({"echoed": "yes"})}

    monkeypatch.setattr(host, "chat_dispatch", fake_chat_dispatch, raising=False)
    # 注：sandbox_host._handle_ai 通过 `from ... import chat_dispatch` 在函数体内 import
    # 因此要 patch 源模块
    import modstore_server.llm_chat_proxy as proxy

    monkeypatch.setattr(proxy, "chat_dispatch", fake_chat_dispatch)

    code = (
        "from modstore_runtime import ai\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "result = ai('hi', schema={'echoed': 'string'})\n"
        "Path('outputs/r.txt').write_text(str(result), encoding='utf-8')\n"
        "print('rpc-done')\n"
    )
    res = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="t6",
            script_text=code,
            files=[],
            api_key="fake-key",
            provider="openai",
            model="gpt-4o-mini",
            script_root=tmp_path,
        )
    )
    assert res.ok is True, f"stderr: {res.stderr}"
    out = next(o for o in res.outputs if o["filename"] == "r.txt")
    body = Path(out["path"]).read_text(encoding="utf-8")
    assert "echoed" in body
    # SDK 调用记录
    assert any(c["method"] == "ai" and c.get("ok") for c in res.sdk_calls)


def test_runtime_sdk_rejects_invalid_token(tmp_path: Path) -> None:
    """直接连 RPC 但用错 token：握手失败、连接关闭。"""
    from modstore_server.script_agent.sandbox_host import (
        SandboxHostContext,
        SandboxRpcServer,
    )

    async def go():
        rpc = SandboxRpcServer(SandboxHostContext(user_id=1))
        port = await rpc.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b'{"hello":"WRONG"}\n')
            await writer.drain()
            # 期望服务端写一行错误响应后关闭连接
            line = await asyncio.wait_for(reader.readline(), timeout=3)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return line
        finally:
            await rpc.stop()

    data = asyncio.run(go())
    text = data.decode("utf-8")
    assert '"ok": false' in text or '"ok":false' in text
    assert "invalid token" in text


def test_sandbox_employee_run_allowlist_blocks_rpc() -> None:
    from modstore_server.script_agent.sandbox_host import SandboxHostContext, SandboxRpcServer

    async def go():
        ctx = SandboxHostContext(user_id=1, employee_run_allowlist=("only-a",))
        srv = SandboxRpcServer(ctx)
        with pytest.raises(RuntimeError, match="允许"):
            await srv._handle_employee_run({"employee_id": "other", "task": "t", "payload": {}})

    asyncio.run(go())


def test_sandbox_employee_run_allowlist_allows_and_runs(monkeypatch, tmp_path: Path) -> None:
    from modstore_server.script_agent.sandbox_host import SandboxHostContext, SandboxRpcServer
    from modstore_server.services import employee as employee_svc

    async def go():
        class _Stub:
            def execute_task(self, **kwargs):
                return {"ok": True, "echo": kwargs.get("employee_id")}

        monkeypatch.setattr(
            employee_svc,
            "get_default_employee_client",
            lambda: _Stub(),
        )
        ctx = SandboxHostContext(user_id=1, employee_run_allowlist=("ok-emp",))
        srv = SandboxRpcServer(ctx)
        r = await srv._handle_employee_run(
            {"employee_id": "ok-emp", "task": "t", "payload": {"x": 1}}
        )
        assert r.get("ok") is True
        assert r.get("echo") == "ok-emp"

    asyncio.run(go())
