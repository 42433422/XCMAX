"""Stable public Mod store response and request models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModStoreCatalogPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    installed: list[dict[str, Any]]
    available: list[dict[str, Any]]
    indexed_count: int


class ModStoreCatalogResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreCatalogPayload


class ModStoreListResponse(BaseModel):
    success: Literal[True] = True
    data: list[dict[str, Any]]


class ModStoreMarketCatalogPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[dict[str, Any]]
    total: int
    collection: str = ""


class ModStoreMarketCatalogResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreMarketCatalogPayload


class ModStoreDetailData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    version: str
    author: str
    description: str
    statistics: Any | None = None
    ratings: list[Any] = Field(default_factory=list)
    rating_count: int = 0
    source: str
    catalog_base_url: str


class ModStoreDetailResponse(BaseModel):
    success: Literal[True] = True
    data: ModStoreDetailData


class ModStoreInstallResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool
    message: str
    data: dict[str, Any] | None = None


class ModStoreSimpleResponse(BaseModel):
    success: bool
    message: str | None = None
    data: dict[str, Any] | None = None


class AiModDeliveryStartBody(BaseModel):
    brief: str = Field(..., min_length=3, max_length=4000)


class ModStoreUpdatesResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]


class ModStoreDependenciesResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]


class ModStoreRebuildResponse(BaseModel):
    success: Literal[True] = True
    data: dict[str, Any]
    message: str | None = None


class ModStoreNotImplementedResponse(BaseModel):
    success: Literal[False] = False
    detail: str
