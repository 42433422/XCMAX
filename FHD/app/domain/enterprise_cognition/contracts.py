"""Shared HTTP and model-tool inputs; identity and approval are never input fields."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enterprise_cognition.goal_contract import GoalDefinition


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StateQuery(EmptyInput):
    entity_type: Literal["order", "customer", "employee", "task", "fund"] = "order"
    entity_id: str | None = Field(default=None, min_length=1, max_length=160)
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    force_refresh: bool = False


class GoalQuery(EmptyInput):
    goal_id: str | None = Field(default=None, min_length=1, max_length=96)


class PlanRequest(EmptyInput):
    goal_id: str = Field(min_length=1, max_length=96)
    request_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)


class OutcomeRequest(EmptyInput):
    run_id: str = Field(min_length=1, max_length=96)


class CognitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["catalog", "query", "goals", "bind_goal", "plan", "evaluate"]
    params: dict[str, Any] = Field(default_factory=dict)


INPUT_MODELS: dict[str, type[BaseModel]] = {
    "catalog": EmptyInput,
    "query": StateQuery,
    "goals": GoalQuery,
    "bind_goal": GoalDefinition,
    "plan": PlanRequest,
    "evaluate": OutcomeRequest,
}
ENTERPRISE_INPUT_SCHEMAS = {
    ("enterprise_cognition", action): model.model_json_schema()
    for action, model in INPUT_MODELS.items()
}
