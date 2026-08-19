"""Request model and progress-step schema for Butler orchestration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def butler_orchestrate_steps() -> List[Dict[str, Any]]:
    return [
        {"id": "snapshot", "label": "备份快照", "status": "pending", "message": None},
        {"id": "plan", "label": "规划改动", "status": "pending", "message": None},
        {"id": "vibe", "label": "vibe-coding 改写", "status": "pending", "message": None},
        {"id": "validate", "label": "服务端校验", "status": "pending", "message": None},
        {"id": "complete", "label": "完成", "status": "pending", "message": None},
    ]


class ButlerOrchestrateBody(BaseModel):
    target_type: str = Field(..., description="'mod' | 'workflow' | 'employee'")
    target_id: str = Field(..., min_length=1, max_length=256)
    brief: str = Field(..., min_length=3, max_length=8000)
    scope: Optional[str] = Field(
        None,
        description="auto | manifest | backend | frontend | workflow_graph | employee_prompt",
    )
    focus_paths: Optional[List[str]] = None
    with_snapshot: bool = True
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
