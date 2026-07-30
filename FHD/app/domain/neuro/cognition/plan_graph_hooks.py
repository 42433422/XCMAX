"""PlanGraph 落盘与失败反思钩子——避免继续膨胀 oversized planner.py。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def observe_plan_graph(
    plan: Any,
    *,
    phase: str,
    trace_id: str,
    extra: dict[str, Any] | None = None,
    force: bool = False,
    reflect_on_failure: bool = False,
    plan_id: str | None = None,
    validate_error: str | None = None,
) -> None:
    """Best-effort PlanGraph 观测；失败不阻断主规划路径。"""
    try:
        from app.domain.neuro.cognition.plan_graph_log import append_plan_graph

        payload_extra = dict(extra or {})
        if validate_error:
            payload_extra["validate_error"] = validate_error
        append_plan_graph(
            plan,
            phase=phase,
            force=force,
            trace_id=trace_id,
            extra=payload_extra,
        )
        if reflect_on_failure and validate_error:
            from app.domain.neuro.evolution.self_reflection import get_self_reflection_engine

            get_self_reflection_engine().critique_and_propose(
                target="prompt_template",
                critique=f"PlanGraph 校验失败: {validate_error}",
                proposal={"action": "revise_planner_prompt", "error": validate_error},
                evidence={"plan_id": plan_id},
            )
    except RECOVERABLE_ERRORS:
        logger.debug("plan_graph observe skipped", exc_info=True)


def finalize_planned_graph(
    planned: Any,
    *,
    plan_id: str,
    context: dict[str, Any] | None,
    validate: Callable[[Any], str | None],
    fallback_factory: Callable[[], Any],
    warn: Callable[[str], None],
) -> Any:
    """校验 / 落盘 / 失败反思 / 回退，集中在此以免 planner 继续涨行。"""
    trace_id = str((context or {}).get("trace_id") or plan_id)
    if planned is not None:
        err = validate(planned)
        if err is None:
            observe_plan_graph(
                planned,
                phase="planned",
                trace_id=trace_id,
                extra={"source": "react_multiagent"},
            )
            return planned
        warn(f"ReAct/CoT 计划校验失败，回退规则规划: {err}")
        observe_plan_graph(
            planned,
            phase="failed",
            force=True,
            trace_id=trace_id,
            extra={"source": "react_multiagent"},
            reflect_on_failure=True,
            plan_id=plan_id,
            validate_error=err,
        )

    fallback = fallback_factory()
    observe_plan_graph(
        fallback,
        phase="planned",
        trace_id=trace_id,
        extra={"source": "fallback_rules"},
    )
    return fallback
