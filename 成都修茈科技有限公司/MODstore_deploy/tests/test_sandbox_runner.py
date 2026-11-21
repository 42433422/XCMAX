"""``script_agent.sandbox_runner`` 的端到端单测：真起子进程跑代码。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modstore_server.script_agent import sandbox_runner

BOUNDARY_ERRORS = (Exception,)


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


def test_sandbox_does_not_inherit_host_credentials(tmp_path: Path, monkeypatch) -> None:
    from modstore_server.script_agent.static_checker import validate_script

    names = ("MODSTORE_JWT_SECRET", "PAYMENT_SECRET_KEY", "DATABASE_URL", "NEW_PROVIDER_KEY")
    for name in names:
        monkeypatch.setenv(name, "sandbox-test-marker")
    code = (
        "import os\n"
        f"assert all(name not in os.environ for name in {names!r})\n"
        "assert os.environ['PYTHONIOENCODING'] == 'utf-8'\n"
        "assert os.environ['MODSTORE_RUNTIME_TOKEN']\n"
        "assert os.environ['MODSTORE_RUNTIME_TOKEN'] != 'caller-override'\n"
        "assert os.environ['SANDBOX_TEST_INPUT'] == 'explicit-value'\n"
        "print('host-credentials-isolated')\n"
    )
    assert validate_script(code) == []
    result = asyncio.run(
        sandbox_runner.run_in_sandbox(
            user_id=1,
            session_id="environment-boundary",
            script_text=code,
            files=[],
            script_root=tmp_path,
            extra_env={
                "SANDBOX_TEST_INPUT": "explicit-value",
                "MODSTORE_RUNTIME_TOKEN": "caller-override",
            },
        )
    )
    assert result.ok, result.stderr
    assert result.stdout.strip() == "host-credentials-isolated"


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
            except BOUNDARY_ERRORS:
                pass
            return line
        finally:
            await rpc.stop()

    data = asyncio.run(go())
    text = data.decode("utf-8")
    assert '"ok": false' in text or '"ok":false' in text
    assert "invalid token" in text


def test_sandbox_employee_run_allowlist_blocks_rpc() -> None:
    from modstore_server.script_agent.sandbox_host import (
        SandboxHostContext,
        SandboxRpcServer,
    )

    async def go():
        ctx = SandboxHostContext(user_id=1, employee_run_allowlist=("only-a",))
        srv = SandboxRpcServer(ctx)
        with pytest.raises(RuntimeError, match="允许"):
            await srv._handle_employee_run({"employee_id": "other", "task": "t", "payload": {}})

    asyncio.run(go())


def test_sandbox_employee_run_allowlist_allows_and_runs(monkeypatch, tmp_path: Path) -> None:
    from modstore_server.script_agent.sandbox_host import (
        SandboxHostContext,
        SandboxRpcServer,
    )
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


_QUICK_OUTPUT = "from pathlib import Path\nPath('outputs/result.txt').write_text('verified')\n"
_QUICK_EMPLOYEE = (
    "from modstore_runtime import employee_run\nemployee_run('worker', task='apply-once')\n"
)


def _run_quick_script_case(monkeypatch, tmp_path, code, *, repaired_code=_QUICK_OUTPUT):
    from modstore_server import workbench_script_job
    from modstore_server.script_agent.static_checker import validate_script

    sandbox_calls, repair_calls = [], []

    async def generate(**kwargs):
        return SimpleNamespace(code=code, errors=[])

    async def repair(**kwargs):
        repair_calls.append(kwargs)
        return SimpleNamespace(code=repaired_code, errors=[])

    async def run(**kwargs):
        call = {"code": kwargs["script_text"]}
        sandbox_calls.append(call)
        call["result"] = await sandbox_runner.run_in_sandbox(**kwargs, timeout_seconds=1)
        return call["result"]

    facade = SimpleNamespace(
        _generate_script=generate,
        _repair_script_once=repair,
        MAX_AGENT_ITERATIONS=2,
        resolve_api_key=lambda *args: ("test-key", "test"),
        resolve_base_url=lambda *args: None,
        validate_script=validate_script,
        SCRIPT_ROOT=tmp_path,
        _sandbox=SimpleNamespace(run_in_sandbox=run),
    )
    monkeypatch.setattr(workbench_script_job, "_facade", lambda: facade)
    result = asyncio.run(
        workbench_script_job.run_script_job(
            db=object(),
            user_id=1,
            session_id="quick-script-receipt",
            brief="Run the employee exactly once and produce its output",
            files=[],
            provider="test",
            model="test",
        )
    )
    return result, sandbox_calls, repair_calls


@pytest.mark.parametrize(
    "ending", ["raise RuntimeError('after effect')\n", "", "import time\ntime.sleep(5)\n"]
)
def test_quick_script_never_replays_employee_effect(monkeypatch, tmp_path, ending):
    from modstore_server.script_agent.sandbox_host import SandboxRpcServer

    effects = []

    async def employee(self, params):
        effects.append(params["task"])
        return {"success": True, "status": "completed", "run_id": "original-run"}

    monkeypatch.setattr(SandboxRpcServer, "_handle_employee_run", employee)
    result, runs, repairs = _run_quick_script_case(
        monkeypatch,
        tmp_path,
        _QUICK_EMPLOYEE + ending,
        repaired_code=_QUICK_EMPLOYEE + _QUICK_OUTPUT,
    )
    assert effects == ["apply-once"]
    assert len(runs) == 1 and repairs == []
    assert result["ok"] is False and result["retryable"] is False
    assert result["timed_out"] is ("time.sleep" in ending)
    assert result["sdk_calls"][0]["method"] == "employee_run"
    assert result["returncode"] == runs[0]["result"].returncode
    assert (result["returncode"] == 0) is (not ending)


def test_quick_script_timeout_receipt_survives_without_repair(monkeypatch, tmp_path):
    result, runs, repairs = _run_quick_script_case(
        monkeypatch, tmp_path, "import time\ntime.sleep(5)\n"
    )
    assert len(runs) == 1 and repairs == []
    assert result["ok"] is False and result["retryable"] is False
    assert result["timed_out"] is True and result["returncode"] != 0
    assert result["returncode"] == runs[0]["result"].returncode
    assert result["sdk_calls"] == []


def test_quick_script_lost_receipt_is_not_replayed(monkeypatch, tmp_path):
    effects = []

    async def lost_receipt(**kwargs):
        effects.append("started")
        raise OSError("lost sandbox receipt")

    monkeypatch.setattr(sandbox_runner, "run_in_sandbox", lost_receipt)
    result, runs, repairs = _run_quick_script_case(monkeypatch, tmp_path, _QUICK_OUTPUT)
    assert effects == ["started"] and len(runs) == 1 and repairs == []
    assert result["ok"] is False and result["retryable"] is False
    assert result["outcome"] in {"unverified", "unknown"}


@pytest.mark.parametrize(
    "receipt",
    [None, {"success": True, "accepted": True}, {"outcome": "unknown", "retryable": False}],
)
def test_quick_script_summary_cannot_complete_an_unverified_employee(
    monkeypatch, tmp_path, receipt
):
    from modstore_server.script_agent.sandbox_host import SandboxRpcServer

    async def employee(self, params):
        return receipt

    monkeypatch.setattr(SandboxRpcServer, "_handle_employee_run", employee)
    result, runs, repairs = _run_quick_script_case(
        monkeypatch, tmp_path, _QUICK_EMPLOYEE + _QUICK_OUTPUT
    )
    assert len(runs) == 1 and repairs == []
    assert result["ok"] is False and result["retryable"] is False
    assert result["returncode"] == 0 and result["timed_out"] is False
    assert result["outputs"] and result["sdk_calls"][0]["method"] == "employee_run"


@pytest.mark.parametrize("code", ["raise RuntimeError('local failure')\n", "print('no file')\n"])
def test_quick_script_repairs_local_file_failure(monkeypatch, tmp_path, code):
    result, runs, repairs = _run_quick_script_case(monkeypatch, tmp_path, code)
    assert result["ok"] is True
    assert len(runs) == 2 and len(repairs) == 1
    assert Path(result["outputs"][0]["path"]).read_text() == "verified"
    assert result["sdk_calls"] == []


def test_quick_script_preserves_confirmed_employee_success(monkeypatch, tmp_path):
    from modstore_server.customer_issue_delivery_contract import execution_succeeded
    from modstore_server.script_agent.sandbox_host import SandboxRpcServer

    effects = []

    async def employee(self, params):
        effects.append(params["task"])
        return {
            "success": True,
            "status": "completed",
            "run_id": "original-run",
            "retryable": False,
        }

    monkeypatch.setattr(SandboxRpcServer, "_handle_employee_run", employee)
    result, runs, repairs = _run_quick_script_case(
        monkeypatch, tmp_path, _QUICK_EMPLOYEE + _QUICK_OUTPUT
    )
    assert result["ok"] is True
    assert effects == ["apply-once"] and len(runs) == 1 and repairs == []
    assert execution_succeeded(result["sdk_calls"][0].get("result"))
    assert Path(result["outputs"][0]["path"]).read_text() == "verified"
