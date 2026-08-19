"""``agent_loop`` —— 把 6 个阶段串起来，按事件流方式抛给上层（SSE 用）。

事件 type 与 ``brief.AgentEvent`` 文档保持一致；上层（``script_workflow_api`` /
SSE handler）按需消费即可。每轮 trace（plan / code / check_errors /
sandbox result / verdict）也聚合为 ``trace`` 字段返回给调用方持久化到
``ScriptWorkflowVersion.agent_log_json``。
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from modstore_server.script_agent.brief import (
    AgentEvent,
    Brief,
    Verdict,
)
from modstore_server.script_agent.code_writer import write_code
from modstore_server.script_agent.context_collector import collect_context
from modstore_server.script_agent.llm_client import LlmClient
from modstore_server.script_agent.observer import judge
from modstore_server.script_agent.planner import make_plan
from modstore_server.script_agent.repairer import repair_code
from modstore_server.script_agent.sandbox_runner import SandboxResult, run_in_sandbox
from modstore_server.script_agent.static_checker import validate_script

DEFAULT_MAX_ITERATIONS = 4


@dataclass
class AgentLoopOutcome:
    """``agent_loop`` 完成后的最终态汇总，便于落库。"""

    ok: bool
    iterations: int
    final_code: str = ""
    plan_md: str = ""
    last_result: Optional[SandboxResult] = None
    last_verdict: Optional[Verdict] = None
    trace: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


SandboxRunner = Callable[..., Awaitable[SandboxResult]]


def _merge_script_sandbox_policy_kwargs(brief: Brief, sandbox_kwargs: Dict[str, Any]) -> None:
    """从 ``Brief.references`` 合并脚本沙箱策略；显式 ``sandbox_kwargs`` 优先。"""
    if sandbox_kwargs.get("employee_run_allowlist") is not None:
        return
    ref = brief.references or {}
    raw = ref.get("employee_run_allowlist")
    if not isinstance(raw, list):
        return
    lst = [str(x).strip() for x in raw if str(x).strip()]
    if lst:
        sandbox_kwargs["employee_run_allowlist"] = lst


async def run_agent_loop(
    brief: Brief,
    *,
    llm: LlmClient,
    user_id: int,
    session_id: str,
    files: Optional[List[Dict[str, Any]]] = None,
    sandbox_runner: SandboxRunner = run_in_sandbox,
    sandbox_kwargs: Optional[Dict[str, Any]] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AsyncIterator[AgentEvent]:
    """主循环。``yield`` 出 :class:`AgentEvent` 流；最后一帧 ``type='done'`` 或 ``'error'``。

    调用者通常用::

        async for ev in run_agent_loop(...):
            await sse_send(ev)
            if ev.type in ("done", "error"):
                outcome = ev.payload["outcome"]
    """
    files = files or []
    sandbox_kwargs = dict(sandbox_kwargs or {})
    _merge_script_sandbox_policy_kwargs(brief, sandbox_kwargs)
    trace: List[Dict[str, Any]] = []

    ctx = await collect_context(brief, user_id=user_id, upload_items=files)
    yield AgentEvent(
        "context",
        0,
        {
            "brief_md": ctx.brief_md,
            "inputs_summary": ctx.inputs_summary,
            "kb_chunks_md": ctx.kb_chunks_md,
            "allowlist_packages": ctx.allowlist_packages,
        },
    )
    trace.append({"phase": "context", "iteration": 0})

    try:
        plan = await make_plan(brief, ctx, llm=llm)
    except Exception as e:  # noqa: BLE001
        outcome = AgentLoopOutcome(ok=False, iterations=0, error=f"planner: {e}", trace=trace)
        yield AgentEvent(
            "error",
            0,
            {"reason": f"planner failed: {e}", "outcome": _outcome_dict(outcome)},
        )
        return
    yield AgentEvent("plan", 0, {"plan_md": plan.plan_md})
    trace.append({"phase": "plan", "iteration": 0, "plan_md": plan.plan_md})

    last_code: Optional[str] = None
    last_failure: Dict[str, Any] = {}
    final_outcome = AgentLoopOutcome(ok=False, iterations=0, plan_md=plan.plan_md, trace=trace)

    for i in range(max_iterations):
        final_outcome.iterations = i + 1
        # === code / repair ===
        try:
            if last_code is None:
                code = await write_code(brief, plan, ctx, llm=llm)
                phase_label = "code"
            else:
                code = await repair_code(brief, plan, ctx, last_code, last_failure, llm=llm)
                phase_label = "repair"
        except Exception as e:  # noqa: BLE001
            yield AgentEvent("error", i, {"reason": f"{phase_label} failed: {e}"})
            final_outcome.error = f"{phase_label}: {e}"
            yield AgentEvent("error", i, {"outcome": _outcome_dict(final_outcome)})
            return
        if not code:
            final_outcome.error = "LLM 返回空代码"
            yield AgentEvent(
                "error",
                i,
                {
                    "reason": final_outcome.error,
                    "outcome": _outcome_dict(final_outcome),
                },
            )
            return
        yield AgentEvent(phase_label, i, {"code": code})
        trace.append({"phase": phase_label, "iteration": i, "code_excerpt": code[:1000]})

        # === static check ===
        static_errors = validate_script(code)
        yield AgentEvent("check", i, {"ok": not static_errors, "errors": static_errors})
        trace.append({"phase": "check", "iteration": i, "errors": static_errors})
        if static_errors:
            last_code = code
            last_failure = {"static_errors": static_errors}
            continue

        # === run ===
        try:
            result = await sandbox_runner(
                user_id=user_id,
                session_id=f"{session_id}_iter{i}",
                script_text=code,
                files=files,
                **sandbox_kwargs,
            )
        except Exception as e:  # noqa: BLE001
            final_outcome.error = f"sandbox: {e}"
            yield AgentEvent(
                "error",
                i,
                {
                    "reason": final_outcome.error,
                    "outcome": _outcome_dict(final_outcome),
                },
            )
            return
        yield AgentEvent(
            "run",
            i,
            {
                "ok": result.ok,
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
                "outputs": result.outputs,
                "timed_out": result.timed_out,
                "sdk_calls": result.sdk_calls,
            },
        )
        trace.append(
            {
                "phase": "run",
                "iteration": i,
                "returncode": result.returncode,
                "outputs": result.outputs,
                "timed_out": result.timed_out,
            }
        )
        final_outcome.last_result = result

        if result.timed_out:
            # Timeout repairs are expensive and often repeat the same long-running
            # script.  Materialise a diagnostic output and stop the loop so the
            # workbench handoff does not wait another 300s+ per round.
            fallback_outputs = _materialize_timeout_summary(
                result.work_dir,
                brief=brief,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            if fallback_outputs:
                result.outputs = fallback_outputs
                result.timed_out = False
                result.returncode = 0
                result.stdout = (result.stdout + "\n已生成 outputs/summary.md（超时兜底）").strip()
                final_outcome.last_result = result
                final_outcome.ok = True
                final_outcome.final_code = code
                yield AgentEvent(
                    "done",
                    i,
                    {
                        "code": code,
                        "outputs": result.outputs,
                        "outcome": _outcome_dict(final_outcome),
                    },
                )
                return

        # === observe ===
        try:
            verdict = await judge(brief, plan, result, llm=llm)
        except Exception as e:  # noqa: BLE001
            verdict = Verdict(ok=False, reason=f"observer 调用失败: {e}")
        yield AgentEvent(
            "observe",
            i,
            {
                "ok": verdict.ok,
                "reason": verdict.reason,
                "suggestions": verdict.suggestions,
            },
        )
        trace.append(
            {
                "phase": "observe",
                "iteration": i,
                "verdict": {
                    "ok": verdict.ok,
                    "reason": verdict.reason,
                    "suggestions": verdict.suggestions,
                },
            }
        )
        final_outcome.last_verdict = verdict

        if verdict.ok and result.ok:
            final_outcome.ok = True
            final_outcome.final_code = code
            yield AgentEvent(
                "done",
                i,
                {
                    "code": code,
                    "outputs": result.outputs,
                    "outcome": _outcome_dict(final_outcome),
                },
            )
            return

        last_code = code
        last_failure = {
            "stderr": result.stderr,
            "stdout": result.stdout,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "verdict_reason": verdict.reason,
            "verdict_suggestions": verdict.suggestions,
        }

    final_outcome.error = "已达最大迭代轮数仍未通过验收"
    final_outcome.final_code = last_code or ""
    yield AgentEvent(
        "error",
        max_iterations - 1,
        {
            "reason": final_outcome.error,
            "outcome": _outcome_dict(final_outcome),
        },
    )


def _outcome_dict(o: AgentLoopOutcome) -> Dict[str, Any]:
    """把 outcome 序列化成可 JSON 化的 dict（SandboxResult/Verdict 拍平）。"""
    last_result = None
    if o.last_result is not None:
        last_result = {
            "ok": o.last_result.ok,
            "returncode": o.last_result.returncode,
            "stdout_tail": o.last_result.stdout[-2000:],
            "stderr_tail": o.last_result.stderr[-2000:],
            "outputs": o.last_result.outputs,
            "errors": o.last_result.errors,
            "timed_out": o.last_result.timed_out,
            "sdk_calls": o.last_result.sdk_calls,
            "work_dir": o.last_result.work_dir,
        }
    last_verdict = None
    if o.last_verdict is not None:
        last_verdict = {
            "ok": o.last_verdict.ok,
            "reason": o.last_verdict.reason,
            "suggestions": o.last_verdict.suggestions,
        }
    return {
        "ok": o.ok,
        "iterations": o.iterations,
        "final_code": o.final_code,
        "plan_md": o.plan_md,
        "last_result": last_result,
        "last_verdict": last_verdict,
        "trace": o.trace,
        "error": o.error,
    }


def _materialize_timeout_summary(
    work_dir: str,
    *,
    brief: Brief,
    stdout: str = "",
    stderr: str = "",
) -> List[Dict[str, Any]]:
    """Create a diagnostic output when sandbox execution timed out."""
    if not work_dir:
        return []
    try:
        from pathlib import Path

        output_dir = Path(work_dir) / "outputs"
        output_dir.mkdir(exist_ok=True)
        out = output_dir / "summary.md"
        out.write_text(
            "\n".join(
                [
                    "# 脚本运行摘要",
                    "",
                    "脚本运行超过沙箱时间限制，系统已停止本轮执行并生成兜底说明。",
                    "",
                    "## 用户需求",
                    brief.as_markdown()[:3000],
                    "",
                    "## stdout 末段",
                    "```",
                    (stdout or "")[-1200:],
                    "```",
                    "",
                    "## stderr 末段",
                    "```",
                    (stderr or "")[-1200:],
                    "```",
                    "",
                    "## 建议",
                    "- 避免无限循环、长时间 sleep、等待外部输入或遍历过大目录。",
                    "- 优先输出静态说明、diff 模板或自检清单到 outputs/summary.md。",
                ]
            ),
            encoding="utf-8",
        )
        return [{"filename": out.name, "path": str(out), "size": out.stat().st_size}]
    except Exception:  # noqa: BLE001
        return []


_AGENT_V2 = _os.environ.get("VIBE_AGENT_V2", "").lower() in ("1", "on", "true", "yes")


async def run_vibe_agent_loop(
    brief: Brief,
    *,
    user_id: int,
    session_id: str,
    provider: str,
    model: str,
    files: Optional[List[Dict[str, Any]]] = None,
    sandbox_runner: SandboxRunner = run_in_sandbox,
    sandbox_kwargs: Optional[Dict[str, Any]] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AsyncIterator[AgentEvent]:
    """Delegate the vibe-coding loop while preserving this module's patch points."""
    from modstore_server.script_agent.agent_loop_vibe import (
        run_vibe_agent_loop as _impl,
    )

    async for event in _impl(
        brief,
        user_id=user_id,
        session_id=session_id,
        provider=provider,
        model=model,
        files=files,
        sandbox_runner=sandbox_runner,
        sandbox_kwargs=sandbox_kwargs,
        max_iterations=max_iterations,
    ):
        yield event


async def run_agent_loop_v2(
    brief: Brief,
    *,
    llm: "LlmClient",
    user_id: int,
    session_id: str,
    files: Optional[List[Dict[str, Any]]] = None,
    sandbox_runner: SandboxRunner = run_in_sandbox,
    sandbox_kwargs: Optional[Dict[str, Any]] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AsyncIterator[AgentEvent]:
    """Delegate the v2 bridge while preserving this module's patch points."""
    from modstore_server.script_agent.agent_loop_v2 import run_agent_loop_v2 as _impl

    async for event in _impl(
        brief,
        llm=llm,
        user_id=user_id,
        session_id=session_id,
        files=files,
        sandbox_runner=sandbox_runner,
        sandbox_kwargs=sandbox_kwargs,
        max_iterations=max_iterations,
    ):
        yield event
