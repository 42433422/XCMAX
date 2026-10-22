"""Public meeting API composed from fact readers, employee execution, and result synthesis."""

from __future__ import annotations

import asyncio as asyncio
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.all_hands_bench import AllHandsBench
from modstore_server.all_hands_context import AllHandsContext
from modstore_server.all_hands_context import (
    _snapshot_employee_cron_overview as _snapshot_employee_cron_overview,
)
from modstore_server.all_hands_coordinator import AllHandsCoordinator
from modstore_server.all_hands_employee import EmployeeReporter
from modstore_server.all_hands_policy import (
    CRAFT_WORKSHOP_STANDBY_IDS as CRAFT_WORKSHOP_STANDBY_IDS,
)
from modstore_server.all_hands_policy import MAX_ALL_HANDS_EMPLOYEES as MAX_ALL_HANDS_EMPLOYEES
from modstore_server.all_hands_policy import _craft_workshop_pkg_ids as _craft_workshop_pkg_ids
from modstore_server.all_hands_policy import (
    _should_standby_manifest_report as _should_standby_manifest_report,
)
from modstore_server.all_hands_policy import (
    all_hands_concurrency_default as all_hands_concurrency_default,
)
from modstore_server.all_hands_policy import (
    all_hands_employee_timeout_sec as all_hands_employee_timeout_sec,
)
from modstore_server.all_hands_policy import (
    clamp_all_hands_max_employees as clamp_all_hands_max_employees,
)
from modstore_server.all_hands_ports import AllHandsProgressCallback
from modstore_server.all_hands_presentation import (
    _coerce_standby_excerpt as _coerce_standby_excerpt,
)
from modstore_server.all_hands_presentation import (
    _craft_pipeline_standby_context as _craft_pipeline_standby_context,
)
from modstore_server.all_hands_presentation import (
    _employee_answer_excerpt as _employee_answer_excerpt,
)
from modstore_server.all_hands_presentation import (
    _is_standby_pipeline_json_noise as _is_standby_pipeline_json_noise,
)
from modstore_server.all_hands_repository import AllHandsRepository
from modstore_server.all_hands_templates import (
    _ALL_HANDS_STANDBY_SYSTEM as _ALL_HANDS_STANDBY_SYSTEM,
)
from modstore_server.all_hands_templates import (
    _MEETING_MINUTES_SYSTEM_PROMPT as _MEETING_MINUTES_SYSTEM_PROMPT,
)
from modstore_server.all_hands_templates import (
    _SYNTHESIZE_SYSTEM_PROMPT as _SYNTHESIZE_SYSTEM_PROMPT,
)
from modstore_server.all_hands_templates import (
    ALL_HANDS_QA_TASK_TEMPLATE as ALL_HANDS_QA_TASK_TEMPLATE,
)
from modstore_server.all_hands_templates import ALL_HANDS_TASK_TEMPLATE as ALL_HANDS_TASK_TEMPLATE
from modstore_server.daily_employee_briefs import (
    collect_yuangon_pack_excerpt,
    resolve_daily_brief_research_brief,
)
from modstore_server.duty_roster import all_planned_employee_ids, yuangon_area_for_pkg
from modstore_server.employee_executor import execute_employee_task
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.models import get_session_factory
from modstore_server.research_tools import build_research_context
from modstore_server.services.llm import resolve_platform_bench_llm


def _repository() -> AllHandsRepository:
    return AllHandsRepository(
        get_session_factory, all_planned_employee_ids, clamp_all_hands_max_employees
    )


def _context() -> AllHandsContext:
    return AllHandsContext(
        get_session_factory,
        load_employee_pack,
        yuangon_area_for_pkg,
        _load_yuangon_employee_meta,
        _snapshot_pending_change_requests,
        _snapshot_employee_cron_overview,
        CRAFT_WORKSHOP_STANDBY_IDS,
    )


def _bench() -> AllHandsBench:
    from modstore_server.services.llm import chat_dispatch_via_session

    return AllHandsBench(
        get_session_factory,
        chat_dispatch_via_session,
        _employee_answer_excerpt,
        _craft_pipeline_standby_context,
        CRAFT_WORKSHOP_STANDBY_IDS,
        _ALL_HANDS_STANDBY_SYSTEM,
        _SYNTHESIZE_SYSTEM_PROMPT,
        _MEETING_MINUTES_SYSTEM_PROMPT,
    )


def _employee_reporter() -> EmployeeReporter:
    return EmployeeReporter(
        resolve_daily_brief_research_brief,
        build_research_context,
        collect_yuangon_pack_excerpt,
        _recent_failures,
        _load_yuangon_employee_meta,
        _manifest_signals,
        _all_hands_role_context,
        yuangon_area_for_pkg,
        ALL_HANDS_QA_TASK_TEMPLATE,
        ALL_HANDS_TASK_TEMPLATE,
        _should_standby_manifest_report,
        _standby_manifest_report_via_bench,
        _coerce_standby_excerpt,
        execute_employee_task,
    )


def _coordinator() -> AllHandsCoordinator:
    return AllHandsCoordinator(
        _resolve_employee_pairs,
        resolve_platform_bench_llm,
        _report_one_employee,
        synthesize_all_hands_answer,
        all_hands_employee_timeout_sec,
        yuangon_area_for_pkg,
        _manifest_signals,
        _recent_failures,
    )


def _resolve_employee_pairs(
    requested_ids: Optional[List[str]], *, max_employees: int
) -> List[Tuple[str, str]]:
    """返回 ``[(pkg_id, display_name), ...]``。

    **编制员工**（``duty_roster.all_planned_employee_ids``）与公开市场无关：不要求
    ``catalog_items.is_public``，也不要求已做「市场上架」。只要能加载员工包即可：

    - Postgres ``catalog_items`` 中 ``artifact=employee_pack``；**或**
    - XC 本地 ``catalog_store.packages.json`` 中已登记 ``artifact=employee_pack`` 且
      ``files/`` 下有对应 zip（与 :func:`modstore_server.employee_runtime.load_employee_pack` 一致）。
    """
    return _repository().employee_pairs(requested_ids, max_employees=max_employees)


def _recent_failures(employee_id: str, limit: int = 6) -> List[Dict[str, Any]]:
    """读员工最近真实失败/告警的执行流水，给"问题与解决"段落做事实根基。

    只纳入真正的失败状态（``failed``、``error``，以及有非空 error 字段的 ``success``）；
    排除 ``skipped``、``blocked_by_risk_gate``、``warning`` 等正常/预期状态。
    默认只取最近 72h 内的记录（可通过 ``MODSTORE_RECENT_FAILURES_HOURS`` 覆盖）。
    同一 ``(task 前缀, error 前缀)`` 组合去重，避免重复 craft 步骤生成多张 P0 卡。
    """
    return _repository().recent_failures(employee_id, limit)


def _snapshot_pending_change_requests(limit: int = 12) -> List[Dict[str, Any]]:
    return _repository().pending_changes(limit)


def _load_yuangon_employee_meta(pkg_id: str) -> Dict[str, Any]:
    """读取 yuangon/<area>/<pkg_id>/employee.yaml 中的 owner/area/domain 等元数据。"""
    return _context().load_metadata(pkg_id)


def _manifest_signals(pkg_id: str) -> Dict[str, Any]:
    """从员工包 manifest 抽取汇报 grounding 字段（identity/role/handlers/depends_on/behavior_rules）。"""
    return _context().manifest_signals(pkg_id)


def _all_hands_role_context(pkg_id: str) -> Dict[str, Any]:
    """按岗位注入员工大会专用上下文，避免「缺 Change ID / 缺调度清单」类空答。"""
    return _context().role_context(pkg_id)


async def _standby_manifest_report_via_bench(
    *,
    pkg_id: str,
    display_name: str,
    task_text: str,
    inp: Dict[str, Any],
    user_id: int,
    bench_provider: str,
    bench_model: str,
) -> Tuple[str, str, int]:
    """制作车间待机：用大会任务模板 + bench LLM，不经员工 cognition（避免 JSON 告警）。"""
    return await _bench().standby_report(
        pkg_id=pkg_id,
        display_name=display_name,
        task_text=task_text,
        inp=inp,
        user_id=user_id,
        bench_provider=bench_provider,
        bench_model=bench_model,
    )


async def _report_one_employee(
    *,
    pkg_id: str,
    display_name: str,
    other_employees: List[str],
    user_id: int,
    bench_provider: str,
    bench_model: str,
    with_research: bool,
    user_question: Optional[str] = None,
) -> Dict[str, Any]:
    return await _employee_reporter().report(
        pkg_id=pkg_id,
        display_name=display_name,
        other_employees=other_employees,
        user_id=user_id,
        bench_provider=bench_provider,
        bench_model=bench_model,
        with_research=with_research,
        user_question=user_question,
    )


async def synthesize_all_hands_answer(
    *,
    user_question: str,
    employees: List[Dict[str, Any]],
    bench_provider: str,
    bench_model: str,
    user_id: int,
) -> Dict[str, Any]:
    """把多名员工的 Q&A 答复送给 bench LLM 合并成「数字管家综合答复」。

    返回 ``{ markdown, cited_employees: [pkg_id], model, error }``；
    bench LLM 不可用或失败时 ``markdown == ""`` 且 ``error`` 非空。
    """
    return await _bench().answer(
        user_question=user_question,
        employees=employees,
        bench_provider=bench_provider,
        bench_model=bench_model,
        user_id=user_id,
    )


async def synthesize_meeting_minutes(*, report: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """将已成功生成的 ``build_all_hands_report`` 结果压缩为五段式「会议摘要」正文。

    返回 ``{ text, generated_at, model, error }``；失败时 ``text`` 可为空且 ``error`` 非空。
    """
    return await _bench().minutes(report=report, user_id=user_id)


async def build_all_hands_report(
    *,
    employee_ids: Optional[List[str]] = None,
    max_employees: int = 8,
    with_research: bool = True,
    user_id: int = 0,
    concurrency: int = 2,
    progress_cb: Optional[AllHandsProgressCallback] = None,
    user_question: Optional[str] = None,
    synthesize: bool = False,
) -> Dict[str, Any]:
    """全员汇报主入口。返回结构化 JSON，前端直接渲染。

    - ``employee_ids`` 为空时：取 ``duty_roster`` ∩ ``catalog`` 全集，按 ``pkg_id`` 排序；
    - ``concurrency`` 默认 2，避免一次性把平台 LLM Bench 配额打满；
    - 不抛异常：单个员工失败时 ``status='error'``，整体仍返回。
    """
    return await _coordinator().build(
        employee_ids=employee_ids,
        max_employees=max_employees,
        with_research=with_research,
        user_id=user_id,
        concurrency=concurrency,
        progress_cb=progress_cb,
        user_question=user_question,
        synthesize=synthesize,
    )
