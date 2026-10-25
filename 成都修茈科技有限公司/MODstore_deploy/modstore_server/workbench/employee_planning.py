"""Employee planning for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.employee_brief_utils import compact_routing_brief
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeePlanningPorts:
    progress: ProgressCallbacks
    db: Session
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    build_plan: Callable[..., Awaitable[dict[str, Any]]]


async def plan_employee(state: EmployeeBuildState, *, ports: EmployeePlanningPorts) -> bool:
    state.workflow_business_ok = None
    state.standalone_smoke_ok = True
    if state.should_skip("employee_plan"):
        await ports.progress.set_step(
            state.session_id, "employee_plan", "done", "已完成（重试复用）"
        )
    else:
        await ports.progress.set_step(
            state.session_id,
            "employee_plan",
            "running",
            "正在拆分员工、脚本工作流与 Skill 组职责",
        )
    _ep_result = await ports.craft_step(
        "employee_plan",
        db=ports.db,
        user_id=state.user_id,
        payload=state.payload,
        prov=state.provider,
        mdl=state.model,
    )
    state.employee_plan = (
        _ep_result["employee_plan"]
        if _ep_result
        else await ports.build_plan(
            ports.db,
            state.user_id,
            payload=state.payload,
            provider=state.provider,
            model=state.model,
        )
    )
    if state.pipeline_label == "txt_full_read":
        _pipeline_label_display = "TXT 全量读取 direct_python"
    elif state.pipeline_label == "txt_generate":
        _pipeline_label_display = "TXT 生成 direct_python + 可选 agent"
    elif state.pipeline_label == "pdf_full_read":
        _pipeline_label_display = "PDF 全量读取 direct_python（原生文字 + 图片 VLM）"
    elif state.pipeline_label == "pdf_generate":
        _pipeline_label_display = "PDF 生成 direct_python + JSON 中介 + 可选 agent"
    elif state.pipeline_label == "word_full_extract":
        _pipeline_label_display = "Word 全量提取 direct_python"
    elif state.pipeline_label == "asset":
        _pipeline_label_display = (
            "LLM 驱动文档审核（agent）"
            if state.needs_llm_reasoning and state.uploaded_docx
            else "资产驱动 direct_python"
        )
    else:
        _pipeline_label_display = "LLM 通用脚手架"
    _plan_display_name = str(state.employee_plan.get("employee_name") or "员工").strip() or "员工"
    await ports.progress.set_step(
        state.session_id,
        "employee_plan",
        "done",
        f"已规划：{_plan_display_name} / {_pipeline_label_display}",
    )
    if state.use_word_extract:
        state.employee_brief = (
            compact_routing_brief(state.routing_brief, max_len=500) or state.routing_brief
        )
    else:
        state.employee_brief = (
            str(
                state.employee_plan.get("employee_brief") or state.routing_brief or state.brief
            ).strip()
            or state.brief
        )
    state.script_brief = (
        str(state.employee_plan.get("script_brief") or state.brief).strip() or state.brief
    )
    state.script_hint = str(state.employee_plan.get("script_runtime_notes") or "").strip()
    state.workflow_brief = (
        str(state.employee_plan.get("workflow_brief") or state.brief).strip() or state.brief
    )
    state.planned_workflow_name = (
        str(state.employee_plan.get("workflow_name") or "").strip() or None
    )
    state.planned_script_name = (
        str(state.employee_plan.get("script_workflow_name") or "").strip() or None
    )
    return False
