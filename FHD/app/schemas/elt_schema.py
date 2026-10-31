"""通用 ETL 公共 API 类型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EltFieldMapping(BaseModel):
    source: str = ""
    target: str
    transforms: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    required: bool = False


class EltValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "error"
    field: str = ""


class EltRowDecision(BaseModel):
    row_id: int
    suggested_action: Literal["new", "update", "skip", "error"]
    final_action: Literal["new", "update", "skip", "error"]
    reason: str = ""
    issues: list[EltValidationIssue] = Field(default_factory=list)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)


class EltRunSummary(BaseModel):
    new: int = 0
    update: int = 0
    skip: int = 0
    error: int = 0
    executed: int = 0


class EltTargetCapability(BaseModel):
    type: str
    label: str
    fields: list[dict[str, Any]] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    default_match_keys: list[str] = Field(default_factory=list)
    supported_actions: list[str] = Field(default_factory=list)
    reversible: bool = False


class EltPreviewRequest(BaseModel):
    upload_id: str
    target_type: str
    template_id: str | None = None
    compatibility_preset_id: str | None = Field(default=None, max_length=180)
    target_config_id: str | None = None


class EltDraftPatch(BaseModel):
    field_mappings: list[EltFieldMapping] | None = None
    validation_rules: list[dict[str, Any]] | None = None
    match_keys: list[str] | None = None
    allowed_update_fields: list[str] | None = None
    action_rules: dict[str, Any] | None = None
    target_config_id: str | None = None
    ocr_confirmed: bool | None = None
    row_overrides: dict[str, Literal["new", "update", "skip"]] | None = None


class EltExecuteRequest(BaseModel):
    confirmed: bool = False
    valid_rows_only: bool = False
    preview_revision: str | None = Field(default=None, max_length=64, pattern=r"^[0-9a-f]{64}$")


class EltShipmentTemplateRequest(BaseModel):
    name: str = Field(default="", max_length=160)
    source_region_id: str | None = Field(default=None, max_length=300)


class EltTemplateRequest(BaseModel):
    name: str
    target_type: str
    draft: dict[str, Any]
    source_features: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class EltTemplateUpdateRequest(BaseModel):
    name: str | None = None
    draft: dict[str, Any]
    source_features: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class EltTargetConfigRequest(BaseModel):
    name: str
    endpoint_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    secret: str | None = None
