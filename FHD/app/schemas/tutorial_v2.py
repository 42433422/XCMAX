"""Public DTO contract for Tutorial V2."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TutorialEvidenceDTO(BaseModel):
    step_id: str
    status: Literal["pending", "failed", "passed"]
    result_code: str
    entity_refs: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int | float | str] = Field(default_factory=dict)
    attempt_count: int = 0
    verified_at: str | None = None


class TutorialStepDTO(BaseModel):
    id: str
    title: str
    goal: str
    instruction: str
    success_criteria: str
    why: str
    hint: str
    route_name: str
    target_selector: str
    required: bool = True
    status: Literal["pending", "failed", "passed"] = "pending"
    evidence: TutorialEvidenceDTO | None = None


class TutorialRunDTO(BaseModel):
    id: str
    workspace_id: str
    course_id: str
    version: int
    status: Literal["active", "paused", "completed", "reset"]
    current_step_id: str
    attempt_count: int
    progress: int = Field(ge=0, le=100)
    completed_steps: int
    total_steps: int
    generation: int
    teaching_space: Literal[True]
    steps: list[TutorialStepDTO]
    started_at: str | None = None
    completed_at: str | None = None


class TutorialCourseDTO(BaseModel):
    id: str
    title: str
    summary: str
    estimated_minutes: int
    prerequisite_ids: list[str]
    version: int
    steps: list[TutorialStepDTO]
    locked: bool
    missing_prerequisite_ids: list[str]
    run: TutorialRunDTO | None = None
    status: Literal["not_started", "active", "paused", "completed", "reset"]
    progress: int = Field(ge=0, le=100)


__all__ = [
    "TutorialCourseDTO",
    "TutorialEvidenceDTO",
    "TutorialRunDTO",
    "TutorialStepDTO",
]
