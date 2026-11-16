"""Read ELT settings from the current environment names only.

Historical ``FHD_*_ETL_*`` variables are not consulted. If any of them are
still set, startup and setting readers fail with the required new names.
"""

from __future__ import annotations

import os

LEGACY_TO_CURRENT = {
    "FHD_EXCEL_ETL_ALLOW_BUILTIN": "FHD_EXCEL_ELT_ALLOW_BUILTIN",
    "FHD_EXCEL_ETL_ALLOW_DIRECT": "FHD_EXCEL_ELT_ALLOW_DIRECT",
    "FHD_EXCEL_ETL_DEFAULT_TARGET": "FHD_EXCEL_ELT_DEFAULT_TARGET",
    "FHD_EXCEL_ETL_HEURISTIC": "FHD_EXCEL_ELT_HEURISTIC",
    "FHD_EXCEL_ETL_KB_PATH": "FHD_EXCEL_ELT_KB_PATH",
    "FHD_EXCEL_ETL_OCR_MAX_PAGES": "FHD_EXCEL_ELT_OCR_MAX_PAGES",
    "FHD_EXCEL_ETL_PROFILE": "FHD_EXCEL_ELT_PROFILE",
    "FHD_EXCEL_ETL_PROFILE_DIR": "FHD_EXCEL_ELT_PROFILE_DIR",
    "FHD_SHIPMENT_ETL_ALLOW_BATCH": "FHD_SHIPMENT_ELT_ALLOW_BATCH",
    "FHD_SHIPMENT_ETL_ALLOW_DIRECT": "FHD_SHIPMENT_ELT_ALLOW_DIRECT",
    "FHD_SHIPMENT_ETL_ALLOW_TMP": "FHD_SHIPMENT_ELT_ALLOW_TMP",
    "FHD_SHIPMENT_ETL_FINGERPRINT_BACKEND": "FHD_SHIPMENT_ELT_FINGERPRINT_BACKEND",
    "FHD_SHIPMENT_ETL_LLM": "FHD_SHIPMENT_ELT_LLM",
    "FHD_SHIPMENT_ETL_LLM_TIMEOUT": "FHD_SHIPMENT_ELT_LLM_TIMEOUT",
    "FHD_SHIPMENT_ETL_PROFILE": "FHD_SHIPMENT_ELT_PROFILE",
    "FHD_SHIPMENT_ETL_PROFILE_DIR": "FHD_SHIPMENT_ELT_PROFILE_DIR",
    "FHD_SHIPMENT_ETL_REQUIRE_RBAC": "FHD_SHIPMENT_ELT_REQUIRE_RBAC",
}


class LegacyEltEnvError(RuntimeError):
    """Raised when a retired ETL environment variable is still present."""


def legacy_elt_env_assignments() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for old, new in LEGACY_TO_CURRENT.items():
        if old in os.environ:
            found.append((old, new))
    return found


def reject_legacy_elt_env() -> None:
    found = legacy_elt_env_assignments()
    if not found:
        return
    mapping = ", ".join(f"{old} → {new}" for old, new in found)
    raise LegacyEltEnvError("已不再读取历史 ETL 环境变量，请改成对应的 ELT 名称后重启：" + mapping)


def elt_getenv(name: str, default: str = "") -> str:
    reject_legacy_elt_env()
    if name in LEGACY_TO_CURRENT:
        raise LegacyEltEnvError(f"已不再读取 {name}，请改用 {LEGACY_TO_CURRENT[name]}")
    value = os.environ.get(name)
    return default if value is None else value
