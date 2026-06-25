"""员工能力声明值对象。

从 manifest 的 ``employee.capabilities`` 与 ``employee_config_v2.cognition.skills``
解析出能力清单。能力 label 用于 P1 的工具作用域派生（capabilities → scoped tools）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmployeeCapability:
    label: str
    description: str = ""

    @property
    def key(self) -> str:
        return self.label.strip().lower().replace(" ", "_")


def _coerce(item: Any) -> EmployeeCapability | None:
    if isinstance(item, str) and item.strip():
        return EmployeeCapability(label=item.strip())
    if isinstance(item, dict):
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            return None
        return EmployeeCapability(
            label=label, description=str(item.get("description") or "").strip()
        )
    return None


def parse_capabilities(manifest: dict[str, Any] | None) -> list[EmployeeCapability]:
    """从 manifest + employee_config_v2 解析能力清单（去重，保序）。"""
    if not isinstance(manifest, dict):
        return []
    out: list[EmployeeCapability] = []
    seen: set[str] = set()

    def _add(item: Any) -> None:
        cap = _coerce(item)
        if cap and cap.key not in seen:
            seen.add(cap.key)
            out.append(cap)

    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    for item in emp.get("capabilities") or []:
        _add(item)

    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    for item in cog.get("skills") or []:
        if isinstance(item, dict):
            _add({"label": item.get("name"), "description": item.get("brief")})
        else:
            _add(item)
    return out


__all__ = ["EmployeeCapability", "parse_capabilities"]
