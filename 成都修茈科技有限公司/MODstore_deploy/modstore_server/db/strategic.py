"""战略-执行分层机制持久化模型。

战略层只读、决策、记录、追踪；执行层写代码、测试、部署。
硬隔离：战略层通过决策账本指挥执行层，执行层结果回写战略层。

四张表：
- ``strategic_decisions`` — 战略决策账本（提议→评估→执行→复盘）
- ``autonomy_boundaries`` — 自治边界规则（哪些操作 AI 可自主、哪些必须人工/会议）
- ``council_meetings`` — 员工自治会议（议程、决议、action items）
- ``strategic_action_items`` — 行动项（与决策 + 会议关联）
- ``strategic_reports`` — 战略层周报/月报（基于 daily_digest_records 聚合）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StrategicDecision(Base):
    """战略决策账本条目。

    生命周期：proposed → (auto_approved | approved | rejected) → executing → completed → (reviewed)
    决策者：``ai-autonomy``（边界内自动）/ ``user``（人工）/ ``council-vote``（会议决议）
    """

    __tablename__ = "strategic_decisions"
    __table_args__ = (UniqueConstraint("decision_id", name="uq_strategic_decisions_decision_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(64), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    rationale = Column(Text, default="")
    proposed_by = Column(
        String(64), nullable=False, index=True
    )  # ai-strategist | user | <employee_id>
    proposed_at = Column(DateTime, default=_utcnow, index=True)

    # strategic（战略层）/ tactical（战术层）/ operational（执行层）
    decision_type = Column(String(32), default="operational", index=True)
    # global | release_train | module | employee | incident
    scope = Column(String(32), default="global", index=True)
    scope_ref = Column(String(128), default="", index=True)  # 关联模块/版本/员工 ID

    # proposed | auto_approved | approved | rejected | executing | completed | withdrawn
    status = Column(String(32), default="proposed", nullable=False, index=True)

    # ai-autonomy | user | council-vote | None
    decided_by = Column(String(64), default="", index=True)
    decided_at = Column(DateTime, nullable=True)

    # 决策详细数据 JSON（输入参数、上下文、评估依据）
    decision_payload_json = Column(Text, default="{}")
    # 执行计划 JSON（执行层员工 ID、任务描述、依赖）
    execution_plan_json = Column(Text, default="{}")
    # 执行结果 JSON（执行层回写）
    execution_result_json = Column(Text, default="{}")

    # 自治边界评估结果
    autonomy_rule_id = Column(String(64), default="", index=True)
    autonomy_action = Column(
        String(32), default="", index=True
    )  # auto | report_only | require_human | require_council
    autonomy_risk_level = Column(
        String(16), default="", index=True
    )  # low | medium | high | critical

    # 复盘
    review_at = Column(DateTime, nullable=True, index=True)
    review_notes = Column(Text, default="")
    reviewed_by = Column(String(64), default="")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class AutonomyBoundary(Base):
    """自治边界规则：定义哪些操作 AI 可自主、哪些必须人工/会议。

    匹配优先级：critical > high > medium > low；同类按 ``rule_id`` 字母序。
    """

    __tablename__ = "autonomy_boundaries"
    __table_args__ = (UniqueConstraint("rule_id", name="uq_autonomy_boundaries_rule_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(64), nullable=False, index=True)
    # code_change | deployment | data_modification | external_comm | financial | rollback | strategic
    category = Column(String(32), nullable=False, index=True)
    # glob 或 regex 模式，匹配 action 描述
    action_pattern = Column(String(256), nullable=False)
    # auto（自动通过）| report_only（通过但记录）| require_human（升级人工）| require_council（会议决议）
    allowed_autonomy = Column(String(32), nullable=False, default="require_human", index=True)
    risk_level = Column(
        String(16), nullable=False, default="medium", index=True
    )  # low | medium | high | critical
    # execution_layer | strategic_layer | both
    scope = Column(String(32), default="both", nullable=False)

    rationale = Column(Text, default="")
    enabled = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class CouncilMeeting(Base):
    """员工自治会议：议程、决议、action items 闭环。"""

    __tablename__ = "council_meetings"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_council_meetings_meeting_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(String(64), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    agenda = Column(Text, default="")

    # daily_standup | weekly_review | monthly_strategy | ad_hoc | incident_review
    meeting_type = Column(String(32), default="ad_hoc", nullable=False, index=True)

    scheduled_at = Column(DateTime, default=_utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    concluded_at = Column(DateTime, nullable=True)

    # scheduled | in_progress | concluded | cancelled
    status = Column(String(32), default="scheduled", nullable=False, index=True)

    # JSON 数组：参与员工 ID 列表
    participants_json = Column(Text, default="[]")
    # 会议纪要 Markdown
    minutes_md = Column(Text, default="")
    # JSON 数组：决议列表（指向 strategic_decisions.decision_id）
    decisions_json = Column(Text, default="[]")
    # JSON 数组：action items 列表
    action_items_json = Column(Text, default="[]")

    # 关联上下文（如基于哪个 daily_digest_record）
    source_digest_record_id = Column(Integer, nullable=True, index=True)
    source_context_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class StrategicActionItem(Base):
    """行动项：与决策 + 会议关联，闭环追踪。"""

    __tablename__ = "strategic_action_items"
    __table_args__ = (UniqueConstraint("action_id", name="uq_strategic_action_items_action_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(String(64), nullable=False, index=True)
    # 关联决策（必填）与会议（可空）
    decision_id = Column(
        String(64),
        ForeignKey("strategic_decisions.decision_id"),
        nullable=False,
        index=True,
    )
    meeting_id = Column(
        String(64),
        ForeignKey("council_meetings.meeting_id"),
        nullable=True,
        index=True,
    )

    description = Column(Text, nullable=False)
    assigned_to = Column(String(64), nullable=False, index=True)  # employee_id
    # pending | in_progress | completed | blocked | cancelled
    status = Column(String(32), default="pending", nullable=False, index=True)

    due_at = Column(DateTime, nullable=True, index=True)
    completed_at = Column(DateTime, nullable=True)
    result_json = Column(Text, default="{}")
    block_reason = Column(Text, default="")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class StrategicReport(Base):
    """战略层周报/月报：基于 daily_digest_records 聚合。"""

    __tablename__ = "strategic_reports"
    __table_args__ = (UniqueConstraint("report_key", name="uq_strategic_reports_report_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    # weekly:2026-W29 | monthly:2026-07
    report_key = Column(String(64), nullable=False, index=True)
    # weekly | monthly
    report_type = Column(String(16), nullable=False, index=True)
    # 报告起始/结束日期
    period_start = Column(Date, nullable=False, index=True)
    period_end = Column(Date, nullable=False, index=True)

    # 报告内容 Markdown
    content_md = Column(Text, default="")
    # 聚合指标 JSON（覆盖率、CI、loop、部署、决策、action items、incident）
    metrics_json = Column(Text, default="{}")
    # 风险预警 JSON
    risks_json = Column(Text, default="[]")
    # 下周/月建议 JSON
    recommendations_json = Column(Text, default="[]")

    # 关联 daily_digest_record IDs（覆盖期间）
    source_digest_ids_json = Column(Text, default="[]")

    # generated | reviewed | published
    status = Column(String(16), default="generated", nullable=False, index=True)
    reviewed_by = Column(String(64), default="")
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, default="")

    generated_by = Column(String(64), default="ai-strategist")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


__all__ = [
    "AutonomyBoundary",
    "CouncilMeeting",
    "StrategicActionItem",
    "StrategicDecision",
    "StrategicReport",
]
