"""测试 :func:`script_agent.agent_loop.run_vibe_agent_loop`。

mock 掉 vibe-coding 的 ``VibeCoder.code`` / ``code_factory.repair``,验证:
- 成功路径首轮通过即 ``done``。
- 沙箱失败 → 第二轮调用 ``code_factory.repair``。
- vibe-coding 缺失时 first frame 是 ``error``。
"""

from __future__ import annotations

import asyncio
import importlib.util
from typing import Any, AsyncIterator, Dict, List

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过 vibe agent loop 测试", allow_module_level=True)

from modstore_server.script_agent.brief import Brief, BriefInputFile, Verdict
from modstore_server.script_agent.sandbox_runner import SandboxResult


def _brief() -> Brief:
    return Brief(
        goal="计算 inputs/data.csv 的列总和",
        outputs="outputs/result.json {total:int}",
        acceptance="outputs/result.json 存在且 total > 0",
        inputs=[BriefInputFile(filename="data.csv", description="数据")],
    )


def _make_sandbox_result(**overrides) -> SandboxResult:
    base = {
        "ok": True,
        "work_dir": "/tmp/sandbox_stub",
        "returncode": 0,
        "stdout": "ok",
        "stderr": "",
        "outputs": [],
        "errors": [],
        "timed_out": False,
    }
    base.update(overrides)
    return SandboxResult(**base)


def _good_sandbox(**_kwargs):
    async def _runner(*args, **kw) -> SandboxResult:
        return _make_sandbox_result()

    return _runner


def _bad_then_good_sandbox():
    calls = {"n": 0}

    async def _runner(*args, **kw) -> SandboxResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return _make_sandbox_result(
                ok=False, returncode=1, stdout="", stderr="ZeroDivisionError", errors=["err"]
            )
        return _make_sandbox_result()

    return _runner, calls


class _StubSkill:
    def __init__(self, skill_id: str = "vc-skill-1", code: str = "print('ok')"):
        self.skill_id = skill_id
        self.code = code


class _StubFactory:
    def __init__(self):
        self.repair_called_with: Dict[str, Any] = {}

    def repair(self, skill_id, failure):
        self.repair_called_with = {"skill_id": skill_id, "failure": dict(failure)}
        return _StubSkill(skill_id=skill_id, code="print('repaired')\n")


class _StubCoder:
    def __init__(self):
        self.code_factory = _StubFactory()
        self.calls: List[Dict[str, Any]] = []

    def code(self, brief: str, *, mode: str = "brief_first", skill_id=None):
        self.calls.append({"brief": brief, "mode": mode, "skill_id": skill_id})
        return _StubSkill(skill_id=skill_id or "vc-skill-1", code="print('first')\n")


@pytest.fixture
def stub_coder(monkeypatch):
    coder = _StubCoder()
    monkeypatch.setattr(
        "modstore_server.integrations.vibe_adapter.get_vibe_coder",
        lambda **kw: coder,
    )
    return coder


@pytest.fixture(autouse=True)
def stub_collect_context(monkeypatch):
    from modstore_server.script_agent.brief import ContextBundle

    async def _ctx(brief, *, user_id, upload_items=None, **kwargs):
        return ContextBundle(
            brief_md=brief.goal or "",
            inputs_summary="",
            kb_chunks_md="",
            allowlist_packages=[],
        )

    monkeypatch.setattr("modstore_server.script_agent.agent_loop.collect_context", _ctx)


@pytest.fixture(autouse=True)
def stub_judge(monkeypatch):
    async def _judge(brief, plan, result, *, llm):
        return Verdict(ok=bool(result.ok), reason="ok" if result.ok else "fail", suggestions=[])

    monkeypatch.setattr("modstore_server.script_agent.agent_loop.judge", _judge)


def _collect(events):
    out = []

    async def _run():
        async for ev in events:
            out.append(ev)

    asyncio.run(_run())
    return out


def test_vibe_loop_first_round_done(monkeypatch, stub_coder):
    from modstore_server.script_agent.agent_loop import run_vibe_agent_loop

    runner = _good_sandbox()
    monkeypatch.setattr("modstore_server.script_agent.agent_loop.validate_script", lambda code: [])

    events = _collect(
        run_vibe_agent_loop(
            _brief(),
            user_id=1,
            session_id="sess",
            provider="openai",
            model="gpt-4o-mini",
            sandbox_runner=runner,
            max_iterations=2,
        )
    )
    types = [ev.type for ev in events]
    assert "code" in types
    assert "done" in types
    assert stub_coder.code_factory.repair_called_with == {}


def test_vibe_loop_repair_after_sandbox_failure(monkeypatch, stub_coder):
    from modstore_server.script_agent.agent_loop import run_vibe_agent_loop

    runner, _calls = _bad_then_good_sandbox()
    monkeypatch.setattr("modstore_server.script_agent.agent_loop.validate_script", lambda code: [])

    events = _collect(
        run_vibe_agent_loop(
            _brief(),
            user_id=1,
            session_id="sess",
            provider="openai",
            model="gpt-4o-mini",
            sandbox_runner=runner,
            max_iterations=3,
        )
    )
    types = [ev.type for ev in events]
    assert types[-1] == "done"
    assert stub_coder.code_factory.repair_called_with["skill_id"]
    assert "ZeroDivisionError" in stub_coder.code_factory.repair_called_with["failure"]["stderr"]


def test_vibe_loop_errors_when_coder_construction_fails(monkeypatch):
    from modstore_server.integrations.vibe_adapter import VibeIntegrationError
    from modstore_server.script_agent.agent_loop import run_vibe_agent_loop

    def _boom(**kw):
        raise VibeIntegrationError("vibe-coding 未安装")

    monkeypatch.setattr("modstore_server.integrations.vibe_adapter.get_vibe_coder", _boom)

    events = _collect(
        run_vibe_agent_loop(
            _brief(),
            user_id=1,
            session_id="sess",
            provider="openai",
            model="gpt-4o-mini",
            sandbox_runner=_good_sandbox(),
        )
    )
    assert events[-1].type == "error"
    assert any("vibe-coding 未安装" in str(ev.payload) for ev in events)
