# mypy: disable-error-code="assignment"
# isort: skip_file
# ruff: noqa: E402, F401
"""工作台 AI 编排：内存会话 + 磁盘持久化（多 worker 可读）+ 异步执行 + GET 轮询。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modstore_server.api.deps import _get_current_user
from modstore_server.craft_executor import dispatch_craft_step as _dispatch_craft_step
from modstore_server.employee_ai_scaffold import (
    build_employee_pack_zip,
    normalize_editor_manifest_for_registry,
)
from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import resolve_api_key, resolve_base_url
from modstore_server.mod_employee_impl_scaffold import (
    _fallback_employee_py,
    generate_mod_employee_impls_async,
    sanitize_employee_stem,
)
from modstore_server.mod_scaffold_runner import (
    analyze_mod_employee_readiness,
    attach_nl_workflow_to_employee_pack_dir,
    create_mod_suite_workflows_async,
    employee_pack_consistency_warnings,
    generate_mod_suite_blueprint_async,
    generate_workflow_for_intent,
    import_mod_suite_repository,
    materialize_employee_pack_if_missing,
    mod_compileall_warnings,
    modstore_library_path,
    patch_workflow_graph_employee_nodes,
    register_mod_employee_packs_async,
    resolve_llm_provider_model_auto,
    run_employee_ai_scaffold_async,
    run_mod_ai_scaffold_async,
    run_mod_suite_mod_sandbox,
    run_mod_suite_workflow_sandboxes,
    write_mod_suite_blueprint,
    write_mod_suite_industry_card,
    write_mod_suite_ui_shell,
)
from modstore_server.models import (
    CatalogItem,
    ScriptWorkflow,
    ScriptWorkflowRun,
    ScriptWorkflowVersion,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.workbench_delivery_bridge import (  # noqa: F401
    get_workbench_session_snapshot,
    start_workbench_session_for_user,
)
from modstore_server.workbench_research import (
    build_research_context,
    fetch_web_search_context_pack,
)
from modstore_server.workbench_script_runner import run_script_agent_job, run_script_job
from modstore_server.workflow_engine import run_workflow_sandbox
from modstore_server.workflow_nl_graph import apply_nl_workflow_graph
from modstore_server.workflow_sandbox_state import record_workflow_sandbox_run

try:
    import edge_tts as _edge_tts

    _EDGE_TTS = _edge_tts
except ImportError:  # pragma: no cover - 可选依赖
    _EDGE_TTS = None

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

_LOG = logging.getLogger(__name__)

_MAX_EMPLOYEES_FOR_LLM = 10

WORKBENCH_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSION_LOCK = asyncio.Lock()

# 画布编排 intent：`workflow` 已规范为 `skill`（Skill 组）
CANVAS_SKILL_INTENT = "skill"


from modstore_server.workbench_api_part01 import (
    _contains_uploaded_docx as _contains_uploaded_docx,
    _canonical_workbench_intent as _canonical_workbench_intent,
    _employee_asset_publish_catalog_from_env as _employee_asset_publish_catalog_from_env,
    _enrich_artifact_skill_aliases as _enrich_artifact_skill_aliases,
    _workbench_session_store_dir as _workbench_session_store_dir,
    _workbench_session_file as _workbench_session_file,
    _persist_workbench_session_unlocked as _persist_workbench_session_unlocked,
    _load_workbench_session_unlocked as _load_workbench_session_unlocked,
    _hydrate_workbench_session_unlocked as _hydrate_workbench_session_unlocked,
    _persist_workbench_session as _persist_workbench_session,
    EmployeeAiDraftBody as EmployeeAiDraftBody,
    EmployeeAiRefinePromptBody as EmployeeAiRefinePromptBody,
    WorkbenchResearchBody as WorkbenchResearchBody,
    WorkbenchWebSearchBody as WorkbenchWebSearchBody,
    WorkbenchSessionCreateBody as WorkbenchSessionCreateBody,
    _parse_workbench_session_create as _parse_workbench_session_create,
    _default_steps as _default_steps,
    _set_step as _set_step,
    _record_craft_step_skip_metric as _record_craft_step_skip_metric,
    _fail_session as _fail_session,
    _finalize_session_done as _finalize_session_done,
)


from modstore_server.workbench_api_part02 import (
    _check_vibe_coding_capability as _check_vibe_coding_capability,
    _employee_handlers_contract_ok as _employee_handlers_contract_ok,
    _employee_quality_extras as _employee_quality_extras,
    _refresh_employee_pack_catalog_zip as _refresh_employee_pack_catalog_zip,
    _assert_employee_catalog_registered as _assert_employee_catalog_registered,
    _load_registry_aligned_employee_manifest as _load_registry_aligned_employee_manifest,
)


from modstore_server.workbench_api_part03 import (
    _employee_pack_workflow_reference_report as _employee_pack_workflow_reference_report,
    _write_workflow_reference_report as _write_workflow_reference_report,
    _cleanup_mod_pipeline_resources as _cleanup_mod_pipeline_resources,
    _script_workflow_brief as _script_workflow_brief,
    _embed_script_workflow_in_employee_pack as _embed_script_workflow_in_employee_pack,
    _strip_json_fence as _strip_json_fence,
    _fallback_employee_orchestration_plan as _fallback_employee_orchestration_plan,
    _build_employee_orchestration_plan as _build_employee_orchestration_plan,
    _planning_record as _planning_record,
    _read_workbench_uploads as _read_workbench_uploads,
    _commit_script_workflow_from_result as _commit_script_workflow_from_result,
    _resolve_default_llm_for_pipeline as _resolve_default_llm_for_pipeline,
    _pipeline_task_failsafe as _pipeline_task_failsafe,
)


from modstore_server.workbench_api_pipeline_script import _run_workbench_script_pipeline
from modstore_server.workbench_api_pipeline_mod import _run_workbench_mod_pipeline
from modstore_server.workbench_api_pipeline_employee import (
    _run_workbench_employee_pipeline,
)
from modstore_server.workbench_api_pipeline_canvas import _run_workbench_canvas_pipeline


async def _run_pipeline(sid: str, user_id: int, payload: Dict[str, Any]) -> None:
    intent = _canonical_workbench_intent(str(payload.get("intent") or ""))
    payload["intent"] = intent
    execution_mode = str(payload.get("execution_mode") or "workflow")
    brief = (payload.get("brief") or "").strip()
    prov = (payload.get("provider") or "").strip() or None
    mdl = (payload.get("model") or "").strip() or None
    replace = bool(payload.get("replace", True))
    gen_wf_graph = bool(payload.get("generate_workflow_graph", True))
    generate_frontend = bool(payload.get("generate_frontend", True))

    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await _fail_session(sid, "spec", "用户不存在")
            return

        if not prov or not mdl:
            _auto_prov, _auto_mdl = await _resolve_default_llm_for_pipeline(db, user_id)
            if not prov:
                prov = _auto_prov
            if not mdl:
                mdl = _auto_mdl

        from modstore_server.employee_brief_utils import extract_routing_brief

        _routing_brief = extract_routing_brief(payload, fallback=brief)

        await _set_step(sid, "spec", "running")

        _spec_result = await _dispatch_craft_step(
            "spec",
            db=db,
            user_id=user.id,
            payload=payload,
            brief=brief,
            routing_brief=_routing_brief,
            prov=prov,
            mdl=mdl,
        )
        spec_warnings: List[str] = []
        _brief_domain_hints: List[str] = []
        _structured_requirement: Dict[str, Any] = {}
        if _spec_result is not None:
            spec_warnings = _spec_result.get("spec_warnings", [])
            _brief_domain_hints = _spec_result.get("brief_domain_hints", [])
            _structured_requirement = _spec_result.get("structured_requirement") or {}
            if _spec_result.get("routing_brief"):
                _routing_brief = (
                    str(_spec_result.get("routing_brief") or _routing_brief).strip()
                    or _routing_brief
                )
        spec_msg = "用户校验通过"
        if spec_warnings:
            spec_msg += "；" + "；".join(spec_warnings[:3])
        if _brief_domain_hints:
            spec_msg += f"；识别领域：{'、'.join(_brief_domain_hints[:4])}"

        async with _SESSION_LOCK:
            sess = WORKBENCH_SESSIONS.get(sid)
            if sess:
                sess["spec_warnings"] = spec_warnings
                sess["spec_domain_hints"] = _brief_domain_hints
                sess["structured_requirement"] = _structured_requirement
                sess["routing_brief"] = _routing_brief
                _persist_workbench_session_unlocked(sid)

        await _set_step(sid, "spec", "done", spec_msg[:480])

        if execution_mode == "script":
            await _run_workbench_script_pipeline(
                sid, user_id, payload, execution_mode, brief, prov, mdl, db
            )
            return

        if intent == "mod":
            await _run_workbench_mod_pipeline(
                sid,
                payload,
                intent,
                brief,
                prov,
                mdl,
                replace,
                generate_frontend,
                db,
                user,
            )
            return

        if intent == "employee":
            await _run_workbench_employee_pipeline(
                sid, user_id, payload, intent, brief, prov, mdl, replace, db, user
            )
            return

        if intent == CANVAS_SKILL_INTENT:
            await _run_workbench_canvas_pipeline(
                sid, payload, intent, brief, prov, mdl, gen_wf_graph, db, user
            )
            return

        await _fail_session(sid, "spec", f"未知 intent: {intent}")


from modstore_server.workbench_api_part04 import (
    workbench_web_search as workbench_web_search,
    workbench_research_context as workbench_research_context,
    create_workbench_session as create_workbench_session,
    create_workbench_script_session as create_workbench_script_session,
    get_workbench_session as get_workbench_session,
    download_workbench_session_file as download_workbench_session_file,
    retry_workbench_session as retry_workbench_session,
    WorkbenchEdgeTtsBody as WorkbenchEdgeTtsBody,
    WorkbenchUnifiedTtsBody as WorkbenchUnifiedTtsBody,
    WorkbenchVibeCodeSkillBody as WorkbenchVibeCodeSkillBody,
    workbench_vibe_code_skill as workbench_vibe_code_skill,
    _publish_vibe_skill_via_local_modstore as _publish_vibe_skill_via_local_modstore,
    _edge_tts_rate_str as _edge_tts_rate_str,
    _edge_tts_stream_chunks as _edge_tts_stream_chunks,
    workbench_unified_tts as workbench_unified_tts,
    workbench_edge_tts as workbench_edge_tts,
    workbench_edge_tts_stream as workbench_edge_tts_stream,
)

# ── AI Employee Draft Pipeline (SSE) ─────────────────────────────────────────


from modstore_server.workbench_api_part05 import (
    employee_ai_draft as employee_ai_draft,
    employee_ai_refine_prompt as employee_ai_refine_prompt,
    EmployeeBenchRequest as EmployeeBenchRequest,
    EmployeePublishRequest as EmployeePublishRequest,
    employee_bench_test as employee_bench_test,
    employee_publish as employee_publish,
    EmployeeSyncTestRequest as EmployeeSyncTestRequest,
    employee_sync_test as employee_sync_test,
    EmployeeSaveBody as EmployeeSaveBody,
)


from modstore_server.workbench_api_part06 import (
    employee_save_impl as employee_save_impl,
    employee_save as employee_save,
    EmployeeExportBody as EmployeeExportBody,
    employee_export as employee_export,
    DispatchRequest as DispatchRequest,
    dispatch_task as dispatch_task,
)
