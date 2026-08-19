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


def discovery_directories(base_dir: str, template_dir: str, *, runtime_root: str | None = None) -> list[str]:
    """Return built-in and current-tenant directories without shared-runtime leakage."""
    runtime_root = runtime_root or get_app_data_dir()
    candidates = [base_dir, template_dir, os.path.join(base_dir, "resources", "templates")]
    # Resolve through the module at call time.  Desktop/bootstrap tests and
    # tenant-scoped runtimes replace this public accessor dynamically; keeping
    # a copied function reference here would silently pin the original tenant.
    tenant_id = tenant_scope.current_tenant_id()
    if tenant_id is not None:
        tenant_root = os.path.join(runtime_root, "tenants", str(tenant_id))
        candidates.extend(
            [os.path.join(tenant_root, "templates"), os.path.join(tenant_root, "document_templates")]
        )
    deduped: list[str] = []
    seen: set[str] = set()
    for folder in candidates:
        key = os.path.normcase(os.path.abspath(folder))
        if key not in seen:
            seen.add(key)
            deduped.append(folder)
    return deduped


__all__ = ["business_scope", "discovery_directories", "infer_template_type_from_filename"]
