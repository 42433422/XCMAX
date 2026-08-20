# mypy: disable-error-code="arg-type"
"""自治边界规则与评估器。

边界定义了 AI 在执行层可自主决策的范围。决策提议进入 ``StrategicDecisionLedger`` 后，
先经 ``AutonomyEvaluator.evaluate`` 评估，根据 ``allowed_autonomy`` 决定：
- ``auto`` → AI 自动通过（``auto_approved``），可立即执行
- ``report_only`` → AI 通过但记录（``auto_approved`` + 标记 report_only）
- ``require_human`` → 升级人工审批（``proposed`` 等待 user）
- ``require_council`` → 调度员工自治会议（``proposed`` 等待 council-vote）

匹配优先级：critical > high > medium > low；同类按 ``rule_id`` 字母序。
首个匹配的规则生效，未匹配则默认 ``require_human``（保守原则）。
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select

from modstore_server.db.base import get_session_factory
from modstore_server.db.strategic import AutonomyBoundary as AutonomyBoundaryModel

logger = logging.getLogger(__name__)


class AutonomyAction(str, Enum):
    """自治边界允许的行动等级。"""

    AUTO = "auto"  # AI 自动通过
    REPORT_ONLY = "report_only"  # AI 通过但记录
    REQUIRE_HUMAN = "require_human"  # 升级人工
    REQUIRE_COUNCIL = "require_council"  # 调度员工自治会议


class RiskLevel(str, Enum):
    """风险等级，影响匹配优先级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_RISK_PRIORITY: Dict[str, int] = {
    RiskLevel.CRITICAL.value: 0,
    RiskLevel.HIGH.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.LOW.value: 3,
}


@dataclass(frozen=True)
class AutonomyBoundaryRule:
    """自治边界规则值对象。"""

    rule_id: str
    category: str
    action_pattern: str
    allowed_autonomy: AutonomyAction
    risk_level: RiskLevel
    scope: str = "both"  # execution_layer | strategic_layer | both
    rationale: str = ""
    enabled: bool = True

    def matches(self, action: str) -> bool:
        """``action_pattern`` 是 glob 风格，对 ``action`` 描述做大小写不敏感匹配。"""
        return fnmatch.fnmatchcase(action.lower(), self.action_pattern.lower())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["allowed_autonomy"] = self.allowed_autonomy.value
        d["risk_level"] = self.risk_level.value
        return d


@dataclass
class AutonomyEvaluation:
    """自治边界评估结果。"""

    matched: bool
    rule: Optional[AutonomyBoundaryRule]
    action: AutonomyAction
    risk_level: RiskLevel
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched": self.matched,
            "rule_id": self.rule.rule_id if self.rule else "",
            "allowed_autonomy": self.action.value,
            "risk_level": self.risk_level.value,
            "fallback_reason": self.fallback_reason,
            "rationale": self.rule.rationale if self.rule else self.fallback_reason,
        }


# 默认自治边界规则（启动时 seed 进 DB）
DEFAULT_AUTONOMY_BOUNDARIES: Sequence[AutonomyBoundaryRule] = (
    # === 执行层可自主（low risk, auto）===
    AutonomyBoundaryRule(
        rule_id="exec-unit-test",
        category="code_change",
        action_pattern="pytest tests/*",
        allowed_autonomy=AutonomyAction.AUTO,
        risk_level=RiskLevel.LOW,
        scope="execution_layer",
        rationale="单元测试可自主执行，无副作用",
    ),
    AutonomyBoundaryRule(
        rule_id="exec-lint-format",
        category="code_change",
        action_pattern="ruff format *",
        allowed_autonomy=AutonomyAction.AUTO,
        risk_level=RiskLevel.LOW,
        scope="execution_layer",
        rationale="代码格式化可自主，无逻辑变更",
    ),
    AutonomyBoundaryRule(
        rule_id="exec-mod-build",
        category="deployment",
        action_pattern="mod pack *",
        allowed_autonomy=AutonomyAction.AUTO,
        risk_level=RiskLevel.LOW,
        scope="execution_layer",
        rationale="Mod 打包可自主，产物待审",
    ),
    # === 执行层仅报告（medium risk, report_only）===
    AutonomyBoundaryRule(
        rule_id="exec-pr-create",
        category="code_change",
        action_pattern="github pr create *",
        allowed_autonomy=AutonomyAction.REPORT_ONLY,
        risk_level=RiskLevel.MEDIUM,
        scope="execution_layer",
        rationale="PR 创建可自主但需报告，便于追踪",
    ),
    AutonomyBoundaryRule(
        rule_id="exec-doc-update",
        category="code_change",
        action_pattern="docs/*.md",
        allowed_autonomy=AutonomyAction.REPORT_ONLY,
        risk_level=RiskLevel.LOW,
        scope="execution_layer",
        rationale="文档更新可自主但需报告",
    ),
    AutonomyBoundaryRule(
        rule_id="exec-track-digest-action-items",
        category="strategic",
        action_pattern="track_digest_action_items*",
        allowed_autonomy=AutonomyAction.REPORT_ONLY,
        risk_level=RiskLevel.MEDIUM,
        scope="strategic_layer",
        rationale="日更行动条目战略层追踪：自动入账、仅报告，不堆人工审批",
    ),
    # === 需会议决议（high risk, require_council）===
    AutonomyBoundaryRule(
        rule_id="council-roadmap-change",
        category="strategic",
        action_pattern="roadmap modify *",
        allowed_autonomy=AutonomyAction.REQUIRE_COUNCIL,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="路线图变更需员工自治会议决议",
    ),
    AutonomyBoundaryRule(
        rule_id="council-version-bump",
        category="strategic",
        action_pattern="version bump *",
        allowed_autonomy=AutonomyAction.REQUIRE_COUNCIL,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="版本号变更需员工自治会议决议",
    ),
    AutonomyBoundaryRule(
        rule_id="council-arch-refactor",
        category="strategic",
        action_pattern="architecture refactor *",
        allowed_autonomy=AutonomyAction.REQUIRE_COUNCIL,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="架构重构需员工自治会议决议",
    ),
    # === 需人工审批（high/critical risk, require_human）===
    AutonomyBoundaryRule(
        rule_id="strat-prod-deploy",
        category="deployment",
        action_pattern="production deploy *",
        allowed_autonomy=AutonomyAction.REQUIRE_HUMAN,
        risk_level=RiskLevel.CRITICAL,
        scope="strategic_layer",
        rationale="生产部署必须人工审批",
    ),
    AutonomyBoundaryRule(
        rule_id="strat-db-migration",
        category="data_modification",
        action_pattern="alembic upgrade *",
        allowed_autonomy=AutonomyAction.REQUIRE_HUMAN,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="数据库迁移必须人工审批",
    ),
    AutonomyBoundaryRule(
        rule_id="strat-rollback",
        category="rollback",
        action_pattern="release rollback *",
        allowed_autonomy=AutonomyAction.REQUIRE_HUMAN,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="生产回滚必须人工审批",
    ),
    AutonomyBoundaryRule(
        rule_id="strat-financial",
        category="financial",
        action_pattern="payment *",
        allowed_autonomy=AutonomyAction.REQUIRE_HUMAN,
        risk_level=RiskLevel.CRITICAL,
        scope="strategic_layer",
        rationale="财务操作必须人工审批",
    ),
    AutonomyBoundaryRule(
        rule_id="strat-external-comm",
        category="external_comm",
        action_pattern="external announce *",
        allowed_autonomy=AutonomyAction.REQUIRE_HUMAN,
        risk_level=RiskLevel.HIGH,
        scope="strategic_layer",
        rationale="对外公告必须人工审批",
    ),
)


class AutonomyEvaluator:
    """自治边界评估器：根据 action 描述匹配规则，决定 AI 可采取的行动等级。

    匹配逻辑：
    1. 启用规则的优先级：critical > high > medium > low
    2. 同优先级按 ``rule_id`` 字母序
    3. 首个匹配规则生效
    4. 无匹配则默认 ``require_human``（保守原则）
    """

    def __init__(self, rules: Optional[Iterable[AutonomyBoundaryRule]] = None) -> None:
        self._rules: List[AutonomyBoundaryRule] = (
            list(rules) if rules else list(DEFAULT_AUTONOMY_BOUNDARIES)
        )

    @classmethod
    def from_db(cls, session: Any = None) -> AutonomyEvaluator:
        """从 DB 加载启用规则；若表为空则 seed 默认规则。"""
        if session is None:
            session = get_session_factory()()
        try:
            stmt = select(AutonomyBoundaryModel).where(AutonomyBoundaryModel.enabled.is_(True))
            rows = session.execute(stmt).scalars().all()
            if not rows:
                # 表为空 → seed 默认规则
                seed_default_boundaries(session=session, commit=True)
                rows = session.execute(stmt).scalars().all()
            rules = [_row_to_rule(r) for r in rows]
            return cls(rules=rules)
        finally:
            if session is not None:
                session.close()

    def evaluate(
        self,
        action: str,
        *,
        scope: str = "both",
    ) -> AutonomyEvaluation:
        """评估给定 action 的自治等级。

        Args:
            action: 操作描述，如 ``"production deploy v10.0.1"``、``"pytest tests/test_strategic"``
            scope: 限定作用域 ``execution_layer`` / ``strategic_layer`` / ``both``

        Returns:
            AutonomyEvaluation: 评估结果（matched/rule/action/risk_level）
        """
        candidates = [
            r
            for r in self._rules
            if r.enabled and (scope == "both" or r.scope == "both" or r.scope == scope)
        ]
        # 按风险等级优先级排序（critical 优先）
        candidates.sort(key=lambda r: (_RISK_PRIORITY.get(r.risk_level.value, 99), r.rule_id))
        for rule in candidates:
            if rule.matches(action):
                return AutonomyEvaluation(
                    matched=True,
                    rule=rule,
                    action=rule.allowed_autonomy,
                    risk_level=rule.risk_level,
                )
        return AutonomyEvaluation(
            matched=False,
            rule=None,
            action=AutonomyAction.REQUIRE_HUMAN,
            risk_level=RiskLevel.MEDIUM,
            fallback_reason="no boundary rule matched; default to require_human (conservative)",
        )

    def list_rules(self, *, enabled_only: bool = True) -> List[AutonomyBoundaryRule]:
        """列出当前评估器的规则。"""
        if enabled_only:
            return [r for r in self._rules if r.enabled]
        return list(self._rules)


def seed_default_boundaries(
    *,
    session: Any = None,
    commit: bool = True,
) -> int:
    """将 ``DEFAULT_AUTONOMY_BOUNDARIES`` 写入 DB（幂等，按 ``rule_id`` 去重）。

    Returns:
        新增规则数（已存在的不计入）。
    """
    own_session = session is None
    if own_session:
        session = get_session_factory()()
    try:
        existing_ids: set[str] = set()
        for row in session.execute(select(AutonomyBoundaryModel.rule_id)).scalars():
            existing_ids.add(str(row))
        added = 0
        now = datetime.now(UTC)
        for rule in DEFAULT_AUTONOMY_BOUNDARIES:
            if rule.rule_id in existing_ids:
                continue
            session.add(
                AutonomyBoundaryModel(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    action_pattern=rule.action_pattern,
                    allowed_autonomy=rule.allowed_autonomy.value,
                    risk_level=rule.risk_level.value,
                    scope=rule.scope,
                    rationale=rule.rationale,
                    enabled=rule.enabled,
                    created_at=now,
                    updated_at=now,
                )
            )
            added += 1
        if commit and added > 0:
            session.commit()
        return added
    finally:
        if own_session:
            session.close()


def _row_to_rule(row: AutonomyBoundaryModel) -> AutonomyBoundaryRule:
    """从 ORM 行还原值对象。"""
    return AutonomyBoundaryRule(
        rule_id=row.rule_id,
        category=row.category,
        action_pattern=row.action_pattern,
        allowed_autonomy=AutonomyAction(row.allowed_autonomy),
        risk_level=RiskLevel(row.risk_level),
        scope=row.scope,
        rationale=row.rationale or "",
        enabled=bool(row.enabled),
    )


__all__ = [
    "AutonomyAction",
    "AutonomyBoundaryRule",
    "AutonomyEvaluation",
    "AutonomyEvaluator",
    "DEFAULT_AUTONOMY_BOUNDARIES",
    "RiskLevel",
    "seed_default_boundaries",
]
