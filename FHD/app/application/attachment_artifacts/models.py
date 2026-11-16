"""附件工件（artifact）的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SheetInfo:
    """单个工作表的元信息与预览行。"""

    name: str
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    rows_preview: list[list[str]] = field(default_factory=list)
    truncated: bool = False
    # 全量明细只在解析态携带，落盘到独立明细文件，不进入 to_dict，避免响应与索引膨胀。
    rows: list[list[str]] = field(default_factory=list, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "rows_preview": [list(row) for row in self.rows_preview],
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SheetInfo:
        return cls(
            name=str(data.get("name") or ""),
            columns=[str(cell) for cell in data.get("columns") or []],
            row_count=int(data.get("row_count") or 0),
            rows_preview=[[str(cell) for cell in row] for row in data.get("rows_preview") or []],
            truncated=bool(data.get("truncated")),
        )


@dataclass
class ArtifactRecord:
    """一个已解析附件工件的记录。"""

    id: str
    name: str
    suffix: str
    size: int
    sha1: str
    created_at: str
    sheets: list[SheetInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "suffix": self.suffix,
            "size": self.size,
            "sha1": self.sha1,
            "created_at": self.created_at,
            "sheets": [sheet.to_dict() for sheet in self.sheets],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRecord:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            suffix=str(data.get("suffix") or ""),
            size=int(data.get("size") or 0),
            sha1=str(data.get("sha1") or ""),
            created_at=str(data.get("created_at") or ""),
            sheets=[SheetInfo.from_dict(item) for item in data.get("sheets") or []],
        )
