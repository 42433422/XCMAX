"""员工编排：在岗协作图入口（定时任务 / 扩展编排调用）。"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from modstore_server.task_router import SubTask

logger = logging.getLogger(__name__)


def _resolve_uid(created_by_user_id: int) -> int:
    from modstore_server.models import User, get_session_factory

    uid = int(created_by_user_id or 0)
    if uid <= 0:
        sf = get_session_factory()
        with sf() as session:
            u = (
                session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
            )  # noqa: E712
            uid = int(u.id) if u else 0
            if uid <= 0:
                u2 = session.query(User).order_by(User.id.asc()).first()
                uid = int(u2.id) if u2 else 0
    return uid


def plan_and_dispatch(
    task: str,
    input_data: Dict[str, Any],
    *,
    target_employee_id: str = "daily-orchestrator",
    created_by_user_id: int = 0,
    include_dependencies: bool = True,
    max_concurrency: int = 2,
    allow_high_risk_real_run: bool = False,
    bench_llm_override: Optional[Tuple[str, str]] = None,
    hint_employees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """以 ``target_employee_id`` 为根展开 ``depends_on`` 拓扑并依次执行。

    ``hint_employees`` 已接通 task_router：若提供则视为已拆解的 employee_id 列表，
    并行执行（不展开 manifest 依赖）。
    ``bench_llm_override`` 仅作用于 ``daily-orchestrator`` 节点（与单日编排一致）。
    """
    from modstore_server.admin_duty_graph_api import execute_duty_graph_programmatic

    uid = _resolve_uid(created_by_user_id)
    if uid <= 0:
        return {"ok": False, "error": "no user in DB for duty graph"}

    # 若 hint_employees 已由 task_router 填充，直接并行执行各员工
    if hint_employees:
        from modstore_server.task_router import SubTask

        subtasks = [
            SubTask(employee_id=eid, task_brief=task, input_data=input_data)
            for eid in hint_employees
        ]
        return dispatch_subtasks(
            subtasks,
            created_by_user_id=uid,
            max_concurrency=max_concurrency,
            allow_high_risk_real_run=allow_high_risk_real_run,
        )

    return execute_duty_graph_programmatic(
        target_employee_id=target_employee_id,
        task=task,
        input_data=input_data,
        created_by_user_id=uid,
        include_dependencies=include_dependencies,
        max_concurrency=max_concurrency,
        allow_high_risk_real_run=allow_high_risk_real_run,
        bench_llm_override=bench_llm_override,
        bench_llm_target_id="daily-orchestrator",
    )


def dispatch_subtasks(
    subtasks: "List[SubTask]",
    *,
    created_by_user_id: int = 0,
    max_concurrency: int = 2,
    allow_high_risk_real_run: bool = False,
) -> Dict[str, Any]:
    """按 SubTask 列表的拓扑顺序执行（depends_on 决定顺序，同层并行）。

    每完成一层后会：
        - 把员工产出里的 ``handoff_to`` 指令解析为下一层 SubTask（实时交接，
          见 ``employee_handoff.build_followup_subtasks``）。
        - 链长上限由 ``MODSTORE_HANDOFF_MAX_DEPTH`` 控制，避免循环交接。

    返回 ``{"ok": bool, "results": List[dict], "handoff_chain": List[dict]}``
    """
    from modstore_server.employee_handoff import build_followup_subtasks

    uid = _resolve_uid(created_by_user_id)

    layers = _topo_layers(subtasks)
    all_results: List[Dict[str, Any]] = []
    completed: Dict[str, Any] = {}
    visited_employees: set = {st.employee_id for st in subtasks}
    handoff_chain: List[Dict[str, Any]] = []
    fallback_brief = subtasks[0].task_brief if subtasks else ""

    layer_index = 0
    for layer in layers:
        layer_results = _run_layer(
            layer,
            uid=uid,
            completed=completed,
            max_concurrency=max_concurrency,
            allow_high_risk_real_run=allow_high_risk_real_run,
        )
        for r in layer_results:
            completed[r["employee_id"]] = r
            all_results.append(r)
        layer_index += 1

    handoff_depth = 0
    last_results = all_results[:]
    while handoff_depth < 8:
        followups = build_followup_subtasks(
            last_results,
            visited=visited_employees,
            depth=handoff_depth,
            fallback_brief=fallback_brief,
        )
        if not followups:
            break
        for st in followups:
            handoff_chain.append(
                {
                    "depth": handoff_depth,
                    "to_employee_id": st.employee_id,
                    "task_brief": st.task_brief[:200],
                }
            )
        followup_results = _run_layer(
            followups,
            uid=uid,
            completed=completed,
            max_concurrency=max_concurrency,
            allow_high_risk_real_run=allow_high_risk_real_run,
        )
        for r in followup_results:
            completed[r["employee_id"]] = r
            all_results.append(r)
        last_results = followup_results
        handoff_depth += 1

    ok = all(r.get("ok", True) for r in all_results)
    return {
        "ok": ok,
        "results": all_results,
        "subtask_count": len(subtasks) + len(handoff_chain),
        "handoff_chain": handoff_chain,
    }


def _topo_layers(subtasks: "List[SubTask]") -> "List[List[SubTask]]":
    """将 SubTask 列表按 depends_on 分成可并行的层次。"""
    remaining = list(subtasks)
    done_ids: set = set()
    layers: List[List] = []

    while remaining:
        layer = [st for st in remaining if all(d in done_ids for d in (st.depends_on or []))]
        if not layer:
            # 循环依赖或无法解析，剩余全部放最后一层
            layer = list(remaining)

        # 按 priority 排序（数字小=优先级高）
        layer.sort(key=lambda s: (s.priority, s.employee_id))
        layers.append(layer)
        done_ids.update(st.employee_id for st in layer)
        remaining = [st for st in remaining if st not in layer]

    return layers


def _run_layer(
    layer: "List[SubTask]",
    *,
    uid: int,
    completed: Dict[str, Any],
    max_concurrency: int,
    allow_high_risk_real_run: bool,
) -> List[Dict[str, Any]]:
    from modstore_server.employee_executor import execute_employee_task

    def _run_one(st) -> Dict[str, Any]:
        # 把已完成的依赖结果注入 input_data
        input_data = dict(st.input_data or {})
        for dep_id in st.depends_on or []:
            if dep_id in completed:
                input_data.setdefault("upstream_results", {})[dep_id] = completed[dep_id]
        try:
            result = execute_employee_task(
                st.employee_id,
                st.task_brief,
                input_data,
                user_id=uid,
            )
            return {"ok": True, "employee_id": st.employee_id, "result": result}
        except Exception as exc:
            logger.exception("dispatch_subtasks: employee=%s failed", st.employee_id)
            return {"ok": False, "employee_id": st.employee_id, "error": str(exc)}

    if len(layer) == 1:
        return [_run_one(layer[0])]

    results = []
    with ThreadPoolExecutor(max_workers=min(max_concurrency, len(layer))) as pool:
        futures = {pool.submit(_run_one, st): st for st in layer}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


__all__ = ["plan_and_dispatch", "dispatch_subtasks"]
