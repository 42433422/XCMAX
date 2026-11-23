"""``script_agent.agent_loop`` 端到端单测：mock LLM + mock sandbox。

覆盖路径：
- happy path：第一轮直接通过
- 静检失败 → 第二轮修复通过
- 运行失败 → 第二轮修复通过
- 验收不通过 → 第二轮修复通过
- 达上限仍失败 → ``error`` 事件
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

import pytest

from modstore_server.script_agent.agent_loop import (
    DEFAULT_MAX_ITERATIONS,
    run_agent_loop,
)
from modstore_server.script_agent.brief import Brief, BriefInputFile
from modstore_server.script_agent.llm_client import StubLlmClient
from modstore_server.script_agent.sandbox_runner import SandboxResult


def _brief() -> Brief:
    return Brief(
        goal="把 inputs/data.csv 汇总成 outputs/result.json",
        outputs="outputs/result.json，包含 total 字段（int）",
        acceptance="outputs/result.json 存在且 'total' 为非负整数",
        inputs=[BriefInputFile(filename="data.csv", description="销售数据")],
    )


def _good_code() -> str:
    return (
        "from pathlib import Path\n"
        "import json\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "Path('outputs/result.json').write_text(json.dumps({'total': 3}))\n"
        "print('done')\n"
    )


def _bad_code() -> str:
    """带禁用 import，会被静检拦截。"""
    return (
        "import subprocess\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "subprocess.run(['true'])\n"
    )


def _ok_result(outputs: List[Dict[str, Any]] | None = None) -> SandboxResult:
    return SandboxResult(
        ok=True,
        work_dir="/tmp/x",
        returncode=0,
        stdout="done\n",
        stderr="",
        outputs=outputs
        or [
            {
                "filename": "result.json",
                "path": "/tmp/x/outputs/result.json",
                "size": 16,
            }
        ],
        errors=[],
        timed_out=False,
    )


def _failed_result() -> SandboxResult:
    return SandboxResult(
        ok=False,
        work_dir="/tmp/x",
        returncode=1,
        stdout="",
        stderr="boom",
        outputs=[],
        errors=["boom"],
        timed_out=False,
    )


def _make_runner(
    results: List[SandboxResult],
) -> Callable[..., Awaitable[SandboxResult]]:
    """按顺序返回一组 SandboxResult 的 mock runner。"""
    queue = list(results)

    async def fake(**kwargs: Any) -> SandboxResult:
        if not queue:
            raise AssertionError("mock sandbox runner: 预设结果耗尽")
        return queue.pop(0)

    return fake


async def _drain(brief: Brief, llm: StubLlmClient, runner) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    async for ev in run_agent_loop(
        brief,
        llm=llm,
        user_id=42,
        session_id="ut",
        files=[],
        sandbox_runner=runner,
    ):
        events.append({"type": ev.type, "iteration": ev.iteration, "payload": ev.payload})
    return events


@pytest.mark.asyncio
async def test_happy_path_first_iteration_passes(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.script_agent.context_collector.collect_context",
        _stub_collect_context,
    )
    llm = StubLlmClient(
        [
            "## 计划\n1. 读取 csv\n2. 汇总\n3. 写 result.json\n验收: outputs/result.json 存在",
            f"```python\n{_good_code()}```",
            '{"ok": true, "reason": "outputs 已生成", "suggestions": []}',
        ]
    )
    runner = _make_runner([_ok_result()])
    events = await _drain(_brief(), llm, runner)
    types = [e["type"] for e in events]
    assert types == ["context", "plan", "code", "check", "run", "observe", "done"]
    done = events[-1]
    assert done["payload"]["outcome"]["ok"] is True
    assert done["payload"]["outcome"]["iterations"] == 1


@pytest.mark.asyncio
async def test_static_check_fails_then_repair_succeeds(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.script_agent.context_collector.collect_context",
        _stub_collect_context,
    )
    llm = StubLlmClient(
        [
            "plan",
            f"```python\n{_bad_code()}```",  # iter 0 code: bad
            f"```python\n{_good_code()}```",  # iter 1 repair
            '{"ok": true, "reason": "ok", "suggestions": []}',  # iter 1 observe
        ]
    )
    runner = _make_runner([_ok_result()])
    events = await _drain(_brief(), llm, runner)
    types = [e["type"] for e in events]
    # 第 0 轮：context, plan, code, check(fail) ；第 1 轮：repair, check(pass), run, observe, done
    assert types == [
        "context",
        "plan",
        "code",
        "check",
        "repair",
        "check",
        "run",
        "observe",
        "done",
    ]
    check_events = [e for e in events if e["type"] == "check"]
    assert check_events[0]["payload"]["ok"] is False
    assert check_events[1]["payload"]["ok"] is True


@pytest.mark.asyncio
async def test_run_fails_then_repair_succeeds(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.script_agent.context_collector.collect_context",
        _stub_collect_context,
    )
    llm = StubLlmClient(
        [
            "plan",
            f"```python\n{_good_code()}```",  # iter 0 code
            f"```python\n{_good_code()}```",  # iter 1 repair
            '{"ok": true, "reason": "ok"}',  # iter 1 observe
        ]
    )
    runner = _make_runner([_failed_result(), _ok_result()])
    events = await _drain(_brief(), llm, runner)
    # 当首轮 returncode!=0，observer 直接判 fail（短路），不调 LLM；
    # 因此 LLM 队列里 "iter 0 observe" 那条不需要
    types = [e["type"] for e in events]
    assert types == [
        "context",
        "plan",
        "code",
        "check",
        "run",
        "observe",
        "repair",
        "check",
        "run",
        "observe",
        "done",
    ]
    runs = [e for e in events if e["type"] == "run"]
    assert runs[0]["payload"]["ok"] is False
    assert runs[1]["payload"]["ok"] is True


@pytest.mark.asyncio
async def test_observer_rejects_then_repair_succeeds(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.script_agent.context_collector.collect_context",
        _stub_collect_context,
    )
    llm = StubLlmClient(
        [
            "plan",
            f"```python\n{_good_code()}```",  # iter 0 code
            '{"ok": false, "reason": "字段缺失", "suggestions": ["补 total"]}',  # iter 0 observe
            f"```python\n{_good_code()}```",  # iter 1 repair
            '{"ok": true, "reason": "ok"}',  # iter 1 observe
        ]
    )
    runner = _make_runner([_ok_result(), _ok_result()])
    events = await _drain(_brief(), llm, runner)
    observes = [e for e in events if e["type"] == "observe"]
    assert observes[0]["payload"]["ok"] is False
    assert observes[1]["payload"]["ok"] is True
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_max_iterations_yields_error(monkeypatch):
    monkeypatch.setattr(
        "modstore_server.script_agent.context_collector.collect_context",
        _stub_collect_context,
    )
    # 每轮都会运行失败（returncode != 0），observer 短路 → 走修复
    # 4 轮 = 1 次 code + 3 次 repair；每轮各 1 次 LLM
    llm = StubLlmClient(
        [
            "plan",
            f"```python\n{_good_code()}```",
            f"```python\n{_good_code()}```",
            f"```python\n{_good_code()}```",
            f"```python\n{_good_code()}```",
        ]
    )
    runner = _make_runner([_failed_result()] * DEFAULT_MAX_ITERATIONS)
    events = await _drain(_brief(), llm, runner)
    assert events[-1]["type"] == "error"
    assert "最大迭代" in events[-1]["payload"]["reason"]
    outcome = events[-1]["payload"]["outcome"]
    assert outcome["ok"] is False
    assert outcome["iterations"] == DEFAULT_MAX_ITERATIONS


# --- helpers ---


async def _stub_collect_context(brief, *, user_id, extra_kb_queries=()):
    """Patch 用：跳过真实 RAG，返回最小 ContextBundle。"""
    from modstore_server.script_agent.brief import ContextBundle

    return ContextBundle(
        brief_md=brief.as_markdown(),
        inputs_summary="(stub)",
        kb_chunks_md="",
        sdk_doc="",
        allowlist_packages=["openpyxl"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "timeout_with_workdir",
        "timeout_without_workdir",
        "employee_transport_only",
        "employee_completed_rejected",
        "employee_completed_observer_error",
        "nested_unknown",
        "nonretryable_sdk",
        "runner_exception",
        "runner_exception_after_safe_failure",
    ],
)
async def test_unsafe_result_is_not_replayed_or_reported_as_success(monkeypatch, tmp_path, case):
    from modstore_server.script_agent import agent_loop as loop
    from modstore_server.script_agent.brief import PlanResult, Verdict

    async def context(brief, **kwargs):
        return await _stub_collect_context(brief, user_id=42)

    async def plan(*args, **kwargs):
        return PlanResult(plan_md="write result")

    async def code(*args, **kwargs):
        return _good_code()

    async def observe(*args, **kwargs):
        if case == "employee_completed_observer_error":
            raise RuntimeError("observer unavailable")
        return Verdict(ok=case == "employee_transport_only", reason="not verified")

    monkeypatch.setattr(loop, "collect_context", context)
    monkeypatch.setattr(loop, "make_plan", plan)
    monkeypatch.setattr(loop, "write_code", code)
    monkeypatch.setattr(loop, "repair_code", code)
    monkeypatch.setattr(loop, "judge", observe)
    result = _ok_result()
    result.work_dir = str(tmp_path)
    if case.startswith("timeout"):
        result.ok = False
        result.timed_out = True
        result.returncode = -9
        result.outputs = []
        result.errors = ["script timed out"]
        if case == "timeout_without_workdir":
            result.work_dir = ""
    elif case.startswith("employee"):
        result.sdk_calls = [{"method": "employee_run", "ok": True}]
        if case != "employee_transport_only":
            result.sdk_calls[0]["result"] = {
                "ok": True,
                "status": "completed",
                "task_id": "original-task",
            }
    elif case == "nested_unknown":
        result.sdk_calls = [{"method": "ai", "ok": True, "result": {"outcome": "unknown"}}]
    elif case == "nonretryable_sdk":
        result.sdk_calls = [{"method": "ai", "ok": False, "retryable": False}]

    calls = 0

    async def runner(**kwargs):
        nonlocal calls
        calls += 1
        if case == "runner_exception_after_safe_failure" and calls == 1:
            return _failed_result()
        if case.startswith("runner_exception"):
            raise TimeoutError("runner acknowledgement lost")
        return result

    events = [
        event
        async for event in loop.run_agent_loop(
            _brief(),
            llm=StubLlmClient([]),
            user_id=42,
            session_id="no-replay",
            sandbox_runner=runner,
            max_iterations=3,
        )
    ]
    assert calls == (2 if case == "runner_exception_after_safe_failure" else 1)
    assert events[-1].type == "error"
    outcome = events[-1].payload["outcome"]
    assert outcome["ok"] is False
    assert outcome["outcome"] == "unverified"
    assert outcome["retryable"] is False
    assert outcome["final_code"] == _good_code()
    if case.startswith("runner_exception"):
        assert outcome["last_result"] is None
        assert outcome["last_verdict"] is None
    else:
        receipt = outcome["last_result"]
        assert receipt["returncode"] == result.returncode
        assert receipt["timed_out"] is result.timed_out
        assert receipt["sdk_calls"] == result.sdk_calls
        if case.startswith("timeout"):
            assert receipt["timed_out"] is True
            assert receipt["returncode"] == -9
            assert not (tmp_path / "outputs" / "summary.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "completed",
        "accepted",
        "running",
        "unknown",
        "invalid_type",
        "rejected",
        "timeout",
        "denied",
        "rpc_error",
        "failed_output",
        "failed_status_output",
    ],
)
async def test_v1_real_rpc_receipt_preserves_effect_identity_and_privacy(
    monkeypatch, tmp_path, case
):
    import json
    import time
    from pathlib import Path
    from types import SimpleNamespace

    from modstore_server.script_agent import agent_loop as loop
    from modstore_server.script_agent.sandbox_runner import run_in_sandbox

    async def context(brief, **kwargs):
        return await _stub_collect_context(brief, user_id=42)

    monkeypatch.setattr(loop, "collect_context", context)
    effects = []
    business = {
        "ok": True,
        "result": {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "ok": True,
                    "accepted": True,
                    "completed": True,
                    "para_task_id": "original-task",
                    "para_result": {
                        "task": {"id": "original-task", "private_text": "secret-business"}
                    },
                },
                {"handler": "echo", "text": "secret-business"},
            ],
            "private_text": "secret-business",
        },
    }
    if case in {"accepted", "running", "unknown"}:
        business = {
            "ok": True,
            "status": case,
            "accepted": True,
            "task_id": "original-task",
            "private_text": "secret-business",
        }
    elif case == "invalid_type":
        business = {
            "ok": True,
            "status": "completed",
            "accepted": "false",
            "task_id": "original-task",
        }
    elif case in {"failed_output", "failed_status_output"}:
        failed = (
            {"ok": False, "error": "secret-business"}
            if case == "failed_output"
            else {"status": "failed"}
        )
        business = {"ok": True, "outputs": [{**failed, "task_id": "original-task"}]}

    def execute_task(**kwargs):
        effects.append(kwargs)
        if case == "rpc_error":
            raise RuntimeError("secret-business")
        if case == "timeout":
            time.sleep(2)
        return business

    monkeypatch.setattr(
        "modstore_server.services.employee.get_default_employee_client",
        lambda: SimpleNamespace(execute_task=execute_task),
    )
    code = (
        "from pathlib import Path\n"
        "from modstore_runtime import employee_run\n"
        "employee_run('worker', 'apply', payload={'user_id': 999})\n"
        "Path('outputs/result.json').write_text('{\"total\": 3}')\n"
    )
    llm = StubLlmClient(
        [
            "produce result",
            f"```python\n{code}```",
            json.dumps({"ok": case != "rejected", "reason": "checked actual output"}),
        ]
    )
    events = [
        event
        async for event in loop.run_agent_loop(
            _brief(),
            llm=llm,
            user_id=42,
            session_id="real-v1-rpc",
            sandbox_runner=run_in_sandbox,
            sandbox_kwargs={
                "script_root": tmp_path,
                "timeout_seconds": 1 if case == "timeout" else 5,
                "employee_run_allowlist": ["other-worker"] if case == "denied" else ["worker"],
            },
        )
    ]
    assert len(effects) == (0 if case == "denied" else 1)
    if effects:
        assert effects[0]["user_id"] == 42
        assert effects[0]["input_data"] == {"user_id": 999}
    outcome = events[-1].payload["outcome"]
    receipt = outcome["last_result"]
    assert len(receipt["sdk_calls"]) == 1
    assert "secret-business" not in json.dumps(outcome)
    if case == "completed":
        assert events[-1].type == "done" and outcome["ok"] is True
        assert outcome["last_verdict"]["ok"] is True
        assert Path(receipt["outputs"][0]["path"]).read_text() == '{"total": 3}'
        assert (
            receipt["sdk_calls"][0]["result"]["result"]["outputs"][0]["para_task_id"]
            == "original-task"
        )
    else:
        assert events[-1].type == "error" and outcome["ok"] is False
        assert outcome["outcome"] == "unverified" and outcome["retryable"] is False
        if case == "timeout":
            assert receipt["timed_out"] is True and receipt["returncode"] != 0
        elif case == "rpc_error":
            assert receipt["sdk_calls"][0]["outcome"] == "unknown"
            assert receipt["sdk_calls"][0]["error"] == "RuntimeError"
            assert "employee_run failed (RuntimeError)" in receipt["stderr_tail"]
        elif case != "denied":
            assert "original-task" in json.dumps(receipt["sdk_calls"])
