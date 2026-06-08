from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CreateWorkflowBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field("", max_length=2000)


class WorkflowExecuteBody(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)


class SandboxRunBody(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)
    mock_employees: bool = True
    validate_only: bool = False


class UpdateWorkflowBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AddWorkflowNodeBody(BaseModel):
    node_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    config: Dict[str, Any] = Field(default_factory=dict)
    position_x: float = 0.0
    position_y: float = 0.0


class AddWorkflowEdgeBody(BaseModel):
    source_node_id: int
    target_node_id: int
    condition: str = ""


class PatchWorkflowNodeBody(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class WorkflowTriggerBody(BaseModel):
    trigger_type: str = Field(..., min_length=1, max_length=32)
    trigger_key: str = Field("", max_length=128)
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class PublishVersionBody(BaseModel):
    note: str = Field("", max_length=2000)
