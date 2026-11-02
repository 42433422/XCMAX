"""Pure path and classification helpers for filesystem template discovery."""

from __future__ import annotations

import os

from app.infrastructure import tenant_scope
from app.utils.path_io.path_utils import get_app_data_dir


def infer_template_type_from_filename(filename: str) -> str:
    name = (filename or "").lower()
    if "考勤" in name:
        return "考勤记录"
    if "客户" in name:
        return "客户"
    if "原材料" in name or "材料" in name:
        return "原材料"
    if "产品" in name:
        return "产品"
    if "出货记录" in name:
        return "出货记录"
    if "发货" in name or "出货单" in name:
        return "发货单"
    return "Excel"


def business_scope(template_type: str | None) -> str | None:
    if (template_type or "").strip() in {"考勤记录", "出货记录"}:
        return "shipmentRecords"
    return None


def discovery_directories(
    base_dir: str, template_dir: str, *, runtime_root: str | None = None
) -> list[str]:
    """Return built-in and current-tenant directories without shared-runtime leakage."""
    runtime_root = runtime_root or get_app_data_dir()
    candidates = [base_dir, template_dir, os.path.join(base_dir, "resources", "templates")]
    candidates.extend(tenant_template_directories(runtime_root=runtime_root))
    deduped: list[str] = []
    seen: set[str] = set()
    for folder in candidates:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen:
            seen.add(key)
            deduped.append(folder)
    return deduped


def tenant_template_directories(*, runtime_root: str | None = None) -> list[str]:
    """Directories owned by the current tenant; installation files are shared."""
    tenant_id = tenant_scope.current_tenant_id()
    if tenant_id is None:
        return []
    tenant_root = os.path.join(
        os.path.realpath(runtime_root or get_app_data_dir()), "tenants", str(tenant_id)
    )
    return [os.path.join(tenant_root, folder) for folder in ("templates", "document_templates")]


def template_path_key(path: str, *, runtime_root: str | None = None) -> str:
    """Normalize the configured runtime alias, preserving child asset identity across path swaps."""
    runtime = os.path.abspath(runtime_root or get_app_data_dir())
    absolute = os.path.abspath(path)
    try:
        if os.path.commonpath([absolute, runtime]) == runtime:
            absolute = os.path.join(os.path.realpath(runtime), os.path.relpath(absolute, runtime))
    except ValueError:  # References may use another Windows drive.
        pass
    return os.path.normcase(absolute)


__all__ = [
    "business_scope",
    "discovery_directories",
    "infer_template_type_from_filename",
    "tenant_template_directories",
    "template_path_key",
]
