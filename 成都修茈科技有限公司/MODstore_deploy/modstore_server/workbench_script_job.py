# ruff: noqa
"""Single-pass workbench script generation and sandbox execution."""
from __future__ import annotations
import importlib
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger("modstore_server.workbench_script_runner")
StatusHook = Callable[[str], Awaitable[None]]
MAX_AGENT_ITERATIONS = 6


def _facade():
    return importlib.import_module("modstore_server.workbench_script_runner")


async def run_script_job(
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
) -> Dict[str, Any]:
    """生成→静态检查→沙箱运行→多轮回修 agent loop。"""

    async def _notify(msg: str) -> None:
        if status_hook:
            try:
                await status_hook(msg)
            except Exception:
                pass

    fake_input_files = [Path(str((f or {}).get("filename") or "input.bin")) for f in files or []]
    repair_trace: List[Dict[str, Any]] = []
    gen = await _facade()._generate_script(
        db=db,
        user_id=user_id,
        brief=brief,
        input_files=fake_input_files,
        provider=provider,
        model=model,
        system_hint=system_hint,
        upload_items=files or [],
    )
    if gen.errors:
        await _notify("脚本生成失败：" + "；".join(gen.errors)[:300])
        return {
            "ok": False,
            "work_dir": "",
            "script": gen.code,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "outputs": [],
            "errors": gen.errors,
        }
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    if db is not None and provider:
        try:
            (api_key, _src) = _facade().resolve_api_key(db, user_id, provider)
            base_url = _facade().resolve_base_url(db, user_id, provider)
        except Exception:
            (api_key, base_url) = (None, None)
    code = gen.code
    last_errors: List[str] = []
    last_stdout = ""
    last_stderr = ""
    last_returncode = -1
    last_outputs: List[Dict[str, Any]] = []
    last_work_dir = ""
    last_sdk_calls: List[Dict[str, Any]] = []
    for iteration in range(1, _facade().MAX_AGENT_ITERATIONS + 1):
        await _notify(f"第 {iteration} 轮：静态检查")
        static_errors = _facade().validate_script(code)
        repair_trace.append(
            {
                "phase": "static_check",
                "iteration": iteration,
                "ok": not static_errors,
                "errors": static_errors,
                "code_excerpt": code[:1000],
            }
        )
        if static_errors:
            last_errors = static_errors
            if not api_key:
                break
            repaired = await _facade()._repair_script_once(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                brief=brief,
                code=code,
                errors=static_errors,
                failure_context="阶段：静态检查。请优先修复语法、import 白名单、危险调用等问题。",
                system_hint=system_hint,
                upload_items=files or [],
            )
            repair_trace.append(
                {
                    "phase": "repair",
                    "iteration": iteration,
                    "reason": "static_check",
                    "ok": not repaired.errors,
                    "errors": repaired.errors,
                    "code_excerpt": repaired.code[:1000],
                }
            )
            if repaired.errors:
                last_errors = repaired.errors
                code = repaired.code or code
                break
            code = repaired.code
            await _notify(f"第 {iteration} 轮静态修复完成，继续下一轮检查")
            continue
        await _notify(f"第 {iteration} 轮：沙箱运行")
        result = await _facade()._sandbox.run_in_sandbox(
            user_id=user_id,
            session_id=f"{session_id}_iter{iteration}",
            script_text=code,
            files=files or [],
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            script_root=_facade().SCRIPT_ROOT,
        )
        ok = bool(result.ok and result.outputs)
        last_stdout = result.stdout[-4000:]
        last_stderr = result.stderr[-4000:]
        last_returncode = result.returncode
        last_outputs = result.outputs
        last_work_dir = result.work_dir
        last_sdk_calls = result.sdk_calls
        last_errors = result.errors or []
        if result.ok and (not result.outputs):
            last_errors = ["脚本运行成功但 outputs/ 下没有生成任何结果文件"]
        elif not result.ok and (not last_errors):
            last_errors = [result.stderr[-1000:] or "脚本沙箱运行失败"]
        repair_trace.append(
            {
                "phase": "run",
                "iteration": iteration,
                "ok": ok,
                "returncode": result.returncode,
                "errors": last_errors,
                "outputs": result.outputs,
                "stdout_tail": last_stdout[-1000:],
                "stderr_tail": last_stderr[-1000:],
            }
        )
        if ok:
            await _notify(f"第 {iteration} 轮沙箱通过，已生成 {len(last_outputs)} 个文件")
            return {
                "ok": True,
                "work_dir": last_work_dir,
                "script": code,
                "stdout": last_stdout,
                "stderr": last_stderr,
                "returncode": last_returncode,
                "outputs": last_outputs,
                "errors": [],
                "sdk_calls": last_sdk_calls,
                "repair_trace": repair_trace,
            }
        if not api_key:
            break
        no_output = result.ok and (not result.outputs)
        await _notify(f"第 {iteration} 轮{('无输出文件，回修' if no_output else '运行失败，回修')}")
        failure_context = f"阶段：沙箱运行/产物验收。\nreturncode: {result.returncode}\nstdout:\n{last_stdout[-1500:]}\nstderr:\n{last_stderr[-1500:]}\noutputs: {result.outputs}\n【关键修复要求】outputs/ 下没有文件是致命错误：\n  1. 在脚本最顶层（不在 if 里）先执行 Path('outputs').mkdir(exist_ok=True)\n  2. 无论 inputs/ 是否有文件，都要无条件写至少一个结果文件，例如 outputs/summary.md\n  3. 写文件语句不能放在 for 循环或 if 分支里，即使没有输入也要有兜底 write\n  4. 每次循环后、函数末尾都要保证 outputs/ 下有至少一个文件"
        repaired = await _facade()._repair_script_once(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            brief=brief,
            code=code,
            errors=last_errors,
            failure_context=failure_context,
            system_hint=system_hint,
            upload_items=files or [],
        )
        repair_trace.append(
            {
                "phase": "repair",
                "iteration": iteration,
                "reason": "run_or_acceptance",
                "ok": not repaired.errors,
                "errors": repaired.errors,
                "code_excerpt": repaired.code[:1000],
            }
        )
        if repaired.errors:
            last_errors = repaired.errors
            code = repaired.code or code
            break
        code = repaired.code
        await _notify(f"第 {iteration} 轮运行修复完成，继续下一轮检查")
    repair_rounds = len([x for x in repair_trace if x.get("phase") == "repair"])
    final_errors = list(last_errors or ["脚本生成未通过检查或沙箱验收"])
    if repair_rounds:
        final_errors = [
            f"已自动回修 {repair_rounds} 轮仍未通过；最后错误：{'; '.join(final_errors)[:800]}"
        ]
    return {
        "ok": False,
        "work_dir": last_work_dir,
        "script": code,
        "stdout": last_stdout,
        "stderr": last_stderr,
        "returncode": last_returncode,
        "outputs": last_outputs,
        "errors": final_errors,
        "sdk_calls": last_sdk_calls,
        "repair_trace": repair_trace,
    }
