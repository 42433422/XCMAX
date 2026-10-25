"""Employee workflows for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.models import User
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeWorkflowPorts:
    progress: ProgressCallbacks
    db: Session
    user: User
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    run_script: Callable[..., Awaitable[dict[str, Any]]]
    commit_script: Callable[..., dict[str, Any] | None]
    embed_script: Callable[..., dict[str, Any]]
    attach_workflow: Callable[..., Awaitable[dict[str, Any]]]
    refresh_catalog: Callable[..., dict[str, Any]]


async def bind_employee_workflows(
    state: EmployeeBuildState, *, ports: EmployeeWorkflowPorts
) -> bool:
    if state.should_skip("script_workflow"):
        await ports.progress.set_step(
            state.session_id, "script_workflow", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "script_workflow"
        if state.use_assets or (state.needs_llm_reasoning and state.uploaded_docx):
            _asset_names = [
                str(f.get("filename") or f.get("name") or "")[:60]
                for f in state.employee_files
                if isinstance(f, dict)
            ][:5]
            _asset_hint = f"（资产：{'、'.join(_asset_names)}）" if _asset_names else ""
            if state.use_word_extract:
                _skip_reason = (
                    "Word direct_python 模式：员工内置 vendor convert，无需配套小程序"
                )
            elif state.needs_llm_reasoning and state.uploaded_docx:
                _skip_reason = "LLM 驱动文档审核模式"
            else:
                _skip_reason = "资产驱动模式"
            await ports.progress.set_step(
                state.session_id,
                "script_workflow",
                "skipped",
                f"{_skip_reason}{(_asset_hint if not state.use_word_extract else '')}",
            )
            state.embed_script_workflow = False
        elif state.embed_script_workflow:
            _LOG.info(
                "pipeline: script_workflow step — prov=%r mdl=%r db=%s sid=%s",
                state.provider,
                state.model,
                type(ports.db).__name__ if ports.db else None,
                state.session_id,
            )
            await ports.progress.set_step(
                state.session_id, "script_workflow", "running", "正在生成员工配套小程序"
            )

            async def _script_progress(msg: str) -> None:
                await ports.progress.set_step(
                    state.session_id, "script_workflow", "running", msg
                )

            _sw_result = await ports.craft_step(
                "script_workflow",
                db=ports.db,
                user_id=state.user_id,
                session_id=f"{state.session_id}-employee-script",
                brief=state.script_brief,
                files=state.employee_files,
                provider=state.provider,
                model=state.model,
                system_hint=state.script_hint,
                payload={
                    **state.payload,
                    "brief": state.script_brief,
                    "workflow_name": state.planned_script_name
                    or state.workflow_name
                    or state.result.get("id")
                    or "员工配套",
                },
                status_hook=_script_progress,
            )
            if _sw_result:
                state.script_result = _sw_result["script_result"]
                state.script_workflow = _sw_result["script_wf"]
            else:
                state.script_result = await ports.run_script(
                    db=ports.db,
                    user_id=state.user_id,
                    session_id=f"{state.session_id}-employee-script",
                    brief=state.script_brief,
                    files=state.employee_files,
                    provider=state.provider,
                    model=state.model,
                    system_hint=state.script_hint,
                    status_hook=_script_progress,
                )
                state.script_workflow = None
                if state.script_result.get("ok") and (
                    not state.script_result.get("errors")
                ):
                    state.script_workflow = ports.commit_script(
                        ports.db,
                        user_id=state.user_id,
                        session_id=state.session_id,
                        payload={
                            **state.payload,
                            "brief": state.script_brief,
                            "workflow_name": state.planned_script_name
                            or state.workflow_name
                            or state.result.get("id")
                            or "员工配套",
                        },
                        files=state.employee_files,
                        result=state.script_result,
                    )
            if not state.script_workflow:
                if state.script_result.get("ok"):
                    _script_err_parts = []
                    if not str(state.script_result.get("script") or "").strip():
                        _script_err_parts.append("脚本代码为空")
                    if state.script_result.get("errors"):
                        _script_err_parts.append(
                            "；".join(
                                (str(e) for e in state.script_result["errors"][:3])
                            )
                        )
                    _skip_reason = (
                        "；".join(_script_err_parts)
                        if _script_err_parts
                        else "未能生成可保存的脚本工作流"
                    )
                    await ports.progress.set_step(
                        state.session_id,
                        "script_workflow",
                        "skipped",
                        f"已跳过：{_skip_reason}",
                    )
                    _LOG.warning(
                        "pipeline: script_wf=None but ok=True — skipping, reason=%s session=%s",
                        _skip_reason,
                        state.session_id,
                    )
                else:
                    _script_err = (
                        "；".join(
                            (
                                str(e)
                                for e in (state.script_result.get("errors") or [])[:3]
                            )
                        )
                        or "脚本执行失败"
                    )
                    msg = f"脚本运行失败：{_script_err}"
                    await ports.progress.set_step(
                        state.session_id, "script_workflow", "error", msg[:300]
                    )
                    await ports.progress.fail(
                        state.session_id, "script_workflow", msg[:1000]
                    )
                    return True
            else:
                await ports.progress.set_step(
                    state.session_id,
                    "script_workflow",
                    "done",
                    f"已生成脚本工作流 id={state.script_workflow.get('id')}",
                )
        else:
            await ports.progress.set_step(
                state.session_id,
                "script_workflow",
                "skipped",
                "已跳过：未开启配套小程序",
            )
    if state.should_skip("embed_script"):
        await ports.progress.set_step(
            state.session_id, "embed_script", "done", "已完成（重试复用）"
        )
    else:
        state.workflow_attachment = {}
        state.saved_package = state.result.get("package") or {}
        state.published_to_catalog = False
        state.current_step = "embed_script"
        if state.embed_script_workflow and state.script_workflow:
            await ports.progress.set_step(
                state.session_id,
                "embed_script",
                "running",
                "正在把配套小程序绑定到员工能力",
            )
            _es_result = await ports.craft_step(
                "embed_script",
                pack_dir=state.pack_dir,
                script_wf=state.script_workflow,
                brief=state.script_brief,
                db=ports.db,
                published_to_catalog=state.published_to_catalog,
                user=ports.user,
            )
            if _es_result:
                state.script_attachment = _es_result["script_attachment"]
                if _es_result.get("saved_package"):
                    state.saved_package = _es_result["saved_package"]
            else:
                state.script_attachment = ports.embed_script(
                    state.pack_dir,
                    script_workflow=state.script_workflow,
                    brief=state.script_brief,
                    db=ports.db,
                )
                if state.published_to_catalog:
                    state.saved_package = ports.refresh_catalog(
                        ports.db, ports.user, state.pack_dir
                    )
            await ports.progress.set_step(
                state.session_id,
                "embed_script",
                "done",
                f"已写入脚本工作流 id={state.script_attachment.get('script_workflow_id')}",
            )
        else:
            if state.use_word_extract:
                _embed_skip = "Word direct_python 模式：无需脚本工作流绑定"
            elif not state.script_workflow:
                _embed_skip = "已跳过绑定：未生成配套脚本工作流"
            else:
                _embed_skip = "已跳过绑定：未开启 embed_script_workflow"
            await ports.progress.set_step(
                state.session_id, "embed_script", "skipped", _embed_skip
            )
    if state.should_skip("workflow"):
        await ports.progress.set_step(
            state.session_id, "workflow", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "workflow"
        await ports.progress.set_step(
            state.session_id, "workflow", "running", "正在创建自动化流程…"
        )

        async def _emp_wf_msg(text: str) -> None:
            await ports.progress.set_step(state.session_id, "workflow", "running", text)

        if state.target == "pack_plus_workflow":
            _wf_result = await ports.craft_step(
                "workflow",
                db=ports.db,
                user=ports.user,
                pack_dir=state.pack_dir,
                brief=state.workflow_brief,
                workflow_name=state.workflow_name or state.planned_workflow_name,
                provider=state.provider,
                model=state.model,
                published_to_catalog=state.published_to_catalog,
                status_hook=_emp_wf_msg,
            )
            if _wf_result:
                state.workflow_attachment = _wf_result["wf_attach"]
                if _wf_result.get("saved_package"):
                    state.saved_package = _wf_result["saved_package"]
            else:
                state.workflow_attachment = await ports.attach_workflow(
                    ports.db,
                    ports.user,
                    pack_dir=state.pack_dir,
                    brief=state.workflow_brief,
                    workflow_name=state.workflow_name or state.planned_workflow_name,
                    provider=state.provider,
                    model=state.model,
                    status_hook=_emp_wf_msg,
                )
                if state.published_to_catalog:
                    state.saved_package = ports.refresh_catalog(
                        ports.db, ports.user, state.pack_dir
                    )
            _eskill_n = int(state.workflow_attachment.get("eskill_count") or 0)
            _nl_ok = (state.workflow_attachment.get("nl") or {}).get("ok")
            if _eskill_n:
                wmsg = f"已创建工作流 id={state.workflow_attachment.get('workflow_id')}；注入 {_eskill_n} 个真脚本 Skill，NL 编排{('成功' if _nl_ok else '有提示')}"
            else:
                wmsg = f"已创建工作流 id={state.workflow_attachment.get('workflow_id')}；NL 生图{('成功' if _nl_ok else '有提示')}"
            await ports.progress.set_step(
                state.session_id, "workflow", "done", wmsg[:480]
            )
        else:
            await ports.progress.set_step(
                state.session_id,
                "workflow",
                "skipped",
                "已跳过：当前为「仅员工包」模式；若需画布请选 pack_plus_workflow 并重新编排",
            )
    return False
