"""员工记忆作用域值对象。

把 ``employee_config_v2.memory`` 声明翻译为「短期/长期开关 + 向量命名空间」。
默认按租户、用户、员工隔离；显式企业共享也必须限定到同一租户。
v2 命名空间不读取无法证明归属的旧 ``emp:<employee_id>`` 索引。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

_DISABLED_MEMORY_TYPES = frozenset({"none", "stateless", "off", ""})


@dataclass(frozen=True)
class MemoryScope:
    employee_id: str
    short_term_enabled: bool = True
    long_term_enabled: bool = True
    user_scoped: bool = True
    tenant_id: int | str | None = None

    def __post_init__(self) -> None:
        tenant = _positive_id(self.tenant_id)
        object.__setattr__(self, "tenant_id", int(tenant) if tenant else None)
        object.__setattr__(self, "employee_id", str(self.employee_id or "").strip())

    def long_term_index(self, user_id: Any = None) -> str:
        """Authenticated v2 index; missing tenant/actor fails closed even for sharing."""
        tenant = _positive_id(self.tenant_id)
        owner = _positive_id(user_id)
        employee = str(self.employee_id or "").strip()
        if not tenant or not owner or not employee:
            return ""
        scope = [tenant, employee, "user" if self.user_scoped else "tenant"]
        if self.user_scoped:
            scope.append(owner)
        digest = hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode()).hexdigest()
        return f"emp:v2:{digest}"

    @classmethod
    def from_config(
        cls,
        employee_id: str,
        config: dict[str, Any] | None,
        *,
        tenant_id: int | str | None = None,
    ) -> MemoryScope:
        mem = {}
        if isinstance(config, dict) and isinstance(config.get("memory"), dict):
            mem = config["memory"]
        mem_type = str(mem.get("type") or "session").strip().lower()
        if mem_type in _DISABLED_MEMORY_TYPES:
            return cls(
                employee_id=employee_id,
                short_term_enabled=False,
                long_term_enabled=False,
                tenant_id=tenant_id,
            )
        long_term = mem.get("long_term")
        long_enabled = True if long_term is None else _truthy(long_term)
        scope = str(mem.get("scope") or "").strip().lower()
        return cls(
            employee_id=employee_id,
            short_term_enabled=True,
            long_term_enabled=long_enabled,
            user_scoped=scope not in ("tenant", "enterprise", "tenant_shared"),
            tenant_id=tenant_id,
        )


def _positive_id(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    text = str(value or "").strip()
    if not text.isdecimal():
        return ""
    number = int(text)
    return str(number) if number > 0 else ""


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


__all__ = ["MemoryScope"]
