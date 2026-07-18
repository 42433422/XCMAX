"""员工有效能力值对象。

来源顺序与合并规则由 ``config/employee_capability_contract.yaml`` 生成，避免运行时代码
自行决定 ``employee.capabilities`` 与 ``employee_config_v2.cognition.skills`` 谁优先。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capability_contract_generated import (
    CAPABILITY_KEY_NORMALIZATION,
    CAPABILITY_MERGE_STRATEGY,
    CAPABILITY_SOURCE_SPECS,
)


@dataclass(frozen=True)
class EmployeeCapability:
    label: str
    description: str = ""

    @property
    def key(self) -> str:
        key = self.label.strip() if CAPABILITY_KEY_NORMALIZATION.get("trim", True) else self.label
        if CAPABILITY_KEY_NORMALIZATION.get("lowercase", True):
            key = key.lower()
        if CAPABILITY_KEY_NORMALIZATION.get("spaces_to_underscore", True):
            key = key.replace(" ", "_")
        return key


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
    """按 SSOT 契约解析能力清单（有序并集，同 key 的首个定义优先）。"""
    if not isinstance(manifest, dict):
        return []
    if CAPABILITY_MERGE_STRATEGY != "ordered_union_first_definition_wins":
        raise RuntimeError(f"unsupported capability merge strategy: {CAPABILITY_MERGE_STRATEGY}")
    out: list[EmployeeCapability] = []
    seen: set[str] = set()

    def _add(item: Any) -> None:
        cap = _coerce(item)
        if cap and cap.key not in seen:
            seen.add(cap.key)
            out.append(cap)

    for path, label_field, description_field in CAPABILITY_SOURCE_SPECS:
        current: object = manifest
        for part in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if not isinstance(current, list):
            continue
        for item in current:
            if isinstance(item, dict):
                _add(
                    {
                        "label": item.get(label_field),
                        "description": item.get(description_field),
                    }
                )
            else:
                _add(item)
    return out


__all__ = ["EmployeeCapability", "parse_capabilities"]
