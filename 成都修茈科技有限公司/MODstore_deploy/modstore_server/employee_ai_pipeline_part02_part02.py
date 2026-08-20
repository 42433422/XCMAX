# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


async def refine_system_prompt(
    current_prompt: str, instruction: str, role_context: str, llm: _facade().LlmClient
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, str]], str]:
    """LLM-improve a system prompt and explain the changes."""
    ctx = f"角色背景：{role_context}\n\n当前 system prompt：\n{current_prompt}\n\n优化指令：{instruction}"
    content = await llm.chat(
        [
            {"role": "system", "content": _facade()._SYS_REFINE_PROMPT},
            {"role": "user", "content": ctx},
        ],
        max_tokens=2048,
    )
    data, err = _facade()._parse_json(content)
    if err:
        return (None, err)
    if not isinstance(data, dict):
        return (None, "须返回 JSON 对象")
    improved = str(data.get("improved_prompt") or "").strip()
    if not improved:
        return (None, "LLM 未返回优化后的 prompt")
    return (
        {
            "improved_prompt": improved,
            "diff_explanation": str(data.get("diff_explanation") or "")[:160],
        },
        "",
    )


async def run_pipeline(
    brief: str,
    *,
    llm: _facade().LlmClient,
    on_event: _facade().Callable[[_facade().Dict[str, _facade().Any]], _facade().Awaitable[None]],
    eligible_workflows: _facade().Optional[
        _facade().List[_facade().Dict[str, _facade().Any]]
    ] = None,
    generate_workflow_fallback: _facade().Optional[
        _facade().Callable[[], _facade().Awaitable[_facade().Dict[str, _facade().Any]]]
    ] = None,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """Run the 6-stage pipeline pushing SSE events via on_event.

    Returns the assembled manifest dict on success, None on fatal failure.
    Stages 4 (skills) and 5 (pricing) are non-fatal: errors produce empty/null
    results but do not abort the pipeline.
    """

    async def _emit(event: str, stage: str, **kw: _facade().Any) -> None:
        await on_event({"event": event, "stage": stage, **kw})

    await _emit("stage_start", "parse_intent")
    intent, err = await _facade().stage_parse_intent(brief, llm)
    if err or intent is None:
        await _emit("stage_error", "parse_intent", error=err or "意图解析失败", retryable=True)
        return None
    await _emit("stage_done", "parse_intent", data=_facade().asdict(intent))
    await _emit("stage_start", "resolve_workflow")

    async def _on_wf_progress(msg: str) -> None:
        await _emit("stage_progress", "resolve_workflow", message=msg)

    wf_choice, err = await _facade().stage_resolve_workflow(
        intent,
        eligible_workflows or [],
        llm,
        generate_fallback=generate_workflow_fallback,
        on_progress=_on_wf_progress,
    )
    if err:
        await _emit("stage_error", "resolve_workflow", error=err, retryable=True)
        return None
    await _emit(
        "stage_done", "resolve_workflow", data=_facade().asdict(wf_choice) if wf_choice else None
    )
    await _emit("stage_start", "suggest_skills")
    skills, err = await _facade().stage_suggest_skills(intent, llm)
    if err:
        await _emit("stage_error", "suggest_skills", error=err, retryable=False)
        skills = []
    await _emit("stage_done", "suggest_skills", data=[_facade().asdict(s) for s in skills])
    await _emit("stage_start", "design_v2")
    v2, err = await _facade().stage_design_v2(intent, wf_choice, llm, suggested_skills=skills)
    if err or v2 is None:
        await _emit("stage_error", "design_v2", error=err or "配置设计失败", retryable=True)
        return None
    await _emit("stage_done", "design_v2", data=_facade().asdict(v2))
    await _emit("stage_start", "suggest_pricing")
    pricing, err = await _facade().stage_suggest_pricing(intent, v2, skills, llm)
    if err:
        await _emit("stage_error", "suggest_pricing", error=err, retryable=False)
        pricing = None
    await _emit(
        "stage_done", "suggest_pricing", data=_facade().asdict(pricing) if pricing else None
    )
    await _emit("stage_start", "assemble")
    manifest, errs = _facade().stage_assemble(intent, wf_choice, v2, skills, pricing)
    if manifest is None:
        await _emit(
            "stage_error",
            "assemble",
            error="; ".join(errs) if errs else "装配失败",
            retryable=False,
        )
        return None
    if errs:
        await _emit("stage_done", "assemble", data=manifest, warnings=errs)
    else:
        await _emit("stage_done", "assemble", data=manifest)
    await _emit("stage_start", "generate_code")
    generated = await _facade().stage_generate_code(brief, manifest, llm)
    if generated.warnings:
        await _emit(
            "stage_done",
            "generate_code",
            data={
                "code_source": generated.code_source,
                "runtime_kind": generated.runtime_kind,
                "vendor_module_count": len(generated.vendor_modules),
                "employee_py_lines": len(generated.employee_py.splitlines()),
            },
            warnings=generated.warnings,
        )
    else:
        await _emit(
            "stage_done",
            "generate_code",
            data={
                "code_source": generated.code_source,
                "runtime_kind": generated.runtime_kind,
                "vendor_module_count": len(generated.vendor_modules),
                "employee_py_lines": len(generated.employee_py.splitlines()),
            },
        )
    await _emit(
        "pipeline_done", "pipeline", manifest=manifest, generated_code=_facade().asdict(generated)
    )
    return manifest
