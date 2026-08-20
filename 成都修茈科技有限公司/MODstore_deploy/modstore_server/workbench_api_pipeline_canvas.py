"""Workbench canvas pipeline branch."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_workbench_canvas_pipeline(
    sid, payload, intent, brief, prov, mdl, gen_wf_graph, db, user
):
    name = (payload.get("workflow_name") or "").strip()
    if not name:
        await _facade()._fail_session(sid, "generate", "请填写 Skill 组名称")
        return
    plan = (payload.get("plan_notes") or "").strip()
    full_desc = brief
    if plan:
        full_desc = f"{brief}\n\n—— 框架与排期 ——\n{plan}"
    _skill_current_step = "generate"
    try:
        await _facade()._set_step(sid, "generate", "running")
        wf = _facade().Workflow(
            user_id=user.id,
            name=name,
            description=full_desc,
            is_active=True,
            kind="skill_group",
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)
        wid = wf.id
        nl_meta: _facade().Dict[str, _facade().Any] = {
            "generate_workflow_graph": gen_wf_graph,
            "nodes_created": 0,
            "edges_created": 0,
            "sandbox_ok": True,
            "validation_errors": [],
            "llm_warnings": [],
        }
        if gen_wf_graph:

            async def _workflow_graph_msg(text: str) -> None:
                await _facade()._set_step(sid, "generate", "running", text)

            nl = await _facade().apply_nl_workflow_graph(
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
                    db.query(_facade().WorkflowEdge).filter(
                        _facade().WorkflowEdge.workflow_id == wid
                    ).delete(synchronize_session=False)
                    db.query(_facade().WorkflowNode).filter(
                        _facade().WorkflowNode.workflow_id == wid
                    ).delete(synchronize_session=False)
                    db.query(_facade().Workflow).filter(_facade().Workflow.id == wid).delete(
                        synchronize_session=False
                    )
                    db.commit()
                except RECOVERABLE_ERRORS:
                    db.rollback()
                await _facade()._fail_session(
                    sid, "generate", nl.get("error") or "工作流图生成失败"
                )
                async with _facade()._SESSION_LOCK:
                    sess = _facade().WORKBENCH_SESSIONS.get(sid)
                    if sess:
                        sess["artifact"] = None
                        _facade()._persist_workbench_session_unlocked(sid)
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
        await _facade()._set_step(sid, "generate", "done")
        _skill_current_step = "validate"
        await _facade()._set_step(sid, "validate", "running")
        node_count = (
            db.query(_facade().WorkflowNode)
            .filter(_facade().WorkflowNode.workflow_id == wid)
            .count()
        )
        if node_count == 0:
            detail = "新建工作流暂无节点，进入画布后再添加节点并运行沙盒校验"
            async with _facade()._SESSION_LOCK:
                sess = _facade().WORKBENCH_SESSIONS.get(sid)
                if sess:
                    sess["sandbox_report"] = None
                    sess["validate_warnings"] = []
                    _facade()._persist_workbench_session_unlocked(sid)
            await _facade()._set_step(sid, "validate", "done", detail)
        else:
            report = _facade().run_workflow_sandbox(
                wid, {}, mock_employees=True, validate_only=True, user_id=user.id
            )
            _facade().record_workflow_sandbox_run(
                db,
                workflow_id=wid,
                user_id=user.id,
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
            async with _facade()._SESSION_LOCK:
                sess = _facade().WORKBENCH_SESSIONS.get(sid)
                if sess:
                    sess["sandbox_report"] = report
                    sess["validate_warnings"] = warns
                    _facade()._persist_workbench_session_unlocked(sid)
            if not errs:
                run_report = _facade().run_workflow_sandbox(
                    wid, {}, mock_employees=True, validate_only=False, user_id=user.id
                )
                _facade().record_workflow_sandbox_run(
                    db,
                    workflow_id=wid,
                    user_id=user.id,
                    report=run_report,
                    validate_only=False,
                    mock_employees=True,
                )
                nl_meta["sandbox_ok"] = bool(run_report.get("ok"))
            await _facade()._set_step(sid, "validate", "done", detail)
        _skill_current_step = "complete"
        await _facade()._set_step(sid, "complete", "done")
        await _facade()._finalize_session_done(
            sid,
            _facade()._enrich_artifact_skill_aliases(
                {"workflow_id": wid, "workflow_name": name, **nl_meta}
            ),
        )
    except RECOVERABLE_ERRORS as e:
        _facade()._LOG.exception(
            "workbench skill pipeline failed session=%s step=%s",
            sid,
            _skill_current_step,
        )
        await _facade()._fail_session(sid, _skill_current_step, str(e)[:2000])
    return
