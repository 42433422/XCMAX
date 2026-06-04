from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error_code: str | None = None
    details: list[dict[str, Any]] | None = None


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "操作成功"
    data: T | None = None


class MessageResponse(BaseModel):
    success: bool = True
    message: str = "操作成功"


class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int
