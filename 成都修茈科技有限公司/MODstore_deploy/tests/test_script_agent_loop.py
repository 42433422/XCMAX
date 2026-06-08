"""``script_agent.agent_loop`` 端到端单测：mock LLM + mock sandbox。

覆盖路径：
- happy path：第一轮直接通过
- 静检失败 → 第二轮修复通过
- 运行失败 → 第二轮修复通过
- 验收不通过 → 第二轮修复通过
- 达上限仍失败 → ``error`` 事件
"""

from __future__ import annotations

import asyncio
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
        or [{"filename": "result.json", "path": "/tmp/x/outputs/result.json", "size": 16}],
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


def _make_runner(results: List[SandboxResult]) -> Callable[..., Awaitable[SandboxResult]]:
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
