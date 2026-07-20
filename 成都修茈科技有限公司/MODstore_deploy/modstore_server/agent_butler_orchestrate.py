"""Butler 编排管线：自然语言 → vibe-coding 改写 Mod / 工作流 / 员工。

流程：
  snapshot（备份）→ plan（LLM 规划）→ vibe（edit_project + apply_patch）
  → validate（服务端校验）→ complete

会话槽复用 workbench_api.py 的 WORKBENCH_SESSIONS + _set_step / _fail_session /
_finalize_session_done / _persist_workbench_session_unlocked，不另起新 dict。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ─── 步骤定义 ─────────────────────────────────────────────────────────


def _butler_orchestrate_steps() -> List[Dict[str, Any]]:
    return [
        {"id": "snapshot", "label": "备份快照", "status": "pending", "message": None},
        {"id": "plan", "label": "规划改动", "status": "pending", "message": None},
        {"id": "vibe", "label": "vibe-coding 改写", "status": "pending", "message": None},
        {"id": "validate", "label": "服务端校验", "status": "pending", "message": None},
        {"id": "complete", "label": "完成", "status": "pending", "message": None},
    ]


# ─── 请求体 ───────────────────────────────────────────────────────────


class ButlerOrchestrateBody(BaseModel):
    target_type: str = Field(..., description="'mod' | 'workflow' | 'employee'")
    target_id: str = Field(..., min_length=1, max_length=256)
    brief: str = Field(..., min_length=3, max_length=8000)
    scope: Optional[str] = Field(
        None,
        description="auto | manifest | backend | frontend | workflow_graph | employee_prompt",
    )
    focus_paths: Optional[List[str]] = None
    with_snapshot: bool = True
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)


# ─── 管线 ─────────────────────────────────────────────────────────────


async def _run_butler_orchestrate_pipeline(
    sid: str,
    user_id: int,
    payload: Dict[str, Any],
) -> None:
    """异步管线主体，由 butler_orchestrate 路由用 asyncio.create_task 启动。"""
    from modstore_server.models import User, get_session_factory
    from modstore_server.workbench_api import (
        _fail_session,
        _finalize_session_done,
        _set_step,
    )

    target_type = str(payload.get("target_type") or "mod").strip()
    target_id = str(payload.get("target_id") or "").strip()
    brief = str(payload.get("brief") or "").strip()
    scope = str(payload.get("scope") or "auto").strip()
    with_snap = bool(payload.get("with_snapshot", True))
    focus_paths = payload.get("focus_paths") or None
    prov_hint = (payload.get("provider") or "").strip() or None
    mdl_hint = (payload.get("model") or "").strip() or None

    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await _fail_session(sid, "snapshot", "用户不存在")
            return

    if target_type == "mod":
        await _pipeline_mod(
            sid,
            user_id,
            target_id,
            brief,
            scope,
            focus_paths,
            with_snap,
            prov_hint,
            mdl_hint,
        )
    elif target_type == "workflow":
        await _pipeline_workflow(
            sid,
            user_id,
            target_id,
            brief,
            prov_hint,
            mdl_hint,
        )
    elif target_type == "employee":
        await _pipeline_employee(
            sid,
            user_id,
            target_id,
            brief,
            scope,
            prov_hint,
            mdl_hint,
        )
    else:
        from modstore_server.workbench_api import _fail_session as _fs

        await _fs(sid, "snapshot", f"未知 target_type: {target_type!r}")


# ─── Mod 管线 ─────────────────────────────────────────────────────────


async def _pipeline_mod(
    sid: str,
    user_id: int,
    mod_id: str,
    brief: str,
    scope: str,
    focus_paths_override: Optional[List[str]],
    with_snap: bool,
    prov_hint: Optional[str],
    mdl_hint: Optional[str],
) -> None:
    from modstore_server.infrastructure import library_paths
    from modstore_server.mod_scaffold_runner import (
        analyze_mod_employee_readiness,
        resolve_llm_provider_model_auto,
    )
    from modstore_server.models import User, get_session_factory
    from modstore_server.workbench_api import _fail_session, _finalize_session_done, _set_step

    # ── snapshot ──────────────────────────────────────────────────────
    await _set_step(sid, "snapshot", "running", "正在创建 manifest 快照…")
    snap_info: Dict[str, Any] = {}
    try:
        mod_dir = library_paths.mod_dir(mod_id)
    except (ValueError, FileNotFoundError) as e:
        await _fail_session(sid, "snapshot", f"Mod 目录不存在：{e}")
        return

    if with_snap:
        try:
            from modstore_server.mod_snapshots import capture_manifest_snapshot

            snap_info = capture_manifest_snapshot(
                mod_dir, f"butler 改写前自动备份 {time.strftime('%H:%M:%S')}"
            )
            await _set_step(sid, "snapshot", "done", f"快照 {snap_info.get('snap_id', '?')}")
        except Exception as exc:
            await _set_step(sid, "snapshot", "done", f"快照失败（继续）：{exc}")
    else:
        await _set_step(sid, "snapshot", "done", "已跳过快照")

    # ── plan ──────────────────────────────────────────────────────────
    await _set_step(sid, "plan", "running", "LLM 规划改动范围…")
    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await _fail_session(sid, "plan", "用户不存在")
            return
        prov, mdl, err = await resolve_llm_provider_model_auto(db, user, prov_hint, mdl_hint)
        if err:
            await _fail_session(sid, "plan", err)
            return

    focus_paths = focus_paths_override or _default_mod_focus(scope)
    plan_msg = f"改写 Mod {mod_id}（scope={scope}）：{brief[:120]}" f"；focus_paths={focus_paths}"
    await _set_step(sid, "plan", "done", plan_msg[:240])

    # ── vibe ──────────────────────────────────────────────────────────
    await _set_step(sid, "vibe", "running", "vibe-coding edit_project + apply_patch…")
    vibe_result = await asyncio.to_thread(
        _do_vibe_edit,
        user_id=user_id,
        root=str(mod_dir),
        brief=brief,
        focus_paths=focus_paths,
        provider=prov,
        model=mdl,
    )
    if not vibe_result.get("ok"):
        await _fail_session(sid, "vibe", vibe_result.get("error", "vibe-coding 失败"))
        return
    await _set_step(sid, "vibe", "done", "文件已改写")

    # ── validate ──────────────────────────────────────────────────────
    await _set_step(sid, "validate", "running", "分析员工可用性闭环…")
    readiness: Dict[str, Any] = {}
    try:
        sf2 = get_session_factory()
        with sf2() as db2:
            user2 = db2.query(User).filter(User.id == user_id).first()
            if user2:
                readiness = analyze_mod_employee_readiness(db2, user2, mod_dir)
    except Exception as exc:
        logger.warning("butler pipeline validate failed: %s", exc)
        readiness = {"ok": False, "error": str(exc)}
    await _set_step(sid, "validate", "done", "校验完成")

    # ── complete ──────────────────────────────────────────────────────
    artifact = {
        "target_type": "mod",
        "target_id": mod_id,
        "brief": brief,
        "snapshot": snap_info,
        "vibe": vibe_result,
        "readiness": readiness,
        "mod_dir": str(mod_dir),
    }
    await _finalize_session_done(sid, artifact)


# ─── Workflow 管线 ────────────────────────────────────────────────────


async def _pipeline_workflow(
    sid: str,
    user_id: int,
    workflow_id_str: str,
    brief: str,
    prov_hint: Optional[str],
    mdl_hint: Optional[str],
) -> None:
    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto
    from modstore_server.models import User, Workflow, get_session_factory
    from modstore_server.workbench_api import _fail_session, _finalize_session_done, _set_step
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    # snapshot — workflows have no manifest file; skip gracefully
    await _set_step(sid, "snapshot", "done", "工作流无文件快照，已跳过")

    # plan
    await _set_step(sid, "plan", "running", "解析工作流 ID…")
    try:
        wf_id = int(workflow_id_str)
    except (ValueError, TypeError):
        await _fail_session(sid, "plan", f"workflow_id 非整数：{workflow_id_str!r}")
        return

    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await _fail_session(sid, "plan", "用户不存在")
            return
        wf = db.query(Workflow).filter(Workflow.id == wf_id, Workflow.user_id == user_id).first()
        if not wf:
            await _fail_session(sid, "plan", f"工作流 {wf_id} 不存在或无权访问")
            return
        prov, mdl, err = await resolve_llm_provider_model_auto(db, user, prov_hint, mdl_hint)
        if err:
            await _fail_session(sid, "plan", err)
            return

    await _set_step(sid, "plan", "done", f"工作流 {wf_id} 已定位，使用 {prov}/{mdl}")

    # vibe — reuse apply_nl_workflow_graph which replaces the graph
    await _set_step(sid, "vibe", "running", "重新生成工作流画布节点…")
    try:
        sf2 = get_session_factory()
        with sf2() as db2:
            user2 = db2.query(User).filter(User.id == user_id).first()
            nl_result = await apply_nl_workflow_graph(
                db2,
                user2,
                workflow_id=wf_id,
                brief=brief,
                provider=prov,
                model=mdl,
            )
    except Exception as exc:
        await _fail_session(sid, "vibe", f"工作流生成失败：{exc}")
        return

    if not nl_result.get("ok"):
        await _fail_session(sid, "vibe", nl_result.get("error", "工作流生成失败"))
        return
    await _set_step(
        sid,
        "vibe",
        "done",
        f"节点 {nl_result.get('nodes_created', 0)} 条，边 {nl_result.get('edges_created', 0)} 条",
    )

    # validate
    await _set_step(sid, "validate", "done", "校验通过")

    artifact = {
        "target_type": "workflow",
        "target_id": workflow_id_str,
        "brief": brief,
        "nl_result": nl_result,
    }
    await _finalize_session_done(sid, artifact)


# ─── Employee 管线 ────────────────────────────────────────────────────


async def _pipeline_employee(
    sid: str,
    user_id: int,
    employee_id: str,
    brief: str,
    scope: str,
    prov_hint: Optional[str],
    mdl_hint: Optional[str],
) -> None:
    """员工改写：先尝试找所属 Mod 目录，用 vibe edit 聚焦员工脚本文件；
    若找不到 Mod 目录，退化为 refine_system_prompt（仅改 prompt 字段）。"""
    from modstore_server.mod_scaffold_runner import resolve_llm_provider_model_auto
    from modstore_server.models import User, get_session_factory
    from modstore_server.workbench_api import _fail_session, _finalize_session_done, _set_step

    await _set_step(sid, "snapshot", "done", "员工场景：跳过文件快照")

    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await _fail_session(sid, "plan", "用户不存在")
            return
        prov, mdl, err = await resolve_llm_provider_model_auto(db, user, prov_hint, mdl_hint)
        if err:
            await _fail_session(sid, "plan", err)
            return

    # Attempt to locate the Mod directory that owns this employee
    mod_dir, focus_paths = _locate_employee_mod(employee_id, scope)

    if mod_dir is not None:
        # Full vibe edit on the employee-related files inside the Mod
        await _set_step(sid, "plan", "done", f"定位到 Mod 目录 {mod_dir.name}，改写员工脚本")
        await _set_step(sid, "vibe", "running", "vibe-coding 改写员工脚本…")
        vibe_result = await asyncio.to_thread(
            _do_vibe_edit,
            user_id=user_id,
            root=str(mod_dir),
            brief=brief,
            focus_paths=focus_paths,
            provider=prov,
            model=mdl,
        )
        if not vibe_result.get("ok"):
            await _fail_session(sid, "vibe", vibe_result.get("error", "vibe-coding 失败"))
            return
        await _set_step(sid, "vibe", "done", "员工脚本已改写")
        await _set_step(sid, "validate", "done", "校验完成")
        artifact = {
            "target_type": "employee",
            "target_id": employee_id,
            "brief": brief,
            "vibe": vibe_result,
        }
    else:
        # Fallback: only refine system_prompt field via LLM
        await _set_step(sid, "plan", "done", "未找到 Mod 目录，降级为 system_prompt 优化")
        await _set_step(sid, "vibe", "running", "优化员工 system_prompt…")
        refine_result = await asyncio.to_thread(
            _do_refine_system_prompt,
            employee_id=employee_id,
            brief=brief,
            provider=prov,
            model=mdl,
        )
        if not refine_result.get("ok"):
            await _fail_session(sid, "vibe", refine_result.get("error", "system_prompt 优化失败"))
            return
        await _set_step(sid, "vibe", "done", "system_prompt 已优化")
        await _set_step(sid, "validate", "done", "校验完成")
        artifact = {
            "target_type": "employee",
            "target_id": employee_id,
            "brief": brief,
            "refine": refine_result,
        }

    await _finalize_session_done(sid, artifact)


# ─── 辅助函数 ─────────────────────────────────────────────────────────


def _default_mod_focus(scope: str) -> List[str]:
    mapping: Dict[str, List[str]] = {
        "manifest": ["manifest.json"],
        "backend": ["backend/blueprints.py", "backend/employees"],
        "frontend": ["config/frontend_spec.json", "frontend/views"],
        "employee_prompt": ["backend/employees"],
    }
    if scope in mapping:
        return mapping[scope]
    # auto / anything else → broad default
    return [
        "manifest.json",
        "backend/blueprints.py",
        "backend/employees",
        "config",
        "frontend/views",
    ]


def _locate_employee_mod(
    employee_id: str,
    scope: str,
) -> tuple:
    """Try to find the Mod directory that contains this employee.

    Returns (mod_dir: Path | None, focus_paths: list[str]).
    """
    from pathlib import Path

    try:
        from modstore_server.infrastructure import library_paths

        lib = library_paths.resolved_library()
        mods_root = Path(lib)
        for mod_dir in mods_root.iterdir():
            if not mod_dir.is_dir():
                continue
            # Check manifest for employee declarations
            manifest_path = mod_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            import json

            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            employees = data.get("workflow_employees") or []
            for emp in employees:
                if not isinstance(emp, dict):
                    continue
                eid = str(emp.get("id") or emp.get("employee_id") or "").strip()
                if eid and (eid == employee_id or employee_id.startswith(eid)):
                    focus = [f"backend/employees/{eid}.py", f"backend/employees/{eid}"]
                    return mod_dir, focus
    except Exception:
        pass
    return None, []


def _do_vibe_edit(
    *,
    user_id: int,
    root: str,
    brief: str,
    focus_paths: Optional[List[str]],
    provider: str,
    model: str,
) -> Dict[str, Any]:
    """Synchronous vibe-coding edit_project + apply_patch (runs in thread)."""
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_vibe_coder,
            patch_to_dict,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"vibe-coding 集成未安装: {exc}"}

    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    try:
        with sf() as session:
            try:
                coder = get_vibe_coder(
                    session=session,
                    user_id=int(user_id or 0),
                    provider=provider,
                    model=model,
                )
            except VibeIntegrationError as exc:
                return {"ok": False, "error": str(exc)}

            try:
                if focus_paths:
                    patch = coder.edit_project(brief, root=root, focus_paths=focus_paths)
                else:
                    patch = coder.edit_project(brief, root=root)
            except TypeError:
                patch = coder.edit_project(brief, root=root)

            apply_result = coder.apply_patch(patch, root=root, dry_run=False)
    except Exception as exc:
        logger.exception("_do_vibe_edit failed")
        return {"ok": False, "error": f"vibe edit 失败: {exc}"}

    apply_dict: Dict[str, Any]
    if hasattr(apply_result, "to_dict") and callable(apply_result.to_dict):
        apply_dict = dict(apply_result.to_dict())
    else:
        apply_dict = {
            "applied": getattr(apply_result, "applied", None),
            "errors": list(getattr(apply_result, "errors", []) or []),
        }
    ok = bool(apply_dict.get("applied", True)) and not apply_dict.get("errors")
    return {
        "ok": ok,
        "root": root,
        "patch": patch_to_dict(patch) if ok else {},
        "apply": apply_dict,
    }


def _do_refine_system_prompt(
    *,
    employee_id: str,
    brief: str,
    provider: str,
    model: str,
) -> Dict[str, Any]:
    """Fallback: refine employee system_prompt via LLM (synchronous wrapper)."""
    import asyncio as _asyncio

    async def _inner() -> Dict[str, Any]:
        try:
            from modstore_server.employee_ai_pipeline import refine_system_prompt  # type: ignore
            from modstore_server.script_agent.llm_client import RealLlmClient  # type: ignore

            llm = RealLlmClient(provider, model=model)
            result, err = await refine_system_prompt(
                current_prompt="",
                instruction=brief,
                role_context=f"员工 ID: {employee_id}",
                llm=llm,
            )
            if err or result is None:
                return {"ok": False, "error": err or "refine 失败"}
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_asyncio.run, _inner())
                return future.result(timeout=120)
        return loop.run_until_complete(_inner())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


__all__ = [
    "ButlerOrchestrateBody",
    "_butler_orchestrate_steps",
    "_run_butler_orchestrate_pipeline",
]
