"""Workbench HTTP contracts and explicit composition of delivery services."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
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
from modstore_server.mod_employee_impl_scaffold import generate_mod_employee_impls_async
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
from modstore_server.models import User, get_session_factory
from modstore_server.workbench import (
    canvas_pipeline,
    coordinator,
    employee_commands,
    employee_delivery,
    employee_drafts,
    employee_generation,
    employee_packages,
    employee_pipeline,
    employee_planning,
    employee_quality,
    employee_registration,
    employee_runtime_checks,
    employee_workflows,
    planning,
    research_api,
    script_pipeline,
    session_api,
    sessions,
    speech_api,
    suite_pipeline,
    task_api,
    vibe_api,
)
from modstore_server.workbench.catalog import (
    _assert_employee_catalog_registered as _assert_employee_catalog_registered,
)
from modstore_server.workbench.catalog import (
    _employee_pack_workflow_reference_report as _employee_pack_workflow_reference_report,
)
from modstore_server.workbench.catalog import (
    _load_registry_aligned_employee_manifest as _load_registry_aligned_employee_manifest,
)
from modstore_server.workbench.catalog import (
    _refresh_employee_pack_catalog_zip as _refresh_employee_pack_catalog_zip,
)
from modstore_server.workbench.catalog import (
    _write_workflow_reference_report as _write_workflow_reference_report,
)
from modstore_server.workbench.delivery_sessions import WorkbenchSessions
from modstore_server.workbench.intent import CANVAS_SKILL_INTENT as CANVAS_SKILL_INTENT
from modstore_server.workbench.intent import (
    _canonical_workbench_intent as _canonical_workbench_intent,
)
from modstore_server.workbench.intent import _contains_uploaded_docx as _contains_uploaded_docx
from modstore_server.workbench.intent import _default_steps as _default_steps
from modstore_server.workbench.intent import (
    _employee_asset_publish_catalog_from_env as _employee_asset_publish_catalog_from_env,
)
from modstore_server.workbench.intent import (
    _enrich_artifact_skill_aliases as _enrich_artifact_skill_aliases,
)
from modstore_server.workbench.package_quality import (
    _employee_handlers_contract_ok as _employee_handlers_contract_ok,
)
from modstore_server.workbench.package_quality import (
    _employee_quality_extras as _employee_quality_extras,
)
from modstore_server.workbench.planning import (
    _fallback_employee_orchestration_plan as _fallback_employee_orchestration_plan,
)
from modstore_server.workbench.planning import _planning_record as _planning_record
from modstore_server.workbench.planning import (
    _resolve_default_llm_for_pipeline as _resolve_default_llm_for_pipeline,
)
from modstore_server.workbench.planning import _script_workflow_brief as _script_workflow_brief
from modstore_server.workbench.planning import _strip_json_fence as _strip_json_fence
from modstore_server.workbench.schemas import DispatchRequest as DispatchRequest
from modstore_server.workbench.schemas import EmployeeAiDraftBody as EmployeeAiDraftBody
from modstore_server.workbench.schemas import (
    EmployeeAiRefinePromptBody as EmployeeAiRefinePromptBody,
)
from modstore_server.workbench.schemas import EmployeeBenchRequest as EmployeeBenchRequest
from modstore_server.workbench.schemas import EmployeeExportBody as EmployeeExportBody
from modstore_server.workbench.schemas import EmployeePublishRequest as EmployeePublishRequest
from modstore_server.workbench.schemas import EmployeeSaveBody as EmployeeSaveBody
from modstore_server.workbench.schemas import EmployeeSyncTestRequest as EmployeeSyncTestRequest
from modstore_server.workbench.schemas import WorkbenchEdgeTtsBody as WorkbenchEdgeTtsBody
from modstore_server.workbench.schemas import WorkbenchResearchBody as WorkbenchResearchBody
from modstore_server.workbench.schemas import (
    WorkbenchSessionCreateBody as WorkbenchSessionCreateBody,
)
from modstore_server.workbench.schemas import WorkbenchUnifiedTtsBody as WorkbenchUnifiedTtsBody
from modstore_server.workbench.schemas import (
    WorkbenchVibeCodeSkillBody as WorkbenchVibeCodeSkillBody,
)
from modstore_server.workbench.schemas import WorkbenchWebSearchBody as WorkbenchWebSearchBody
from modstore_server.workbench.schemas import (
    _parse_workbench_session_create as _parse_workbench_session_create,
)
from modstore_server.workbench.script_delivery import (
    _commit_script_workflow_from_result as _commit_script_workflow_from_result,
)
from modstore_server.workbench.script_delivery import (
    _embed_script_workflow_in_employee_pack as _embed_script_workflow_in_employee_pack,
)
from modstore_server.workbench.speech_api import _edge_tts_rate_str as _edge_tts_rate_str
from modstore_server.workbench.speech_api import _edge_tts_stream_chunks as _edge_tts_stream_chunks
from modstore_server.workbench.suite_pipeline import (
    _cleanup_mod_pipeline_resources as _cleanup_mod_pipeline_resources,
)
from modstore_server.workbench.uploads import read_workbench_uploads
from modstore_server.workbench.vibe_readiness import (
    _check_vibe_coding_capability as _check_vibe_coding_capability,
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
except ImportError:
    _EDGE_TTS = None
else:
    _EDGE_TTS = _edge_tts
router = APIRouter(prefix="/api/workbench", tags=["workbench"])
_LOG = logging.getLogger(__name__)
WORKBENCH_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSION_LOCK = asyncio.Lock()


def _session_store() -> sessions.SessionStore:
    return sessions.SessionStore(
        data=WORKBENCH_SESSIONS,
        lock=_SESSION_LOCK,
        path_for=_workbench_session_file,
        legacy_directory=Path(__file__).parent / "data" / "workbench_sessions",
    )


def _progress() -> sessions.ProgressCallbacks:
    return sessions.ProgressCallbacks(_set_step, _fail_session, _finalize_session_done)


def _session_api_ports() -> session_api.SessionApiPorts:
    return session_api.SessionApiPorts(
        sessions=_session_store(),
        start=start_workbench_session_for_user,
        snapshot=get_workbench_session_snapshot,
        run_pipeline=_run_pipeline,
    )


def _package_ports() -> employee_packages.EmployeePackagePorts:
    return employee_packages.EmployeePackagePorts(
        database=get_session_factory,
        library=modstore_library_path,
        build_archive=build_employee_pack_zip,
        normalize_manifest=normalize_editor_manifest_for_registry,
    )


def _draft_ports() -> employee_drafts.DraftPorts:
    return employee_drafts.DraftPorts(
        database=get_session_factory,
        resolve_model=resolve_llm_provider_model_auto,
        generate_workflow=generate_workflow_for_intent,
    )


def _command_ports() -> employee_commands.EmployeeCommandPorts:
    return employee_commands.EmployeeCommandPorts(
        database=get_session_factory,
        library=modstore_library_path,
        materialize=materialize_employee_pack_if_missing,
    )


def _vibe_ports() -> vibe_api.VibePorts:
    return vibe_api.VibePorts(
        database=get_session_factory, publish=_publish_vibe_skill_via_local_modstore
    )


def _employee_services(db: Session, user: User) -> employee_pipeline.EmployeeBuildServices:
    store, progress = (_session_store(), _progress())
    return employee_pipeline.EmployeeBuildServices(
        sessions=store,
        progress=progress,
        planning=employee_planning.EmployeePlanningPorts(
            progress=progress,
            db=db,
            craft_step=_dispatch_craft_step,
            build_plan=_build_employee_orchestration_plan,
        ),
        generation=employee_generation.EmployeeGenerationPorts(
            sessions=store,
            progress=progress,
            db=db,
            user=user,
            craft_step=_dispatch_craft_step,
            scaffold=run_employee_ai_scaffold_async,
        ),
        workflows=employee_workflows.EmployeeWorkflowPorts(
            progress=progress,
            db=db,
            user=user,
            craft_step=_dispatch_craft_step,
            run_script=run_script_agent_job,
            commit_script=_commit_script_workflow_from_result,
            embed_script=_embed_script_workflow_in_employee_pack,
            attach_workflow=attach_nl_workflow_to_employee_pack_dir,
            refresh_catalog=_refresh_employee_pack_catalog_zip,
        ),
        registration=employee_registration.EmployeeRegistrationPorts(
            progress=progress,
            db=db,
            user=user,
            craft_step=_dispatch_craft_step,
            refresh_catalog=_refresh_employee_pack_catalog_zip,
            catalog_registered=_assert_employee_catalog_registered,
            sandbox=run_workflow_sandbox,
            record_sandbox=record_workflow_sandbox_run,
        ),
        runtime=employee_runtime_checks.EmployeeRuntimePorts(
            progress=progress,
            craft_step=_dispatch_craft_step,
            vibe_checks=_check_vibe_coding_capability,
            compile_warnings=mod_compileall_warnings,
            consistency_warnings=employee_pack_consistency_warnings,
            manifest=read_manifest,
        ),
        quality=employee_quality.EmployeeQualityPorts(
            sessions=store,
            progress=progress,
            craft_step=_dispatch_craft_step,
            quality_extras=_employee_quality_extras,
        ),
        delivery=employee_delivery.EmployeeDeliveryPorts(sessions=store, progress=progress),
    )


def _workbench_session_store_dir() -> Path:
    return sessions.session_store_directory()


def _workbench_session_file(sid: str) -> Path:
    return _workbench_session_store_dir() / sessions.session_filename(sid)


def _persist_workbench_session_unlocked(sid: str) -> None:
    """多 worker / 多进程时内存 dict 不共享，落盘以便 GET 轮询命中任意进程可读。"""
    return _session_store().persist(sid)


def _load_workbench_session_unlocked(sid: str) -> Optional[Dict[str, Any]]:
    return _session_store().load(sid)


def _hydrate_workbench_session_unlocked(sid: str) -> None:
    return _session_store().hydrate(sid)


async def _persist_workbench_session(sid: str) -> None:
    return await _session_store().persist_locked(sid)


async def _set_step(
    sid: str, step_id: str, status: str, message: Optional[Union[str, dict]] = None
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
    return await sessions.SessionProgress(
        _session_store(), _record_craft_step_skip_metric
    ).set_step(sid, step_id, status, message)


def _record_craft_step_skip_metric(step_id: str, status: str, sess: Optional[dict]) -> None:
    return sessions.record_craft_skip(step_id, status, sess)


async def _fail_session(sid: str, step_id: str, err: str) -> None:
    return await sessions.SessionProgress(_session_store(), _record_craft_step_skip_metric).fail(
        sid, step_id, err
    )


async def _finalize_session_done(sid: str, artifact: Dict[str, Any]) -> None:
    """Atomically write artifact + status=done.

    Guards against the case where a pipeline branch returns early without
    explicitly completing every step: any step still in pending/running is
    force-promoted to done so the frontend never sees status=done alongside
    non-terminal steps (which would cause premature navigation).

    If the session already ended in ``error`` (e.g. :func:`_fail_session`), this
    function is a no-op so we never overwrite a failure with a false ``done``.
    """
    return await sessions.SessionProgress(_session_store(), _record_craft_step_skip_metric).finish(
        sid, artifact
    )


async def _build_employee_orchestration_plan(
    db: Session,
    user_id: int,
    *,
    payload: Dict[str, Any],
    provider: Optional[str],
    model: Optional[str],
) -> Dict[str, Any]:
    return await planning._build_employee_orchestration_plan(
        db,
        user_id,
        payload=payload,
        provider=provider,
        model=model,
        ports=planning.PlanningPorts(resolve_api_key, resolve_base_url, chat_dispatch),
    )


async def _read_workbench_uploads(files: List[UploadFile]) -> List[Dict[str, Any]]:
    return await read_workbench_uploads(files)


def _pipeline_task_failsafe(sid: str) -> Any:
    """Return a done-callback for asyncio tasks created from _run_pipeline.

    If the task raises an unhandled exception (any branch that forgot try/except),
    this callback marks the session as error and sets the first running step to error,
    preventing the zombie-session where status stays 'running' forever.
    """
    return _session_store().task_failsafe(sid)


async def _run_workbench_script_pipeline(
    sid, user_id, payload, execution_mode, brief, prov, mdl, db
):
    return await script_pipeline._run_workbench_script_pipeline(
        sid,
        user_id,
        payload,
        execution_mode,
        brief,
        prov,
        mdl,
        db,
        ports=script_pipeline.ScriptPorts(
            _session_store(),
            _progress(),
            run_script_job,
            _commit_script_workflow_from_result,
        ),
    )


async def _run_workbench_mod_pipeline(
    sid, payload, intent, brief, prov, mdl, replace, generate_frontend, db, user
):
    return await suite_pipeline._run_workbench_mod_pipeline(
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
        ports=suite_pipeline.SuitePorts(
            sessions=_session_store(),
            progress=_progress(),
            readiness=analyze_mod_employee_readiness,
            create_workflows=create_mod_suite_workflows_async,
            generate_employees=generate_mod_employee_impls_async,
            blueprint=generate_mod_suite_blueprint_async,
            import_repository=import_mod_suite_repository,
            compile_warnings=mod_compileall_warnings,
            patch_employee_nodes=patch_workflow_graph_employee_nodes,
            register_employees=register_mod_employee_packs_async,
            scaffold=run_mod_ai_scaffold_async,
            mod_sandbox=run_mod_suite_mod_sandbox,
            workflow_sandboxes=run_mod_suite_workflow_sandboxes,
            write_blueprint=write_mod_suite_blueprint,
            write_industry=write_mod_suite_industry_card,
            write_ui=write_mod_suite_ui_shell,
        ),
    )


async def _run_workbench_employee_pipeline(
    sid, user_id, payload, intent, brief, prov, mdl, replace, db, user
):
    return await employee_pipeline.run_employee_pipeline(
        sid,
        user_id,
        payload,
        brief,
        prov,
        mdl,
        replace,
        services=_employee_services(db, user),
    )


async def _run_workbench_canvas_pipeline(
    sid, payload, intent, brief, prov, mdl, gen_wf_graph, db, user
):
    return await canvas_pipeline._run_workbench_canvas_pipeline(
        sid,
        payload,
        intent,
        brief,
        prov,
        mdl,
        gen_wf_graph,
        db,
        user,
        ports=canvas_pipeline.CanvasPorts(
            _session_store(),
            _progress(),
            apply_nl_workflow_graph,
            run_workflow_sandbox,
            record_workflow_sandbox_run,
        ),
    )


async def _run_pipeline(sid: str, user_id: int, payload: Dict[str, Any]) -> None:
    return await coordinator._run_pipeline(
        sid,
        user_id,
        payload,
        ports=coordinator.PipelinePorts(
            sessions=_session_store(),
            progress=_progress(),
            database=get_session_factory,
            resolve_model=_resolve_default_llm_for_pipeline,
            craft_step=_dispatch_craft_step,
            script=_run_workbench_script_pipeline,
            suite=_run_workbench_mod_pipeline,
            employee=_run_workbench_employee_pipeline,
            canvas=_run_workbench_canvas_pipeline,
        ),
    )


@router.post("/web-search", summary="工作台 · 联网检索网页摘要（供直接对话）")
async def workbench_web_search(
    body: WorkbenchWebSearchBody, user: User = Depends(_get_current_user)
):
    """与 Agent `internet_search` 同源：Bing 爬虫 → Tavily → DDG/SearXNG，并抓取结果页正文。"""
    return await research_api.workbench_web_search(
        body,
        user,
        ports=research_api.ResearchPorts(fetch_web_search_context_pack, build_research_context),
    )


@router.post("/research-context", summary="联网检索摘要 + GitHub 公开资料（供需求规划）")
async def workbench_research_context(
    body: WorkbenchResearchBody, user: User = Depends(_get_current_user)
):
    """
    优先 Bing HTML 爬虫检索网页摘要，失败时用 Tavily 兜底（不抓取任意第三方 URL），
    并从结果与用户 brief 中解析 github.com 仓库，仅通过 api.github.com 拉取公开元数据与 README，
    拼成有上限的 context_pack。
    """
    return await research_api.workbench_research_context(
        body,
        user,
        ports=research_api.ResearchPorts(fetch_web_search_context_pack, build_research_context),
    )


@router.post("/sessions", summary="启动工作台 AI 编排（异步）")
async def create_workbench_session(request: Request, user: User = Depends(_get_current_user)):
    return await session_api.create_workbench_session(request, user, ports=_session_api_ports())


@router.post("/script-sessions", summary="启动 AI + Python 文件处理任务")
async def create_workbench_script_session(
    metadata: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: User = Depends(_get_current_user),
):
    return await session_api.create_workbench_script_session(
        metadata, files, user, ports=_session_api_ports()
    )


@router.get("/sessions/{session_id}", summary="查询编排会话（轮询）")
async def get_workbench_session(session_id: str, user: User = Depends(_get_current_user)):
    return await session_api.get_workbench_session(session_id, user, ports=_session_api_ports())


@router.get("/sessions/{session_id}/files/{filename}", summary="下载脚本执行结果文件")
async def download_workbench_session_file(
    session_id: str, filename: str, user: User = Depends(_get_current_user)
):
    return await session_api.download_workbench_session_file(
        session_id, filename, user, ports=_session_api_ports()
    )


@router.post("/sessions/{session_id}/retry", summary="重试编排会话")
async def retry_workbench_session(session_id: str, user: User = Depends(_get_current_user)):
    return await session_api.retry_workbench_session(session_id, user, ports=_session_api_ports())


@router.post("/vibe-code-skill", summary="vibe-coding NL → CodeSkill 全闭环")
async def workbench_vibe_code_skill(
    body: WorkbenchVibeCodeSkillBody, user: User = Depends(_get_current_user)
):
    """vibe-coding 端到端 API:生成代码、试跑、可选直接上架本 MODstore。

    本接口同步返回(单次代码生成大约 5-30 秒,取决于 LLM 速度);
    长时间任务请用「脚本工作流」。
    """
    return await vibe_api.workbench_vibe_code_skill(body, user, ports=_vibe_ports())


def _publish_vibe_skill_via_local_modstore(
    coder: Any, skill_id: str, publish_cfg: Dict[str, Any], *, user_id: int
) -> Dict[str, Any]:
    """直接调本 MODstore 的 catalog 上传接口,不用 HTTP 自调来回。

    用 vibe-coding 的 ``SkillPackager`` 打包(它知道 .xcmod 内部结构),
    再走 :func:`catalog_store.append_package` + ``CatalogItem`` 写库。
    """
    return vibe_api._publish_vibe_skill_via_local_modstore(
        coder, skill_id, publish_cfg, user_id=user_id, ports=_vibe_ports()
    )


@router.post("/tts", summary="统一 TTS（MiMo → Edge 神经音，返回完整音频）")
async def workbench_unified_tts(
    body: WorkbenchUnifiedTtsBody, _user: User = Depends(_get_current_user)
):
    """优先小米 MiMo-V2.5 TTS，失败回退 edge-tts；不提供浏览器系统 TTS。"""
    return await speech_api.workbench_unified_tts(
        body,
        _user,
        ports=speech_api.SpeechPorts(cast(speech_api.EdgeBackend | None, _EDGE_TTS)),
    )


@router.post("/tts/edge", summary="微软在线神经 TTS（edge-tts，返回 MP3）")
async def workbench_edge_tts(body: WorkbenchEdgeTtsBody, _user: User = Depends(_get_current_user)):
    return await speech_api.workbench_edge_tts(
        body,
        _user,
        ports=speech_api.SpeechPorts(cast(speech_api.EdgeBackend | None, _EDGE_TTS)),
    )


@router.post("/tts/edge/stream", summary="微软在线神经 TTS（edge-tts，chunked MP3 流）")
async def workbench_edge_tts_stream(
    body: WorkbenchEdgeTtsBody, _user: User = Depends(_get_current_user)
):
    return await speech_api.workbench_edge_tts_stream(
        body,
        _user,
        ports=speech_api.SpeechPorts(cast(speech_api.EdgeBackend | None, _EDGE_TTS)),
    )


@router.post("/employee-ai/draft", summary="6 阶段 AI 员工生成（SSE 流式）")
async def employee_ai_draft(body: EmployeeAiDraftBody, user: User = Depends(_get_current_user)):
    """SSE 事件序列：stage_start / stage_progress / stage_done / stage_error / pipeline_done。

    ``pipeline_done`` 携带完整 manifest；客户端可在收到后离线编辑，再调 ``/api/mods/ai-scaffold``
    或 ``import_zip`` 落库上架（保持与现有 employee 工作台链路兼容）。
    """
    return await employee_drafts.employee_ai_draft(body, user, ports=_draft_ports())


@router.post("/employee-ai/refine-prompt", summary="LLM 优化 system prompt")
async def employee_ai_refine_prompt(
    body: EmployeeAiRefinePromptBody, user: User = Depends(_get_current_user)
):
    """用 LLM 重写 employee system prompt，返回优化后文本与一句话 diff 说明。"""
    return await employee_drafts.employee_ai_refine_prompt(body, user, ports=_draft_ports())


@router.post(
    "/employee-bench-test",
    summary="员工上架前基准测试（LLM 生成任务 + 执行 + 五维审核）",
)
async def employee_bench_test(body: EmployeeBenchRequest, user: User = Depends(_get_current_user)):
    """
    1. LLM 生成 1-5 级（每级 3 条）共 15 项测试任务
    2. 逐条执行并记录 ok / cost_tokens / duration_ms
    3. 量化打分 + 五维审核
    4. 返回完整报告，前端据此决定是否允许上架
    """
    return await employee_commands.employee_bench_test(body, user, ports=_command_ports())


@router.post("/employee-publish", summary="员工包上架到商店目录")
async def employee_publish(body: EmployeePublishRequest, user: User = Depends(_get_current_user)):
    """
    将本地库中的员工包重建 zip 并写入商店目录（catalog_store + catalog_items）。
    调用方应先通过 /employee-bench-test 且 passed=true，再调此接口。
    """
    return await employee_commands.employee_publish(body, user, ports=_command_ports())


@router.post("/employee-sync-test", summary="员工同步测试：bench→发布→推送到宿主安装")
async def employee_sync_test(
    body: EmployeeSyncTestRequest, user: User = Depends(_get_current_user)
):
    """
    一键同步流程：
    1. LLM 生成 1-5 级测试任务并执行 + 五维审核
    2. 通过后发布到 MODstore catalog（/v1/packages）
    3. 调用宿主 fhd-sandbox-runtime 的 /api/mod-store/install 安装此员工包
       → 员工出现在宿主「一键托管」面板、「员工工作流管理」页等位置
    """
    return await employee_commands.employee_sync_test(body, user, ports=_command_ports())


async def employee_save_impl(body: EmployeeSaveBody, user: User) -> Dict[str, Any]:
    """employee_save 核心实现；管理员批量对齐 manifest 时可复用（传入登记作者 user）。"""
    return await employee_packages.employee_save_impl(body, user, ports=_package_ports())


@router.post("/employee-save", summary="保存/持久化编辑器当前 manifest 到服务器库并注册 ESkill")
async def employee_save(body: EmployeeSaveBody, user: User = Depends(_get_current_user)):
    """把前端编辑器的当前 manifest 保存到 library/<pack_id>，解压运行时文件，
    并通过 vibe-coding 将 cognition.skills 注册为真实可执行 ESkill。

    register_skills=true（默认）时会调用 LLM 为每个 skill 生成 Python 代码并在数据库创建 ESkill 记录。
    返回保存的 pack_id、已注册 ESkill 数量和下载元信息。
    """
    return await employee_save_impl(body, user)


@router.post("/employee-export", summary="根据当前 manifest 生成完整 .xcemp 并下载（不落盘）")
async def employee_export(body: EmployeeExportBody, user: User = Depends(_get_current_user)):
    """接收前端当前 manifest，用后端模板生成完整 .xcemp（含 blueprints.py + employee.py），直接返回 zip 流。
    ``standalone=true`` 时额外嵌入 zipapp 入口（与 employee_pack_export._build_employee_pack_zip_with_source 一致），
    便于本机 ``python xxx.xcemp validate`` / ``run``；平台装载仍只读 ``<pack_id>/manifest.json`` 与 ``backend/``。
    不写入数据库，仅供本地查看/调试用。
    """
    return await employee_packages.employee_export(body, user, ports=_package_ports())


@router.post("/dispatch", summary="任务拆解路由 → 多员工并行执行")
async def dispatch_task(body: DispatchRequest, user: User = Depends(_get_current_user)):
    """接收自然语言任务描述，由 task_router 拆解为子任务列表，按拓扑执行各员工。

    use_task_router=False 时退化为指定单员工的 plan_and_dispatch。
    """
    return await task_api.dispatch_task(body, user)


_ACTIVE_INLINE_SESSIONS: set[str] = set()


def _delivery_sessions() -> WorkbenchSessions:
    return WorkbenchSessions(_session_store(), _run_pipeline, _progress(), _ACTIVE_INLINE_SESSIONS)


async def start_workbench_session_for_user(
    user_id: int,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    run_inline: bool = False,
    delivery_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    return await _delivery_sessions().start(
        user_id,
        payload,
        session_id=session_id,
        run_inline=run_inline,
        delivery_context=delivery_context,
    )


async def get_workbench_session_snapshot(session_id: str, user_id: int) -> dict[str, Any] | None:
    return await _delivery_sessions().snapshot(session_id, user_id)
