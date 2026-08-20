# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _default_steps(
    intent: str, execution_mode: str = "workflow", *, employee_target: str = "pack_only"
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    intent = _facade()._canonical_workbench_intent(intent)
    if execution_mode == "script":
        return [
            {"id": "spec", "label": "理解任务", "status": "pending", "message": None},
            {
                "id": "generate",
                "label": "生成处理脚本",
                "status": "pending",
                "message": None,
            },
            {
                "id": "validate",
                "label": "安全检查",
                "status": "pending",
                "message": None,
            },
            {
                "id": "run",
                "label": "运行并生成文件",
                "status": "pending",
                "message": None,
            },
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    if intent == "mod":
        return [
            {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
            {
                "id": "manifest",
                "label": "生成蓝图与 JSON",
                "status": "pending",
                "message": None,
            },
            {
                "id": "repo",
                "label": "新建 Mod 仓库",
                "status": "pending",
                "message": None,
            },
            {
                "id": "industry",
                "label": "生成行业卡片",
                "status": "pending",
                "message": None,
            },
            {
                "id": "employees",
                "label": "创建员工骨架",
                "status": "pending",
                "message": None,
            },
            {
                "id": "employee_impls",
                "label": "生成员工脚本",
                "status": "pending",
                "message": None,
            },
            {
                "id": "workflows",
                "label": "生成员工 Skill 组（画布编排）",
                "status": "pending",
                "message": None,
            },
            {
                "id": "register_packs",
                "label": "登记员工包并修复图",
                "status": "pending",
                "message": None,
            },
            {
                "id": "api",
                "label": "生成/绑定 API 节点",
                "status": "pending",
                "message": None,
            },
            {
                "id": "workflow_sandbox",
                "label": "工作流沙箱测试",
                "status": "pending",
                "message": None,
            },
            {
                "id": "mod_sandbox",
                "label": "Mod 沙箱测试",
                "status": "pending",
                "message": None,
            },
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    base = [
        {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
        {"id": "generate", "label": "生成产物", "status": "pending", "message": None},
        {"id": "validate", "label": "服务端校验", "status": "pending", "message": None},
    ]
    if intent == "employee":
        base.insert(
            1,
            {
                "id": "employee_plan",
                "label": "规划一站式员工",
                "status": "pending",
                "message": None,
            },
        )
        base.extend(
            [
                {
                    "id": "script_workflow",
                    "label": "生成配套小程序",
                    "status": "pending",
                    "message": None,
                },
                {
                    "id": "embed_script",
                    "label": "绑定到员工",
                    "status": "pending",
                    "message": None,
                },
            ]
        )
        if (employee_target or "").strip().lower() == "pack_plus_workflow":
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
        else:
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
    base.append({"id": "complete", "label": "完成", "status": "pending", "message": None})
    if intent == _facade().CANVAS_SKILL_INTENT:
        base[1]["label"] = "创建 Skill 组"
    return base


async def _set_step(
    sid: str,
    step_id: str,
    status: str,
    message: _facade().Optional[_facade().Union[str, dict]] = None,
) -> None:
    """Update a workbench step.

    ``message`` may now be either a plain string (legacy) or a structured
    dict with keys: ``summary``, ``round``, ``current_tool``, ``todos``,
    ``slow_hint``.  The Vue frontend uses ``summary`` as the fallback text
    when it encounters a dict.

    ``status`` may be: pending / running / done / skipped / error.
    ``skipped`` is distinct from ``done`` — it means the step was not
    applicable and was bypassed, not that it completed successfully.
    """
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        for s in sess["steps"]:
            if s["id"] == step_id:
                prev_status = s.get("status")
                if prev_status in ("done", "error") and status not in (
                    "done",
                    "error",
                    "skipped",
                ):
                    break
                if prev_status == "running" and status == "pending":
                    break
                s["status"] = status
                if message is not None:
                    s["message"] = message
                if status == "running" and prev_status != "running":
                    s["started_at"] = (
                        _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z"
                    )
                elif status in ("done", "error", "skipped"):
                    s.pop("started_at", None)
                break
        _facade()._persist_workbench_session_unlocked(sid)
    if status in ("done", "error", "skipped"):
        _facade()._record_craft_step_skip_metric(step_id, status, sess)


def _record_craft_step_skip_metric(
    step_id: str, status: str, sess: _facade().Optional[dict]
) -> None:
    if status not in ("skipped",):
        return
    try:
        from modstore_server.craft_executor import (
            _record_craft_execution,
            craft_step_to_employee_id,
        )

        employee_id = craft_step_to_employee_id(step_id)
        if not employee_id:
            return
        user_id = 0
        if sess:
            user_id = sess.get("user_id", 0)
        _record_craft_execution(
            employee_id=employee_id,
            user_id=user_id,
            task=f"craft pipeline step: {step_id}",
            status="skipped",
            duration_ms=0,
            llm_tokens=0,
        )
    except RECOVERABLE_ERRORS:
        pass


async def _fail_session(sid: str, step_id: str, err: str) -> None:
    msg = (err or "步骤失败").strip()[:1000]
    if step_id == "workflow_sandbox" and msg:
        try:
            from modstore_server.craft_failure_signals import emit_craft_step_failure

            async with _facade()._SESSION_LOCK:
                _facade()._hydrate_workbench_session_unlocked(sid)
                sess = _facade().WORKBENCH_SESSIONS.get(sid) or {}
            emit_craft_step_failure(
                step_id="workflow_sandbox",
                error=msg,
                user_id=int(sess.get("user_id") or 0),
            )
        except RECOVERABLE_ERRORS:
            _facade()._LOG.debug("workflow_sandbox fail signal emit skipped", exc_info=True)
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        sess["status"] = "error"
        sess["error"] = msg
        updated = False
        for s in sess["steps"]:
            if s["id"] == step_id and s["status"] == "running":
                s["status"] = "error"
                s["message"] = msg
                updated = True
                break
        if not updated:
            for s in sess["steps"]:
                if s["id"] == step_id:
                    s["status"] = "error"
                    s["message"] = msg
                    break
        _facade()._persist_workbench_session_unlocked(sid)


async def _finalize_session_done(sid: str, artifact: _facade().Dict[str, _facade().Any]) -> None:
    """Atomically write artifact + status=done.

    Guards against the case where a pipeline branch returns early without
    explicitly completing every step: any step still in pending/running is
    force-promoted to done so the frontend never sees status=done alongside
    non-terminal steps (which would cause premature navigation).

    If the session already ended in ``error`` (e.g. :func:`_fail_session`), this
    function is a no-op so we never overwrite a failure with a false ``done``.
    """
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        if sess.get("status") == "error":
            _facade()._LOG.warning(
                "finalize_session_done skipped: session already error sid=%s err=%s",
                sid,
                (sess.get("error") or "")[:200],
            )
            return
        for s in sess.get("steps") or []:
            if s.get("status") not in ("done", "error", "skipped"):
                _facade()._LOG.warning(
                    "workbench session=%s step=%s was still in state=%s at finalize; marking skipped",
                    sid,
                    s.get("id"),
                    s.get("status"),
                )
                s["status"] = "skipped"
                if not s.get("message"):
                    s["message"] = "管线收尾时标记跳过"
                s.pop("started_at", None)
        sess["status"] = "done"
        sess["artifact"] = artifact
        _facade()._persist_workbench_session_unlocked(sid)
