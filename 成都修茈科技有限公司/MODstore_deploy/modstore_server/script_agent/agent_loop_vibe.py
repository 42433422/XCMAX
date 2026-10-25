# mypy: disable-error-code="operator"
"""Vibe-coding implementation for the script-agent compatibility facade."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any, AsyncIterator, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.script_agent.brief import AgentEvent, Brief
from modstore_server.script_agent.sandbox_runner import run_in_sandbox

DEFAULT_MAX_ITERATIONS = 4
SandboxRunner = object


def _facade():
    return importlib.import_module("modstore_server.script_agent.agent_loop")


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
    """vibe-coding 驱动版的 agent loop。

    与 :func:`run_agent_loop` 行为对齐(同样的 :class:`AgentEvent` 流、SSE 兼容);
    内部:

    1. 用 ``vibe_coding.NLCodeSkillFactory`` 一次生成 brief→code(brief_first 自带
       内部沙盒校验,失败会抛 :class:`VibeCodingError`)。
    2. 把生成的代码丢给 MODstore 的 :func:`run_in_sandbox` 跑用户上传的样本文件,
       因为 vibe-coding 的内部沙盒不知道 ``ctx['files']`` 这套约定。
    3. 如果运行失败,把 stderr / observer verdict 反馈给 vibe-coding 的
       ``code_factory.repair`` 走多轮修复。
    4. PatchLedger / CodeStore 自动保留补丁链,可在工作台沙箱报告里回看。

    任何 vibe-coding 缺失/构造失败都会立刻 ``yield`` 一帧 ``error`` 并退出,
    上层 SSE 消费者按通用错误处理即可。
    """
    files = files or []
    sandbox_kwargs = dict(sandbox_kwargs or {})
    _facade()._merge_script_sandbox_policy_kwargs(brief, sandbox_kwargs)
    trace: List[Dict[str, Any]] = []
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_vibe_coder,
        )
    except ImportError as exc:
        outcome = _facade().AgentLoopOutcome(
            ok=False, iterations=0, error=f"integrations 未导入: {exc}", trace=trace
        )
        yield _facade().AgentEvent(
            "error",
            0,
            {"reason": str(outcome.error), "outcome": _facade()._outcome_dict(outcome)},
        )
        return
    ctx = await _facade().collect_context(brief, user_id=user_id, upload_items=files)
    yield _facade().AgentEvent(
        "context",
        0,
        {
            "brief_md": ctx.brief_md,
            "inputs_summary": ctx.inputs_summary,
            "kb_chunks_md": ctx.kb_chunks_md,
            "allowlist_packages": ctx.allowlist_packages,
        },
    )
    trace.append({"phase": "context", "iteration": 0, "engine": "vibe"})
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    coder = None
    try:
        with sf() as session:
            coder = get_vibe_coder(
                session=session,
                user_id=int(user_id or 0),
                provider=provider,
                model=model,
            )
    except VibeIntegrationError as exc:
        outcome = _facade().AgentLoopOutcome(ok=False, iterations=0, error=str(exc), trace=trace)
        yield _facade().AgentEvent(
            "error",
            0,
            {"reason": str(exc), "outcome": _facade()._outcome_dict(outcome)},
        )
        return
    except RECOVERABLE_ERRORS as exc:
        outcome = _facade().AgentLoopOutcome(
            ok=False, iterations=0, error=f"vibe coder 构造失败: {exc}", trace=trace
        )
        yield _facade().AgentEvent(
            "error",
            0,
            {"reason": str(outcome.error), "outcome": _facade()._outcome_dict(outcome)},
        )
        return
    yield _facade().AgentEvent("plan", 0, {"plan_md": ctx.brief_md or brief.goal or ""})
    trace.append({"phase": "plan", "iteration": 0, "engine": "vibe"})
    last_skill = None
    last_failure: Dict[str, Any] = {}
    final_outcome = _facade().AgentLoopOutcome(
        ok=False, iterations=0, plan_md=ctx.brief_md or brief.goal or "", trace=trace
    )
    brief_text = (ctx.brief_md or brief.goal or "").strip()
    skill_id_hint: Optional[str] = f"script_{session_id}" if session_id else None
    for i in range(max_iterations):
        final_outcome.iterations = i + 1
        try:
            if last_skill is None:
                skill = await asyncio.to_thread(
                    coder.code, brief_text, mode="brief_first", skill_id=skill_id_hint
                )
                phase_label = "code"
            else:
                failure_blob = {
                    "stderr": last_failure.get("stderr") or "",
                    "stdout": last_failure.get("stdout") or "",
                    "verdict_reason": last_failure.get("verdict_reason") or "",
                    "verdict_suggestions": last_failure.get("verdict_suggestions") or [],
                }
                skill = await asyncio.to_thread(
                    coder.code_factory.repair,
                    skill_id_hint or last_skill.skill_id,
                    failure_blob,
                )
                phase_label = "repair"
        except RECOVERABLE_ERRORS as exc:
            yield _facade().AgentEvent("error", i, {"reason": f"vibe {phase_label} failed: {exc}"})
            final_outcome.error = f"vibe {phase_label}: {exc}"
            yield _facade().AgentEvent(
                "error", i, {"outcome": _facade()._outcome_dict(final_outcome)}
            )
            return
        code = (getattr(skill, "code", "") or "").strip()
        if not code:
            final_outcome.error = "vibe-coding 返回空代码"
            yield _facade().AgentEvent(
                "error",
                i,
                {
                    "reason": final_outcome.error,
                    "outcome": _facade()._outcome_dict(final_outcome),
                },
            )
            return
        last_skill = skill
        skill_id_hint = getattr(skill, "skill_id", None) or skill_id_hint
        yield _facade().AgentEvent(phase_label, i, {"code": code, "skill_id": skill_id_hint})
        trace.append(
            {
                "phase": phase_label,
                "iteration": i,
                "engine": "vibe",
                "skill_id": skill_id_hint,
                "code_excerpt": code[:1000],
            }
        )
        static_errors = _facade().validate_script(code)
        yield _facade().AgentEvent("check", i, {"ok": not static_errors, "errors": static_errors})
        trace.append(
            {
                "phase": "check",
                "iteration": i,
                "engine": "vibe",
                "errors": static_errors,
            }
        )
        if static_errors:
            last_failure = {
                "stderr": "\n".join(static_errors),
                "stdout": "",
                "verdict_reason": "static_check_failed",
                "verdict_suggestions": [],
            }
            continue
        try:
            result = await sandbox_runner(
                user_id=user_id,
                session_id=f"{session_id}_iter{i}_vibe",
                script_text=code,
                files=files,
                **sandbox_kwargs,
            )
        except RECOVERABLE_ERRORS as exc:
            final_outcome.error = f"sandbox: {exc}"
            yield _facade().AgentEvent(
                "error",
                i,
                {
                    "reason": final_outcome.error,
                    "outcome": _facade()._outcome_dict(final_outcome),
                },
            )
            return
        yield _facade().AgentEvent(
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
                "engine": "vibe",
                "returncode": result.returncode,
                "outputs": result.outputs,
                "timed_out": result.timed_out,
            }
        )
        final_outcome.last_result = result
        if result.timed_out:
            fallback_outputs = _facade()._materialize_timeout_summary(
                result.work_dir, brief=brief, stdout=result.stdout, stderr=result.stderr
            )
            if fallback_outputs:
                result.outputs = fallback_outputs
                result.timed_out = False
                result.returncode = 0
                result.stdout = (result.stdout + "\n已生成 outputs/summary.md（超时兜底）").strip()
                final_outcome.last_result = result
                final_outcome.ok = True
                final_outcome.final_code = code
                yield _facade().AgentEvent(
                    "done",
                    i,
                    {
                        "code": code,
                        "outputs": result.outputs,
                        "skill_id": skill_id_hint,
                        "outcome": _facade()._outcome_dict(final_outcome),
                    },
                )
                return
        from modstore_server.script_agent.brief import PlanResult as _PlanResult

        plan_obj = _PlanResult(plan_md=ctx.brief_md or brief.goal or "")
        try:
            from modstore_server.script_agent.llm_client import RealLlmClient

            with sf() as judge_session:
                judge_llm = RealLlmClient.from_user_session(
                    judge_session, int(user_id or 0), provider, model
                )
                verdict = await _facade().judge(brief, plan_obj, result, llm=judge_llm)
        except RECOVERABLE_ERRORS as exc:
            verdict = _facade().Verdict(ok=False, reason=f"observer 调用失败: {exc}")
        yield _facade().AgentEvent(
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
                "engine": "vibe",
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
            yield _facade().AgentEvent(
                "done",
                i,
                {
                    "code": code,
                    "outputs": result.outputs,
                    "skill_id": skill_id_hint,
                    "outcome": _facade()._outcome_dict(final_outcome),
                },
            )
            return
        last_failure = {
            "stderr": result.stderr,
            "stdout": result.stdout,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "verdict_reason": verdict.reason,
            "verdict_suggestions": verdict.suggestions,
        }
    final_outcome.error = "vibe agent 已达最大迭代轮数仍未通过验收"
    final_outcome.final_code = getattr(last_skill, "code", "") or "" if last_skill else ""
    yield _facade().AgentEvent(
        "error",
        max_iterations - 1,
        {
            "reason": final_outcome.error,
            "outcome": _facade()._outcome_dict(final_outcome),
        },
    )
