"""与 XCAGI app.infrastructure.mods.artifact_constants 语义一致（MODstore 独立包内校验）。"""

from __future__ import annotations

ARTIFACT_MOD = "mod"
ARTIFACT_EMPLOYEE_PACK = "employee_pack"
ARTIFACT_BUNDLE = "bundle"
BUNDLE_MAX_DEPTH = 2


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
