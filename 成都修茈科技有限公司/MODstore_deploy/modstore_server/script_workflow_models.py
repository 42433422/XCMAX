"""Pydantic request and response contracts for script-workflow routes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WorkflowSummary(BaseModel):
    id: int
    name: str
    status: str
    brief_goal: str
    created_at: str
    updated_at: str


class CommitSessionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    schema_in: Dict[str, Any] = Field(default_factory=dict)


class FeedbackBody(BaseModel):
    hint: str = Field(..., min_length=1, max_length=4000)


class EditWithAiBody(BaseModel):
    hint: str = Field(..., min_length=1, max_length=4000)
    provider: Optional[str] = None
    model: Optional[str] = None


class UpdateWorkflowBody(BaseModel):
    name: Optional[str] = None
    schema_in: Optional[Dict[str, Any]] = None
