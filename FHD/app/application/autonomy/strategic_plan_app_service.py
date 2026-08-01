"""战略规划应用服务：收集上下文 → LLM 分解 → 反思 → 落盘。"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.autonomy.strategic_planner import (
    QuarterlyPlan,
    StrategicPlanner,
    current_quarter,
    heuristic_quarterly_plan,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _fhd_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _plan_log_path() -> Path:
    override = (os.environ.get("XCAGI_STRATEGIC_PLAN_LOG") or "").strip()
    if override:
        return Path(override)
    return _fhd_root() / "resources" / "autonomy" / "strategic_plans.jsonl"


def gather_planning_context() -> dict[str, Any]:
    """从仓库状态拼战略上下文（best-effort，无网络强依赖）。"""
    ctx: dict[str, Any] = {
        "autonomy_debts": [
            "运维 policy 仍大量依赖硬阈值（如 crash threshold）",
            "impact-predictor 主路径仍是 switch-case 规则机",
            "缺少长程目标分解与反思修正的生产闭环",
        ],
        "project_gaps": [],
        "capability_proposals": [],
        "skills": [],
    }
    state = _fhd_root() / "docs" / "PROJECT_STATE.md"
    try:
        if state.is_file():
            text = state.read_text(encoding="utf-8")
            section = re.search(r"仍未解决[\s\S]*?(?=\n## |\Z)", text)
            if section:
                bullets = re.findall(r"^-\s+(.+)$", section.group(0), flags=re.M)
                ctx["project_gaps"] = [b.strip()[:160] for b in bullets[:12]]
    except RECOVERABLE_ERRORS:
        logger.debug("read PROJECT_STATE failed", exc_info=True)

    skills = _fhd_root() / "resources" / "neuro" / "skill_contracts.json"
    try:
        if skills.is_file():
            raw = json.loads(skills.read_text(encoding="utf-8"))
            ctx["skills"] = [
                str(s.get("skill_id"))
                for s in (raw.get("skills") or [])
                if isinstance(s, dict) and s.get("skill_id")
            ][:20]
    except RECOVERABLE_ERRORS:
        logger.debug("read skill contracts failed", exc_info=True)

    proposals = _fhd_root() / "test_reports" / "capability_proposal.jsonl"
    try:
        if proposals.is_file():
            rows: list[dict[str, Any]] = []
            with proposals.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(rec, dict):
                        rows.append(
                            {
                                "title": str(rec.get("raw_input") or "")[:80],
                                "reason": str(rec.get("reason") or ""),
                            }
                        )
            ctx["capability_proposals"] = rows[-12:]
    except RECOVERABLE_ERRORS:
        logger.debug("read capability proposals failed", exc_info=True)

    return ctx


def append_plan(plan: QuarterlyPlan) -> Path:
    path = _plan_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = plan.to_dict()
    rec["ts_unix"] = time.time()
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def latest_plan() -> dict[str, Any] | None:
    path = _plan_log_path()
    if not path.is_file():
        return None
    latest: dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    latest = rec
    except RECOVERABLE_ERRORS:
        return None
    return latest


async def build_quarterly_plan(
    goal: str | None = None,
    *,
    critique: str | None = None,
    quarter: str | None = None,
    use_llm: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """主入口：分解「这个季度做哪三个功能」。"""
    ctx = gather_planning_context()
    q = quarter or current_quarter()
    goal_text = (goal or "").strip() or (
        "本季度把 XCMAX 从阈值自治推进到 LLM 驱动的目标分解与反思修正，并交付 3 个可验收功能。"
    )

    chat = None
    if use_llm:
        try:
            # 组装：导入 registry 触发其向 domain LLMPort 的自注册
            from app.infrastructure.llm.providers import registry as _llm_registry  # noqa: F401
            from app.domain.neuro.cognition.llm_port import get_llm_port

            chat = get_llm_port()
        except RECOVERABLE_ERRORS:
            logger.debug("llm port unavailable for strategic plan", exc_info=True)

    planner = StrategicPlanner(chat=chat)
    plan = await planner.plan_with_reflection(
        goal_text,
        context=ctx,
        quarter=q,
        critique=critique,
    )
    if persist:
        append_plan(plan)
    payload = plan.to_dict()
    payload["persisted"] = bool(persist)
    payload["context_summary"] = {
        "gap_count": len(ctx.get("project_gaps") or []),
        "proposal_count": len(ctx.get("capability_proposals") or []),
        "skill_count": len(ctx.get("skills") or []),
    }
    return payload


def build_quarterly_plan_sync(
    goal: str | None = None,
    *,
    critique: str | None = None,
    quarter: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """无事件循环时的同步启发式入口（脚本/CI）。"""
    ctx = gather_planning_context()
    plan = heuristic_quarterly_plan(
        goal or "本季度推进 LLM 战略规划与自治软约束化",
        context=ctx,
        quarter=quarter or current_quarter(),
    )
    if critique:
        # 同步路径只做标注式反思
        plan.revisions.append(
            {
                "phase": "reflect",
                "source": "sync_heuristic",
                "critique": str(critique)[:500],
                "at": datetime.now(UTC).isoformat(),
            }
        )
    if persist:
        append_plan(plan)
    return plan.to_dict()
