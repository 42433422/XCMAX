"""附件工件（artifact）的数据模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

ELT_WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})


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
    """一个已解析附件工件的记录。

    归属字段由服务端登录身份写入，读路径按同一组字段校验；旧记录缺少归属时
    一律不可读，避免无主数据被默认放行。
    """

    id: str
    name: str
    suffix: str
    size: int
    sha1: str
    created_at: str
    sheets: list[SheetInfo] = field(default_factory=list)
    owner_user_id: str = ""
    tenant_id: str = ""
    mod_id: str = ""
    conversation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "suffix": self.suffix,
            "size": self.size,
            "sha1": self.sha1,
            "created_at": self.created_at,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "mod_id": self.mod_id,
            "conversation_id": self.conversation_id,
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
            owner_user_id=str(data.get("owner_user_id") or ""),
            tenant_id=str(data.get("tenant_id") or ""),
            mod_id=str(data.get("mod_id") or ""),
            conversation_id=str(data.get("conversation_id") or ""),
        )


@dataclass(frozen=True)
class ArtifactScope:
    """一次请求的服务端身份作用域；不接受客户端传入的归属声明。"""

    owner_user_id: str
    tenant_id: str = ""
    mod_id: str = ""
    conversation_id: str = ""

    def __post_init__(self) -> None:
        for name in ("owner_user_id", "tenant_id", "mod_id", "conversation_id"):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        if not self.owner_user_id:
            raise ValueError("工件作用域缺少账号归属")

    def allows(self, record: ArtifactRecord) -> bool:
        """账号与租户必须相等；记录带 Mod/会话绑定时再收紧到同一绑定。"""
        if record.owner_user_id != self.owner_user_id:
            return False
        if record.tenant_id != self.tenant_id:
            return False
        if record.mod_id and record.mod_id != self.mod_id:
            return False
        if record.conversation_id and record.conversation_id != self.conversation_id:
            return False
        return True


def artifact_scope_from_context(context: Mapping[str, Any] | None) -> ArtifactScope | None:
    """从已校验的服务端运行上下文构造作用域；无账号归属时返回 ``None``。"""
    data = context if isinstance(context, Mapping) else {}
    owner = str(data.get("user_id") or data.get("actor_id") or "").strip()
    if not owner:
        return None
    return ArtifactScope(
        owner_user_id=owner,
        tenant_id=str(data.get("tenant_id") or ""),
        mod_id=str(data.get("mod_id") or data.get("active_mod_id") or ""),
        conversation_id=str(data.get("conversation_id") or ""),
    )
