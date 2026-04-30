"""XCAGI Mod / 员工包 / 组合包 artifact 枚举（与 MODstore ADR 0003 对齐）。"""

from __future__ import annotations

ARTIFACT_MOD = "mod"
ARTIFACT_EMPLOYEE_PACK = "employee_pack"
ARTIFACT_BUNDLE = "bundle"

BUNDLE_MAX_DEPTH = 2

__all__ = [
    "ARTIFACT_MOD",
    "ARTIFACT_EMPLOYEE_PACK",
    "ARTIFACT_BUNDLE",
    "BUNDLE_MAX_DEPTH",
    "normalize_artifact",
]


def normalize_artifact(data: dict | None) -> str:
    if not data or not isinstance(data, dict):
        return ARTIFACT_MOD
    raw = data.get("artifact") or data.get("kind")
    if not raw or not isinstance(raw, str):
        return ARTIFACT_MOD
    v = raw.strip().lower()
    if v in (ARTIFACT_MOD, ARTIFACT_EMPLOYEE_PACK, ARTIFACT_BUNDLE):
        return v
    return ARTIFACT_MOD
