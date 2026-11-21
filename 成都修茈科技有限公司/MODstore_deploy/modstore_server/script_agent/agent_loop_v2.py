# mypy: disable-error-code="attr-defined, import-not-found, no-any-return, operator, valid-type"
"""AgentLoop v2 event-stream bridge implementation."""

from __future__ import annotations

import importlib
from typing import Any, AsyncIterator, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.script_agent.agent_loop import AgentLoopOutcome, _outcome_dict
from modstore_server.script_agent.brief import AgentEvent, Brief, PlanResult, Verdict
from modstore_server.script_agent.llm_client import (
    SCRIPT_AGENT_CODE_MAX_TOKENS,
    LlmClient,
)
from modstore_server.script_agent.observer import judge
from modstore_server.script_agent.sandbox_runner import (
    run_in_sandbox,
    sandbox_replay_block_reason,
    sandbox_verification_error,
)

DEFAULT_MAX_ITERATIONS = 4
SandboxRunner = object


def _facade():
    return importlib.import_module("modstore_server.script_agent.agent_loop")


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
    """AgentLoop v2 shim that produces the same ``AgentEvent`` stream.

    Internally uses :class:`vibe_coding.agent.loop.AgentLoop` with:
    - Parallel read-only tool dispatch (``asyncio.gather``)
    - ``ripgrep_search`` / ``read_file_v2`` fast tools
    - ``TodoStore`` task management

    The generated code is still validated by ``validate_script`` + run via
    the existing ``sandbox_runner`` so the MODstore execution environment is
    unchanged.
    """
    files = files or []
    sandbox_kwargs = dict(sandbox_kwargs or {})
    _facade()._merge_script_sandbox_policy_kwargs(brief, sandbox_kwargs)
    trace: List[Dict[str, Any]] = []
    try:
        from vibe_coding.agent.loop import AgentLoop
    except ImportError:
        async for ev in _facade().run_agent_loop(
            brief,
            llm=llm,
            user_id=user_id,
            session_id=session_id,
            files=files,
            sandbox_runner=sandbox_runner,
            sandbox_kwargs=sandbox_kwargs,
            max_iterations=max_iterations,
        ):
            yield ev
        return

    async def _maybe_await(value: Any) -> Any:
        import inspect as _inspect

        if _inspect.isawaitable(value):
            return await value
        return value

    class _LLMBridge:
        async def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
            sys_msg = (system or "").strip()
            if json_mode:
                sys_msg = (
                    sys_msg + "\n\n" if sys_msg else ""
                ) + "Return only one valid JSON object. Do not wrap it in Markdown fences."
            msgs = []
            if sys_msg:
                msgs.append({"role": "system", "content": sys_msg})
            msgs.append({"role": "user", "content": user or ""})
            result = await _maybe_await(llm.chat(msgs, max_tokens=SCRIPT_AGENT_CODE_MAX_TOKENS))
            return str(result or "")

    ctx = await _facade().collect_context(brief, user_id=user_id, upload_items=files)
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
    trace.append({"phase": "context", "iteration": 0, "engine": "v2"})
    from vibe_coding.agent.react.tools import ToolRegistry, tool

    reg = ToolRegistry()
    outcome = AgentLoopOutcome(
        ok=False, iterations=0, plan_md=ctx.brief_md or brief.goal or "", trace=trace
    )
    executed_code = ""
    replay_blocked = ""

    @tool(
        "static_check",
        description="AST + import whitelist check for generated Python code.",
    )
    def static_check_tool(code: str) -> dict:
        errs = _facade().validate_script(code)
        return {"ok": not errs, "errors": errs}

    async def _run_sandbox(code: str) -> dict:
        nonlocal executed_code, replay_blocked
        if replay_blocked:
            outcome.error = replay_blocked
            outcome.last_verdict = Verdict(ok=False, reason=replay_blocked)
            return {
                "ok": False,
                "outcome": "unverified",
                "retryable": False,
                "errors": [replay_blocked],
            }
        # Keep evidence in this trusted tool closure. Model answers and tool
        # event payloads cannot create a successful execution receipt.
        executed_code = code.strip()
        outcome.last_result = outcome.last_verdict = None
        outcome.error = ""
        errs = _facade().validate_script(code)
        if errs:
            outcome.error = "static_check: " + "; ".join(errs)
            return {"ok": False, "errors": errs}
        try:
            res = await sandbox_runner(
                user_id=user_id,
                session_id=f"{session_id}_v2",
                script_text=code,
                files=files,
                **sandbox_kwargs,
            )
            outcome.last_result = res
            replay_blocked = sandbox_replay_block_reason(res)
            verification_error = sandbox_verification_error(res)
            if verification_error:
                outcome.last_verdict = Verdict(ok=False, reason=verification_error)
            else:
                outcome.last_verdict = await judge(
                    brief, PlanResult(plan_md=outcome.plan_md), res, llm=llm
                )
        except RECOVERABLE_ERRORS as exc:
            if outcome.last_result is None:
                replay_blocked = sandbox_replay_block_reason(None)
            outcome.error = f"sandbox validation: {exc}"
            outcome.last_verdict = Verdict(ok=False, reason=outcome.error)
            return {"ok": False, "errors": [outcome.error], "retryable": False}
        return {
            "ok": res.ok,
            "returncode": res.returncode,
            "stdout": res.stdout[-3000:],
            "stderr": res.stderr[-3000:],
            "outputs": res.outputs,
            "timed_out": res.timed_out,
            "verdict": _outcome_dict(outcome)["last_verdict"],
        }

    @tool(
        "run_sandbox",
        description="Run Python code in the project sandbox and return results.",
    )
    async def run_sandbox_tool(code: str) -> dict:
        return await _run_sandbox(code)

    reg.register(static_check_tool)
    reg.register(run_sandbox_tool)
    goal = f"Write Python code for this task and validate it:\n\n{ctx.brief_md or brief.goal}\n\nAcceptance: {brief.acceptance}\n\nSteps:\n1. Generate code\n2. Call static_check; fix errors if any\n3. Call run_sandbox with the code; fix if returncode != 0 or no outputs\n4. When sandbox ok=true and acceptance is met, give final_answer with the code."
    yield AgentEvent("plan", 0, {"plan_md": ctx.brief_md or brief.goal or ""})
    trace.append({"phase": "plan", "iteration": 0, "engine": "v2"})
    agent_loop = AgentLoop(
        _LLMBridge(),
        reg,
        mode="agent",
        max_steps=max_iterations * 3,
        allow_parallel=False,
        system_addendum=f"Allowed packages: {', '.join(ctx.allowlist_packages or [])}\n"
        + (ctx.kb_chunks_md[:2000] if ctx.kb_chunks_md else ""),
    )
    final_code = ""
    last_iteration = 0
    run_id = f"script-{session_id}"

    def finish(*, ok: bool = False, error: str = "") -> Dict[str, Any]:
        outcome.ok, outcome.error = ok, error
        outcome.iterations, outcome.final_code = last_iteration + 1, final_code
        return _outcome_dict(outcome)

    async for v2ev in agent_loop.arun(goal, run_id=run_id):
        evtype = v2ev.type if isinstance(v2ev.type, str) else v2ev.type.value
        payload = v2ev.payload or {}
        if evtype == "tool_call_end":
            tname = payload.get("tool", "")
            it = v2ev.step_index
            if tname == "static_check":
                errs = []
                out = payload.get("output") or {}
                if isinstance(out, dict):
                    errs = list(out.get("errors") or [])
                ok = not errs
                yield AgentEvent("check", it, {"ok": ok, "errors": errs})
                trace.append({"phase": "check", "iteration": it, "errors": errs, "engine": "v2"})
                last_iteration = it
            elif tname == "run_sandbox":
                receipt = _outcome_dict(outcome)
                out = receipt["last_result"]
                if out is not None:
                    yield AgentEvent(
                        "run",
                        it,
                        out,
                    )
                    trace.append(
                        {
                            "phase": "run",
                            "iteration": it,
                            "engine": "v2",
                            "returncode": out.get("returncode"),
                        }
                    )
                if receipt["last_verdict"] is not None:
                    verdict = receipt["last_verdict"]
                    yield AgentEvent("observe", it, verdict)
                    trace.append(
                        {"phase": "observe", "iteration": it, "verdict": verdict, "engine": "v2"}
                    )
                last_iteration = it
        elif evtype == "final_answer":
            final_code = str(payload.get("answer") or "")
            if "```python" in final_code:
                import re as _re

                m = _re.search("```python\\n(.*?)```", final_code, _re.DOTALL)
                if m:
                    final_code = m.group(1).strip()
            final_code = final_code.strip()
            result, verdict = outcome.last_result, outcome.last_verdict
            verified = bool(
                final_code
                and final_code == executed_code
                and result is not None
                and not sandbox_verification_error(result)
                and verdict is not None
                and verdict.ok is True
            )
            if not verified or result is None:
                reason = (
                    "final_answer does not match the latest sandbox code"
                    if final_code != executed_code
                    else outcome.error
                    or (verdict.reason if verdict is not None else "")
                    or "final_answer has no successful sandbox and acceptance receipt"
                )
                yield AgentEvent(
                    "error", last_iteration, {"reason": reason, "outcome": finish(error=reason)}
                )
                return
            yield AgentEvent(
                "done",
                last_iteration,
                {"code": final_code, "outputs": result.outputs, "outcome": finish(ok=True)},
            )
            return
        elif evtype == "error":
            reason = str(payload.get("reason") or "agent v2 error")
            yield AgentEvent(
                "error", last_iteration, {"reason": reason, "outcome": finish(error=reason)}
            )
            return
    yield AgentEvent(
        "error",
        last_iteration,
        {
            "reason": "agent_loop_v2: no final answer produced",
            "outcome": finish(error="no answer"),
        },
    )
