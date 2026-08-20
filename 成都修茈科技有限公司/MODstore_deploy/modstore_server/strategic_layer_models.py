"""Pydantic request contracts for the strategic-layer HTTP API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProposeDecisionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="决策标题")
    action: str = Field(
        ..., min_length=1, max_length=500, description="操作描述（用于自治边界匹配）"
    )
    rationale: str = Field("", max_length=2000, description="提议理由")
    actor: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="提议人 ID（ai-strategist/user/<employee_id>）",
    )
    payload: Dict[str, Any] = Field(default_factory=dict, description="决策附加上下文")
    decision_type: str = Field("operational", description="strategic/tactical/operational")
    scope: str = Field("global", description="global/release_train/module/employee/incident")
    scope_ref: str = Field("", max_length=256, description="关联 ID（模块名/版本号/员工 ID 等）")
    execution_plan: Dict[str, Any] = Field(default_factory=dict, description="执行计划 JSON")


class DecisionReviewRequest(BaseModel):
    decided_by: str = Field("user", description="决策者标识：user/council-vote")
    review_notes: str = Field("", max_length=4000, description="决策备注（reject 必填）")


class WithdrawRequest(BaseModel):
    actor: str = Field(..., min_length=1, max_length=128, description="撤回人 ID")
    reason: str = Field(..., min_length=1, max_length=2000, description="撤回原因")


class StartExecutionRequest(BaseModel):
    execution_plan: Dict[str, Any] = Field(default_factory=dict, description="执行计划更新")


class CompleteExecutionRequest(BaseModel):
    execution_result: Dict[str, Any] = Field(default_factory=dict, description="执行结果 JSON")
    review_at: Optional[str] = Field(None, description="复盘截止时间 ISO 字符串（默认 +7d）")


class ReviewDecisionRequest(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=128, description="复盘人 ID")
    review_notes: str = Field(..., min_length=1, max_length=4000, description="复盘结论")


class ScheduleMeetingRequest(BaseModel):
    meeting_type: str = Field(
        "ad_hoc",
        description="daily_standup/weekly_review/monthly_strategy/ad_hoc/incident_review",
    )
    title: str = Field(..., min_length=1, max_length=200)
    scheduled_at: str = Field(..., description="开始时间 ISO 字符串")
    chair: str = Field("", max_length=128, description="主持人 ID")
    required_participants: List[str] = Field(default_factory=list, description="必需参会人 ID 列表")
    optional_participants: List[str] = Field(default_factory=list, description="可选参会人 ID 列表")
    agenda: str = Field(..., min_length=1, max_length=4000, description="议程（Markdown 文本）")
    context: Dict[str, Any] = Field(default_factory=dict, description="会议上下文")


class ConcludeMeetingRequest(BaseModel):
    minutes_md: str = Field(..., min_length=1, max_length=20000, description="会议纪要 Markdown")
    actor: str = Field("ai-strategist", max_length=128, description="结束人 ID")
    decisions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="会议决议列表，每项含 {decision_id, vote_outcome, vote_summary}",
    )
    action_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="action items 列表，每项含 {description, assigned_to, decision_id, due_at}",
    )


class CancelMeetingRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000, description="取消原因")


class UpdateActionItemRequest(BaseModel):
    status: Optional[str] = Field(
        None, description="pending/in_progress/completed/blocked/cancelled"
    )
    result: Optional[Dict[str, Any]] = Field(None, description="执行结果 JSON")
    block_reason: Optional[str] = Field(None, max_length=2000, description="阻塞原因")
    completed_at: Optional[str] = Field(None, description="完成时间 ISO 字符串")


class GenerateWeeklyReportRequest(BaseModel):
    target_date: Optional[str] = Field(None, description="目标日期 ISO 字符串（默认今天）")
    actor: str = Field("ai-strategist", max_length=128, description="生成人 ID")


class GenerateMonthlyReportRequest(BaseModel):
    year: Optional[int] = Field(None, ge=2020, le=2100, description="年份（默认上个月所在年）")
    month: Optional[int] = Field(None, ge=1, le=12, description="月份（默认上个月）")
    actor: str = Field("ai-strategist", max_length=128, description="生成人 ID")


class StrategicCouncilReviewRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=128)
    package_id: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., min_length=1, max_length=64)
    package_sha256: str = Field(..., min_length=64, max_length=64)
    goal_id: str = Field(..., min_length=1, max_length=128)
    loop_run_id: str = Field(..., min_length=1, max_length=128)
    para_task_id: str = Field(..., min_length=1, max_length=128)
    strategy_intent: str = Field(..., min_length=1, max_length=4000)
    changed_files: List[Any] = Field(default_factory=list)
