"""LLM 驱动的战略规划器——目标分解 / 反思修正 / 季度长程规划。

回答「这个季度做哪三个功能」，而不是 CRASH_THRESHOLD 式阈值机。
LLM 不可用时走可解释启发式回退（能力提案 + 文档缺口），不假装 AGI。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SYSTEM = """你是 XCMAX 的战略规划官（Strategic Planner）。
公司主张「AGI 主导工程」，你必须把抽象目标拆成可交付功能赌注。
硬性规则：
1. 只输出 JSON（不要 markdown 围栏）。
2. features 必须恰好 3 项，按优先级降序。
3. 每项含 title/why/success_metric/horizon_weeks/dependencies/risk。
4. risk ∈ {low, medium, high}；horizon_weeks ∈ [1, 13]。
5. 优先可验证闭环与收入/自治能力，禁止空泛口号。
"""


@dataclass
class FeatureBet:
    title: str
    why: str
    success_metric: str
    horizon_weeks: int = 4
    dependencies: list[str] = field(default_factory=list)
    risk: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuarterlyPlan:
    quarter: str
    goal: str
    features: list[FeatureBet]
    rationale: str = ""
    revisions: list[dict[str, Any]] = field(default_factory=list)
    source: str = "llm"
    generated_at: str = ""
    context_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quarter": self.quarter,
            "goal": self.goal,
            "features": [f.to_dict() for f in self.features],
            "rationale": self.rationale,
            "revisions": list(self.revisions),
            "source": self.source,
            "generated_at": self.generated_at,
            "context_keys": list(self.context_keys),
            "feature_count": len(self.features),
        }


class ChatPort(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str | None: ...


def current_quarter(now: datetime | None = None) -> str:
    dt = now or datetime.now(UTC)
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _clamp_weeks(value: Any) -> int:
    try:
        weeks = int(value)
    except (TypeError, ValueError):
        weeks = 4
    return max(1, min(13, weeks))


def _normalize_features(raw: Any) -> list[FeatureBet]:
    items = raw if isinstance(raw, list) else []
    out: list[FeatureBet] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        risk = str(item.get("risk") or "medium").lower()
        if risk not in {"low", "medium", "high"}:
            risk = "medium"
        deps = item.get("dependencies") or []
        if not isinstance(deps, list):
            deps = []
        out.append(
            FeatureBet(
                title=title[:120],
                why=str(item.get("why") or "")[:400],
                success_metric=str(item.get("success_metric") or "")[:200],
                horizon_weeks=_clamp_weeks(item.get("horizon_weeks")),
                dependencies=[str(d)[:80] for d in deps[:8]],
                risk=risk,
            )
        )
    return out[:3]


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def heuristic_quarterly_plan(
    goal: str,
    *,
    context: dict[str, Any] | None = None,
    quarter: str | None = None,
) -> QuarterlyPlan:
    """无 LLM 时的可解释回退：从上下文缺口拼出三个功能赌注。"""
    ctx = context or {}
    goal_l = (goal or "").lower()
    prefer_autonomy = any(
        k in goal_l for k in ("自治", "agi", "规划", "阈值", "impact", "季度", "功能")
    )

    gaps: list[FeatureBet] = []
    for gap in (ctx.get("project_gaps") or [])[:6]:
        if isinstance(gap, str) and gap.strip():
            gaps.append(
                FeatureBet(
                    title=f"关闭缺口：{gap.strip()[:60]}",
                    why="PROJECT_STATE / 架构债明确未解决",
                    success_metric="缺口从「仍未解决」移出或有验收证据",
                    horizon_weeks=6,
                    risk="medium",
                )
            )
    props: list[FeatureBet] = []
    for prop in (ctx.get("capability_proposals") or [])[:6]:
        if not isinstance(prop, dict):
            continue
        title = str(prop.get("title") or prop.get("raw_input") or "").strip()
        if title:
            props.append(
                FeatureBet(
                    title=f"兑现能力提案：{title[:50]}",
                    why="开放世界未命中已沉淀为能力提案",
                    success_metric="提案对应技能/意图可执行且有回归测试",
                    horizon_weeks=5,
                    risk="medium",
                )
            )
    debts: list[FeatureBet] = []
    for item in (ctx.get("autonomy_debts") or [])[:6]:
        if isinstance(item, str) and item.strip():
            debts.append(
                FeatureBet(
                    title=item.strip()[:80],
                    why="自治层仍依赖硬阈值/规则机，需 LLM 规划能力",
                    success_metric="关键决策有 LLM 分解+反思修订审计",
                    horizon_weeks=4,
                    risk="high",
                )
            )

    defaults = [
        FeatureBet(
            title="LLM 季度规划闭环上生产",
            why="把战略从阈值机升级为可拆解目标",
            success_metric="每季度自动产出 3 个功能赌注并经反思修订",
            horizon_weeks=4,
            risk="medium",
        ),
        FeatureBet(
            title="运维自治软约束化",
            why="CRASH_THRESHOLD 等硬阈值改为带 floor 的自适应",
            success_metric="崩溃回滚阈值可影子学习且不低于安全下限",
            horizon_weeks=3,
            risk="high",
        ),
        FeatureBet(
            title="ImpactPredictor 规则+LLM 双轨",
            why="switch-case 只做安全轨，复杂副作用走 LLM 顾问",
            success_metric="高风险动作有 advisory 记录且误拦可审计",
            horizon_weeks=5,
            risk="medium",
        ),
    ]
    # 分桶轮询，避免 PROJECT_STATE 缺口挤掉自治债
    buckets = [debts, gaps, props, defaults] if prefer_autonomy else [gaps, props, debts, defaults]
    candidates: list[FeatureBet] = []
    seen: set[str] = set()
    while len(candidates) < 3:
        progressed = False
        for bucket in buckets:
            if len(candidates) >= 3:
                break
            while bucket:
                bet = bucket.pop(0)
                if bet.title in seen:
                    continue
                seen.add(bet.title)
                candidates.append(bet)
                progressed = True
                break
        if not progressed:
            break
    while len(candidates) < 3:
        candidates.append(defaults[len(candidates) % len(defaults)])

    return QuarterlyPlan(
        quarter=quarter or current_quarter(),
        goal=goal.strip() or "本季度把自治从阈值机推进到可规划 AGI 工程",
        features=candidates[:3],
        rationale="heuristic_fallback: ranked from project gaps / capability proposals / autonomy debts",
        source="heuristic_fallback",
        generated_at=datetime.now(UTC).isoformat(),
        context_keys=sorted(str(k) for k in ctx.keys()),
    )


class StrategicPlanner:
    """目标分解 + 反思修正。"""

    def __init__(self, chat: ChatPort | None = None) -> None:
        self._chat = chat

    async def decompose_quarterly_goal(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        quarter: str | None = None,
    ) -> QuarterlyPlan:
        q = quarter or current_quarter()
        ctx = context or {}
        if self._chat is None:
            return heuristic_quarterly_plan(goal, context=ctx, quarter=q)

        user_payload = {
            "quarter": q,
            "goal": goal,
            "context": ctx,
            "required_feature_count": 3,
        }
        try:
            text = await self._chat.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "请把目标拆成恰好 3 个本季度功能赌注。输入：\n"
                            + json.dumps(user_payload, ensure_ascii=False)[:6000]
                        ),
                    },
                ],
                temperature=0.25,
                max_tokens=1600,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("strategic decompose llm failed", exc_info=True)
            text = None

        parsed = _extract_json(text or "")
        features = _normalize_features((parsed or {}).get("features"))
        if len(features) < 3:
            fallback = heuristic_quarterly_plan(goal, context=ctx, quarter=q)
            fallback.revisions.append(
                {
                    "phase": "decompose",
                    "reason": "llm_incomplete_or_unavailable",
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            return fallback

        return QuarterlyPlan(
            quarter=str((parsed or {}).get("quarter") or q),
            goal=str((parsed or {}).get("goal") or goal),
            features=features,
            rationale=str((parsed or {}).get("rationale") or "llm_decompose"),
            source="llm",
            generated_at=datetime.now(UTC).isoformat(),
            context_keys=sorted(str(k) for k in ctx.keys()),
        )

    async def reflect_and_revise(
        self,
        plan: QuarterlyPlan,
        *,
        critique: str,
        context: dict[str, Any] | None = None,
    ) -> QuarterlyPlan:
        """对已有季度计划做反思修正（可多轮）。"""
        critique = str(critique or "").strip()
        if not critique:
            return plan

        if self._chat is None:
            revised = QuarterlyPlan(
                quarter=plan.quarter,
                goal=plan.goal,
                features=list(plan.features),
                rationale=plan.rationale,
                revisions=list(plan.revisions)
                + [
                    {
                        "phase": "reflect",
                        "source": "heuristic",
                        "critique": critique[:500],
                        "at": datetime.now(UTC).isoformat(),
                        "note": "no_llm_keep_plan_annotate_only",
                    }
                ],
                source=plan.source,
                generated_at=datetime.now(UTC).isoformat(),
                context_keys=list(plan.context_keys),
            )
            # 启发式：若批评提到「风险过高」，把第一项 risk 标 high 并后移
            if "风险" in critique and revised.features:
                first = revised.features[0]
                first.risk = "high"
                revised.features = revised.features[1:] + [first]
            return revised

        payload = {
            "plan": plan.to_dict(),
            "critique": critique,
            "context": context or {},
        }
        try:
            text = await self._chat.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            "请根据 critique 修订季度计划，仍输出恰好 3 个 features。\n"
                            + json.dumps(payload, ensure_ascii=False)[:7000]
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=1600,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("strategic reflect llm failed", exc_info=True)
            text = None

        parsed = _extract_json(text or "")
        features = _normalize_features((parsed or {}).get("features"))
        if len(features) < 3:
            plan.revisions.append(
                {
                    "phase": "reflect",
                    "source": "llm_failed",
                    "critique": critique[:500],
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            return plan

        return QuarterlyPlan(
            quarter=plan.quarter,
            goal=str((parsed or {}).get("goal") or plan.goal),
            features=features,
            rationale=str((parsed or {}).get("rationale") or plan.rationale),
            revisions=list(plan.revisions)
            + [
                {
                    "phase": "reflect",
                    "source": "llm",
                    "critique": critique[:500],
                    "at": datetime.now(UTC).isoformat(),
                }
            ],
            source="llm",
            generated_at=datetime.now(UTC).isoformat(),
            context_keys=list(plan.context_keys),
        )

    async def plan_with_reflection(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        quarter: str | None = None,
        critique: str | None = None,
    ) -> QuarterlyPlan:
        plan = await self.decompose_quarterly_goal(goal, context=context, quarter=quarter)
        if critique:
            plan = await self.reflect_and_revise(plan, critique=critique, context=context)
        else:
            # 默认自反思一轮：检查是否空泛 / 缺成功指标
            weak = [f.title for f in plan.features if len(f.success_metric.strip()) < 8]
            if weak or plan.source == "heuristic_fallback":
                auto_critique = (
                    "请强化 success_metric 的可验证性，并确保三项覆盖："
                    "用户价值闭环、自治规划能力、运维安全软约束；"
                    f"薄弱项={weak or ['heuristic']}。"
                )
                plan = await self.reflect_and_revise(plan, critique=auto_critique, context=context)
        return plan
