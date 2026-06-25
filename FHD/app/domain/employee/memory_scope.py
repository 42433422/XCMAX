"""员工记忆作用域值对象。

把 ``employee_config_v2.memory`` 声明翻译为「短期/长期开关 + 向量命名空间」。
长期向量索引默认按员工维度隔离（``emp:<employee_id>``），可选叠加用户维度。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DISABLED_MEMORY_TYPES = frozenset({"none", "stateless", "off", ""})


@dataclass(frozen=True)
class MemoryScope:
    employee_id: str
    short_term_enabled: bool = True
    long_term_enabled: bool = True
    user_scoped: bool = False

    def long_term_index(self, user_id: str | None = None) -> str:
        """长期向量库 index_id。默认按员工隔离；user_scoped 时叠加用户维度。"""
        base = f"emp:{self.employee_id}"
        uid = str(user_id or "").strip()
        if self.user_scoped and uid:
            return f"{base}:usr:{uid}"
        return base

    @classmethod
    def from_config(cls, employee_id: str, config: dict[str, Any] | None) -> MemoryScope:
        mem = {}
        if isinstance(config, dict) and isinstance(config.get("memory"), dict):
            mem = config["memory"]
        mem_type = str(mem.get("type") or "session").strip().lower()
        if mem_type in _DISABLED_MEMORY_TYPES:
            return cls(
                employee_id=employee_id,
                short_term_enabled=False,
                long_term_enabled=False,
            )
        long_term = mem.get("long_term")
        long_enabled = True if long_term is None else _truthy(long_term)
        scope = str(mem.get("scope") or "").strip().lower()
        return cls(
            employee_id=employee_id,
            short_term_enabled=True,
            long_term_enabled=long_enabled,
            user_scoped=scope in ("user", "per_user", "user_scoped"),
        )


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


__all__ = ["MemoryScope"]
