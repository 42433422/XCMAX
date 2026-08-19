"""战略决策账本 — 领域模型 + 服务。

决策生命周期：
    proposed
      ↓ (AutonomyEvaluator.evaluate)
      ├─ AUTO        → auto_approved → executing → completed
      ├─ REPORT_ONLY → auto_approved → executing → completed（标记 report_only）
      ├─ REQUIRE_HUMAN → proposed（等待 user.approve / user.reject）
      └─ REQUIRE_COUNCIL → proposed（等待 council_meeting.conclude → approved/rejected）

状态转换约束（单调推进，禁止回退）：
    proposed → auto_approved | approved | rejected | withdrawn
    auto_approved → executing | withdrawn
    approved → executing | withdrawn
    executing → completed | withdrawn
    completed → reviewed（仅一次，不可再变）

任何状态转换都通过 ``StrategicDecisionLedger`` 服务完成，确保审计日志完整。
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modstore_server.db.base import get_session_factory
from modstore_server.db.strategic import StrategicDecision as StrategicDecisionModel
from modstore_server.strategic_layer.autonomy_boundary import (
    AutonomyAction,
    AutonomyEvaluator,
)
from modstore_server.strategic_layer.decision_ledger_lifecycle import (
    DecisionLedgerLifecycleMixin,
)

logger = logging.getLogger(__name__)


class DecisionStatus(str, Enum):
    """决策状态枚举（单调推进，禁止回退）。"""

    PROPOSED = "proposed"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"


class DecisionType(str, Enum):
    """决策类型：战略层 / 战术层 / 执行层。"""

    STRATEGIC = "strategic"
    TACTICAL = "tactical"
    OPERATIONAL = "operational"


class DecidedBy(str, Enum):
    """决策者标识。"""

    AI_AUTONOMY = "ai-autonomy"
    USER = "user"
    COUNCIL_VOTE = "council-vote"


# 允许的状态转换图（from_status → {to_status...}）
_ALLOWED_TRANSITIONS: Dict[DecisionStatus, frozenset[DecisionStatus]] = {
    DecisionStatus.PROPOSED: frozenset(
        {
            DecisionStatus.AUTO_APPROVED,
            DecisionStatus.APPROVED,
            DecisionStatus.REJECTED,
            DecisionStatus.WITHDRAWN,
        }
    ),
    DecisionStatus.AUTO_APPROVED: frozenset({DecisionStatus.EXECUTING, DecisionStatus.WITHDRAWN}),
    DecisionStatus.APPROVED: frozenset({DecisionStatus.EXECUTING, DecisionStatus.WITHDRAWN}),
    DecisionStatus.EXECUTING: frozenset({DecisionStatus.COMPLETED, DecisionStatus.WITHDRAWN}),
    DecisionStatus.COMPLETED: frozenset(),  # 终态（review 通过字段标记，不改 status）
    DecisionStatus.REJECTED: frozenset(),
    DecisionStatus.WITHDRAWN: frozenset(),
}


class DecisionLifecycleError(Exception):
    """非法状态转换或操作。"""


class DecisionAlreadyDecidedError(DecisionLifecycleError):
    """决策已经处于终态（rejected/withdrawn/completed），不能再变更。"""


def _has_idempotency_key(row: StrategicDecisionModel, key: str) -> bool:
    """Return whether a persisted record was created for this exact stable key."""
    try:
        payload = json.loads(str(row.decision_payload_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("_idempotency_key") == key


@dataclass
class DecisionProposer:
    """决策提议人值对象。"""

    actor: str  # ai-strategist | user | <employee_id>
    rationale: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategicDecisionRecord:
    """战略决策记录值对象（与 ORM 解耦）。"""

    decision_id: str
    title: str
    rationale: str
    proposed_by: str
    proposed_at: datetime
    decision_type: DecisionType
    scope: str
    scope_ref: str
    status: DecisionStatus
    decided_by: str
    decided_at: Optional[datetime]
    decision_payload: Dict[str, Any]
    execution_plan: Dict[str, Any]
    execution_result: Dict[str, Any]
    autonomy_rule_id: str
    autonomy_action: str
    autonomy_risk_level: str
    review_at: Optional[datetime]
    review_notes: str
    reviewed_by: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision_type"] = self.decision_type.value
        d["status"] = self.status.value
        d["proposed_at"] = self.proposed_at.isoformat() if self.proposed_at else None
        d["decided_at"] = self.decided_at.isoformat() if self.decided_at else None
        d["review_at"] = self.review_at.isoformat() if self.review_at else None
        d["created_at"] = self.created_at.isoformat() if self.created_at else None
        d["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return d


class StrategicDecisionLedger(DecisionLedgerLifecycleMixin):
    """战略决策账本服务。

    所有决策的提议、评估、批准、执行、完成、复盘均通过此服务，确保审计日志完整。
    状态转换受 ``_ALLOWED_TRANSITIONS`` 约束，违反则抛 ``DecisionLifecycleError``。
    """

    def __init__(
        self,
        *,
        evaluator: Optional[AutonomyEvaluator] = None,
        session_factory: Any = None,
    ) -> None:
        self._evaluator = evaluator
        self._session_factory = session_factory or get_session_factory

    # ---------------- 提议 ----------------

    def propose(
        self,
        *,
        title: str,
        action: str,
        proposer: DecisionProposer,
        decision_type: DecisionType = DecisionType.OPERATIONAL,
        scope: str = "global",
        scope_ref: str = "",
        execution_plan: Optional[Dict[str, Any]] = None,
        idempotency_key: str = "",
    ) -> StrategicDecisionRecord:
        """提议新决策；立即评估自治边界，根据 ``allowed_autonomy`` 决定初始状态。

        Args:
            title: 决策标题
            action: 操作描述（用于自治边界匹配，如 ``"production deploy v10.0.1"``）
            proposer: 提议人值对象
            decision_type: 决策类型（默认 operational）
            scope: 作用域 ``global`` / ``release_train`` / ``module`` / ``employee`` / ``incident``
            scope_ref: 关联 ID（如模块名/版本号/员工 ID）
            execution_plan: 执行计划 JSON（执行层员工 ID、任务描述、依赖）
            idempotency_key: 可选的稳定键；相同键只创建一条决策，适用于调度任务。

        Returns:
            StrategicDecisionRecord: 创建后的决策记录（含自治评估结果）
        """
        if not title or not title.strip():
            raise ValueError("title must not be empty")
        if not action or not action.strip():
            raise ValueError("action must not be empty")

        normalized_key = str(idempotency_key or "").strip()
        if len(normalized_key) > 256:
            raise ValueError("idempotency_key too long")
        decision_id = (
            f"dec-{hashlib.sha256(normalized_key.encode('utf-8')).hexdigest()[:16]}"
            if normalized_key
            else f"dec-{uuid.uuid4().hex[:16]}"
        )

        # Check before running any downstream decision work.  The deterministic
        # decision id plus the unique database constraint also protects the race
        # between two scheduler processes; the IntegrityError path below reloads
        # the winner instead of creating a duplicate strategic request.
        session = self._session_factory()()
        try:
            if normalized_key:
                existing = session.execute(
                    select(StrategicDecisionModel).where(
                        StrategicDecisionModel.decision_id == decision_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if not _has_idempotency_key(existing, normalized_key):
                        raise DecisionLifecycleError("idempotency_key collision")
                    return _model_to_record(existing)
        finally:
            session.close()

        evaluator = self._evaluator or AutonomyEvaluator.from_db()
        evaluation = evaluator.evaluate(action)

        now = datetime.now(timezone.utc)

        # 根据自治评估决定初始状态
        if evaluation.action == AutonomyAction.AUTO:
            status = DecisionStatus.AUTO_APPROVED
            decided_by = DecidedBy.AI_AUTONOMY.value
            decided_at: Optional[datetime] = now
        elif evaluation.action == AutonomyAction.REPORT_ONLY:
            status = DecisionStatus.AUTO_APPROVED
            decided_by = DecidedBy.AI_AUTONOMY.value
            decided_at = now
        else:
            # REQUIRE_HUMAN / REQUIRE_COUNCIL → 保持 proposed，等待外部决策
            status = DecisionStatus.PROPOSED
            decided_by = ""
            decided_at = None

        record = StrategicDecisionRecord(
            decision_id=decision_id,
            title=title.strip(),
            rationale=proposer.rationale,
            proposed_by=proposer.actor,
            proposed_at=now,
            decision_type=decision_type,
            scope=scope,
            scope_ref=scope_ref,
            status=status,
            decided_by=decided_by,
            decided_at=decided_at,
            decision_payload={
                **proposer.payload,
                "action": action,
                **({"_idempotency_key": normalized_key} if normalized_key else {}),
            },
            execution_plan=execution_plan or {},
            execution_result={},
            autonomy_rule_id=evaluation.rule.rule_id if evaluation.rule else "",
            autonomy_action=evaluation.action.value,
            autonomy_risk_level=evaluation.risk_level.value,
            review_at=None,
            review_notes="",
            reviewed_by="",
            created_at=now,
            updated_at=now,
        )

        session = self._session_factory()()
        try:
            session.add(_record_to_model(record))
            session.commit()
            logger.info(
                "decision proposed decision_id=%s title=%s status=%s autonomy=%s",
                decision_id,
                record.title,
                record.status.value,
                record.autonomy_action,
            )
            return record
        except IntegrityError:
            session.rollback()
            if normalized_key:
                existing = session.execute(
                    select(StrategicDecisionModel).where(
                        StrategicDecisionModel.decision_id == decision_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    if not _has_idempotency_key(existing, normalized_key):
                        raise DecisionLifecycleError("idempotency_key collision")
                    return _model_to_record(existing)
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- 决策 ----------------

    def approve(
        self,
        decision_id: str,
        *,
        decided_by: DecidedBy,
        review_notes: str = "",
    ) -> StrategicDecisionRecord:
        """人工或会议通过决策（仅 ``proposed`` 状态可调用）。"""
        return self._transition(
            decision_id,
            target_status=DecisionStatus.APPROVED,
            decided_by=decided_by,
            review_notes=review_notes,
        )

    def reject(
        self,
        decision_id: str,
        *,
        decided_by: DecidedBy,
        review_notes: str,
    ) -> StrategicDecisionRecord:
        """人工或会议否决决策（仅 ``proposed`` 状态可调用）。"""
        if not review_notes or not review_notes.strip():
            raise ValueError("review_notes required for rejection")
        return self._transition(
            decision_id,
            target_status=DecisionStatus.REJECTED,
            decided_by=decided_by,
            review_notes=review_notes.strip(),
        )

    def withdraw(
        self,
        decision_id: str,
        *,
        actor: str,
        reason: str,
    ) -> StrategicDecisionRecord:
        """撤回决策（任意非终态可调用）。"""
        if not reason.strip():
            raise ValueError("reason required for withdrawal")
        return self._transition(
            decision_id,
            target_status=DecisionStatus.WITHDRAWN,
            decided_by_str=actor,
            review_notes=reason.strip(),
        )

    # ---------------- 执行 ----------------

    def start_execution(
        self,
        decision_id: str,
        *,
        execution_plan: Optional[Dict[str, Any]] = None,
    ) -> StrategicDecisionRecord:
        """开始执行决策（``auto_approved`` 或 ``approved`` 状态可调用）。"""
        return self._transition(
            decision_id,
            target_status=DecisionStatus.EXECUTING,
            execution_plan=execution_plan,
        )

    def complete_execution(
        self,
        decision_id: str,
        *,
        execution_result: Dict[str, Any],
        review_at: Optional[datetime] = None,
    ) -> StrategicDecisionRecord:
        """执行层回写完成结果（``executing`` 状态可调用）。

        Args:
            decision_id: 决策 ID
            execution_result: 执行结果 JSON（执行层员工填入）
            review_at: 复盘截止时间（默认 7 天后）
        """
        if not execution_result:
            execution_result = {}
        if review_at is None:
            review_at = datetime.now(timezone.utc).replace(microsecond=0)
            # 默认 7 天后复盘
            from datetime import timedelta

            review_at = review_at + timedelta(days=7)
        return self._transition(
            decision_id,
            target_status=DecisionStatus.COMPLETED,
            execution_result=execution_result,
            review_at=review_at,
        )


def _record_to_model(record: StrategicDecisionRecord) -> StrategicDecisionModel:
    return StrategicDecisionModel(
        decision_id=record.decision_id,
        title=record.title,
        rationale=record.rationale,
        proposed_by=record.proposed_by,
        proposed_at=record.proposed_at,
        decision_type=record.decision_type.value,
        scope=record.scope,
        scope_ref=record.scope_ref,
        status=record.status.value,
        decided_by=record.decided_by,
        decided_at=record.decided_at,
        decision_payload_json=json.dumps(record.decision_payload, ensure_ascii=False),
        execution_plan_json=json.dumps(record.execution_plan, ensure_ascii=False),
        execution_result_json=json.dumps(record.execution_result, ensure_ascii=False),
        autonomy_rule_id=record.autonomy_rule_id,
        autonomy_action=record.autonomy_action,
        autonomy_risk_level=record.autonomy_risk_level,
        review_at=record.review_at,
        review_notes=record.review_notes,
        reviewed_by=record.reviewed_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _model_to_record(row: StrategicDecisionModel) -> StrategicDecisionRecord:
    def _loads(s: str, default: Any) -> Any:
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:
            return default

    return StrategicDecisionRecord(
        decision_id=row.decision_id,
        title=row.title,
        rationale=row.rationale or "",
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        decision_type=DecisionType(row.decision_type or "operational"),
        scope=row.scope or "global",
        scope_ref=row.scope_ref or "",
        status=DecisionStatus(row.status),
        decided_by=row.decided_by or "",
        decided_at=row.decided_at,
        decision_payload=_loads(row.decision_payload_json, {}),
        execution_plan=_loads(row.execution_plan_json, {}),
        execution_result=_loads(row.execution_result_json, {}),
        autonomy_rule_id=row.autonomy_rule_id or "",
        autonomy_action=row.autonomy_action or "",
        autonomy_risk_level=row.autonomy_risk_level or "",
        review_at=row.review_at,
        review_notes=row.review_notes or "",
        reviewed_by=row.reviewed_by or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "DecisionAlreadyDecidedError",
    "DecisionLifecycleError",
    "DecisionProposer",
    "DecisionStatus",
    "DecisionType",
    "DecidedBy",
    "StrategicDecisionLedger",
    "StrategicDecisionRecord",
]
