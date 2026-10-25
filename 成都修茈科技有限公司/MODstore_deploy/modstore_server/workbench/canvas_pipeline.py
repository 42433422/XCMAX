"""Canvas pipeline for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Dict, cast

from modstore_server.models import Workflow, WorkflowEdge, WorkflowNode
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.intent import _enrich_artifact_skill_aliases
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class CanvasPorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    generate_graph: Callable[..., Awaitable[dict[str, Any]]]
    sandbox: Callable[..., dict[str, Any]]
    record_sandbox: Callable[..., Any]


async def _run_workbench_canvas_pipeline(
    sid,
    payload,
    intent,
    brief,
    prov,
    mdl,
    gen_wf_graph,
    db,
    user,
    *,
    ports: CanvasPorts,
):
    name = (payload.get("workflow_name") or "").strip()
    if not name:
        await ports.progress.fail(sid, "generate", "请填写 Skill 组名称")
        return
    plan = (payload.get("plan_notes") or "").strip()
    full_desc = brief
    if plan:
        full_desc = f"{brief}\n\n—— 框架与排期 ——\n{plan}"
    _skill_current_step = "generate"
    try:
        await ports.progress.set_step(sid, "generate", "running")
        wf = Workflow(
            user_id=cast(int, user.id),
            name=name,
            description=full_desc,
            is_active=True,
            kind="skill_group",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        wid = wf.id
        nl_meta: Dict[str, Any] = {
            "generate_workflow_graph": gen_wf_graph,
            "nodes_created": 0,
            "edges_created": 0,
            "sandbox_ok": True,
            "validation_errors": [],
            "llm_warnings": [],
        }
        if gen_wf_graph:

            async def _workflow_graph_msg(text: str) -> None:
                await ports.progress.set_step(sid, "generate", "running", text)

            nl = await ports.generate_graph(
                db,
                user,
                workflow_id=wid,
                brief=full_desc,
                provider=prov,
                model=mdl,
                status_hook=_workflow_graph_msg,
            )
            if not nl.get("ok"):
                try:
                    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wid).delete(
                        synchronize_session=False
                    )
                    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wid).delete(
                        synchronize_session=False
                    )
                    db.query(Workflow).filter(Workflow.id == wid).delete(synchronize_session=False)
                    db.commit()
                except RECOVERABLE_ERRORS:
                    db.rollback()
                await ports.progress.fail(sid, "generate", nl.get("error") or "工作流图生成失败")
                async with ports.sessions.lock:
                    sess = ports.sessions.data.get(sid)
                    if sess:
                        sess["artifact"] = None
                        ports.sessions.persist(sid)
                return
            nl_meta.update(
                {
                    "nodes_created": int(nl.get("nodes_created") or 0),
                    "edges_created": int(nl.get("edges_created") or 0),
                    "sandbox_ok": bool(nl.get("sandbox_ok")),
                    "validation_errors": nl.get("validation_errors") or [],
                    "llm_warnings": nl.get("llm_warnings") or [],
                }
            )
        await ports.progress.set_step(sid, "generate", "done")
        _skill_current_step = "validate"
        await ports.progress.set_step(sid, "validate", "running")
        node_count = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wid).count()
        if node_count == 0:
            detail = "新建工作流暂无节点，进入画布后再添加节点并运行沙盒校验"
            async with ports.sessions.lock:
                sess = ports.sessions.data.get(sid)
                if sess:
                    sess["sandbox_report"] = None
                    sess["validate_warnings"] = []
                    ports.sessions.persist(sid)
            await ports.progress.set_step(sid, "validate", "done", detail)
        else:
            report = ports.sandbox(
                wid,
                {},
                mock_employees=True,
                validate_only=True,
                user_id=cast(int, user.id),
            )
            ports.record_sandbox(
                db,
                workflow_id=wid,
                user_id=cast(int, user.id),
                report=report,
                validate_only=True,
                mock_employees=True,
            )
            errs = report.get("errors") or []
            warns = report.get("warnings") or []
            detail = None
            if errs:
                detail = "校验提示（可进画布修改）：" + "；".join((str(e) for e in errs[:8]))
            elif warns:
                detail = "提示：" + "；".join((str(w) for w in warns[:6]))
            async with ports.sessions.lock:
                sess = ports.sessions.data.get(sid)
                if sess:
                    sess["sandbox_report"] = report
                    sess["validate_warnings"] = warns
                    ports.sessions.persist(sid)
            if not errs:
                run_report = ports.sandbox(
                    wid,
                    {},
                    mock_employees=True,
                    validate_only=False,
                    user_id=cast(int, user.id),
                )
                ports.record_sandbox(
                    db,
                    workflow_id=wid,
                    user_id=cast(int, user.id),
                    report=run_report,
                    validate_only=False,
                    mock_employees=True,
                )
                nl_meta["sandbox_ok"] = bool(run_report.get("ok"))
            await ports.progress.set_step(sid, "validate", "done", detail)
        _skill_current_step = "complete"
        await ports.progress.set_step(sid, "complete", "done")
        await ports.progress.finish(
            sid,
            _enrich_artifact_skill_aliases({"workflow_id": wid, "workflow_name": name, **nl_meta}),
        )
    except RECOVERABLE_ERRORS as e:
        _LOG.exception(
            "workbench skill pipeline failed session=%s step=%s",
            sid,
            _skill_current_step,
        )
        await ports.progress.fail(sid, _skill_current_step, str(e)[:2000])
    return
