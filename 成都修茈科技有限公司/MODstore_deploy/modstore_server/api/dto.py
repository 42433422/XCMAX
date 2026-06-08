"""Request/Response DTOs extracted from app.py for DDD layer separation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfigDTO(BaseModel):
    library_root: str = ""
    xcagi_root: str = ""
    xcagi_backend_url: str = ""


class HealthResponse(BaseModel):
    ok: bool = True
    deploy_tier: str = "local"
    git_sha: str = ""
    hostname: str = ""
    tavily_configured: bool = False
    scheduler_running: Optional[bool] = None


class CreateModDTO(BaseModel):
    mod_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    industry_id: str = Field(
        "通用", max_length=64, description="行业预设 id，写入 manifest.industry"
    )


class ModAiScaffoldDTO(BaseModel):
    brief: str = Field(..., min_length=3, max_length=30000)
    suggested_id: str = Field("", max_length=64)
    replace: bool = True
    industry_id: str = Field(
        "通用", max_length=64, description="行业预设 id，生成后写入 manifest.industry"
    )
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
    manifest_override: Optional[Dict[str, Any]] = Field(None, alias="_manifest_override")


class FrontendRegenerateDTO(BaseModel):
    brief: str = Field("", max_length=8000)


class SyncDTO(BaseModel):
    mod_ids: Optional[List[str]] = None


class ManifestPutDTO(BaseModel):
    manifest: Dict[str, Any]


class ModFilePutDTO(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""


class WorkflowEmployeeCatalogDTO(BaseModel):
    workflow_index: int = Field(0, ge=0)
    industry: str = Field("通用", max_length=64)
    price: float = Field(0, ge=0)
    release_channel: str = Field("stable", pattern="^(stable|draft)$")


class WorkflowEmployeeClosureDTO(BaseModel):
    register_missing: bool = True
    patch_canvas: bool = True
    industry: str = Field("通用", max_length=64)


class AttachCatalogEmployeeDTO(BaseModel):
    pkg_id: str = Field(..., min_length=1, max_length=128)
    catalog_item_id: Optional[int] = Field(None, ge=1)


class ModSnapshotCaptureDTO(BaseModel):
    label: str = Field("", max_length=240)


class SandboxDTO(BaseModel):
    mod_id: str = Field(..., min_length=1)
    mode: str = Field(default="copy", pattern="^(copy|symlink)$")


class FocusPrimaryDTO(BaseModel):
    mod_id: str = Field(..., min_length=1)


class ExportFhdShellDTO(BaseModel):
    output_path: str = ""
