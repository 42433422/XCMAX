"""Product-plane admission rules for desktop employee packs.

The enterprise desktop is a customer execution plane.  Platform operations
employees may be present in a developer or historical user-data directory, but
they must never become enterprise schedulers, event subscribers, routes, or
executable workers merely because their manifest is on disk.
"""

from __future__ import annotations

from typing import Any

from app.mod_sdk.product_skus import resolve_product_sku


CONTROL_PLANE_EMPLOYEE_IDS = frozenset(
    {
        "daily-orchestrator",
        "llm-ops-engineer",
    }
)
CONTROL_PLANE_AREAS = frozenset({"platform-core", "server-and-ops"})


def is_enterprise_client_plane() -> bool:
    """Whether this process is the enterprise customer desktop SKU."""
    return resolve_product_sku() == "enterprise"


def is_control_plane_employee(employee_id: str, manifest: dict[str, Any] | None = None) -> bool:
    """Identify management/operations packs from an explicit ID or manifest role."""
    eid = str(employee_id or "").strip()
    if eid in CONTROL_PLANE_EMPLOYEE_IDS:
        return True
    data = manifest if isinstance(manifest, dict) else {}
    v2 = data.get("employee_config_v2") if isinstance(data.get("employee_config_v2"), dict) else {}
    identity = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
    area = str(identity.get("area") or data.get("area") or "").strip().lower()
    owner = str(identity.get("owner") or data.get("owner") or "").strip().lower()
    return owner == "admin" and area in CONTROL_PLANE_AREAS


def employee_pack_allowed_in_runtime(
    employee_id: str, manifest: dict[str, Any] | None = None
) -> bool:
    """Customer desktop never exposes control-plane employee packs."""
    return not is_enterprise_client_plane() or not is_control_plane_employee(employee_id, manifest)


def automatic_employee_runtime_enabled() -> bool:
    """Cron and event-driven employees belong to the management control plane."""
    return not is_enterprise_client_plane()


def employee_execution_block_reason(
    employee_id: str, manifest: dict[str, Any] | None = None
) -> str | None:
    if is_enterprise_client_plane() and is_control_plane_employee(employee_id, manifest):
        return "企业桌面端不执行管理控制面员工。"
    return None


__all__ = [
    "CONTROL_PLANE_EMPLOYEE_IDS",
    "automatic_employee_runtime_enabled",
    "employee_execution_block_reason",
    "employee_pack_allowed_in_runtime",
    "is_control_plane_employee",
    "is_enterprise_client_plane",
]
