"""Typed operating-goal input; contains no database or tool execution imports."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class GoalDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal_id: str = Field(min_length=1, max_length=96, pattern=r"^[\w.:-]+$")
    objective: str = Field(min_length=1, max_length=2000)
    entity_type: Literal["order", "customer", "employee", "task", "fund"]
    entity_id: str = Field(min_length=1, max_length=160)
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=64)
    direction: Literal["increase", "decrease"]
    target: Decimal = Field(allow_inf_nan=False)
    deadline: AwareDatetime | None = None
    strategic_plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    strategic_feature_index: int | None = Field(default=None, ge=0, le=63)

    @field_validator("target", mode="before")
    @classmethod
    def reject_boolean_target(cls, value):
        if isinstance(value, bool):
            raise ValueError("target must be a finite number")
        return value

    @model_validator(mode="after")
    def normalize_authority_id(self) -> Self:
        if self.entity_type in {"order", "customer", "fund"}:
            if not self.entity_id.isdigit() or int(self.entity_id) <= 0:
                raise ValueError("entity_id must be a positive authoritative row ID")
            self.entity_id = str(int(self.entity_id))
        return self
