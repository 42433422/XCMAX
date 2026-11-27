"""Strict data schemas for non-executing goal assessments and plan proposals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    node_id: str = Field(min_length=1, max_length=80)
    tool_id: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=200)
    params: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    approval_required: bool


class PlannedToolCall(PlanToolAction):
    response_excerpt: str = Field(
        min_length=1, max_length=4000, description="当前成稿中包含该动作的原文"
    )


class PlannedNavigation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    navigation_id: str = Field(min_length=1, max_length=80)
    response_excerpt: str = Field(min_length=1, max_length=4000)


class FileCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    evidence_id: str = Field(min_length=1, max_length=200)
    source_excerpt: str = Field(
        min_length=1, max_length=4000, description="宿主文件证据中的连续原文"
    )
    response_excerpt: str = Field(
        min_length=1, max_length=4000, description="由该文件证据支撑的当前成稿原文"
    )


class GoalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goal_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=4000)
    kind: Literal["reply", "read", "write", "constraint", "planned_action"]
    status: Literal["satisfied", "unmet", "not_applicable"]
    evidence_ids: list[str] = Field(max_length=256)
    reason: str = Field(min_length=1, max_length=4000)
    planned_calls: list[PlannedToolCall] = Field(
        default_factory=list,
        max_length=64,
        description="planned_action 的业务动作契约。纯文字方案使用 reply。",
    )
    planned_navigation: list[PlannedNavigation] = Field(
        default_factory=list,
        max_length=20,
        description="planned_action 的人工页面入口和成稿原文。",
    )
    file_basis: Literal["independent", "passages", "complete"] | None = Field(
        default=None,
        description=(
            "independent：目标与成稿均不依赖附件事实；passages：依赖附件局部内容；"
            "complete：汇总、比较或完整性声明需要完整范围。历史助手答复不属于文件证据。"
        ),
    )
    file_citations: list[FileCitation] = Field(
        default_factory=list,
        max_length=64,
        description="逐项关联成稿事实与实际文件引文。缺少所需来源时目标为 unmet。",
    )


class GoalReview(BaseModel):
    """A non-executing semantic assessment, constrained by host receipt validation."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goals: list[GoalAssessment] = Field(min_length=1, max_length=64)
    violations: list[str] = Field(max_length=64)
    uncovered_sources: list[str] = Field(max_length=64)
    feedback: str = Field(max_length=12000)
    feedback_disposition: Literal["none", "advisory", "blocking"] | None = None
    plan_content: Literal["steps", "narrative"] | None = Field(
        default=None,
        description=(
            "从原始要求与成稿独立识别方案类型。出现或要求具体工具、参数或产品入口时为 steps，"
            "包括尚未核实的具体声明。narrative 仅用于与产品能力无关的文字方案。"
        ),
    )
