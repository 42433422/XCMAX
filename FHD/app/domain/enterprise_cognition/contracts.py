"""Shared HTTP and model-tool inputs; identity and approval are never input fields."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.enterprise_cognition.goal_contract import GoalDefinition


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StateQuery(EmptyInput):
    entity_type: Literal["order", "customer", "employee", "task", "fund", "inventory", "production"] = (
        "order"
    )
    entity_id: str | None = Field(default=None, min_length=1, max_length=160)
    limit: int = Field(default=10, ge=1, le=20, strict=True)
    force_refresh: bool = False
    as_of: AwareDatetime | None = None
    scenario_delivery_quantity: str | None = Field(
        default=None, max_length=32, pattern=r"^[0-9]+(?:\.[0-9]{1,4})?$"
    )

    @model_validator(mode="after")
    def validate_world_query(self) -> StateQuery:
        if self.as_of is not None and (
            self.entity_id is None or self.force_refresh or self.scenario_delivery_quantity is not None
        ):
            raise ValueError("historical_query_requires_single_entity_without_refresh_or_scenario")
        if self.scenario_delivery_quantity is not None and (
            self.entity_id is None or self.entity_type != "order"
        ):
            raise ValueError("delivery_scenario_requires_single_order")
        return self


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
