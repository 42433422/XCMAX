# mypy: disable-error-code="attr-defined, misc, no-any-return, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_01(ctx: dict[str]) -> bool:
    ctx["_wf_sandbox_biz_ok"]: _facade().Optional[bool] = None
    ctx["_standalone_smoke_ok"] = True
    if ctx["_should_skip"]("employee_plan"):
        await _facade()._set_step(ctx["sid"], "employee_plan", "done", "已完成（重试复用）")
    else:
        await _facade()._set_step(
            ctx["sid"],
            "employee_plan",
            "running",
            "正在拆分员工、脚本工作流与 Skill 组职责",
        )
    _ep_result = await _facade()._dispatch_craft_step(
        "employee_plan",
        db=ctx["db"],
        user_id=ctx["user_id"],
        payload=ctx["payload"],
        prov=ctx["prov"],
        mdl=ctx["mdl"],
    )
    ctx["employee_plan"] = (
        _ep_result["employee_plan"]
        if _ep_result
        else await _facade()._build_employee_orchestration_plan(
            ctx["db"],
            ctx["user_id"],
            payload=ctx["payload"],
            provider=ctx["prov"],
            model=ctx["mdl"],
        )
    )
    if ctx["_pipeline_label"] == "txt_full_read":
        _pipeline_label_display = "TXT 全量读取 direct_python"
    elif ctx["_pipeline_label"] == "txt_generate":
        _pipeline_label_display = "TXT 生成 direct_python + 可选 agent"
    elif ctx["_pipeline_label"] == "pdf_full_read":
        _pipeline_label_display = "PDF 全量读取 direct_python（原生文字 + 图片 VLM）"
    elif ctx["_pipeline_label"] == "pdf_generate":
        _pipeline_label_display = "PDF 生成 direct_python + JSON 中介 + 可选 agent"
    elif ctx["_pipeline_label"] == "word_full_extract":
        _pipeline_label_display = "Word 全量提取 direct_python"
    elif ctx["_pipeline_label"] == "asset":
        _pipeline_label_display = (
            "LLM 驱动文档审核（agent）"
            if ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]
            else "资产驱动 direct_python"
        )
    else:
        _pipeline_label_display = "LLM 通用脚手架"
    _plan_display_name = str(ctx["employee_plan"].get("employee_name") or "员工").strip() or "员工"
    await _facade()._set_step(
        ctx["sid"],
        "employee_plan",
        "done",
        f"已规划：{_plan_display_name} / {_pipeline_label_display}",
    )
    if ctx["_use_word_extract_pipeline"]:
        ctx["employee_brief"] = (
            ctx["compact_routing_brief"](ctx["_routing_brief"], max_len=500)
            or ctx["_routing_brief"]
        )
    else:
        ctx["employee_brief"] = (
            str(
                ctx["employee_plan"].get("employee_brief") or ctx["_routing_brief"] or ctx["brief"]
            ).strip()
            or ctx["brief"]
        )
    ctx["script_brief"] = (
        str(ctx["employee_plan"].get("script_brief") or ctx["brief"]).strip() or ctx["brief"]
    )
    ctx["script_hint"] = str(ctx["employee_plan"].get("script_runtime_notes") or "").strip()
    ctx["workflow_brief"] = (
        str(ctx["employee_plan"].get("workflow_brief") or ctx["brief"]).strip() or ctx["brief"]
    )
    ctx["planned_workflow_name"] = (
        str(ctx["employee_plan"].get("workflow_name") or "").strip() or None
    )
    ctx["planned_script_name"] = (
        str(ctx["employee_plan"].get("script_workflow_name") or "").strip() or None
    )
    return False
