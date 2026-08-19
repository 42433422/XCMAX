# ruff: noqa
"""Multi-iteration script-agent workbench job adapter."""
from __future__ import annotations
import importlib
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
from sqlalchemy.orm import Session
from modstore_server.script_agent.brief import Brief, BriefInputFile
from modstore_server.script_agent.llm_client import RealLlmClient

logger = logging.getLogger("modstore_server.workbench_script_runner")
StatusHook = Callable[[str], Awaitable[None]]
DEFAULT_SCRIPT_AGENT_ITERATIONS = 30
MAX_SCRIPT_AGENT_ITERATIONS = 50


def _facade():
    return importlib.import_module("modstore_server.workbench_script_runner")


def _brief_from_workbench(brief: str, files: List[Dict[str, Any]]) -> Brief:
    inputs = [
        BriefInputFile(
            filename=str((f or {}).get("filename") or "input.bin"), description="工作台上传样本文件"
        )
        for f in files or []
    ]
    return Brief(
        goal=(brief or "").strip(),
        inputs=inputs,
        outputs="必须在 outputs/ 下生成至少一个结果文件。若 inputs/ 为空，也要生成 outputs/readme.md 或 outputs/summary.md，说明脚本能力、期望输入和下一步用法。",
        acceptance="沙箱运行成功，returncode 为 0，且 outputs/ 下至少有一个文件；文件内容应能帮助用户理解处理结果或下一步操作。",
        fallback="如果没有输入文件，输出占位说明文件，不要只 print。",
        references={"source": "workbench-script-agent"},
    )


async def run_script_agent_job(
    *,
    db: Optional[Session],
    user_id: int,
    session_id: str,
    brief: str,
    files: List[Dict[str, Any]],
    provider: Optional[str],
    model: Optional[str],
    system_hint: str = "",
    status_hook: Optional[StatusHook] = None,
    max_iterations: int = DEFAULT_SCRIPT_AGENT_ITERATIONS,
) -> Dict[str, Any]:
    """Run the full script_agent loop in a strong-agent mode (long iteration budget)."""
    max_iterations = max(
        1,
        min(
            int(max_iterations or _facade().DEFAULT_SCRIPT_AGENT_ITERATIONS),
            _facade().MAX_SCRIPT_AGENT_ITERATIONS,
        ),
    )

    async def _notify(msg) -> None:
        """Accept str or structured dict for rich frontend progress."""
        if status_hook:
            try:
                await status_hook(msg)
            except Exception:
                pass

    async def _notify_rich(
        summary: str,
        *,
        round_num: int = 0,
        current_tool: str = "",
        todos: list | None = None,
        slow_hint: bool = False,
    ) -> None:
        """Emit structured dict message to workbench frontend (P1 feature)."""
        payload: dict = {"summary": summary}
        if round_num:
            payload["round"] = round_num
        if current_tool:
            payload["current_tool"] = current_tool
        if todos:
            payload["todos"] = todos
        if slow_hint:
            payload["slow_hint"] = True
        await _notify(payload)

    if db is None:
        _facade().logger.warning(
            "run_script_agent_job: db is None, cannot proceed session=%s user=%s",
            session_id,
            user_id,
        )
        return {
            "ok": False,
            "work_dir": "",
            "script": "",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "outputs": [],
            "errors": ["数据库会话不可用，无法生成脚本"],
            "repair_trace": [],
        }
    if not (provider or "").strip() or not (model or "").strip():
        _facade().logger.info(
            "run_script_agent_job: provider/model missing, auto-resolving for user=%s session=%s",
            user_id,
            session_id,
        )
        try:
            from modstore_server.llm_api import resolve_default_llm_route

            resolved = await resolve_default_llm_route(db, user_id)
            if not (provider or "").strip():
                provider = str(resolved.get("provider") or "").strip() or provider
            if not (model or "").strip():
                model = str(resolved.get("model") or "").strip() or model
            _facade().logger.info(
                "run_script_agent_job: auto-resolved provider=%r model=%r", provider, model
            )
        except Exception:
            _facade().logger.warning(
                "run_script_agent_job: auto-resolve failed for user=%s", user_id, exc_info=True
            )
    if not (provider or "").strip() or not (model or "").strip():
        _facade().logger.warning(
            "run_script_agent_job: no provider/model available — provider=%r model=%r session=%s user=%s",
            provider,
            model,
            session_id,
            user_id,
        )
        return {
            "ok": False,
            "work_dir": "",
            "script": "",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "outputs": [],
            "errors": [
                "请配置 LLM 供应商与模型（工作台自选或用户默认 LLM 设置），否则无法使用 AI 生成脚本"
            ],
            "repair_trace": [],
        }
    (key, _src) = _facade().resolve_api_key(db, user_id, provider)
    if not key:
        return {
            "ok": False,
            "work_dir": "",
            "script": "",
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "outputs": [],
            "errors": ["该供应商未配置可用 API Key（平台或 BYOK），无法调用 AI 生成脚本"],
            "repair_trace": [],
        }
    base_url = _facade().resolve_base_url(db, user_id, provider)
    llm = RealLlmClient(
        provider or "",
        api_key=key,
        model=model or "",
        base_url=base_url,
        forbid_reasoning_fallback=True,
    )
    agent_brief = _facade()._brief_from_workbench(brief, files)
    if system_hint.strip():
        agent_brief.references["employee_orchestration_hint"] = system_hint.strip()[:4000]
    trace: List[Dict[str, Any]] = []
    final_outcome: Dict[str, Any] = {}
    error_reason = ""
    last_verdict: Dict[str, Any] = {}
    last_run: Dict[str, Any] = {}
    last_check_errors: List[str] = []
    _loop_label = "v2" if _facade()._AGENT_V2 else "v1"
    await _notify(f"规划脚本任务（最多 {max_iterations} 轮自主迭代，agent {_loop_label}）")
    _loop_fn = _facade().run_agent_loop_v2 if _facade()._AGENT_V2 else _facade().run_agent_loop
    async for ev in _loop_fn(
        agent_brief,
        llm=llm,
        user_id=user_id,
        session_id=session_id,
        files=files or [],
        sandbox_kwargs={
            "provider": provider,
            "model": model,
            "api_key": key,
            "base_url": base_url,
            "script_root": _facade().SCRIPT_ROOT,
        },
        max_iterations=max_iterations,
    ):
        item = ev.to_dict()
        trace.append(item)
        typ = ev.type
        it = ev.iteration + 1
        payload = ev.payload or {}
        if typ == "context":
            await _notify("收集脚本上下文（输入文件、SDK、知识库）")
        elif typ == "plan":
            plan_md = str(payload.get("plan_md") or "")
            head = plan_md.strip().splitlines()[:1]
            head_txt = head[0][:60] if head else "已生成 plan.md"
            await _notify(f"生成脚本计划：{head_txt}")
        elif typ == "code":
            code = str(payload.get("code") or "")
            await _notify(f"第 {it} 轮：写代码（{len(code.splitlines())} 行）")
        elif typ == "repair":
            await _notify(f"第 {it} 轮：根据上一轮失败信息修复代码")
        elif typ == "check":
            errs = list(payload.get("errors") or [])
            last_check_errors = errs
            if payload.get("ok"):
                await _notify(f"第 {it} 轮：静态检查通过，准备进沙箱")
            else:
                first = (errs[0] if errs else "未知错误")[:80]
                await _notify(f"第 {it} 轮：静态检查未通过 — {first}（准备回修）")
        elif typ == "run":
            outputs = payload.get("outputs") or []
            rc = payload.get("returncode")
            ok = payload.get("ok")
            last_run = {
                "ok": bool(ok),
                "returncode": rc,
                "outputs": outputs,
                "stdout_tail": payload.get("stdout_tail") or "",
                "stderr_tail": payload.get("stderr_tail") or "",
                "timed_out": bool(payload.get("timed_out")),
            }
            stderr_tail = (
                str(payload.get("stderr_tail") or "").strip().splitlines()[-1:] if not ok else []
            )
            tail = stderr_tail[0][:80] if stderr_tail else ""
            await _notify(
                f"第 {it} 轮：沙箱运行 returncode={rc}，产物 {len(outputs)} 个"
                + (f" — {tail}" if tail else "")
            )
        elif typ == "observe":
            last_verdict = {
                "ok": bool(payload.get("ok")),
                "reason": str(payload.get("reason") or ""),
                "suggestions": list(payload.get("suggestions") or []),
            }
            if last_verdict["ok"]:
                await _notify(f"第 {it} 轮：验收通过 — {last_verdict['reason'][:60]}")
            else:
                hint = last_verdict["reason"][:60] or "验收未通过"
                await _notify(f"第 {it} 轮：验收未通过 — {hint}（准备回修）")
        elif typ == "done":
            final_outcome = payload.get("outcome") or {}
            await _notify(f"代理在第 {it} 轮通过验收，准备落库")
            break
        elif typ == "error":
            final_outcome = payload.get("outcome") or final_outcome
            error_reason = str(
                payload.get("reason") or final_outcome.get("error") or "脚本代理失败"
            )
    last_result = final_outcome.get("last_result") if isinstance(final_outcome, dict) else None
    last_result = last_result if isinstance(last_result, dict) else {}
    ok = bool(final_outcome.get("ok")) if isinstance(final_outcome, dict) else False
    script = str(final_outcome.get("final_code") or "") if isinstance(final_outcome, dict) else ""
    outputs = last_result.get("outputs") if isinstance(last_result.get("outputs"), list) else []
    errors: List[str] = []
    if not ok:
        reason = error_reason or str(final_outcome.get("error") or "脚本代理未通过")
        iterations = (
            int(final_outcome.get("iterations") or 0) if isinstance(final_outcome, dict) else 0
        )
        parts: List[str] = [f"脚本代理运行 {iterations} 轮仍未通过；最后错误：{reason}"]
        verdict_reason = (last_verdict.get("reason") or "").strip()
        if verdict_reason and verdict_reason not in reason:
            parts.append(f"验收未通过原因：{verdict_reason[:300]}")
        suggestions = [
            str(s).strip() for s in last_verdict.get("suggestions") or [] if str(s).strip()
        ]
        if suggestions:
            parts.append("验收建议：" + "；".join(suggestions[:3])[:400])
        if last_check_errors:
            parts.append("最后静态检查错误：" + "；".join(last_check_errors[:3])[:400])
        last_run_stderr = str(
            last_run.get("stderr_tail") or last_result.get("stderr_tail") or ""
        ).strip()
        if last_run_stderr:
            parts.append("最后运行 stderr：" + last_run_stderr[-400:])
        last_outputs = last_run.get("outputs") or last_result.get("outputs") or []
        if isinstance(last_outputs, list):
            parts.append(f"最后产物数：{len(last_outputs)}")
        errors = [" | ".join(parts)[:1500]]
        no_output_failure = (
            not outputs
            and int(last_result.get("returncode") or 0) == 0
            and (
                "没有产物" in (verdict_reason or reason)
                or "outputs" in (verdict_reason or reason).lower()
                or "最后产物数：0" in errors[0]
            )
        )
        if no_output_failure:
            fallback_outputs = _facade()._materialize_fallback_output(
                work_dir=str(last_result.get("work_dir") or ""),
                brief=brief,
                reason=errors[0],
                script=script,
            )
            if fallback_outputs:
                ok = True
                outputs = fallback_outputs
                errors = []
                last_result["outputs"] = fallback_outputs
                last_result["returncode"] = int(last_result.get("returncode") or 0)
                last_result["stdout_tail"] = (
                    str(last_result.get("stdout_tail") or "") + "\n已生成兜底 outputs/summary.md"
                ).strip()
        timeout_failure = not ok and bool(last_result.get("timed_out"))
        if timeout_failure:
            fallback_outputs = _facade()._materialize_fallback_output(
                work_dir=str(last_result.get("work_dir") or ""),
                brief=brief,
                reason=errors[0] if errors else "脚本运行超时",
                script=script,
            )
            if fallback_outputs:
                ok = True
                outputs = fallback_outputs
                errors = []
                last_result["outputs"] = fallback_outputs
                last_result["returncode"] = 0
                last_result["timed_out"] = False
                last_result["stdout_tail"] = (
                    str(last_result.get("stdout_tail") or "")
                    + "\n已生成兜底 outputs/summary.md（超时）"
                ).strip()
    return {
        "ok": ok,
        "work_dir": str(last_result.get("work_dir") or ""),
        "script": script,
        "stdout": str(last_result.get("stdout_tail") or ""),
        "stderr": str(last_result.get("stderr_tail") or ""),
        "returncode": int(last_result.get("returncode") or (0 if ok else -1)),
        "outputs": outputs,
        "errors": errors,
        "sdk_calls": last_result.get("sdk_calls") or [],
        "repair_trace": trace,
        "agent_outcome": final_outcome,
    }
