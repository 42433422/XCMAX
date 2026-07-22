"""战略-执行分层机制 — 领域模型与服务层。

包结构：
- ``decision_ledger`` — 战略决策账本（提议/评估/执行/复盘 全生命周期）
- ``autonomy_boundary`` — 自治边界规则（AI 可自主 vs 必须人工/会议）
- ``council_meeting`` — 员工自治会议（议程、决议、action items 闭环）
- ``strategic_report_service`` — 战略层周报/月报自动产出（基于 daily_digest_records 聚合）

设计原则：
1. 战略层只读、决策、记录、追踪；执行层写代码、测试、部署
2. 战略层通过决策账本指挥执行层，执行层结果回写战略层
3. AI 在 autonomy_boundary 允许范围内可自主决策；超界升级人工或会议
4. 决策账本是不可变审计日志（status 单调推进，禁止回退）
"""

from __future__ import annotations

from modstore_server.strategic_layer.autonomy_boundary import (
    DEFAULT_AUTONOMY_BOUNDARIES,
    AutonomyAction,
    AutonomyBoundaryRule,
    AutonomyEvaluator,
    RiskLevel,
    seed_default_boundaries,
)
from modstore_server.strategic_layer.council_meeting import (
    CouncilMeetingService,
    MeetingDecisionRef,
    MeetingParticipants,
    MeetingStatus,
    MeetingType,
)
from modstore_server.strategic_layer.decision_ledger import (
    DecidedBy,
    DecisionAlreadyDecidedError,
    DecisionLifecycleError,
    DecisionProposer,
    DecisionStatus,
    DecisionType,
    StrategicDecisionLedger,
    StrategicDecisionRecord,
)
from modstore_server.strategic_layer.digest_strategic_bridge import (
    TRACK_ACTION,
    TRACK_SCOPE,
    ensure_digest_track_decision,
    mirror_daily_status,
    sync_daily_to_strategic,
    sync_record_after_status_writeback,
)
from modstore_server.strategic_layer.strategic_report_service import (
    StrategicReportService,
    WeeklyReportPeriod,
    monthly_report_key,
    weekly_report_key,
)

__all__ = [
    "AutonomyAction",
    "AutonomyBoundaryRule",
    "AutonomyEvaluator",
    "DEFAULT_AUTONOMY_BOUNDARIES",
    "CouncilMeetingService",
    "MeetingDecisionRef",
    "MeetingParticipants",
    "MeetingStatus",
    "MeetingType",
    "DecisionAlreadyDecidedError",
    "DecisionLifecycleError",
    "DecisionProposer",
    "DecisionStatus",
    "DecisionType",
    "DecidedBy",
    "RiskLevel",
    "TRACK_ACTION",
    "TRACK_SCOPE",
    "StrategicDecisionLedger",
    "StrategicDecisionRecord",
    "StrategicReportService",
    "WeeklyReportPeriod",
    "ensure_digest_track_decision",
    "mirror_daily_status",
    "monthly_report_key",
    "seed_default_boundaries",
    "sync_daily_to_strategic",
    "sync_record_after_status_writeback",
    "weekly_report_key",
]
