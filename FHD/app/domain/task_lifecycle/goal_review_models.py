"""Strict goal review schemas and frozen source identities; no execution authority."""

from __future__ import annotations

from collections.abc import Sequence
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


def goal_source_catalogue(
    contract: dict[str, Any], answers: Sequence[dict[str, Any]] = ()
) -> dict[str, dict[str, Any]]:
    """Derive locatable obligations from frozen user input, never assistant/tool claims."""
    kinds = ["reply", "constraint"] + (
        ["planned_action"]
        if contract["scope"].get("requested_deliverable") == "action_plan"
        else ["read", "write"]
    )
    sources = {
        "request": {"text": contract["request"]["text"], "role": "user", "allowed_kinds": kinds}
    }
    for row in answers:
        identity, text = row.get("source_id"), row.get("answer")
        if (
            isinstance(identity, str)
            and identity.startswith("answer:")
            and identity != "answer:"
            and identity not in sources
            and isinstance(text, str)
            and text.strip()
        ):
            sources[identity] = {"text": text, "role": "user", "allowed_kinds": kinds}
    objective = (contract["scope"].get("constraints") or {}).get("objective")
    if isinstance(objective, str) and objective.strip():
        sources["objective"] = {
            "text": objective,
            "role": "host",
            "allowed_kinds": ["read", "write"],
        }
    for index, row in enumerate(contract["request"].get("history") or []):
        if (
            isinstance(row, dict)
            and row.get("role") == "user"
            and isinstance(row.get("content"), str)
            and row["content"].strip()
        ):
            sources[f"history:{index}:user"] = {
                "text": row["content"],
                "role": "user",
                "allowed_kinds": ["reply", "constraint"],
            }
    return sources


def normalize_review_provenance(raw: Any, contract: dict[str, Any]) -> Any:
    """Normalize current-request aliases only for verbatim frozen request text."""
    if not isinstance(raw, dict) or not isinstance(raw.get("goals"), list):
        return raw
    request = contract["request"]["text"]
    for goal in raw["goals"]:
        if (
            isinstance(goal, dict)
            and goal.get("source_id") in {"original_request", "input", "user_request"}
            and isinstance(goal.get("source"), str)
            and goal["source"] in request
        ):
            goal["source_id"] = "request"
    return raw


def review_judgments(review: dict[str, Any]) -> dict[str, Any]:
    """Only identifiers and verbatim source bindings may change during repair."""
    return {
        **review,
        "goals": [
            {
                key: value
                for key, value in goal.items()
                if key not in {"goal_id", "source_id", "source"}
            }
            for goal in review["goals"]
        ],
    }


def preserves_source_bindings(
    previous: dict[str, Any],
    review: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> bool:
    for before, after in zip(previous["goals"], review["goals"], strict=True):
        quote = before["source"]
        if quote in sources.get(before["source_id"], {}).get("text", ""):
            if (before["source_id"], quote) != (after["source_id"], after["source"]):
                return False
        elif (
            any(quote in source["text"] for source in sources.values()) and quote != after["source"]
        ):
            return False
    return True
